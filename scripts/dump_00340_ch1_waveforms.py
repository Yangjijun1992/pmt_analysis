#!/usr/bin/env python
"""Dump all raw waveforms from 00340 CH1 (LV2387) — backup utility."""

import sys, time, json
sys.path.insert(0, "/home/yjj/pmt_analysis/src")

import numpy as np
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path("/home/yjj/pmt_analysis/output/00340_ch1_dump")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STORAGE_DIR = '/mnt/data/TPC/run_R8520/'

print("Creating Context...", flush=True)
from waveform_analysis.core.context import Context
from waveform_analysis.core import records_view
from waveform_analysis.core.plugins.plugin_sets import plugins_io, plugins_waveform

ctx = Context(storage_dir=STORAGE_DIR)
ctx.register(*plugins_io())
ctx.register(*plugins_waveform())
ctx.set_config({
    'data_root': STORAGE_DIR,
    'daq_adapter': 'v1725',
    'show_progress': False,
    'use_filtered': False,
    'wave_source': 'records',
})

print("Loading records_view for 00340...", flush=True)
t0 = time.time()
rv = records_view(ctx, '00340')
t1 = time.time()
print(f"Loaded in {t1-t0:.1f}s", flush=True)

records = rv.records
total = len(records)
print(f"Total records: {total}", flush=True)

# Filter CH1 records
ch1_records = [r for r in records if int(r["channel"]) == 1]
n_ch1 = len(ch1_records)
print(f"CH1 records: {n_ch1}", flush=True)

# Dump metadata first
meta = {
    "run_id": "00340",
    "pmt_id": "LV2387",
    "channel": 1,
    "board": 0,
    "total_records": total,
    "ch1_records": n_ch1,
    "dump_time": datetime.now().isoformat(),
    "sampling_rate_hz": 250e6,
    "dt_ns": 4.0,
}
meta_path = OUTPUT_DIR / "metadata.json"
meta_path.write_text(json.dumps(meta, indent=2))
print(f"Metadata saved to {meta_path}", flush=True)

# Dump all CH1 waveforms
record_id_file = OUTPUT_DIR / "record_ids.txt"
waveform_dir = OUTPUT_DIR / "waveforms"
waveform_dir.mkdir(parents=True, exist_ok=True)

record_ids = []
t0 = time.time()

for i, rec in enumerate(ch1_records):
    rid = int(rec["record_id"])
    record_ids.append(str(rid))
    wave = rv.signals(np.array([rid]))[0]

    wf_path = waveform_dir / f"{rid}.npy"
    np.save(wf_path, wave)

    if (i + 1) % 5000 == 0 or (i + 1) == n_ch1:
        elapsed = time.time() - t0
        rate = (i + 1) / elapsed
        eta = (n_ch1 - i - 1) / rate if rate > 0 else 0
        print(f"  [{i+1}/{n_ch1}] {waveform_dir}/{rid}.npy "
              f"({elapsed:.1f}s elapsed, ~{rate:.0f} wf/s, ETA {eta:.0f}s)", flush=True)

record_id_file.write_text("\n".join(record_ids))
elapsed = time.time() - t0
print(f"\nDone. {n_ch1} waveforms saved to {waveform_dir}", flush=True)
print(f"Record ID list saved to {record_id_file}", flush=True)
print(f"Total time: {elapsed:.1f}s ({n_ch1/elapsed:.0f} wf/s)", flush=True)
