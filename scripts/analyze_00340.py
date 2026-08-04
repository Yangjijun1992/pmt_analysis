#!/usr/bin/env python
"""Subsampled analysis of run 00340 — CH1 (LV2387) afterpulse verification."""

import sys, time
sys.path.insert(0, "/home/yjj/pmt_analysis/src")

import numpy as np
from pathlib import Path

from pmt_analysis.runinfo import get_runinfo
from pmt_analysis.io.raw_reader import RawDataBundle

# ---------------------------------------------------------------------------
# Load data via waveform_analysis directly
# ---------------------------------------------------------------------------
print("Creating Context...", flush=True)
from waveform_analysis.core.context import Context
from waveform_analysis.core import records_view
from waveform_analysis.core.plugins.plugin_sets import plugins_io, plugins_waveform

storage_dir = '/mnt/data/TPC/run_R8520/'
ctx = Context(storage_dir=storage_dir)
ctx.register(*plugins_io())
ctx.register(*plugins_waveform())
ctx.set_config({
    'data_root': storage_dir,
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
print(f"Total records: {len(records)}", flush=True)

# Subsample to first 30000 records
N_USE = 30000
records_subset = records[:N_USE]
print(f"Using first {N_USE} records", flush=True)

class SubsetRV:
    def __init__(self, recs, full_rv):
        self.records = recs
        self._full_rv = full_rv
    def signals(self, record_ids):
        return self._full_rv.signals(record_ids)

rv_subset = SubsetRV(records_subset, rv)

# Load runinfo
ri = get_runinfo("00340", "/mnt/data/TPC")
pmt_id_map = {}
for bi in ri.metadata.get("mapping", []):
    for ch_info in bi.get("channels", []):
        pmt_id_map[(bi["board_id"], ch_info["ch"])] = ch_info["pmt"]

bundle = RawDataBundle(
    runinfo=ri, source_path=[], data=rv_subset,
    data_format="records", event_count=N_USE,
    channel_count=7, waveform_count=N_USE,
    metadata={"boards": [0]},
)

# ---------------------------------------------------------------------------
# STEP 0: Detect noisy channels
# ---------------------------------------------------------------------------
print("\n=== Step 0: Detect noisy channels ===", flush=True)
from pmt_analysis.analysis.app_noise_suppress import (
    detect_noisy_channels, compute_channel_baseline_stats,
    DEFAULT_NOISE_CHANNEL_RMS_THRESHOLD,
)

waveforms_by_ch = {}
n_sample = min(N_USE, 700)
for i in range(n_sample):
    ch = int(records_subset[i]["channel"])
    if ch not in waveforms_by_ch:
        waveforms_by_ch[ch] = []
    if len(waveforms_by_ch[ch]) < 100:
        rid = int(records_subset[i]["record_id"])
        wave = rv_subset.signals(np.array([rid]))[0]
        waveforms_by_ch[ch].append(wave)

noisy_channels = detect_noisy_channels(waveforms_by_ch)
bl_stats = compute_channel_baseline_stats(waveforms_by_ch)

for ch in sorted(waveforms_by_ch.keys()):
    pmt = pmt_id_map.get((0, ch), "?")
    is_n = "NOISY" if ch in noisy_channels else "clean"
    print(f"  CH{ch} ({pmt}): {is_n}, RMS={bl_stats.get(ch, 0):.2f} ADC", flush=True)

# ---------------------------------------------------------------------------
# STEP 1: Find main pulses
# ---------------------------------------------------------------------------
print("\n=== Step 1: Find main pulses ===", flush=True)
from pmt_analysis.analysis.app import (
    find_main_pulses_per_channel, find_afterpulse_candidates_per_channel,
    select_afterpulses_per_channel, analyze_app,
)

t0 = time.time()
main_pulses_by_ch = find_main_pulses_per_channel(bundle)
t1 = time.time()
print(f"Main pulses found in {t1-t0:.1f}s", flush=True)
for (b, ch), mps in sorted(main_pulses_by_ch.items()):
    pmt = pmt_id_map.get((b, ch), "?")
    print(f"  CH{ch} ({pmt}): {len(mps)} main pulses", flush=True)

# ---------------------------------------------------------------------------
# STEP 2: Find afterpulse candidates (standard)
# ---------------------------------------------------------------------------
print("\n=== Step 2: Standard afterpulse candidate search ===", flush=True)
t0 = time.time()
raw_afterpulses_by_ch = find_afterpulse_candidates_per_channel(bundle, main_pulses_by_ch)
t1 = time.time()
print(f"Candidates found in {t1-t0:.1f}s", flush=True)
for (b, ch), aps in sorted(raw_afterpulses_by_ch.items()):
    pmt = pmt_id_map.get((b, ch), "?")
    print(f"  CH{ch} ({pmt}): {len(aps)} raw candidates", flush=True)

# ---------------------------------------------------------------------------
# STEP 2b: Noise suppression for noisy channels
# ---------------------------------------------------------------------------
print("\n=== Step 2b: Noise suppression ===", flush=True)
from pmt_analysis.analysis.app import _merge_noise_suppressed_afterpulses
from pmt_analysis.analysis.app_noise_suppress import NoiseSuppressionResult

noise_results = {}
for ch in sorted(waveforms_by_ch.keys()):
    noise_results[ch] = NoiseSuppressionResult(
        channel=ch,
        is_noisy=(ch in noisy_channels),
        baseline_rms=bl_stats.get(ch, 0.0),
    )

if noisy_channels:
    t0 = time.time()
    raw_afterpulses_by_ch = _merge_noise_suppressed_afterpulses(
        bundle=bundle,
        main_pulses_by_ch=main_pulses_by_ch,
        raw_afterpulses_by_ch=raw_afterpulses_by_ch,
        noisy_channels=noisy_channels,
        noise_results=noise_results,
    )
    t1 = time.time()
    print(f"Noise suppression done in {t1-t0:.1f}s", flush=True)
    for (b, ch), aps in sorted(raw_afterpulses_by_ch.items()):
        pmt = pmt_id_map.get((b, ch), "?")
        ns_count = sum(1 for ap in aps if ap.metadata.get("noise_suppressed"))
        print(f"  CH{ch} ({pmt}): {len(aps)} candidates ({ns_count} noise-suppressed)", flush=True)
else:
    print("No noisy channels — skipping noise suppression", flush=True)

# ---------------------------------------------------------------------------
# STEP 3: Select afterpulses
# ---------------------------------------------------------------------------
print("\n=== Step 3: Select afterpulses ===", flush=True)
selected = select_afterpulses_per_channel(raw_afterpulses_by_ch)
for (b, ch), aps in sorted(selected.items()):
    pmt = pmt_id_map.get((b, ch), "?")
    print(f"  CH{ch} ({pmt}): {len(aps)} final afterpulses", flush=True)

# ---------------------------------------------------------------------------
# STEP 4-6: SPE gains + APP
# ---------------------------------------------------------------------------
print("\n=== Steps 4-6: SPE gains + PE + APP ===", flush=True)
from pmt_analysis.analysis.app import (
    load_spe_gains_by_pmt_id, normalize_to_pe_per_channel, compute_app_per_channel,
)

spe_gains = load_spe_gains_by_pmt_id(pmt_id_map)
normalize_to_pe_per_channel(main_pulses_by_ch, selected, spe_gains)
channel_results = compute_app_per_channel(main_pulses_by_ch, selected, spe_gains)

print("\n=== Per-Channel Results ===", flush=True)
print(f"{'PMT':<12} {'CH':>3} {'Main':>6} {'AP':>6} {'Main_w_AP':>10} {'APP_raw':>14} {'APP_PE':>14} {'Gain':>10}", flush=True)
print("-" * 80, flush=True)
for ch_r in channel_results:
    pmt = pmt_id_map.get((ch_r.board, ch_r.channel), "?")
    gs = f"{ch_r.spe_gain:.4f}" if ch_r.spe_gain else "N/A"
    ar = f"{ch_r.app_value:.10f}" if ch_r.app_value else "N/A"
    ap = f"{ch_r.app_value_pe:.10f}" if ch_r.app_value_pe else "N/A"
    print(f"{pmt:<12} {ch_r.channel:>3} {ch_r.main_pulse_count:>6} {ch_r.afterpulse_count:>6} "
          f"{ch_r.main_pulse_with_afterpulse_count:>10} {ar:>14} {ap:>14} {gs:>10}", flush=True)

# ---------------------------------------------------------------------------
# CH1 (LV2387) verification segments
# ---------------------------------------------------------------------------
TARGET_CH = 1
TARGET_PMT = "LV2387"
N_SHOW = 10

ch1_result = next((c for c in channel_results if c.channel == TARGET_CH), None)
ch1_aps = ch1_result.afterpulses if ch1_result else []

print(f"\n{'='*60}", flush=True)
print(f"CH{TARGET_CH} ({TARGET_PMT}) AFTERPULSE VERIFICATION", flush=True)
print(f"{'='*60}", flush=True)
print(f"Main pulses: {ch1_result.main_pulse_count}", flush=True)
print(f"Afterpulse candidates: {len(ch1_aps)}", flush=True)
print(f"APP_raw = {ch1_result.app_value}", flush=True)
print(f"APP_PE  = {ch1_result.app_value_pe}", flush=True)
print(f"SPE_gain = {ch1_result.spe_gain}", flush=True)

if not ch1_aps:
    print("\nNo afterpulses in final selection. Showing raw candidates instead.", flush=True)
    ch1_aps = raw_afterpulses_by_ch.get((0, TARGET_CH), [])
    print(f"Raw candidates: {len(ch1_aps)}", flush=True)

if not ch1_aps:
    print("No afterpulse candidates at all for CH1.", flush=True)
    sys.exit(0)

ch1_aps_sorted = sorted(ch1_aps, key=lambda x: (x.event_index or 0, x.min_point or 0))
n_show = min(N_SHOW, len(ch1_aps_sorted))

print(f"\n{'='*60}", flush=True)
print(f"Showing {n_show} afterpulse waveform segments", flush=True)
print(f"{'='*60}", flush=True)

for idx, ap in enumerate(ch1_aps_sorted[:n_show]):
    record_id = ap.metadata.get("record_id")
    if record_id is None:
        continue
    waveform = rv_subset.signals(np.array([record_id]))[0]

    ap_pos = ap.min_point or ap.start or 0
    margin = 80
    seg_start = max(0, ap_pos - margin)
    seg_end = min(len(waveform), ap_pos + margin + 1)
    segment = waveform[seg_start:seg_end]

    bsl_len = min(30, len(waveform))
    bsl = np.mean(waveform[:bsl_len])
    seg_bsl = segment - bsl

    ns_tag = " [NOISE-SUPPRESSED]" if ap.metadata.get("noise_suppressed") else ""
    charge_pe_str = f"{ap.charge_pe:.6f}" if ap.charge_pe is not None else "N/A"

    print(f"\n>> Segment #{idx+1}: evt={ap.event_index}, record_id={record_id}{ns_tag}", flush=True)
    print(f"   delay={ap.delay_time:.1f}ns  height={ap.height:.1f}ADC  "
          f"charge_raw={ap.charge:.6f}  charge_PE={charge_pe_str}", flush=True)
    print(f"   pulse: start={ap.start}, min_point={ap.min_point}, end={ap.end}", flush=True)
    if ap.metadata.get("noise_suppressed"):
        print(f"   noise_RMS={ap.metadata.get('noise_rms', 'N/A')} ADC", flush=True)

    n = len(segment)
    n_per = 10

    # Raw waveform
    print(f"   raw [{seg_start}:{seg_end}] ({len(segment)} samples):", flush=True)
    for r in range(0, n, n_per):
        rend = min(r + n_per, n)
        vals = " ".join(f"{segment[i]:7.1f}" for i in range(r, rend))
        print(f"     [{seg_start+r:4d}] {vals}", flush=True)

    # Baseline-subtracted
    print(f"   bsl-sub [{seg_start}:{seg_end}]:", flush=True)
    for r in range(0, n, n_per):
        rend = min(r + n_per, n)
        vals = " ".join(f"{seg_bsl[i]:7.1f}" for i in range(r, rend))
        print(f"     [{seg_start+r:4d}] {vals}", flush=True)

    # AP marker
    ap_rel = ap_pos - seg_start
    marker = " " * 11 + " " * (ap_rel * 8) + " ^   AP"
    print(f"    {marker}", flush=True)

print(f"\n{'='*60}", flush=True)
print("Analysis complete.", flush=True)
