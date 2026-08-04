#!/usr/bin/env python
"""Plot CH1 (LV2387) afterpulse verification waveforms with main pulses for run 00340."""

import sys, time, os
sys.path.insert(0, "/home/yjj/pmt_analysis/src")

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

from pmt_analysis.runinfo import get_runinfo
from pmt_analysis.io.raw_reader import RawDataBundle

# ---------------------------------------------------------------------------
# Load data
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
print(f"Loaded in {time.time()-t0:.1f}s", flush=True)

records = rv.records
N_USE = 30000
records_subset = records[:N_USE]
print(f"Total records: {len(records)}, using first {N_USE}", flush=True)

class SubsetRV:
    def __init__(self, recs, full_rv):
        self.records = recs
        self._full_rv = full_rv
    def signals(self, record_ids):
        return self._full_rv.signals(record_ids)

rv_subset = SubsetRV(records_subset, rv)

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
# Steps 0-6: Run analysis
# ---------------------------------------------------------------------------
from pmt_analysis.analysis.app_noise_suppress import (
    detect_noisy_channels, compute_channel_baseline_stats,
)
from pmt_analysis.analysis.app import (
    find_main_pulses_per_channel, find_afterpulse_candidates_per_channel,
    select_afterpulses_per_channel,
    load_spe_gains_by_pmt_id, normalize_to_pe_per_channel, compute_app_per_channel,
    _merge_noise_suppressed_afterpulses,
)
from pmt_analysis.analysis.app_noise_suppress import NoiseSuppressionResult

# Step 0
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

# Step 1
main_pulses_by_ch = find_main_pulses_per_channel(bundle)

# Step 2
raw_afterpulses_by_ch = find_afterpulse_candidates_per_channel(bundle, main_pulses_by_ch)

# Step 2b
noise_results = {}
for ch in sorted(waveforms_by_ch.keys()):
    noise_results[ch] = NoiseSuppressionResult(
        channel=ch, is_noisy=(ch in noisy_channels),
        baseline_rms=bl_stats.get(ch, 0.0),
    )

raw_afterpulses_by_ch = _merge_noise_suppressed_afterpulses(
    bundle=bundle, main_pulses_by_ch=main_pulses_by_ch,
    raw_afterpulses_by_ch=raw_afterpulses_by_ch,
    noisy_channels=noisy_channels, noise_results=noise_results,
)

# Step 3
selected = select_afterpulses_per_channel(raw_afterpulses_by_ch)

# Steps 4-6
spe_gains = load_spe_gains_by_pmt_id(pmt_id_map)
normalize_to_pe_per_channel(main_pulses_by_ch, selected, spe_gains)
channel_results = compute_app_per_channel(main_pulses_by_ch, selected, spe_gains)

# ---------------------------------------------------------------------------
# Find CH1 afterpulses and their main pulses
# ---------------------------------------------------------------------------
TARGET_CH = 1
ch1_result = next((c for c in channel_results if c.channel == TARGET_CH), None)
ch1_aps = ch1_result.afterpulses if ch1_result else []
ch1_aps_sorted = sorted(ch1_aps, key=lambda x: (x.event_index or 0, x.min_point or 0))
N_SHOW = min(10, len(ch1_aps_sorted))

# Build lookup: event_index -> MainPulseRecord for CH1
ch1_mps_by_event = {}
for mp in main_pulses_by_ch.get((0, TARGET_CH), []):
    ch1_mps_by_event[mp.event_index] = mp

# Build lookup: record_id -> MainPulseRecord
ch1_mps_by_rid = {}
for mp in main_pulses_by_ch.get((0, TARGET_CH), []):
    rid = mp.metadata.get("record_id")
    if rid is not None:
        ch1_mps_by_rid[rid] = mp

# ---------------------------------------------------------------------------
# Plot: 10 segments in a 5-row x 2-col grid
# ---------------------------------------------------------------------------
DT_NS = float(records_subset[0]["dt"])  # ns per sample

fig, axes = plt.subplots(5, 2, figsize=(20, 28))
fig.suptitle(
    f"Run 00340 — CH1 (LV2387) Afterpulse Verification\n"
    f"APP={ch1_result.app_value:.6f}, "
    f"Gain={ch1_result.spe_gain:.4f}, "
    f"Main={ch1_result.main_pulse_count}, AP={ch1_result.afterpulse_count}",
    fontsize=11, y=0.99,
)

for idx in range(N_SHOW):
    row, col = idx // 2, idx % 2
    ax = axes[row, col]
    ap = ch1_aps_sorted[idx]

    record_id = ap.metadata.get("record_id")
    if record_id is None:
        ax.text(0.5, 0.5, "No record_id", transform=ax.transAxes, ha="center", va="center")
        continue

    waveform = rv_subset.signals(np.array([record_id]))[0]

    # Baseline
    bsl = np.mean(waveform[:30])

    # Time axis in ns
    t = np.arange(len(waveform)) * DT_NS
    t_us = t / 1000.0  # us

    # Plot full waveform (baseline subtracted)
    wf_bsl = waveform - bsl
    ax.plot(t_us, wf_bsl, color='steelblue', linewidth=0.5, alpha=0.7, label='Waveform (bsl-sub)')

    # Mark main pulse region
    main_pulse = ch1_mps_by_rid.get(record_id)
    if main_pulse is not None and main_pulse.start is not None and main_pulse.end is not None:
        mp_start_us = main_pulse.start * DT_NS / 1000.0
        mp_end_us = main_pulse.end * DT_NS / 1000.0
        ax.axvspan(mp_start_us, mp_end_us, alpha=0.15, color='orange', label=f'Main pulse [{main_pulse.start}:{main_pulse.end}]')
        ax.axvline(x=(main_pulse.sample_index or 0) * DT_NS / 1000.0,
                   color='red', linestyle='--', linewidth=0.8, alpha=0.6)

    # Mark afterpulse region
    ap_start_us = (ap.start or 0) * DT_NS / 1000.0
    ap_end_us = (ap.end or 0) * DT_NS / 1000.0
    ax.axvspan(ap_start_us, ap_end_us, alpha=0.25, color='green', label=f'AP [{ap.start}:{ap.end}]')

    # Mark AP min point
    ap_min_us = (ap.min_point or 0) * DT_NS / 1000.0
    ax.axvline(x=ap_min_us, color='darkgreen', linestyle=':', linewidth=1.0, alpha=0.9)

    # Title with parameters
    ns_tag = "[NS]" if ap.metadata.get("noise_suppressed") else ""
    charge_pe = f"{ap.charge_pe:.3f}" if ap.charge_pe is not None else "N/A"
    title = (
        f"#{idx+1}  evt={ap.event_index}  rid={record_id}  {ns_tag}\n"
        f"delay={ap.delay_time:.0f}ns  "
        f"h_ap={ap.height:.0f}ADC  "
        f"Q_ap={ap.charge:.3f}  "
        f"Q_PE={charge_pe}"
    )
    ax.set_title(title, fontsize=9, fontfamily='monospace')

    # Zoom to region around afterpulse with context for main pulse
    margin_samples = 200
    if main_pulse is not None and main_pulse.end is not None and ap.start is not None:
        x_min = main_pulse.start - margin_samples
    else:
        x_min = (ap.start or 0) - margin_samples
    x_max = max((ap.end or 0), (ap.start or 0)) + margin_samples

    x_min = max(0, x_min)
    x_max = min(len(waveform), x_max)

    ax.set_xlim(x_min * DT_NS / 1000.0, x_max * DT_NS / 1000.0)

    y_min = np.min(wf_bsl[x_min:x_max])
    y_max = np.max(wf_bsl[x_min:x_max])
    y_pad = max(50, (y_max - y_min) * 0.15)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    ax.set_xlabel("Time [μs]", fontsize=8)
    ax.set_ylabel("ADC (bsl-sub)", fontsize=8)
    ax.legend(fontsize=7, loc='upper right')
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.3)

# Hide unused axes
for idx in range(N_SHOW, 10):
    row, col = idx // 2, idx % 2
    axes[row, col].set_visible(False)

plt.tight_layout(rect=[0, 0, 1, 0.98])

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
output_dir = Path("/home/yjj/pmt_analysis/output")
output_dir.mkdir(parents=True, exist_ok=True)
out_path = output_dir / "run00340_ch1_ap_verification.png"
fig.savefig(str(out_path), dpi=200, bbox_inches="tight")
print(f"\nSaved: {out_path}", flush=True)
plt.close(fig)

# ---------------------------------------------------------------------------
# Also plot zoomed-in segments (inset style): each AP with enough context
# ---------------------------------------------------------------------------
fig2, axes2 = plt.subplots(5, 2, figsize=(20, 28))
fig2.suptitle(
    f"Run 00340 — CH1 (LV2387) Afterpulse Zoom (main pulse + AP)\n"
    f"APP={ch1_result.app_value:.6f}, "
    f"Gain={ch1_result.spe_gain:.4f}",
    fontsize=11, y=0.99,
)

for idx in range(N_SHOW):
    row, col = idx // 2, idx % 2
    ax = axes2[row, col]
    ap = ch1_aps_sorted[idx]

    record_id = ap.metadata.get("record_id")
    if record_id is None:
        ax.text(0.5, 0.5, "No record_id", transform=ax.transAxes, ha="center", va="center")
        continue

    waveform = rv_subset.signals(np.array([record_id]))[0]
    bsl = np.mean(waveform[:30])
    wf_bsl = waveform - bsl
    t = np.arange(len(waveform)) * DT_NS / 1000.0

    main_pulse = ch1_mps_by_rid.get(record_id)

    # Determine zoom range: from just before main pulse to just after AP
    zoom_pad = 80  # samples of padding on each side
    if main_pulse is not None and main_pulse.start is not None:
        z_start = max(0, main_pulse.start - zoom_pad)
    else:
        z_start = max(0, (ap.start or 0) - zoom_pad)
    z_end = min(len(waveform), max((ap.end or 0), (ap.start or 0)) + zoom_pad + 100)

    # Plot zoomed waveform
    ax.plot(t[z_start:z_end], wf_bsl[z_start:z_end],
            color='steelblue', linewidth=0.6, alpha=0.8)

    # Mark main pulse
    if main_pulse is not None and main_pulse.start is not None and main_pulse.end is not None:
        mp_s = main_pulse.start * DT_NS / 1000.0
        mp_e = main_pulse.end * DT_NS / 1000.0
        ax.axvspan(mp_s, mp_e, alpha=0.12, color='orange')
        ax.axvline(x=(main_pulse.sample_index or 0) * DT_NS / 1000.0,
                   color='red', linestyle='--', linewidth=0.8)

    # Mark AP
    ap_s = (ap.start or 0) * DT_NS / 1000.0
    ap_e = (ap.end or 0) * DT_NS / 1000.0
    ax.axvspan(ap_s, ap_e, alpha=0.2, color='green')
    ax.axvline(x=(ap.min_point or 0) * DT_NS / 1000.0,
               color='darkgreen', linestyle=':', linewidth=1.0)

    ns_tag = "[NS]" if ap.metadata.get("noise_suppressed") else ""
    charge_pe = f"{ap.charge_pe:.3f}" if ap.charge_pe is not None else "N/A"
    title = (
        f"#{idx+1}  evt={ap.event_index}  rid={record_id}  {ns_tag}\n"
        f"delay={ap.delay_time:.0f}ns  "
        f"h_ap={ap.height:.0f}ADC  "
        f"Q_PE={charge_pe}"
    )
    ax.set_title(title, fontsize=9, fontfamily='monospace')

    y_data = wf_bsl[z_start:z_end]
    y_pad = max(20, (np.max(y_data) - np.min(y_data)) * 0.15)
    ax.set_ylim(np.min(y_data) - y_pad, np.max(y_data) + y_pad)

    ax.set_xlabel("Time [μs]", fontsize=8)
    ax.set_ylabel("ADC (bsl-sub)", fontsize=8)
    ax.legend(fontsize=7)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.3)

for idx in range(N_SHOW, 10):
    row, col = idx // 2, idx % 2
    axes2[row, col].set_visible(False)

plt.tight_layout(rect=[0, 0, 1, 0.98])
out_path2 = output_dir / "run00340_ch1_ap_zoom.png"
fig2.savefig(str(out_path2), dpi=200, bbox_inches="tight")
print(f"Saved: {out_path2}", flush=True)
plt.close(fig2)

print("\nDone.", flush=True)
