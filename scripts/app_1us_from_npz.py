"""Compute afterpulse probability within a time window after the main pulse.

Reads a saved per-channel .npz diagnostics file and prints the main pulse
area and the afterpulse probability for an arbitrary run_id / pmt_id / channel.

Usage:
    python scripts/app_1us_from_npz.py --run-id 00354 --pmt-id LV2264 --channel 4
    python scripts/app_1us_from_npz.py --run-id 00358 --pmt-id LV2345 --channel 3 --window-ns 2000
    python scripts/app_1us_from_npz.py --npz /path/to/run00354_LV2264_ch4.npz --window-ns 1000
"""
import argparse

import numpy as np

DEFAULT_OUTPUT_DIR = "/mnt/data/PMT/R8520_406/output"
DEFAULT_WINDOW_NS = 1000.0  # 1 us window after the main pulse


def main() -> None:
    parser = argparse.ArgumentParser(description="Afterpulse probability in a window after the main pulse.")
    parser.add_argument("--run-id", help="5-digit run id (e.g. 00354)")
    parser.add_argument("--pmt-id", help="PMT id (e.g. LV2264)")
    parser.add_argument("--channel", type=int, help="Channel number")
    parser.add_argument("--npz", help="Direct path to the .npz file (overrides run-id/pmt-id/channel)")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory for .npz files")
    parser.add_argument("--window-ns", type=float, default=DEFAULT_WINDOW_NS, help="Window after main pulse in ns")
    args = parser.parse_args()

    if args.npz:
        npz_path = args.npz
    else:
        if not (args.run_id and args.pmt_id and args.channel is not None):
            parser.error("Provide either --npz or --run-id/--pmt-id/--channel together")
        npz_path = f"{args.output_dir}/run{args.run_id}_{args.pmt_id}_ch{args.channel}.npz"

    window_ns = args.window_ns

    f = np.load(npz_path)

    run_id = str(f["run_id"])
    pmt_id = str(f["pmt_id"])
    channel = int(f["channel"])

    main_area_pe = f["main_area_pe"]
    ap_delta_ns = f["ap_delta_time"]
    ap_area_pe = f["ap_area_pe"]

    n_main = len(main_area_pe)
    main_area_pe_sum = float(np.sum(main_area_pe))

    in_window = ap_delta_ns <= window_ns
    ap_area_pe_win = float(np.sum(ap_area_pe[in_window]))
    n_ap_win = int(np.count_nonzero(in_window))

    app_win = ap_area_pe_win / main_area_pe_sum if main_area_pe_sum > 0 else 0.0

    print(f"Run ID          : {run_id}")
    print(f"PMT ID          : {pmt_id}")
    print(f"Channel         : {channel}")
    print(f"Main pulse count: {n_main}")
    print(f"Main pulse area (sum, PE): {main_area_pe_sum:.6f}")
    print(f"Main pulse area (mean, PE): {float(np.mean(main_area_pe)):.6f}")
    print(f"Window          : {window_ns:.0f} ns after main pulse")
    print(f"Afterpulses in window   : {n_ap_win}")
    print(f"Afterpulse area in window (PE): {ap_area_pe_win:.6f}")
    print(f"APP within {window_ns:.0f} ns       : {app_win:.9f}")

    f.close()


if __name__ == "__main__":
    main()
