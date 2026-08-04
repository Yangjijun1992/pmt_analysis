#!/usr/bin/env python
"""Plot noise-suppressed CH1 (LV2387) afterpulse events for run 00340.

Shows raw waveform, dynamic baseline, corrected waveform, and trigger threshold.
Saves 10 afterpulse events as multi-panel PNG figures.
"""

import sys, time, os, pickle
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
# Steps 0-6: Run analysis (same as analyze_00340.py)
# ---------------------------------------------------------------------------
from pmt_analysis.analysis.app_noise_suppress import (
    detect_noisy_channels, compute_channel_baseline_stats,
    DEFAULT_NOISE_CHANNEL_RMS_THRESHOLD, DEFAULT_QUALITY_RMS_THRESHOLD,
    DEFAULT_MEDIAN_WINDOW_SIZE, DEFAULT_TRIGGER_SIGMA,
    DEFAULT_SLOPE_THRESHOLD, DEFAULT_DEAD_TIME_SAMPLES,
    DEFAULT_AFTERPULSE_MIN_INTERVAL_SAMPLES,
    NoiseSuppressionResult,
    _process_event_with_noise_suppression,
    NoiseSuppressedEvent,
)
from pmt_analysis.analysis.app import (
    find_main_pulses_per_channel,
    find_afterpulse_candidates_per_channel,
    select_afterpulses_per_channel,
    load_spe_gains_by_pmt_id, normalize_to_pe_per_channel, compute_app_per_channel,
    _merge_noise_suppressed_afterpulses, AfterpulseRecord, cal_area,
)

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

print(f"Noisy channels: {noisy_channels}")

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
# Re-run noise suppression on CH1 to capture NoiseSuppressedEvent objects
# ---------------------------------------------------------------------------
TARGET_CH = 1
TARGET_PMT = "LV2387"

ch1_mps = main_pulses_by_ch.get((0, TARGET_CH), [])
print(f"\nCH{TARGET_CH} ({TARGET_PMT}): {len(ch1_mps)} main pulses")

# Build record_id -> main pulse lookup for CH1
mp_by_record_ch1 = {}
for mp in ch1_mps:
    rid = mp.metadata.get("record_id")
    if rid is not None:
        mp_by_record_ch1[rid] = mp

# Run noise-suppressed processing on all CH1 events with main pulses
print(f"Running noise suppression on all CH1 events...")
noise_events: list[NoiseSuppressedEvent] = []
rejected_count = 0

for i in range(len(records_subset)):
    rec = records_subset[i]
    record_id = int(rec["record_id"])
    if record_id not in mp_by_record_ch1:
        continue

    mp = mp_by_record_ch1[record_id]
    dt_ns = float(rec["dt"])
    waveform = rv_subset.signals(np.array([record_id]))[0]

    result = _process_event_with_noise_suppression(
        waveform=waveform,
        main_pulse_start=mp.start or 0,
        main_pulse_end=mp.end or len(waveform),
        event_index=mp.event_index or i,
        record_id=record_id,
        board=0,
        channel=TARGET_CH,
        dt_ns=dt_ns,
        quality_rms_threshold=DEFAULT_QUALITY_RMS_THRESHOLD,
        median_window_size=DEFAULT_MEDIAN_WINDOW_SIZE,
        trigger_sigma=DEFAULT_TRIGGER_SIGMA,
        slope_threshold=DEFAULT_SLOPE_THRESHOLD,
        dead_time_samples=DEFAULT_DEAD_TIME_SAMPLES,
        afterpulse_min_interval=DEFAULT_AFTERPULSE_MIN_INTERVAL_SAMPLES,
    )

    if result is None:
        continue
    if not result.event_valid:
        rejected_count += 1
        # Still keep rejected events for plotting
        noise_events.append(result)
        continue
    noise_events.append(result)

print(f"Total noise events: {len(noise_events)}")
print(f"Rejected (bad quality): {rejected_count}")
print(f"Events with afterpulses: {sum(1 for e in noise_events if len(e.afterpulses) > 0)}")

# ---------------------------------------------------------------------------
# Save full noise events to pickle for offline use
# ---------------------------------------------------------------------------
output_dir = Path("/home/yjj/pmt_analysis/output")

# Save as .npz for easier access
events_with_aps = [e for e in noise_events if e.event_valid and len(e.afterpulses) > 0]
print(f"\nEvents with afterpulses (valid): {len(events_with_aps)}")

# ---------------------------------------------------------------------------
# Plot: 10 events with noise suppression details (full width)
# Each event gets its own figure showing:
#   - Top: raw waveform + dynamic baseline + main pulse mask
#   - Bottom: corrected waveform + trigger threshold + AP markers
# ---------------------------------------------------------------------------
N_SHOW = 10
events_to_plot = events_with_aps[:N_SHOW]
DT_NS = float(records_subset[0]["dt"])

print(f"\nPlotting {len(events_to_plot)} noise-suppressed events...")

for idx, event in enumerate(events_to_plot):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 8), sharex=True)

    n = len(event.raw_waveform)
    x = np.arange(n) * DT_NS / 1000.0  # us

    main_pulse_start = event.main_pulse_start
    main_pulse_end = event.main_pulse_end

    # ---- Top panel: Raw waveform + dynamic baseline + main pulse mask ----
    ax1.plot(x, event.raw_waveform, "k-", linewidth=0.5, alpha=0.7, label="Raw waveform")
    ax1.plot(x, event.baseline_curve, "r-", linewidth=1.2, alpha=0.9, label="Dynamic baseline (median)")

    # Shade main pulse region
    mp_s_us = main_pulse_start * DT_NS / 1000.0
    mp_e_us = main_pulse_end * DT_NS / 1000.0
    ax1.axvspan(mp_s_us, mp_e_us, color="yellow", alpha=0.12, label="Main pulse (masked)")

    ax1.set_ylabel("ADC (raw)", fontsize=10)
    ax1.legend(fontsize=7, loc="upper right")
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(labelsize=8)

    # ---- Bottom panel: Corrected waveform + threshold + AP markers ----
    ax2.plot(x, event.corrected_waveform, "b-", linewidth=0.5, alpha=0.8, label="Corrected waveform")
    ax2.axhline(y=0, color="gray", linestyle="--", linewidth=0.5, alpha=0.4)

    threshold = -event.noise_rms * DEFAULT_TRIGGER_SIGMA
    ax2.axhline(
        y=threshold, color="darkgreen", linestyle="--", linewidth=1.0, alpha=0.8,
        label=f"Trigger = -{DEFAULT_TRIGGER_SIGMA}·RMS = {threshold:.1f} ADC",
    )
    ax2.axhline(
        y=event.noise_rms, color="orange", linestyle=":", linewidth=0.6, alpha=0.5,
        label=f"+RMS = {event.noise_rms:.1f} ADC",
    )
    ax2.axhline(
        y=-event.noise_rms, color="orange", linestyle=":", linewidth=0.6, alpha=0.5,
    )

    # Mark afterpulse regions and min points
    for j, ap in enumerate(event.afterpulses):
        ap_s_us = ap.start * DT_NS / 1000.0
        ap_e_us = ap.end * DT_NS / 1000.0
        ax2.axvspan(ap_s_us, ap_e_us, color="limegreen", alpha=0.15, label=f"AP#{j+1}" if j == 0 else "")
        ax2.axvline(x=ap.min_point * DT_NS / 1000.0, color="red", linestyle="-", linewidth=0.8, alpha=0.8)
        ax2.plot(
            ap.min_point * DT_NS / 1000.0,
            event.corrected_waveform[ap.min_point],
            "ro", markersize=5, markerfacecolor="none", markeredgewidth=1.2,
        )
        # Annotate delay time
        ax2.annotate(
            f"Δt={ap.delay_time_ns:.0f}ns",
            xy=(ap.min_point * DT_NS / 1000.0, event.corrected_waveform[ap.min_point]),
            xytext=(ap.min_point * DT_NS / 1000.0 + 0.5, event.corrected_waveform[ap.min_point] - 30),
            fontsize=7, color="red",
            arrowprops=dict(arrowstyle="->", color="red", lw=0.8),
        )

    # Shade afterpulse search region (after main pulse + 35 samples)
    search_start = main_pulse_end + DEFAULT_AFTERPULSE_MIN_INTERVAL_SAMPLES
    sr_s_us = search_start * DT_NS / 1000.0
    ax2.axvline(x=sr_s_us, color="purple", linestyle=":", linewidth=0.8, alpha=0.6, label="Search start")

    # Zoom to region around main pulse + afterpulses
    zoom_pad = 200  # samples
    if event.afterpulses:
        ap_max_end = max(ap.end for ap in event.afterpulses)
    else:
        ap_max_end = main_pulse_end + 500
    x_min = max(0, main_pulse_start - zoom_pad)
    x_max = min(n, max(ap_max_end, main_pulse_end) + zoom_pad + 200)
    ax1.set_xlim(x_min * DT_NS / 1000.0, x_max * DT_NS / 1000.0)
    ax2.set_xlim(x_min * DT_NS / 1000.0, x_max * DT_NS / 1000.0)

    # Y limits for bottom panel
    y_data = event.corrected_waveform[x_min:x_max]
    y_min, y_max = np.min(y_data), np.max(y_data)
    y_pad = max(30, (y_max - y_min) * 0.2)
    ax2.set_ylim(y_min - y_pad, y_max + y_pad)

    ax2.set_xlabel("Time [μs]", fontsize=10)
    ax2.set_ylabel("ADC (corrected)", fontsize=10)
    ax2.legend(fontsize=7, loc="lower left")
    ax2.grid(True, alpha=0.3)
    ax2.tick_params(labelsize=8)

    # Title
    num_aps = len(event.afterpulses)
    ap_delays = ", ".join(f"{ap.delay_time_ns:.0f}ns" for ap in event.afterpulses[:5])
    if num_aps > 5:
        ap_delays += f" ... (+{num_aps - 5})"
    title = (
        f"Run 00340 — CH{TARGET_CH} ({TARGET_PMT}) — Event #{idx+1}  "
        f"rid={event.record_id}  evt={event.event_index}  "
        f"noise_RMS={event.noise_rms:.1f}ADC  "
        f"AP={num_aps}"
    )
    fig.suptitle(title, fontsize=10, y=0.99)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    out_path = output_dir / f"run00340_ch1_ns_event_{idx+1:02d}.png"
    fig.savefig(str(out_path), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  [{idx+1}/{len(events_to_plot)}] Saved: {out_path.name}")

# ---------------------------------------------------------------------------
# Also: Plot rejected events (bad quality filter) for comparison
# ---------------------------------------------------------------------------
rejected_valid = [e for e in noise_events if not e.event_valid and len(e.afterpulses) == 0]
print(f"\nRejected events: {len(rejected_valid)}")

if rejected_valid:
    N_REJ_SHOW = min(5, len(rejected_valid))
    for idx, event in enumerate(rejected_valid[:N_REJ_SHOW]):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 8), sharex=True)

        n = len(event.raw_waveform)
        x = np.arange(n) * DT_NS / 1000.0

        mp_s_us = event.main_pulse_start * DT_NS / 1000.0
        mp_e_us = event.main_pulse_end * DT_NS / 1000.0

        ax1.plot(x, event.raw_waveform, "k-", linewidth=0.5, alpha=0.7, label="Raw waveform")
        ax1.axvspan(mp_s_us, mp_e_us, color="yellow", alpha=0.12, label="Main pulse")

        # Show the quality filter window
        q_ws = (event.main_pulse_end + 150) * DT_NS / 1000.0
        q_we = min(event.main_pulse_end + 500, n) * DT_NS / 1000.0
        ax1.axvspan(q_ws, q_we, color="red", alpha=0.1, label="Quality window (REJECTED)")

        ax1.set_ylabel("ADC (raw)", fontsize=10)
        ax1.legend(fontsize=7)
        ax1.grid(True, alpha=0.3)
        ax1.tick_params(labelsize=8)

        ax2.plot(x, event.raw_waveform, "b-", linewidth=0.5, alpha=0.8, label="Waveform (no correction)")
        ax2.axhline(y=0, color="gray", linestyle="--", linewidth=0.5, alpha=0.4)
        ax2.set_xlabel("Time [μs]", fontsize=10)
        ax2.set_ylabel("ADC", fontsize=10)
        ax2.legend(fontsize=7)
        ax2.grid(True, alpha=0.3)
        ax2.tick_params(labelsize=8)

        x_min = max(0, event.main_pulse_start - 200)
        x_max = min(n, event.main_pulse_end + 800)
        ax1.set_xlim(x_min * DT_NS / 1000.0, x_max * DT_NS / 1000.0)
        ax2.set_xlim(x_min * DT_NS / 1000.0, x_max * DT_NS / 1000.0)

        title = (
            f"Run 00340 — CH{TARGET_CH} ({TARGET_PMT}) — REJECTED Event  "
            f"rid={event.record_id}  evt={event.event_index}"
        )
        fig.suptitle(title, fontsize=10, y=0.99)
        plt.tight_layout(rect=[0, 0, 1, 0.97])
        out_path = output_dir / f"run00340_ch1_rejected_{idx+1:02d}.png"
        fig.savefig(str(out_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        print(f"  [REJ {idx+1}] Saved: {out_path.name}")

# ---------------------------------------------------------------------------
# Summary plot: all events with noise suppression in a grid (compact)
# ---------------------------------------------------------------------------
print("\nPlotting compact grid...")
n_total = len(events_to_plot)
n_cols = 2
n_rows = 5
fig_grid, axes_grid = plt.subplots(n_rows, n_cols, figsize=(20, 26))

for idx, event in enumerate(events_to_plot):
    row, col = idx // n_cols, idx % n_cols
    ax = axes_grid[row, col]

    n = len(event.raw_waveform)
    x = np.arange(n) * DT_NS / 1000.0

    # Plot corrected waveform
    ax.plot(x, event.corrected_waveform, "steelblue", linewidth=0.5, alpha=0.8)

    # Main pulse region
    mp_s = event.main_pulse_start * DT_NS / 1000.0
    mp_e = event.main_pulse_end * DT_NS / 1000.0
    ax.axvspan(mp_s, mp_e, color="orange", alpha=0.1)

    # Threshold
    threshold = -event.noise_rms * DEFAULT_TRIGGER_SIGMA
    ax.axhline(y=threshold, color="green", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.4, alpha=0.4)

    # AP markers
    for ap in event.afterpulses:
        ax.axvline(x=ap.min_point * DT_NS / 1000.0, color="red", linestyle="-", linewidth=0.6, alpha=0.7)
        ax.plot(ap.min_point * DT_NS / 1000.0, event.corrected_waveform[ap.min_point],
                "ro", markersize=3, markerfacecolor="none", markeredgewidth=0.8)

    # Zoom
    if event.afterpulses:
        ap_max = max(ap.end for ap in event.afterpulses)
    else:
        ap_max = event.main_pulse_end + 500
    x_min = max(0, event.main_pulse_start - 150)
    x_max = min(n, max(ap_max, event.main_pulse_end) + 300)
    ax.set_xlim(x_min * DT_NS / 1000.0, x_max * DT_NS / 1000.0)

    y_data = event.corrected_waveform[x_min:x_max]
    y_min_v, y_max_v = np.min(y_data), np.max(y_data)
    y_pad_v = max(20, (y_max_v - y_min_v) * 0.15)
    ax.set_ylim(y_min_v - y_pad_v, y_max_v + y_pad_v)

    ap_delays = ",".join(f"{ap.delay_time_ns:.0f}" for ap in event.afterpulses[:4])
    title = f"#{idx+1} rid={event.record_id} evt={event.event_index}  AP={len(event.afterpulses)}  RMS={event.noise_rms:.1f}"
    if ap_delays:
        title += f"\nΔt={ap_delays}ns"
    ax.set_title(title, fontsize=8, fontfamily='monospace')
    ax.tick_params(labelsize=6)
    ax.set_xlabel("Time [μs]", fontsize=7)
    ax.set_ylabel("ADC", fontsize=7)
    ax.grid(True, alpha=0.25)

for idx in range(len(events_to_plot), n_rows * n_cols):
    row, col = idx // n_cols, idx % n_cols
    axes_grid[row, col].set_visible(False)

fig_grid.suptitle(
    f"Run 00340 — CH{TARGET_CH} ({TARGET_PMT}) — Noise-Suppressed Afterpulse Events\n"
    f"Dynamic baseline (median, ws=51) → corrected → trigger = -{DEFAULT_TRIGGER_SIGMA}·RMS "
    f"| slope > {DEFAULT_SLOPE_THRESHOLD} ADC/sample | dead time = {DEFAULT_DEAD_TIME_SAMPLES} samples",
    fontsize=10, y=0.995,
)
plt.tight_layout(rect=[0, 0, 1, 0.985])
grid_path = output_dir / "run00340_ch1_noise_suppression_grid.png"
fig_grid.savefig(str(grid_path), dpi=200, bbox_inches="tight")
plt.close(fig_grid)
print(f"Saved: {grid_path.name}")

print("\nDone.")
print(f"\nOutput files in {output_dir}/:")
for f in sorted(output_dir.glob("run00340_ch1_ns_event_*.png")):
    print(f"  {f.name}")
for f in sorted(output_dir.glob("run00340_ch1_rejected_*.png")):
    print(f"  {f.name}")
print(f"  {grid_path.name}")
