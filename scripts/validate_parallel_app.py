"""Validate the parallel APP framework on a real After Pulse run.

Loads the bundle once, runs analyze_app_parallel with a given number of
workers, times it, and prints the per-channel APP summary for comparison
against the serial result.
"""
import sys
import time

from pmt_analysis.analysis.app_parallel import analyze_app_parallel
from pmt_analysis.io.raw_reader import NotebookBasedRawDataReader
from pmt_analysis.runinfo import get_runinfo


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "00376"
    n_workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    ri = get_runinfo(run_id)
    pmt_map = {}
    for bi in ri.metadata.get("mapping", []):
        for ci in bi.get("channels", []):
            pmt_map[(bi["board_id"], ci["ch"])] = ci["pmt"]

    print(f"Loading run {run_id} ...", flush=True)
    t0 = time.time()
    bundle = NotebookBasedRawDataReader().read(ri)
    print(f"Loaded in {time.time()-t0:.1f}s, events={bundle.event_count}", flush=True)

    print(f"Running parallel APP with {n_workers} workers ...", flush=True)
    t1 = time.time()
    result = analyze_app_parallel(bundle, n_workers=n_workers, pmt_id_map=pmt_map)
    wall = time.time() - t1
    print(f"APP computation wall time: {wall:.1f}s", flush=True)

    print(f"\nmain_pulse_count = {result.main_pulse_count}")
    print(f"afterpulse_count = {result.afterpulse_count}")
    print(f"APP (overall raw) = {result.app_value}")
    print(f"APP (overall PE) = {result.app_value_pe}")
    print()
    print(f"{'PMT_ID':<8}{'CH':>3}{'MainN':>8}{'AP_N':>10}{'APP_raw':>12}{'APP_pe':>12}")
    s_by = {ch.channel: ch for ch in result.channels}
    for ch in result.channels:
        pmt = pmt_map.get((ch.board, ch.channel), "?")
        print(f"{pmt:<8}{ch.channel:>3}{ch.main_pulse_count:>8}{ch.afterpulse_count:>10}"
              f"{ch.app_value:>12.6f}{ch.app_value_pe:>12.6f}")


if __name__ == "__main__":
    main()
