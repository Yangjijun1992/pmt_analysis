#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plot validation waveforms for analysis_v4: 20 events with no AP (排除)
   and 20 events with afterpulses (正常).

For each event, show:
  Panel 1: Raw waveform + main pulse mask
  Panel 2: Raw + dynamic baseline + corrected waveform
  Panel 3: Corrected waveform + dynamic threshold + noise-suppressed AP markers

Output: output/00340_ch1_dump/analysis_v4/plots/no_ap_events/  (排除)
        output/00340_ch1_dump/analysis_v4/plots/has_ap_events/ (正常)
"""

import sys, time, json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import medfilt

sys.path.insert(0, "/home/yjj/pmt_analysis/src")
from pmt_analysis.analysis.app import preprocess_waveform, cal_area

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
DUMP_DIR = Path("/home/yjj/pmt_analysis/output/00340_ch1_dump")
WAVEFORM_DIR = DUMP_DIR / "waveforms"
OUTPUT_DIR = DUMP_DIR / "analysis_v4" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAIN_PULSE_THR = 500
DT_NS = 4.0
WAVEFORM_LEN = 1500

MEDIAN_WINDOW = 51
TRIGGER_SIGMA = 5.0
SLOPE_THRESHOLD = 0.5
DEAD_TIME = 35
AP_MIN_INTERVAL = 35

# ═══════════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════════════════════
print("Loading data...", flush=True)
with open(DUMP_DIR / "record_ids.txt") as f:
    record_ids = [int(line.strip()) for line in f if line.strip()]
print(f"  {len(record_ids)} record IDs", flush=True)

waveforms: Dict[int, np.ndarray] = {}
for rid in record_ids:
    waveforms[rid] = np.load(WAVEFORM_DIR / f"{rid}.npy")
print(f"  Loaded {len(waveforms)} waveforms", flush=True)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: FIND MAIN PULSES
# ═══════════════════════════════════════════════════════════════════════════════
print("Finding main pulses...", flush=True)
rid_to_mp = {}
for rid in record_ids:
    wf = waveforms[rid]
    processed, baseline_val = preprocess_waveform(wf)

    first_crossing = None
    for i in range(len(processed)):
        if processed[i] < -MAIN_PULSE_THR:
            first_crossing = i
            break
    if first_crossing is None:
        continue

    search_end = min(len(processed), first_crossing + 200)
    min_idx = first_crossing
    for i in range(first_crossing + 1, search_end):
        if processed[i] < processed[min_idx]:
            min_idx = i
        if i > first_crossing + 5 and processed[i] > -MAIN_PULSE_THR:
            break
    abs_min = int(np.argmin(processed))
    if abs(abs_min - first_crossing) < 300 and processed[abs_min] < processed[min_idx]:
        min_idx = abs_min

    if abs(float(processed[min_idx])) < MAIN_PULSE_THR:
        continue

    start_idx = min_idx
    for i in range(min_idx - 1, -1, -1):
        if processed[i] >= 0:
            start_idx = i + 1
            break
    else:
        start_idx = 0

    end_idx = min_idx
    for i in range(min_idx + 1, len(processed)):
        if processed[i] >= 0:
            end_idx = i
            break
    else:
        end_idx = len(processed) - 1

    if end_idx <= start_idx:
        continue

    rid_to_mp[rid] = {
        "start": start_idx, "end": end_idx + 1,
        "min_point": min_idx, "height": abs(float(processed[min_idx])),
        "baseline": baseline_val,
    }
print(f"  Found {len(rid_to_mp)} main pulses", flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
# BASELINE CORRECTION (same as analysis_v4)
# ═══════════════════════════════════════════════════════════════════════════════
def baseline_correction(waveform, mp_start, mp_end, window_size):
    n = len(waveform)
    mask = np.ones(n, dtype=bool)
    mask[mp_start:mp_end + 1] = False

    ksize = window_size
    if ksize % 2 == 0:
        ksize += 1
    baseline = medfilt(waveform.astype(np.float64), ksize)

    if not np.all(mask):
        invalid = ~mask
        valid_idx = np.where(mask)[0]
        if len(valid_idx) >= 2:
            baseline[invalid] = np.interp(
                np.where(invalid)[0], valid_idx, baseline[valid_idx],
            )
    return waveform.astype(np.float64) - baseline, baseline


def estimate_noise_rms(corrected, mp_start, n_baseline=50):
    n = min(n_baseline, mp_start)
    if n < 3:
        return 0.5
    return max(float(np.std(corrected[:n])), 0.5)


def find_afterpulses(corrected, search_start, noise_rms,
                     trigger_sigma, slope_threshold, dead_time,
                     dt_ns, mp_end):
    n = len(corrected)
    threshold = -(trigger_sigma * noise_rms)
    results = []
    last_trigger = None
    i = search_start

    while i < n - 2:
        if corrected[i] >= threshold:
            i += 1
            continue
        slope = float(corrected[i + 1] - corrected[i])
        if slope >= -slope_threshold:
            i += 1
            continue
        if last_trigger is not None and (i - last_trigger) < dead_time:
            i += 1
            continue

        start = i
        while start > max(0, search_start):
            if corrected[start - 1] <= corrected[start]:
                start -= 1
            else:
                break

        min_point = start
        min_val = corrected[start]
        j = start + 1
        while j < n and corrected[j] <= corrected[j - 1]:
            if corrected[j] < min_val:
                min_val, min_point = corrected[j], j
            j += 1

        end = min_point
        for e in range(min_point + 1, n):
            if corrected[e] >= -noise_rms * 0.3:
                end = e
                break
        else:
            end = n - 1

        if abs(float(corrected[min_point])) < abs(threshold):
            i += 1
            continue

        height = abs(float(corrected[min_point]))
        delay_ns = (min_point - mp_end) * dt_ns

        results.append({
            "start": int(start), "min_point": int(min_point),
            "end": min(int(end + 1), n),
            "height": height, "delay_time_ns": delay_ns,
        })
        last_trigger = int(min_point)
        i = end + dead_time

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# COLLECT EVENTS WITH AND WITHOUT AFTERPULSES
# ═══════════════════════════════════════════════════════════════════════════════
print("Running noise-suppressed search...", flush=True)
events_no_ap = []   # 排除: no afterpulses found
events_has_ap = []  # 正常: has afterpulses
t0 = time.time()
n_processed = 0

for rid in record_ids:
    if rid not in rid_to_mp:
        continue
    mp = rid_to_mp[rid]
    wf = waveforms[rid]

    corrected, baseline_curve = baseline_correction(wf, mp["start"], mp["end"], MEDIAN_WINDOW)
    noise_rms = estimate_noise_rms(corrected, mp["start"])

    search_start = mp["end"] + AP_MIN_INTERVAL
    if search_start >= WAVEFORM_LEN:
        search_start = WAVEFORM_LEN - 1

    aps = find_afterpulses(
        corrected, search_start, noise_rms,
        TRIGGER_SIGMA, SLOPE_THRESHOLD, DEAD_TIME,
        DT_NS, mp["end"],
    )

    event_data = {
        "record_id": rid,
        "waveform": wf,
        "mp_start": mp["start"],
        "mp_end": mp["end"],
        "mp_min": mp["min_point"],
        "mp_height": mp["height"],
        "baseline_val": mp["baseline"],
        "baseline_curve": baseline_curve,
        "corrected": corrected,
        "noise_rms": noise_rms,
        "afterpulses": aps,
    }

    if len(aps) == 0 and len(events_no_ap) < 20:
        events_no_ap.append(event_data)
        print(f"  No-AP #{len(events_no_ap)}: rid={rid}", flush=True)
    elif len(aps) > 0 and len(events_has_ap) < 20:
        events_has_ap.append(event_data)
        print(f"  Has-AP #{len(events_has_ap)}: rid={rid} ({len(aps)} APs)", flush=True)

    n_processed += 1
    if len(events_no_ap) >= 20 and len(events_has_ap) >= 20:
        break
    if n_processed % 5000 == 0:
        print(f"    processed {n_processed} events ({time.time() - t0:.1f}s)", flush=True)

print(f"Collected {len(events_no_ap)} no-AP events, {len(events_has_ap)} has-AP events", flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PLOTTING FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════
def plot_event(dd, idx, out_dir, label, is_no_ap):
    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
    x = np.arange(len(dd["waveform"]))
    x_us = x * DT_NS / 1000.0

    n = len(dd["waveform"])
    zoom_start = max(0, dd["mp_start"] - 100)
    zoom_end = min(n, max(dd["mp_end"] + 800, 1200))

    # ── Panel 1: Raw waveform with main pulse ──
    ax = axes[0]
    ax.plot(x, dd["waveform"], "k-", linewidth=0.6, label="Raw waveform")
    ax.axvspan(dd["mp_start"], dd["mp_end"], color="yellow", alpha=0.2, label="Main pulse (masked)")
    ax.axvline(dd["mp_min"], color="orange", linestyle="--", linewidth=1.0,
               label=f"Main pulse min (sample {dd['mp_min']}, {dd['mp_height']:.0f} ADC)")
    ax.axhline(dd["baseline_val"], color="gray", linestyle=":", alpha=0.5, label=f"Baseline ({dd['baseline_val']:.1f} ADC)")

    # Search region marker
    search_start = dd["mp_end"] + AP_MIN_INTERVAL
    ax.axvline(search_start, color="purple", linestyle=":", linewidth=0.8, alpha=0.6, label="AP search start")

    ax.set_ylabel("ADC (raw)")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)
    status = "EXCLUDED (no AP)" if is_no_ap else "NORMAL (has AP)"
    ax.set_title(f"Record {dd['record_id']} — {status}  |  "
                 f"Main pulse: {dd['mp_height']:.0f} ADC  |  noise RMS: {dd['noise_rms']:.1f} ADC",
                 fontsize=11)

    # ── Panel 2: Raw + baseline + corrected ──
    ax = axes[1]
    ax.plot(x, dd["waveform"], "k-", linewidth=0.6, alpha=0.5, label="Raw waveform")
    ax.plot(x, dd["baseline_curve"], "r-", linewidth=1.2, label="Dynamic baseline (median, ws=51)")
    ax.plot(x, dd["corrected"], "b-", linewidth=0.8, alpha=0.8, label="Corrected waveform")
    ax.axvspan(dd["mp_start"], dd["mp_end"], color="yellow", alpha=0.1)
    ax.axhline(0, color="gray", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.set_ylabel("ADC")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)

    # ── Panel 3: Corrected + threshold + AP markers ──
    ax = axes[2]
    ax.plot(x, dd["corrected"], "b-", linewidth=0.7, alpha=0.8, label="Corrected waveform")
    ax.axhline(0, color="gray", linestyle="--", linewidth=0.5, alpha=0.5)

    threshold = -dd["noise_rms"] * TRIGGER_SIGMA
    ax.axhline(threshold, color="green", linestyle="--", linewidth=1.0,
               label=f"Dynamic threshold = -{TRIGGER_SIGMA} * RMS = {threshold:.1f} ADC")
    ax.axhline(-dd["noise_rms"], color="orange", linestyle=":", linewidth=0.8,
               label=f"RMS = {dd['noise_rms']:.1f} ADC")
    ax.axhline(dd["noise_rms"], color="orange", linestyle=":", linewidth=0.6, alpha=0.5)

    # Mark afterpulses
    for j, ap in enumerate(dd["afterpulses"]):
        ax.axvspan(ap["start"], ap["end"], color="limegreen", alpha=0.15,
                   label=f"AP #{j+1}" if j == 0 else "")
        ax.axvline(ap["min_point"], color="red", linestyle="-", linewidth=1.0, alpha=0.8)
        ax.plot(ap["min_point"], dd["corrected"][ap["min_point"]],
                "ro", markersize=6, markerfacecolor="none", markeredgewidth=1.5)
        ax.annotate(
            f"dt={ap['delay_time_ns']:.0f}ns",
            xy=(ap["min_point"], dd["corrected"][ap["min_point"]]),
            xytext=(ap["min_point"] + 30, dd["corrected"][ap["min_point"]] - 40),
            fontsize=7, color="red",
            arrowprops=dict(arrowstyle="->", color="red", lw=0.8),
        )

    ax.set_xlabel("Sample index")
    ax.set_ylabel("ADC (corrected)")
    ax.legend(fontsize=7, loc="lower left")
    ax.grid(True, alpha=0.3)

    # Zoom
    axes[0].set_xlim(zoom_start, zoom_end)
    axes[1].set_xlim(zoom_start, zoom_end)
    axes[2].set_xlim(zoom_start, zoom_end)

    # Y limits for panel 3
    y_data = dd["corrected"][zoom_start:zoom_end]
    y_min_v = min(np.min(y_data), threshold * 2)
    y_max_v = max(np.max(y_data), abs(threshold) * 0.5)
    y_pad_v = max(20, (y_max_v - y_min_v) * 0.15)
    axes[2].set_ylim(y_min_v - y_pad_v, y_max_v + y_pad_v)

    plt.tight_layout()
    out_path = out_dir / f"{label}_{idx+1:02d}_rec{dd['record_id']}.png"
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# GENERATE PLOTS
# ═══════════════════════════════════════════════════════════════════════════════
print("\nPlotting 20 excluded (no AP) events...", flush=True)
no_ap_dir = OUTPUT_DIR / "no_ap_events"
no_ap_dir.mkdir(parents=True, exist_ok=True)
for idx, dd in enumerate(events_no_ap):
    out = plot_event(dd, idx, no_ap_dir, "no_ap", is_no_ap=True)
    print(f"  [{idx+1}/20] {out}", flush=True)

print("\nPlotting 20 normal (has AP) events...", flush=True)
has_ap_dir = OUTPUT_DIR / "has_ap_events"
has_ap_dir.mkdir(parents=True, exist_ok=True)
for idx, dd in enumerate(events_has_ap):
    out = plot_event(dd, idx, has_ap_dir, "has_ap", is_no_ap=False)
    print(f"  [{idx+1}/20] {out}", flush=True)

print(f"\nDone.")
print(f"Excluded (no AP): {no_ap_dir}/")
print(f"Normal (has AP):  {has_ap_dir}/")
