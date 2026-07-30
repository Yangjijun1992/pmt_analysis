from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from pmt_analysis.analysis.app import (
    analyze_app,
    print_main_pulse_summary,
    print_afterpulse_summary,
    plot_afterpulse_2d_histogram,
    plot_afterpulse_delta_time_all_channels,
    plot_main_pulse_area_all_channels,
    plot_main_pulse_diagnostics,
    save_diagnostics_npz,
)
from pmt_analysis.analysis.dark_count import DarkCountResult, analyze_dark_count
from pmt_analysis.analysis.gain import GainAnalysisResult, GainFitResult, analyze_gain
from pmt_analysis.config import DEFAULT_DB_PATH, DEFAULT_TPC_DATA_ROOT
from pmt_analysis.db.mapping import MappingError, MappingTable, load_mapping_from_runinfo
from pmt_analysis.db.writer import write_analysis_results
from pmt_analysis.io.raw_reader import NotebookBasedRawDataReader
from pmt_analysis.models import RunInfo
from pmt_analysis.plotting.validation import (
    plot_area_histogram,
    plot_dark_count_baseline_2d,
    plot_dark_count_validation,
    plot_filtered_waveform_overlay,
    plot_spe_gain_validation,
    plot_waveform_overlay,
)
from pmt_analysis.runinfo import get_runinfo


def _load_mapping(ri: RunInfo) -> Optional[MappingTable]:
    raw_mapping = ri.metadata.get("mapping")
    if raw_mapping is None:
        return None
    return load_mapping_from_runinfo({"mapping": raw_mapping})


def analyze_runs(
    run_ids: Sequence[int],
    output_dir: str,
    data_root: str = DEFAULT_TPC_DATA_ROOT,
    save_plots: bool = True,
    write_db: bool = False,
    github_user: str = "",
    github_token: str = "",
) -> int:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("PMT analysis pipeline started")
    print(f"Run IDs: {list(run_ids)}")
    print(f"Output directory: {output_path.resolve()}")
    print(f"TPC data root: {data_root}")
    print(f"Save plots: {save_plots}")
    print(f"Write DB: {write_db}")
    if write_db:
        print(f"Database path: {DEFAULT_DB_PATH}")
    print()

    reader = NotebookBasedRawDataReader()

    run_infos: List[RunInfo] = []
    for rid in run_ids:
        try:
            ri = get_runinfo(rid, data_root)
            run_infos.append(ri)
            print(f"[run_id={ri.run_id}] runtype      = {ri.runtype}")
            print(f"[run_id={ri.run_id}] datatype     = {ri.datatype}")
            print(f"[run_id={ri.run_id}] runinfo_path = {ri.runinfo_path}")
            print(f"[run_id={ri.run_id}] raw_dir      = {ri.raw_dir}")
            print(f"[run_id={ri.run_id}] outfile_name = {ri.outfile_name}")
            print()
        except Exception as e:
            print(f"[run_id={rid}] ERROR: {e}")
            print()

    if not run_infos:
        print("No valid runinfo found. Aborting.")
        return 1

    print("Runinfo discovery completed.")
    print()

    all_plot_paths: List[str] = []

    # Read raw data and analyze for each run
    for ri in run_infos:
        run_plot_paths: List[str] = []
        try:
            print(f"[run_id={ri.run_id}] Loading raw data...")
            bundle = reader.read(ri)
            print(f"[run_id={ri.run_id}] source_path    = {bundle.source_path}")
            print(f"[run_id={ri.run_id}] data_format    = {bundle.data_format}")
            print(f"[run_id={ri.run_id}] event_count    = {bundle.event_count}")
            print(f"[run_id={ri.run_id}] channel_count  = {bundle.channel_count}")
            print(f"[run_id={ri.run_id}] waveform_count = {bundle.waveform_count}")
            meta = bundle.metadata
            print(f"[run_id={ri.run_id}] board_count    = {meta.get('board_count', 'N/A')}")
            print(f"[run_id={ri.run_id}] boards         = {meta.get('boards', 'N/A')}")
            print(f"[run_id={ri.run_id}] daq_time_s     = {meta.get('daq_time_s', 'N/A'):.3f}")
            print()

            # Build pmt_id_map from runinfo mapping (used across all analysis types)
            pmt_id_map: Dict[Tuple[int, int], str] = {}
            raw_mapping = ri.metadata.get("mapping")
            if raw_mapping:
                for board_info in raw_mapping:
                    board_id = board_info["board_id"]
                    for ch_info in board_info.get("channels", []):
                        ch_id = ch_info["ch"]
                        pmt_id = ch_info["pmt"]
                        pmt_id_map[(board_id, ch_id)] = pmt_id

            # Normalize datatype list for lookup
            dt_set = {d.lower() for d in ri.datatype}

            # Waveform overlay plot
            if save_plots:
                if "spe gain" in dt_set:
                    # For SPE Gain runs, only plot filtered waveforms (RMS < threshold)
                    wfm_plot = plot_filtered_waveform_overlay(
                        bundle=bundle,
                        output_dir=output_path,
                        run_id=ri.run_id,
                        x_range=(50, 150),
                        rms_threshold=50.0,
                    )
                else:
                    wfm_plot = plot_waveform_overlay(
                        bundle=bundle,
                        output_dir=output_path,
                        run_id=ri.run_id,
                        x_range=(50, 150),
                    )
                if wfm_plot:
                    run_plot_paths.append(wfm_plot)
                    print(f"[run_id={ri.run_id}] waveform overlay plot: {wfm_plot}")

            # Dark count analysis
            dcr_result = None
            if "dark rate" in dt_set:
                print(f"[run_id={ri.run_id}] Running dark count analysis...")
                dcr_result = analyze_dark_count(bundle)
                print(f"[run_id={ri.run_id}] asymmetry_threshold       = {dcr_result.asymmetry_threshold}")
                print(f"[run_id={ri.run_id}] total_pulse_count         = {dcr_result.total_pulse_count}")
                print(f"[run_id={ri.run_id}] total_dark_count          = {dcr_result.total_dark_count}")
                print(f"[run_id={ri.run_id}] total_noise_count         = {dcr_result.total_noise_count}")
                if dcr_result.total_daq_run_time_length_s is not None:
                    print(f"[run_id={ri.run_id}] total_daq_run_time_length = {dcr_result.total_daq_run_time_length_s:.3f} s")
                else:
                    print(f"[run_id={ri.run_id}] total_daq_run_time_length = N/A")
                if dcr_result.dark_count_rate_hz is not None:
                    print(f"[run_id={ri.run_id}] dark_count_rate          = {dcr_result.dark_count_rate_hz:.2f} Hz")
                else:
                    print(f"[run_id={ri.run_id}] dark_count_rate          = N/A")
                print()

                for ch_result in dcr_result.channels:
                    rate_str = f"{ch_result.dark_count_rate_hz:.2f} Hz" if ch_result.dark_count_rate_hz is not None else "N/A"
                    pmt_id = pmt_id_map.get((ch_result.board, ch_result.channel), "?")
                    print(
                        f"[run_id={ri.run_id}]   Board {ch_result.board}, Channel {ch_result.channel} ({pmt_id}): "
                        f"pulses={ch_result.total_pulses}, dark={ch_result.dark_count}, "
                        f"noise={ch_result.noise_count}, rate={rate_str}"
                    )
                print()
            else:
                print(f"[run_id={ri.run_id}] Skipping dark count analysis (datatype={ri.datatype})")
                print()

            # SPE Gain analysis
            gain_result = None
            if "spe gain" in dt_set:
                print(f"[run_id={ri.run_id}] Running SPE gain analysis...")
                gain_result = analyze_gain(bundle)
                print(f"[run_id={ri.run_id}] SPE Gain Analysis Results:")
                for ch_result in gain_result.channels:
                    pmt_id = pmt_id_map.get((ch_result.board, ch_result.channel), "?")
                    if ch_result.fit_success:
                        print(
                            f"[run_id={ri.run_id}]   Board {ch_result.board}, Channel {ch_result.channel} ({pmt_id}): "
                            f"sample_count={ch_result.sample_count}, "
                            f"feature_name=SPE_charge, "
                            f"fit_success=True, "
                            f"gain_value={ch_result.gain_value:.2f} +/- {ch_result.gain_error:.2f}, "
                            f"sigma={ch_result.sigma:.2f} +/- {ch_result.sigma_error:.2f}"
                        )
                    else:
                        print(
                            f"[run_id={ri.run_id}]   Board {ch_result.board}, Channel {ch_result.channel} ({pmt_id}): "
                            f"sample_count={ch_result.sample_count}, "
                            f"feature_name=SPE_charge, "
                            f"fit_success=False"
                        )
                print()
            else:
                print(f"[run_id={ri.run_id}] Skipping SPE gain analysis (datatype={ri.datatype})")
                print()

            # APP analysis
            app_result = None
            if "after pulse" in dt_set:
                print(f"[run_id={ri.run_id}] Running APP analysis...")
                try:
                    app_result = analyze_app(bundle, pmt_id_map=pmt_id_map or None)
                    print(f"[run_id={ri.run_id}] main_pulse_count = {app_result.main_pulse_count}")
                    print(f"[run_id={ri.run_id}] afterpulse_count = {app_result.afterpulse_count}")
                    print(f"[run_id={ri.run_id}] APP (overall raw) = {app_result.app_value}")
                    print(f"[run_id={ri.run_id}] APP (overall PE) = {app_result.app_value_pe}")
                    print()

                    # Per-channel summary table
                    header = (
                        f"[run_id={ri.run_id}]   "
                        f"{'PMT_ID':<10} {'CH':>3} {'MainN':>6} {'MainArea_mean':>14} "
                        f"{'AP_N':>6} {'APP':>10} {'SPE_gain':>10}"
                    )
                    print(header)
                    print(f"[run_id={ri.run_id}]   {'-' * 65}")
                    for ch_r in app_result.channels:
                        ch = ch_r.channel
                        pmt_id = pmt_id_map.get((0, ch), "?")
                        main_area_mean = (
                            ch_r.main_pulse_charge / ch_r.main_pulse_count
                            if ch_r.main_pulse_count > 0 else 0
                        )
                        main_area_mean_pe = (
                            ch_r.main_pulse_charge_pe / ch_r.main_pulse_count
                            if ch_r.main_pulse_count > 0 else 0
                        )
                        gain_str = f"{ch_r.spe_gain:.4f}" if ch_r.spe_gain else "N/A"
                        app_str = f"{ch_r.app_value_pe:.6f}" if ch_r.app_value_pe is not None else f"{ch_r.app_value:.6f}" if ch_r.app_value is not None else "N/A"
                        area_str = f"{main_area_mean_pe:.4f}" if ch_r.spe_gain else f"{main_area_mean:.4f}"
                        print(
                            f"[run_id={ri.run_id}]   "
                            f"{pmt_id:<10} {ch:>3} {ch_r.main_pulse_count:>6} {area_str:>14} "
                            f"{ch_r.afterpulse_count:>6} {app_str:>10} {gain_str:>10}"
                        )

                    print()
                    print_main_pulse_summary(app_result.channels, pmt_id_map)
                    print_afterpulse_summary(app_result.channels, pmt_id_map)

                    # 2D histogram (one figure per channel)
                    hist_files = plot_afterpulse_2d_histogram(
                        app_result.channels, pmt_id_map, ri.run_id, str(output_path),
                    )
                    for f in hist_files:
                        print(f"[run_id={ri.run_id}] Afterpulse 2D histogram: {f}")
                        run_plot_paths.append(f)

                    # Delta time distribution (all channels)
                    dt_plot = plot_afterpulse_delta_time_all_channels(
                        app_result.channels, pmt_id_map, ri.run_id, str(output_path),
                    )
                    print(f"[run_id={ri.run_id}] Afterpulse delta time plot: {dt_plot}")
                    run_plot_paths.append(dt_plot)

                    # Main pulse area distribution (all channels)
                    area_plot = plot_main_pulse_area_all_channels(
                        app_result.channels, pmt_id_map, ri.run_id, str(output_path),
                    )
                    print(f"[run_id={ri.run_id}] Main pulse area plot: {area_plot}")
                    run_plot_paths.append(area_plot)

                    # Main pulse diagnostics
                    main_diag_files = plot_main_pulse_diagnostics(
                        app_result.channels, pmt_id_map, ri.run_id, str(output_path),
                    )
                    for f in main_diag_files:
                        print(f"[run_id={ri.run_id}] Main pulse diagnostics: {f}")
                        run_plot_paths.append(f)

                    # Save diagnostic .npz files
                    npz_files = save_diagnostics_npz(
                        app_result.channels, pmt_id_map, ri.run_id, str(output_path),
                    )
                    for f in npz_files:
                        print(f"[run_id={ri.run_id}] Saved: {f}")
                except Exception as e:
                    print(f"[run_id={ri.run_id}] APP analysis failed: {e}")
                    app_result = None
                print()
            else:
                print(f"[run_id={ri.run_id}] Skipping APP analysis (datatype={ri.datatype})")
                print()

            # Validation plots
            if save_plots:
                print(f"[run_id={ri.run_id}] Generating validation plots...")

                if dcr_result is not None:
                    dcr_plot = plot_dark_count_validation(
                        result=dcr_result,
                        output_dir=output_path,
                        run_id=ri.run_id,
                    )
                    if dcr_plot:
                        run_plot_paths.append(dcr_plot)
                        print(f"[run_id={ri.run_id}]   dark_count plot: {dcr_plot}")

                    baseline_2d_plot = plot_dark_count_baseline_2d(
                        result=dcr_result,
                        output_dir=output_path,
                        run_id=ri.run_id,
                    )
                    if baseline_2d_plot:
                        run_plot_paths.append(baseline_2d_plot)
                        print(f"[run_id={ri.run_id}]   baseline_2d plot: {baseline_2d_plot}")

                if gain_result is not None:
                    hist_dict: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}
                    params_dict: Dict[int, Dict[str, float]] = {}
                    for ch_f in gain_result.channels:
                        if ch_f.histogram_counts is not None and ch_f.histogram_edges is not None:
                            hist_dict[ch_f.channel] = (ch_f.histogram_counts, ch_f.histogram_edges)
                        if ch_f.fit_success and ch_f.fit_parameters:
                            params_dict[ch_f.channel] = ch_f.fit_parameters

                    gain_plot = plot_spe_gain_validation(
                        result=gain_result,
                        output_dir=output_path,
                        run_id=ri.run_id,
                        histogram_counts=hist_dict or None,
                        fit_params=params_dict or None,
                    )
                    if gain_plot:
                        run_plot_paths.append(gain_plot)
                        print(f"[run_id={ri.run_id}]   spe_gain plot: {gain_plot}")

                    area_plot = plot_area_histogram(
                        bundle=bundle,
                        output_dir=output_path,
                        run_id=ri.run_id,
                        histogram_counts=hist_dict or None,
                        fit_params=params_dict or None,
                        hist_range=(-10.0, 40.0),
                        n_bins=100,
                    )
                    if area_plot:
                        run_plot_paths.append(area_plot)
                        print(f"[run_id={ri.run_id}]   area histogram plot: {area_plot}")

                all_plot_paths.extend(run_plot_paths)
                print()

            # Database write
            if write_db:
                print(f"[run_id={ri.run_id}] Preparing database write...")
                try:
                    mapping = _load_mapping(ri)
                    if mapping is None:
                        print(f"[run_id={ri.run_id}] No mapping found in runinfo. Skipping DB write.")
                    else:
                        print(f"[run_id={ri.run_id}] Mapping loaded: {len(mapping.entries)} channel(s)")
                        write_analysis_results(
                            db_path=DEFAULT_DB_PATH,
                            mapping=mapping,
                            run_id=ri.run_id,
                            dark_result=dcr_result,
                            gain_result=gain_result,
                            app_result=app_result,
                            github_user=github_user,
                            github_token=github_token,
                        )
                except MappingError as e:
                    print(f"[run_id={ri.run_id}] Mapping error: {e}. Skipping DB write.")
                except Exception as e:
                    print(f"[run_id={ri.run_id}] Database write error: {e}")
                print()
            else:
                print(f"[run_id={ri.run_id}] Skipping database write (use --write-db to enable).")
                print()

        except Exception as e:
            print(f"[run_id={ri.run_id}] ANALYSIS ERROR: {e}")
            print()

    # Final summary
    print("=" * 60)
    print("Analysis Summary")
    print("=" * 60)
    print(f"  Runs processed: {len(run_infos)} / {len(run_ids)}")
    print(f"  Output directory: {output_path.resolve()}")
    if all_plot_paths:
        print(f"  Validation plots ({len(all_plot_paths)}):")
        for p in all_plot_paths:
            print(f"    - {p}")
    else:
        print("  Validation plots: none generated")
    print("=" * 60)
    print("Analysis completed.")

    return 0
