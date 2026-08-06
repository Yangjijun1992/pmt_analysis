"""Compute afterpulse probability (APP) within configurable windows after the
main pulse for all channels of a run, reading per-channel .npz files.

Usage:
    python scripts/app_windows_from_npz.py --run-id 00373 --windows 1000 5000
"""
import argparse
from pathlib import Path

import numpy as np

DEFAULT_OUTPUT_DIR = "/mnt/data/PMT/R8520_406/output"
DEFAULT_WINDOWS_NS = (1000.0, 5000.0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="APP within configurable windows after the main pulse, per PMT."
    )
    parser.add_argument("--run-id", required=True, help="5-digit run id (e.g. 00373)")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                        help="Directory holding the per-channel .npz files")
    parser.add_argument("--windows", type=float, nargs="+", default=list(DEFAULT_WINDOWS_NS),
                        help="Windows after main pulse in ns (default: 1000 5000)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    run_id = args.run_id
    windows = args.windows

    files = sorted(output_dir.glob(f"run{run_id}_*.npz"))

    rows = []
    for f in files:
        name = f.name
        if "all_channels" in name:
            continue
        try:
            data = np.load(f)
            pmt_id = str(data["pmt_id"])
            channel = int(data["channel"])
            main_area_pe = data["main_area_pe"]
            ap_delta_ns = data["ap_delta_time"]
            ap_area_pe = data["ap_area_pe"]
        except Exception as e:
            print(f"ERROR loading {name}: {e}")
            continue
        finally:
            try:
                data.close()
            except Exception:
                pass

        n_main = len(main_area_pe)
        main_sum = float(np.sum(main_area_pe))
        app_vals = {}
        for w in windows:
            in_win = ap_delta_ns <= w
            ap_win = float(np.sum(ap_area_pe[in_win]))
            app_vals[w] = ap_win / main_sum if main_sum > 0 else 0.0

        rows.append((pmt_id, channel, n_main, main_sum, app_vals))

    rows.sort(key=lambda r: r[1])

    print(f"Run ID : {run_id}")
    print("Method : APP(window) = sum(afterpulse_area_pe [delta_time <= window]) / sum(main_area_pe)")
    print(f"Windows: " + ", ".join(f"{w:.0f} ns" for w in windows))
    print()

    header = f"{'PMT_ID':<8}{'CH':>3}{'MainN':>8}" + "".join(f"{f'APP_{w:.0f}ns':>14}" for w in windows)
    print(header)
    print("-" * len(header))
    for pmt_id, channel, n_main, main_sum, app_vals in rows:
        line = f"{pmt_id:<8}{channel:>3}{n_main:>8}"
        line += "".join(f"{app_vals[w]:>14.6f}" for w in windows)
        print(line)


if __name__ == "__main__":
    main()
