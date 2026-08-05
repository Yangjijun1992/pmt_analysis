"""Dark count analysis using ONLY the asymmetry cut (no noise-suppression filters).

Re-analyzes a Dark Rate run considering only:
    asymmetry = pulse_height / (pulse_height + overshoot) > 0.7  -> dark count
    otherwise                                                     -> noise

The rising-edge sharpness/prominence noise filters are optional refinements.
By default (require_edge_features=False) they are not applied, so
classification relies purely on asymmetry.
"""
import sys

import numpy as np

from pmt_analysis.analysis.dark_count import (
    estimate_total_daq_run_time_length,
    compute_pulse_record,
)
from pmt_analysis.io.raw_reader import NotebookBasedRawDataReader
from pmt_analysis.runinfo import get_runinfo

ASYMMETRY_THRESHOLD = 0.7


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "00368"
    ri = get_runinfo(run_id)
    bundle = NotebookBasedRawDataReader().read(ri)

    rv = bundle.data
    records = rv.records
    boards = sorted(set(records["board"].tolist()))

    daq_time_s = estimate_total_daq_run_time_length(bundle)
    if daq_time_s is None:
        daq_time_s = 0.0

    print(f"Run ID      : {run_id}")
    print(f"Total DAQ   : {daq_time_s:.3f} s")
    print(f"Method      : asymmetry cut only (threshold = {ASYMMETRY_THRESHOLD})")
    print()

    channels_per_board = {}
    for b in boards:
        chs = sorted(set(records[records["board"] == b]["channel"].tolist()))
        channels_per_board[b] = chs

    total_pulses = total_dark = total_noise = 0
    pmt_map = {}
    for board_info in ri.metadata.get("mapping", []):
        board_id = board_info["board_id"]
        for ch_info in board_info.get("channels", []):
            pmt_map[(board_id, ch_info["ch"])] = ch_info["pmt"]

    print(f"{'PMT_ID':<8} {'CH':>3} {'pulses':>9} {'dark':>9} {'noise':>9} {'rate(Hz)':>10}")
    for board in boards:
        for channel in channels_per_board[board]:
            mask = (records["board"] == board) & (records["channel"] == channel)
            rec_slice = records[mask]
            rec_ids = rec_slice["record_id"]
            rec_baselines = rec_slice["baseline"]

            if len(rec_ids) == 0:
                continue

            waves = rv.signals(rec_ids)

            dark = noise = 0
            for i in range(len(waves)):
                wave = waves[i]
                pulse = compute_pulse_record(
                    wave=wave,
                    record_id=int(rec_ids[i]),
                    board=board,
                    channel=channel,
                    asymmetry_threshold=ASYMMETRY_THRESHOLD,
                    record_baseline=float(rec_baselines[i]),
                    require_edge_features=False,  # asymmetry cut only
                )
                if pulse is None:
                    continue
                if pulse.is_dark_count:
                    dark += 1
                else:
                    noise += 1

            total_ch = dark + noise
            total_pulses += total_ch
            total_dark += dark
            total_noise += noise
            rate = dark / daq_time_s if daq_time_s > 0 else 0.0
            pmt_id = pmt_map.get((board, channel), "?")
            print(f"{pmt_id:<8} {channel:>3} {total_ch:>9} {dark:>9} {noise:>9} {rate:>10.2f}")

    total_rate = total_dark / daq_time_s if daq_time_s > 0 else 0.0
    print("-" * 55)
    print(f"TOTAL       : pulses={total_pulses}, dark={total_dark}, noise={total_noise}, rate={total_rate:.2f} Hz")


if __name__ == "__main__":
    main()
