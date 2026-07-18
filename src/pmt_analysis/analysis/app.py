"""APP (After Pulse Probability) Analysis Module.

Algorithm Summary:
    1. Per-channel main pulse identification: height > threshold (default 1000 ADC)
    2. Per-channel afterpulse search: threshold crossing after main pulse end + interval
    3. Per-channel APP = sum(afterpulse_charges) / sum(main_pulse_charges)
    4. PE normalization: divide raw charges by per-channel SPE gain from database
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pmt_analysis.io.raw_reader import RawDataBundle

PE_FACT = (2.0 / 16384.0) * 4.0e-9 / (50.0 * 1.6e-19) / 1.0e6

DEFAULT_MAIN_PULSE_HEIGHT_THRESHOLD = 1000  # ADC
DEFAULT_AMPLITUDE_THRESHOLD = 20  # ADC
DEFAULT_AFTERPULSE_MIN_INTERVAL = 35  # samples
DEFAULT_MIN_INTERVAL_BETWEEN_PULSES = 10  # samples


class AppAnalysisError(Exception):
    pass


@dataclass
class MainPulseRecord:
    event_index: Optional[int] = None
    channel_index: Optional[int] = None
    sample_index: Optional[int] = None
    height: Optional[float] = None
    charge: Optional[float] = None
    charge_pe: Optional[float] = None
    start: Optional[int] = None
    end: Optional[int] = None
    baseline: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AfterpulseRecord:
    event_index: Optional[int] = None
    channel_index: Optional[int] = None
    delay_time: Optional[float] = None
    height: Optional[float] = None
    charge: Optional[float] = None
    charge_pe: Optional[float] = None
    start: Optional[int] = None
    end: Optional[int] = None
    min_point: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelAppResult:
    board: int = 0
    channel: int = 0
    main_pulses: List[MainPulseRecord] = field(default_factory=list)
    afterpulses: List[AfterpulseRecord] = field(default_factory=list)
    main_pulse_count: int = 0
    afterpulse_candidate_count: int = 0
    afterpulse_count: int = 0
    main_pulse_with_afterpulse_count: int = 0
    main_pulse_charge: float = 0.0
    afterpulse_charge: float = 0.0
    app_value: Optional[float] = None
    spe_gain: Optional[float] = None
    main_pulse_charge_pe: float = 0.0
    afterpulse_charge_pe: float = 0.0
    app_value_pe: Optional[float] = None


@dataclass
class AppAnalysisResult:
    channels: List[ChannelAppResult] = field(default_factory=list)
    main_pulse_count: int = 0
    afterpulse_candidate_count: int = 0
    afterpulse_count: int = 0
    main_pulse_with_afterpulse_count: int = 0
    app_value: Optional[float] = None
    app_value_pe: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def filter_points(points: List[int], min_interval: int) -> List[int]:
    filtered: List[int] = []
    last_idx: Optional[int] = None
    for idx in points:
        if last_idx is None or idx - last_idx >= min_interval:
            filtered.append(idx)
            last_idx = idx
    return filtered


def cal_area(waveform: np.ndarray, st: int, ed: int, baseline: float) -> float:
    if ed <= st:
        return 0.0
    sum_val = np.sum(waveform[st:ed])
    area = baseline * (ed - st) - sum_val
    return float(area * PE_FACT)


def findpulse_st_ed(
    waveform: np.ndarray,
    baseline: float,
    reference_point: int,
    search_range: int = 5,
) -> Tuple[int, int, int]:
    start_range = max(0, reference_point - search_range)
    end_range = min(len(waveform), reference_point + search_range)

    min_index = reference_point
    min_value = waveform[reference_point]
    for i in range(start_range, end_range):
        if waveform[i] < min_value:
            min_value = waveform[i]
            min_index = i

    start_index = min_index
    while start_index > start_range:
        if (waveform[start_index] - waveform[start_index - 1]) < 0:
            start_index -= 1
        else:
            break

    end_index = min_index
    if end_index + 1 < end_range and waveform[min_index] == waveform[end_index + 1]:
        end_index += 1

    while end_index + 1 < end_range:
        if (waveform[end_index + 1] - waveform[end_index]) > 0:
            end_index += 1
        else:
            break

    return start_index, min_index, end_index


def iter_waveforms(bundle: RawDataBundle):
    rv = bundle.data
    records = rv.records

    for i in range(len(records)):
        rec = records[i]
        record_id = int(rec["record_id"])
        board = int(rec["board"])
        channel = int(rec["channel"])
        wave = rv.signals(np.array([record_id]))[0]
        yield i, board, channel, record_id, wave


def preprocess_waveform(waveform: np.ndarray) -> Tuple[np.ndarray, float]:
    n_baseline = min(30, len(waveform))
    baseline = float(np.mean(waveform[:n_baseline]))
    return waveform - baseline, baseline


def find_main_pulses_per_channel(
    bundle: RawDataBundle,
    height_threshold: float = DEFAULT_MAIN_PULSE_HEIGHT_THRESHOLD,
) -> Dict[Tuple[int, int], List[MainPulseRecord]]:
    """Find main pulses, grouped by (board, channel).

    Returns:
        Dict mapping (board, channel) -> list of MainPulseRecord
    """
    grouped: Dict[Tuple[int, int], List[MainPulseRecord]] = {}

    for record_idx, board, channel, record_id, waveform in iter_waveforms(bundle):
        processed, baseline = preprocess_waveform(waveform)

        min_idx = int(np.argmin(processed))
        pulse_height = abs(float(processed[min_idx]))

        if pulse_height < height_threshold:
            continue

        start_idx = min_idx
        while start_idx > 0:
            if processed[start_idx] > processed[start_idx - 1]:
                break
            start_idx -= 1

        end_idx = min_idx
        baseline_threshold = 50.0  # ADC — pulse ends when signal returns to within this of baseline
        baseline_return_count = 0
        baseline_return_needed = 3  # need this many consecutive samples near baseline
        while end_idx < len(processed) - 1:
            end_idx += 1
            if abs(processed[end_idx]) < baseline_threshold:
                baseline_return_count += 1
                if baseline_return_count >= baseline_return_needed:
                    break
            else:
                baseline_return_count = 0

        charge = cal_area(processed, start_idx, end_idx + 1, 0.0)

        mp = MainPulseRecord(
            event_index=record_idx,
            channel_index=channel,
            sample_index=min_idx,
            height=pulse_height,
            charge=charge,
            start=start_idx,
            end=end_idx + 1,
            baseline=baseline,
            metadata={
                "board": board,
                "record_id": record_id,
            },
        )

        key = (board, channel)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(mp)

    return grouped


def find_afterpulse_candidates_per_channel(
    bundle: RawDataBundle,
    main_pulses_by_channel: Dict[Tuple[int, int], List[MainPulseRecord]],
    amplitude_threshold: float = DEFAULT_AMPLITUDE_THRESHOLD,
    afterpulse_min_interval: int = DEFAULT_AFTERPULSE_MIN_INTERVAL,
) -> Dict[Tuple[int, int], List[AfterpulseRecord]]:
    """Find afterpulse candidates per channel.

    Returns:
        Dict mapping (board, channel) -> list of AfterpulseRecord
    """
    grouped: Dict[Tuple[int, int], List[AfterpulseRecord]] = {}
    rv = bundle.data
    records = rv.records

    # Build record_id -> main pulses lookup per channel
    mp_by_record_ch: Dict[Tuple[int, int, int], List[MainPulseRecord]] = {}
    for (board, channel), pulses in main_pulses_by_channel.items():
        for mp in pulses:
            record_id = mp.metadata.get("record_id")
            if record_id is not None:
                key = (board, channel, record_id)
                if key not in mp_by_record_ch:
                    mp_by_record_ch[key] = []
                mp_by_record_ch[key].append(mp)

    for i in range(len(records)):
        rec = records[i]
        record_id = int(rec["record_id"])
        board = int(rec["board"])
        channel = int(rec["channel"])

        key = (board, channel, record_id)
        if key not in mp_by_record_ch:
            continue

        waveform = rv.signals(np.array([record_id]))[0]
        processed, baseline = preprocess_waveform(waveform)

        for mp in mp_by_record_ch[key]:
            if mp.end is None:
                continue

            search_start = mp.end + afterpulse_min_interval
            if search_start >= len(processed):
                continue

            ref_points: List[int] = []
            above_threshold = False

            for j in range(search_start, len(processed)):
                if processed[j] < -amplitude_threshold:
                    if not above_threshold:
                        ref_points.append(j)
                        above_threshold = True
                else:
                    above_threshold = False

            ref_points = filter_points(ref_points, 2)

            ch_key = (board, channel)
            if ch_key not in grouped:
                grouped[ch_key] = []

            pulse_idx = 1
            for ref_idx in ref_points:
                try:
                    st, minp, ed = findpulse_st_ed(processed, 0.0, ref_idx)
                except Exception:
                    continue

                if ed < st:
                    continue

                pulse_height = abs(float(processed[minp]))
                if pulse_height < amplitude_threshold:
                    continue

                charge = cal_area(processed, st, ed + 1, 0.0)
                delay_start = st - (mp.end if mp.end else 0)
                dt_ns = float(rec["dt"])  # ns per sample
                delay_time_ns = delay_start * dt_ns

                ap = AfterpulseRecord(
                    event_index=mp.event_index,
                    channel_index=channel,
                    delay_time=float(delay_time_ns),
                    height=pulse_height,
                    charge=charge,
                    start=st,
                    end=ed + 1,
                    min_point=minp,
                    metadata={
                        "board": board,
                        "record_id": record_id,
                        "pulse_index": pulse_idx,
                        "main_pulse_end": mp.end,
                        "dt_ns": dt_ns,
                    },
                )
                grouped[ch_key].append(ap)
                pulse_idx += 1

    return grouped


def select_afterpulses_per_channel(
    afterpulses_by_channel: Dict[Tuple[int, int], List[AfterpulseRecord]],
    min_interval: int = DEFAULT_MIN_INTERVAL_BETWEEN_PULSES,
) -> Dict[Tuple[int, int], List[AfterpulseRecord]]:
    """Filter afterpulse candidates per channel."""
    result: Dict[Tuple[int, int], List[AfterpulseRecord]] = {}

    for ch_key, afterpulses in afterpulses_by_channel.items():
        if not afterpulses:
            result[ch_key] = []
            continue

        grouped: Dict[int, List[AfterpulseRecord]] = {}
        for ap in afterpulses:
            rid = ap.metadata.get("record_id", -1)
            if rid not in grouped:
                grouped[rid] = []
            grouped[rid].append(ap)

        filtered: List[AfterpulseRecord] = []
        for rid, group in grouped.items():
            group.sort(key=lambda x: x.min_point or 0)
            last_min_point: Optional[int] = None
            for ap in group:
                if last_min_point is None or (ap.min_point or 0) - last_min_point >= min_interval:
                    filtered.append(ap)
                    last_min_point = ap.min_point

        result[ch_key] = filtered

    return result


def load_spe_gains_by_pmt_id(
    pmt_id_map: Dict[Tuple[int, int], str],
) -> Dict[Tuple[int, int], float]:
    """Load SPE gains from pmtdata database by pmt_id.

    Tries pmtdata client first, then falls back to local SQLite DB.

    Args:
        pmt_id_map: Dict mapping (board, channel) -> pmt_id

    Returns:
        Dict mapping (board, channel) -> spe_gain
    """
    gains: Dict[Tuple[int, int], float] = {}
    missing_pmt_ids = set(pmt_id_map.values())

    # Try pmtdata client first
    try:
        import pmtdata as pmt
        with pmt.PMTDataClient(use_remote=False) as client:
            df = client.get_pmt_data()
            for ch_key, pmt_id in pmt_id_map.items():
                df_pmt = df[df['pmt_id'] == pmt_id]
                if df_pmt.empty:
                    continue
                df_latest = df_pmt.sort_values('measurement_time').iloc[-1]
                gain = float(df_latest['gain'])
                gains[ch_key] = gain
                missing_pmt_ids.discard(pmt_id)
                print(f"  Loaded SPE gain: {pmt_id} (Board {ch_key[0]}, CH {ch_key[1]}) = {gain:.4f}")
    except ImportError:
        print("  WARNING: pmtdata not available, trying local DB")
    except Exception as e:
        print(f"  WARNING: pmtdata client failed: {e}, trying local DB")

    # Fallback: query local SQLite DB
    if missing_pmt_ids:
        try:
            import sqlite3
            from pmt_analysis.config import DEFAULT_DB_PATH
            conn = sqlite3.connect(DEFAULT_DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "SELECT pmt_id, spe_gain FROM measurements "
                "WHERE spe_gain IS NOT NULL AND pmt_id IN ({})".format(
                    ",".join("?" * len(missing_pmt_ids))
                ),
                list(missing_pmt_ids),
            )
            db_gains = {row[0]: row[1] for row in cur.fetchall()}
            conn.close()
            for ch_key, pmt_id in pmt_id_map.items():
                if ch_key in gains:
                    continue
                gain = db_gains.get(pmt_id)
                if gain is not None:
                    gains[ch_key] = gain
                    print(f"  Loaded SPE gain (local DB): {pmt_id} (Board {ch_key[0]}, CH {ch_key[1]}) = {gain:.4f}")
        except Exception as e:
            print(f"  WARNING: Failed to load SPE gains from local DB: {e}")

    if not gains:
        print("  WARNING: No SPE gains loaded, PE normalization will be skipped")
    return gains


def normalize_to_pe_per_channel(
    main_pulses_by_channel: Dict[Tuple[int, int], List[MainPulseRecord]],
    afterpulses_by_channel: Dict[Tuple[int, int], List[AfterpulseRecord]],
    spe_gains: Dict[Tuple[int, int], float],
) -> Dict[Tuple[int, int], float]:
    """Divide raw charges by SPE gain to get PE-normalized charges.

    Sets charge_pe on each MainPulseRecord and AfterpulseRecord.

    Returns:
        Dict mapping (board, channel) -> spe_gain used
    """
    for ch_key, pulses in main_pulses_by_channel.items():
        gain = spe_gains.get(ch_key)
        for mp in pulses:
            if gain is not None and gain > 0 and mp.charge is not None:
                mp.charge_pe = mp.charge / gain

    for ch_key, pulses in afterpulses_by_channel.items():
        gain = spe_gains.get(ch_key)
        for ap in pulses:
            if gain is not None and gain > 0 and ap.charge is not None:
                ap.charge_pe = ap.charge / gain

    return spe_gains


def compute_app_per_channel(
    main_pulses_by_channel: Dict[Tuple[int, int], List[MainPulseRecord]],
    afterpulses_by_channel: Dict[Tuple[int, int], List[AfterpulseRecord]],
    spe_gains: Dict[Tuple[int, int], float],
) -> List[ChannelAppResult]:
    """Compute APP for each channel independently."""
    all_keys = set(main_pulses_by_channel.keys()) | set(afterpulses_by_channel.keys())
    results: List[ChannelAppResult] = []

    for ch_key in sorted(all_keys):
        board, channel = ch_key
        main_pulses = main_pulses_by_channel.get(ch_key, [])
        afterpulses = afterpulses_by_channel.get(ch_key, [])

        main_count = len(main_pulses)
        ap_count = len(afterpulses)

        # Raw charge
        main_charge = sum(mp.charge or 0 for mp in main_pulses)
        ap_charge = sum(ap.charge or 0 for ap in afterpulses)
        app_raw = (ap_charge / main_charge) if main_charge > 0 else None

        # PE-normalized charge
        spe_gain = spe_gains.get(ch_key)
        main_charge_pe = sum(mp.charge_pe or 0 for mp in main_pulses)
        ap_charge_pe = sum(ap.charge_pe or 0 for ap in afterpulses)
        app_pe = (ap_charge_pe / main_charge_pe) if main_charge_pe > 0 else None

        # Count main pulses that have afterpulses
        main_ids = set(ap.event_index for ap in afterpulses)

        results.append(ChannelAppResult(
            board=board,
            channel=channel,
            main_pulses=main_pulses,
            afterpulses=afterpulses,
            main_pulse_count=main_count,
            afterpulse_count=ap_count,
            main_pulse_with_afterpulse_count=len(main_ids),
            main_pulse_charge=main_charge,
            afterpulse_charge=ap_charge,
            app_value=app_raw,
            spe_gain=spe_gain,
            main_pulse_charge_pe=main_charge_pe,
            afterpulse_charge_pe=ap_charge_pe,
            app_value_pe=app_pe,
        ))

    return results


def print_main_pulse_summary(
    channel_results: List[ChannelAppResult],
    pmt_id_map: Dict[Tuple[int, int], str],
    n_show: int = 5,
) -> None:
    """Print first n main pulses per channel for quick inspection."""
    print("  --- Main Pulse Summary (first few per channel) ---")
    for ch_r in channel_results:
        ch = ch_r.channel
        pmt_id = pmt_id_map.get((ch_r.board, ch), "?")
        print(f"  CH{ch} ({pmt_id}): {ch_r.main_pulse_count} main pulses")
        for mp in ch_r.main_pulses[:n_show]:
            mp_pe = f"{mp.charge_pe:.4f}" if mp.charge_pe is not None else "N/A"
            print(
                f"    height={mp.height:.1f} ADC, "
                f"area={mp.charge:.4f}, area_pe={mp_pe}, "
                f"start={mp.start}, end={mp.end}"
            )
        if ch_r.main_pulse_count > n_show:
            print(f"    ... ({ch_r.main_pulse_count - n_show} more)")
    print()


def print_afterpulse_summary(
    channel_results: List[ChannelAppResult],
    pmt_id_map: Dict[Tuple[int, int], str],
    n_show: int = 10,
) -> None:
    """Print first n afterpulses per channel for quick inspection."""
    print("  --- Afterpulse Summary (first few per channel) ---")
    for ch_r in channel_results:
        ch = ch_r.channel
        pmt_id = pmt_id_map.get((ch_r.board, ch), "?")
        print(f"  CH{ch} ({pmt_id}): {ch_r.afterpulse_count} afterpulses")
        for ap in ch_r.afterpulses[:n_show]:
            ap_pe = f"{ap.charge_pe:.4f}" if ap.charge_pe is not None else "N/A"
            print(
                f"    delta_time={ap.delay_time:.1f} ns, "
                f"area={ap.charge:.4f}, area_pe={ap_pe}, "
                f"height={ap.height:.1f} ADC"
            )
        if ch_r.afterpulse_count > n_show:
            print(f"    ... ({ch_r.afterpulse_count - n_show} more)")
    print()


def plot_afterpulse_2d_histogram(
    channel_results: List[ChannelAppResult],
    pmt_id_map: Dict[Tuple[int, int], str],
    run_id: str,
    output_path: str,
    sample_rate_hz: float = 250e6,
) -> str:
    """Plot 2D histogram of afterpulse area_pe vs delta_time for each channel.

    Each channel gets a two-panel figure:
      - Top: 2D histogram (delta_time vs area_pe) with log color scale
      - Bottom: 1D projection of delta_time distribution

    Ion position markers are overlaid as vertical dashed lines.

    Args:
        channel_results: Per-channel results
        pmt_id_map: Board/channel -> pmt_id mapping
        run_id: Run ID for title
        output_path: Directory to save figures (one per channel)
        sample_rate_hz: DAQ sampling rate for converting samples to time

    Returns:
        Path to saved figure directory
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.colors
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter
    from mpl_toolkits.axes_grid1 import make_axes_locatable
    from pathlib import Path

    ns_to_us = 1e3 / sample_rate_hz

    # Ion identification positions (us)
    ion_labels_light = ["H$^+$", "He$^+$"]
    positions_light = [0.28, 0.56]
    ion_labels_heavy = ["CH$_4^+$", "N$_2^+$", "Ar$^+$", "Xe$^{++}$", "Xe$^+$"]
    positions_heavy = [1.01, 1.33, 1.58, 2.02, 2.85]

    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []

    for ch_r in channel_results:
        ch = ch_r.channel
        pmt_id = pmt_id_map.get((ch_r.board, ch), "?")

        delta_times = np.array([
            ap.delay_time / 1000.0 for ap in ch_r.afterpulses if ap.delay_time is not None
        ])  # ns -> us
        area_pes = np.array([
            ap.charge_pe for ap in ch_r.afterpulses if ap.charge_pe is not None
        ])

        if len(delta_times) == 0 or len(area_pes) == 0:
            continue

        dt_max = min(np.percentile(delta_times, 99.5), 5.5)  # us
        area_max = min(np.percentile(area_pes, 99.5), 30.0)

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(5, 5), sharex=True)

        # --- Top: 2D histogram ---
        hist = ax1.hist2d(
            delta_times, area_pes,
            bins=[80, 80],
            range=[[0, dt_max], [0, area_max]],
            cmap="jet",
            density=True,
            norm=matplotlib.colors.LogNorm(),
        )

        divider = make_axes_locatable(ax1)
        cax = divider.append_axes("right", size="5%", pad=0.1)
        cbar = plt.colorbar(hist[3], ax=cax)
        cbar.set_label("Density", fontsize=10)
        cbar.ax.tick_params(labelsize=8)

        ax1.set_ylabel("Afterpulse Area [PE]", fontsize=11)
        ax1.tick_params(axis="y", direction="in", labelsize=9, pad=4, length=4, width=1)

        # Ion markers — light
        for pos, label in zip(positions_light, ion_labels_light):
            if pos <= dt_max:
                ax1.axvline(pos, color="red", alpha=0.8, linestyle="--", linewidth=1)
                ax2.axvline(pos, color="red", alpha=0.8, linestyle="--", linewidth=1)
                ax2.text(pos, ax2.get_ylim()[1] if ax2.get_ylim()[1] > 0 else 1e4,
                         label, ha="center", va="top", fontsize=8, color="black",
                         rotation=90)

        # Ion markers — heavy
        for pos, label in zip(positions_heavy, ion_labels_heavy):
            if pos <= dt_max:
                ax1.axvline(pos, color="grey", alpha=0.8, linestyle="--", linewidth=1)
                ax2.axvline(pos, color="grey", alpha=0.8, linestyle="--", linewidth=1)
                ax2.text(pos, ax2.get_ylim()[1] if ax2.get_ylim()[1] > 0 else 1e4,
                         label, ha="center", va="top", fontsize=8, color="black",
                         rotation=90)

        # --- Bottom: 1D delta_time histogram ---
        ax2.hist(
            delta_times,
            bins=80,
            range=(0, dt_max),
            histtype="stepfilled",
            color="skyblue",
            edgecolor="skyblue",
            linewidth=0.8,
            alpha=0.9,
        )
        ax2.set_ylabel("Counts", fontsize=11)
        ax2.set_xlabel("Time Delay [$\\mu$s]", fontsize=11)
        ax2.tick_params(axis="x", direction="in", labelsize=9, pad=4, length=4, width=1)
        ax2.tick_params(axis="y", direction="in", labelsize=9, pad=4, length=4, width=1)

        ax2.yaxis.set_major_formatter(ScalarFormatter(useMathText=True))
        ax2.ticklabel_format(style="sci", axis="y", scilimits=(4, 4))
        ax2.yaxis.get_offset_text().set_fontsize(9)

        plt.subplots_adjust(hspace=0)

        fig.suptitle(
            f"Run {run_id} — CH{ch} ({pmt_id}) — {len(delta_times)} afterpulses",
            fontsize=10, y=0.98,
        )

        ch_path = str(out_dir / f"run{run_id}_afterpulse_2d_ch{ch}.png")
        fig.savefig(ch_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        saved_files.append(ch_path)

    return saved_files


def plot_main_pulse_diagnostics(
    channel_results: List[ChannelAppResult],
    pmt_id_map: Dict[Tuple[int, int], str],
    run_id: str,
    output_dir: str,
) -> List[str]:
    """Plot main pulse parameter histograms for each channel.

    For each channel, generates a 2x2 figure with:
      - Top-left: height (ADC) histogram
      - Top-right: area (raw) histogram
      - Bottom-left: area_pe (PE) histogram
      - Bottom-right: baseline (ADC) histogram

    Returns:
        List of saved file paths
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved_files = []

    for ch_r in channel_results:
        ch = ch_r.channel
        pmt_id = pmt_id_map.get((ch_r.board, ch), "?")

        heights = np.array([mp.height for mp in ch_r.main_pulses if mp.height is not None])
        charges = np.array([mp.charge for mp in ch_r.main_pulses if mp.charge is not None])
        charge_pes = np.array([mp.charge_pe for mp in ch_r.main_pulses if mp.charge_pe is not None])
        baselines = np.array([mp.baseline for mp in ch_r.main_pulses if mp.baseline is not None])

        if len(heights) == 0:
            continue

        fig, axes = plt.subplots(2, 2, figsize=(8, 6))
        fig.suptitle(
            f"Run {run_id} — CH{ch} ({pmt_id}) — {len(heights)} main pulses",
            fontsize=10, y=0.98,
        )

        # Height
        ax = axes[0, 0]
        ax.hist(heights, bins=60, color="steelblue", edgecolor="steelblue", alpha=0.85)
        ax.set_xlabel("Height [ADC]", fontsize=9)
        ax.set_ylabel("Counts", fontsize=9)
        ax.tick_params(labelsize=8, length=3, width=0.8)
        mean_h = np.mean(heights)
        ax.axvline(mean_h, color="red", linestyle="--", linewidth=1, label=f"mean={mean_h:.0f}")
        ax.legend(fontsize=7)

        # Area (raw)
        ax = axes[0, 1]
        ax.hist(charges, bins=60, color="darkorange", edgecolor="darkorange", alpha=0.85)
        ax.set_xlabel("Area [raw]", fontsize=9)
        ax.set_ylabel("Counts", fontsize=9)
        ax.tick_params(labelsize=8, length=3, width=0.8)
        mean_c = np.mean(charges)
        ax.axvline(mean_c, color="red", linestyle="--", linewidth=1, label=f"mean={mean_c:.1f}")
        ax.legend(fontsize=7)

        # Area (PE)
        ax = axes[1, 0]
        if len(charge_pes) > 0:
            ax.hist(charge_pes, bins=60, color="seagreen", edgecolor="seagreen", alpha=0.85)
            mean_pe = np.mean(charge_pes)
            ax.axvline(mean_pe, color="red", linestyle="--", linewidth=1, label=f"mean={mean_pe:.1f}")
            ax.legend(fontsize=7)
        else:
            ax.text(0.5, 0.5, "No PE data", transform=ax.transAxes,
                    ha="center", va="center", fontsize=9, color="gray")
        ax.set_xlabel("Area [PE]", fontsize=9)
        ax.set_ylabel("Counts", fontsize=9)
        ax.tick_params(labelsize=8, length=3, width=0.8)

        # Baseline
        ax = axes[1, 1]
        if len(baselines) > 0:
            ax.hist(baselines, bins=60, color="mediumpurple", edgecolor="mediumpurple", alpha=0.85)
            mean_bl = np.mean(baselines)
            ax.axvline(mean_bl, color="red", linestyle="--", linewidth=1, label=f"mean={mean_bl:.1f}")
            ax.legend(fontsize=7)
        else:
            ax.text(0.5, 0.5, "No baseline data", transform=ax.transAxes,
                    ha="center", va="center", fontsize=9, color="gray")
        ax.set_xlabel("Baseline [ADC]", fontsize=9)
        ax.set_ylabel("Counts", fontsize=9)
        ax.tick_params(labelsize=8, length=3, width=0.8)

        plt.tight_layout(rect=[0, 0, 1, 0.96])
        ch_path = str(out_dir / f"run{run_id}_main_pulse_ch{ch}.png")
        fig.savefig(ch_path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        saved_files.append(ch_path)

    return saved_files


def plot_afterpulse_delta_time_all_channels(
    channel_results: List[ChannelAppResult],
    pmt_id_map: Dict[Tuple[int, int], str],
    run_id: str,
    output_path: str,
) -> str:
    """Plot delta_time distribution for all channels on one canvas.

    Each channel gets a small subplot. Ion position markers are overlaid.

    Args:
        channel_results: Per-channel results
        pmt_id_map: Board/channel -> pmt_id mapping
        run_id: Run ID for title
        output_path: Path to save the figure

    Returns:
        Path to saved figure
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter
    from pathlib import Path

    n_ch = len(channel_results)
    rows, cols = 3, 3

    fig, axes = plt.subplots(rows, cols, figsize=(2.5 * cols, 2.2 * rows), sharex=True, sharey=True)
    if rows == 1 and cols == 1:
        axes = np.array([[axes]])
    elif rows == 1:
        axes = axes.reshape(1, -1)
    elif cols == 1:
        axes = axes.reshape(-1, 1)

    # Ion markers
    ion_labels = ["H$^+$", "He$^+$", "CH$_4^+$", "N$_2^+$", "Ar$^+$", "Xe$^{++}$", "Xe$^+$"]
    positions = [0.28, 0.56, 1.01, 1.33, 1.58, 2.02, 2.85]

    for idx, ch_r in enumerate(channel_results):
        row = idx // cols
        col = idx % cols
        ax = axes[row, col]
        ch = ch_r.channel
        pmt_id = pmt_id_map.get((ch_r.board, ch), "?")

        delta_times_us = np.array([
            ap.delay_time / 1000.0 for ap in ch_r.afterpulses if ap.delay_time is not None
        ])

        if len(delta_times_us) == 0:
            ax.text(0.5, 0.5, f"CH{ch}: no afterpulses", transform=ax.transAxes,
                    ha="center", va="center", fontsize=8, color="gray")
            ax.set_title(f"CH{ch} ({pmt_id})", fontsize=8)
            continue

        ax.hist(delta_times_us, bins=80, range=(0, 4),
                histtype="stepfilled", color="skyblue", edgecolor="skyblue",
                linewidth=0.8, alpha=0.9)

        # Ion markers
        ymax = ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 1e4
        for pos, label in zip(positions, ion_labels):
            if pos <= 4.0:
                ax.axvline(pos, color="red", alpha=0.8, linestyle="--", linewidth=0.6)
                ax.text(pos, ymax * 0.95, label, ha="center", va="top",
                        fontsize=6, color="black", rotation=90)

        ax.set_title(f"CH{ch} ({pmt_id}) — {len(delta_times_us)} AP", fontsize=8)
        ax.set_xlim(0, 4)
        ax.tick_params(labelsize=7, length=3, width=0.8)
        ax.yaxis.set_major_formatter(ScalarFormatter(useMathText=True))
        ax.ticklabel_format(style="sci", axis="y", scilimits=(4, 4))
        ax.yaxis.get_offset_text().set_fontsize(6)

    # Hide unused axes
    for idx in range(n_ch, rows * cols):
        row = idx // cols
        col = idx % cols
        axes[row, col].set_visible(False)

    # X label only on bottom row
    for col in range(cols):
        axes[-1, col].set_xlabel("Delay Time [$\\mu$s]", fontsize=8)

    # Y label only on left column
    for row in range(rows):
        axes[row, 0].set_ylabel("Counts", fontsize=8)

    fig.suptitle(f"Run {run_id} — Afterpulse Delta Time Distribution", fontsize=9, y=1.01)
    plt.tight_layout(rect=[0, 0, 1, 0.99])

    out = str(Path(output_path) / f"run{run_id}_afterpulse_delta_time_all.png")
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_main_pulse_area_all_channels(
    channel_results: List[ChannelAppResult],
    pmt_id_map: Dict[Tuple[int, int], str],
    run_id: str,
    output_path: str,
) -> str:
    """Plot main pulse area distribution for all channels in a 3x3 grid.

    Each channel gets a small subplot showing the area histogram.

    Args:
        channel_results: Per-channel results
        pmt_id_map: Board/channel -> pmt_id mapping
        run_id: Run ID for title
        output_path: Path to save the figure

    Returns:
        Path to saved figure
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path

    n_ch = len(channel_results)
    rows, cols = 3, 3

    fig, axes = plt.subplots(rows, cols, figsize=(2.5 * cols, 2.2 * rows), sharex=False, sharey=True)
    if rows == 1 and cols == 1:
        axes = np.array([[axes]])
    elif rows == 1:
        axes = axes.reshape(1, -1)
    elif cols == 1:
        axes = axes.reshape(-1, 1)

    for idx, ch_r in enumerate(channel_results):
        row = idx // cols
        col = idx % cols
        ax = axes[row, col]
        ch = ch_r.channel
        pmt_id = pmt_id_map.get((ch_r.board, ch), "?")

        charges_pe = np.array([mp.charge_pe for mp in ch_r.main_pulses if mp.charge_pe is not None])

        if len(charges_pe) == 0:
            ax.text(0.5, 0.5, f"CH{ch}: no data", transform=ax.transAxes,
                    ha="center", va="center", fontsize=8, color="gray")
            ax.set_title(f"CH{ch} ({pmt_id})", fontsize=8)
            continue

        mean_pe = np.mean(charges_pe)
        std_pe = np.std(charges_pe)

        ax.hist(charges_pe, bins=60, color="steelblue", edgecolor="steelblue",
                linewidth=0.6, alpha=0.85)
        ax.axvline(mean_pe, color="red", linestyle="--", linewidth=0.8,
                   label=f"mean={mean_pe:.1f}")
        ax.legend(fontsize=6, loc="upper right")

        ax.set_title(f"CH{ch} ({pmt_id}) — {len(charges_pe)} pulses", fontsize=8)
        ax.tick_params(labelsize=7, length=3, width=0.8)

    # Hide unused axes
    for idx in range(n_ch, rows * cols):
        row = idx // cols
        col = idx % cols
        axes[row, col].set_visible(False)

    # X label only on bottom row
    for col in range(cols):
        axes[-1, col].set_xlabel("Main Pulse Area [PE]", fontsize=8)

    # Y label only on left column
    for row in range(rows):
        axes[row, 0].set_ylabel("Counts", fontsize=8)

    fig.suptitle(f"Run {run_id} — Main Pulse Area Distribution", fontsize=9, y=1.01)
    plt.tight_layout(rect=[0, 0, 1, 0.99])

    out = str(Path(output_path) / f"run{run_id}_main_pulse_area_all.png")
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out


def save_diagnostics_npz(
    channel_results: List[ChannelAppResult],
    pmt_id_map: Dict[Tuple[int, int], str],
    run_id: str,
    output_dir: str,
) -> List[str]:
    """Save main pulse and afterpulse data per channel as .npz files.

    Creates one file per channel: run{run_id}_ch{ch}.npz
    Contains:
        main: height, area, area_pe, start, end
        afterpulse: delta_time, area, area_pe, height, start, end

    Returns:
        List of saved file paths
    """
    from pathlib import Path

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    saved = []

    for ch_r in channel_results:
        ch = ch_r.channel
        board = ch_r.board
        pmt_id = pmt_id_map.get((board, ch), "?")

        # Main pulses
        n_main = len(ch_r.main_pulses)
        mp_height = np.array([mp.height for mp in ch_r.main_pulses]) if n_main > 0 else np.array([])
        mp_area = np.array([mp.charge for mp in ch_r.main_pulses]) if n_main > 0 else np.array([])
        mp_area_pe = np.array([mp.charge_pe if mp.charge_pe is not None else 0.0 for mp in ch_r.main_pulses]) if n_main > 0 else np.array([])
        mp_start = np.array([mp.start for mp in ch_r.main_pulses]) if n_main > 0 else np.array([], dtype=int)
        mp_end = np.array([mp.end for mp in ch_r.main_pulses]) if n_main > 0 else np.array([], dtype=int)

        # Afterpulses
        n_ap = len(ch_r.afterpulses)
        ap_delay = np.array([ap.delay_time for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([])
        ap_area = np.array([ap.charge for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([])
        ap_area_pe = np.array([ap.charge_pe if ap.charge_pe is not None else 0.0 for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([])
        ap_height = np.array([ap.height for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([])
        ap_start = np.array([ap.start for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([], dtype=int)
        ap_end = np.array([ap.end for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([], dtype=int)

        path = out / f"run{run_id}_{pmt_id}_ch{ch}.npz"
        np.savez_compressed(
            path,
            run_id=run_id,
            pmt_id=pmt_id,
            board=board,
            channel=ch,
            main_height=mp_height,
            main_area=mp_area,
            main_area_pe=mp_area_pe,
            main_start=mp_start,
            main_end=mp_end,
            ap_delta_time=ap_delay,
            ap_area=ap_area,
            ap_area_pe=ap_area_pe,
            ap_height=ap_height,
            ap_start=ap_start,
            ap_end=ap_end,
        )
        saved.append(str(path))

    # Save combined file with all channels
    combined = {
        "run_id": run_id,
        "channels": np.array([ch_r.channel for ch_r in channel_results]),
        "pmt_ids": np.array([pmt_id_map.get((ch_r.board, ch_r.channel), "?") for ch_r in channel_results]),
    }
    for ch_r in channel_results:
        ch = ch_r.channel
        n_main = len(ch_r.main_pulses)
        n_ap = len(ch_r.afterpulses)
        combined[f"ch{ch}_main_height"] = np.array([mp.height for mp in ch_r.main_pulses]) if n_main > 0 else np.array([])
        combined[f"ch{ch}_main_area"] = np.array([mp.charge for mp in ch_r.main_pulses]) if n_main > 0 else np.array([])
        combined[f"ch{ch}_main_area_pe"] = np.array([mp.charge_pe if mp.charge_pe is not None else 0.0 for mp in ch_r.main_pulses]) if n_main > 0 else np.array([])
        combined[f"ch{ch}_main_start"] = np.array([mp.start for mp in ch_r.main_pulses]) if n_main > 0 else np.array([], dtype=int)
        combined[f"ch{ch}_main_end"] = np.array([mp.end for mp in ch_r.main_pulses]) if n_main > 0 else np.array([], dtype=int)
        combined[f"ch{ch}_ap_delta_time"] = np.array([ap.delay_time for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([])
        combined[f"ch{ch}_ap_area"] = np.array([ap.charge for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([])
        combined[f"ch{ch}_ap_area_pe"] = np.array([ap.charge_pe if ap.charge_pe is not None else 0.0 for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([])
        combined[f"ch{ch}_ap_height"] = np.array([ap.height for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([])
        combined[f"ch{ch}_ap_start"] = np.array([ap.start for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([], dtype=int)
        combined[f"ch{ch}_ap_end"] = np.array([ap.end for ap in ch_r.afterpulses]) if n_ap > 0 else np.array([], dtype=int)

    combined_path = out / f"run{run_id}_all_channels.npz"
    np.savez_compressed(combined_path, **combined)
    saved.append(str(combined_path))

    return saved


def analyze_app(
    bundle: RawDataBundle,
    main_pulse_height_threshold: float = DEFAULT_MAIN_PULSE_HEIGHT_THRESHOLD,
    amplitude_threshold: float = DEFAULT_AMPLITUDE_THRESHOLD,
    afterpulse_min_interval: int = DEFAULT_AFTERPULSE_MIN_INTERVAL,
    min_interval_between_pulses: int = DEFAULT_MIN_INTERVAL_BETWEEN_PULSES,
    pmt_id_map: Optional[Dict[Tuple[int, int], str]] = None,
) -> AppAnalysisResult:
    """Perform complete APP analysis.

    Steps:
        1. Find main pulses per channel
        2. Find afterpulse candidates per channel
        3. Select afterpulses per channel
        4. Load SPE gains by pmt_id (if pmt_id_map provided)
        5. Normalize charges to PE
        6. Compute APP per channel

    Args:
        bundle: Raw data bundle
        main_pulse_height_threshold: Minimum height for main pulse (ADC)
        amplitude_threshold: Minimum height for afterpulse (ADC)
        afterpulse_min_interval: Minimum samples between main pulse end and afterpulse
        min_interval_between_pulses: Minimum interval between afterpulses
        pmt_id_map: Dict mapping (board, channel) -> pmt_id for SPE gain lookup
    """
    try:
        # Step 1: Find main pulses per channel
        main_pulses_by_ch = find_main_pulses_per_channel(
            bundle, height_threshold=main_pulse_height_threshold,
        )

        # Step 2: Find afterpulse candidates per channel
        raw_afterpulses_by_ch = find_afterpulse_candidates_per_channel(
            bundle, main_pulses_by_ch,
            amplitude_threshold=amplitude_threshold,
            afterpulse_min_interval=afterpulse_min_interval,
        )

        # Step 3: Select afterpulses per channel
        afterpulses_by_ch = select_afterpulses_per_channel(
            raw_afterpulses_by_ch,
            min_interval=min_interval_between_pulses,
        )

        # Step 4: Load SPE gains by pmt_id
        spe_gains: Dict[Tuple[int, int], float] = {}
        if pmt_id_map:
            print(f"  Loading SPE gains from pmtdata...")
            spe_gains = load_spe_gains_by_pmt_id(pmt_id_map)
            if not spe_gains:
                print(f"  WARNING: No SPE gains loaded, PE normalization skipped")

        # Step 5: Normalize to PE
        normalize_to_pe_per_channel(main_pulses_by_ch, afterpulses_by_ch, spe_gains)

        # Step 6: Compute per-channel APP
        channel_results = compute_app_per_channel(
            main_pulses_by_ch, afterpulses_by_ch, spe_gains,
        )

        # Aggregate
        total_main = sum(r.main_pulse_count for r in channel_results)
        total_ap = sum(r.afterpulse_count for r in channel_results)
        total_ap_with = sum(r.main_pulse_with_afterpulse_count for r in channel_results)
        total_main_charge = sum(r.main_pulse_charge for r in channel_results)
        total_ap_charge = sum(r.afterpulse_charge for r in channel_results)
        total_main_charge_pe = sum(r.main_pulse_charge_pe for r in channel_results)
        total_ap_charge_pe = sum(r.afterpulse_charge_pe for r in channel_results)

        app_overall = (total_ap_charge / total_main_charge) if total_main_charge > 0 else None
        app_overall_pe = (total_ap_charge_pe / total_main_charge_pe) if total_main_charge_pe > 0 else None

        total_raw_ap = sum(len(v) for v in raw_afterpulses_by_ch.values())

        return AppAnalysisResult(
            channels=channel_results,
            main_pulse_count=total_main,
            afterpulse_candidate_count=total_raw_ap,
            afterpulse_count=total_ap,
            main_pulse_with_afterpulse_count=total_ap_with,
            app_value=app_overall,
            app_value_pe=app_overall_pe,
            metadata={
                "run_id": bundle.runinfo.run_id,
                "main_pulse_height_threshold": main_pulse_height_threshold,
                "amplitude_threshold": amplitude_threshold,
                "afterpulse_min_interval": afterpulse_min_interval,
                "spe_gains_loaded": bool(spe_gains),
            },
        )

    except Exception as e:
        raise AppAnalysisError(
            f"APP analysis failed for run_id={bundle.runinfo.run_id}: {e}"
        ) from e
