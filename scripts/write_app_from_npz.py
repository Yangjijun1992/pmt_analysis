"""Write APP results for a run to the DB from saved per-channel .npz files.

Reconstructs each channel's raw APP (sum(ap_area)/sum(main_area)) from the
diagnostic .npz files saved by the analysis, then writes records via the
DB writer (which applies global pmt_id de-duplication).

Use when an APP analysis completed but its DB write was skipped (e.g. the
SPE gains were unavailable so app_value_pe was None and no record was built).

Usage:
    python scripts/write_app_from_npz.py --run-id 00388 \\
        --github-user Yangjijun1992 --github-token <token> [--output-dir ...]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from pmt_analysis.analysis.app import AppAnalysisResult, ChannelAppResult
from pmt_analysis.db.mapping import ChannelMapping, MappingTable, load_mapping_from_runinfo
from pmt_analysis.db.writer import write_analysis_results
from pmt_analysis.runinfo import get_runinfo

DEFAULT_OUTPUT_DIR = "/mnt/data/PMT/R8520_406/output"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write APP results from saved .npz to DB.")
    parser.add_argument("--run-id", required=True, help="5-digit run id")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory of .npz files")
    parser.add_argument("--github-user", required=True, help="Authorized GitHub username")
    parser.add_argument("--github-token", required=True, help="GitHub classic token")
    args = parser.parse_args()

    run_id = args.run_id
    ri = get_runinfo(run_id)
    raw_mapping = ri.metadata.get("mapping")
    if raw_mapping is None:
        print(f"No mapping found for run {run_id}; aborting.")
        return
    mapping = load_mapping_from_runinfo({"mapping": raw_mapping})

    out_dir = Path(args.output_dir)
    # Match per-channel files only (excludes run{id}_all_channels.npz)
    files = sorted(
        f for f in out_dir.glob(f"run{args.run_id}_*_ch*.npz")
        if "_all_channels" not in f.name
    )
    if not files:
        print(f"No per-channel .npz files found for run {run_id} in {out_dir}")
        return

    channels = []
    for f in files:
        data = np.load(f)
        pmt_id = str(data["pmt_id"])
        board = int(data["board"])
        channel = int(data["channel"])
        main_area = data["main_area"]
        ap_area = data["ap_area"]
        main_sum = float(main_area.sum()) if main_area.size else 0.0
        ap_sum = float(ap_area.sum()) if ap_area.size else 0.0
        app_raw = (ap_sum / main_sum) if main_sum > 0 else None
        data.close()

        channels.append(ChannelAppResult(
            board=board,
            channel=channel,
            main_pulse_count=int(len(main_area)),
            afterpulse_count=int(len(ap_area)),
            main_pulse_charge=main_sum,
            afterpulse_charge=ap_sum,
            app_value=app_raw,
            app_value_pe=None,
        ))
        print(f"  {pmt_id:<8} ch{channel}  raw APP = {app_raw:.6f}")

    app_result = AppAnalysisResult(
        channels=channels,
        main_pulse_count=sum(c.main_pulse_count for c in channels),
        afterpulse_count=sum(c.afterpulse_count for c in channels),
        app_value=(sum(c.afterpulse_charge for c in channels) /
                   sum(c.main_pulse_charge for c in channels)
                   if sum(c.main_pulse_charge for c in channels) > 0 else None),
    )

    count = write_analysis_results(
        db_path="/mnt/data/TPC/database/pmt_data.db",
        mapping=mapping,
        run_id=run_id,
        app_result=app_result,
        github_user=args.github_user,
        github_token=args.github_token,
    )
    print(f"Wrote {count} measurement record(s) for run {run_id}.")


if __name__ == "__main__":
    main()
