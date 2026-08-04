#!/usr/bin/env python
"""Plot 10 discarded events from CH1 noise-suppressed analysis.

Shows for each discarded event:
  - Raw waveform with main pulse region highlighted
  - Corrected waveform (baseline subtracted)
  - Standard afterpulse search results (20 ADC threshold)
  - Dynamic threshold line

"s discarded" means events filtered out by Phase 1 quality check
(PtP in afterglow window > 30 ADC).
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, "/home/yjj/pmt_analysis/src")
from pmt_analysis.analysis.app import (
    MainPulseRecord,
    preprocess_waveform,
    findpulse_st_ed,
    filter_points,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DUMP_DIR = Path("/home/yjj/pmt_analysis/output/00340_ch1_dump")
WAVEFORM_DIR = DUMP_DIR / "waveforms"
OUTPUT_DIR = DUMP_DIR / "analysis_v3" / "discarded_plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BOARD = 0
CHANNEL = 1
DT_NS = 4.0
AFTERPULSE_AMPLITUDE_THRESHOLD = 20
AFTERPULSE_MIN_INTERVAL = 35
MAIN_PULSE_HEIGHT_THRESHOLD = 500

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
record_ids_path = DUMP_DIR / "record_ids.txt"
with open(record_ids_path) as f:
    record_ids = [int(line.strip()) for line in f if line.strip()]

print(f"Loading {len(record_ids)} waveforms...", flush=True)
waveforms: Dict[int, np.ndarray] = {}
for rid in record_ids:
    waveforms[rid] = np.load(WAVEFORM_DIR / f"{rid}.npy")
print(f"  Done.", flush=True)

# ---------------------------------------------------------------------------
# Step 1: Find main pulses (same as analysis_v3)
# ---------------------------------------------------------------------------
def find_main_pulses_modified():
    pulses: List[MainPulseRecord] = []
    for rid in record_ids:
        waveform = waveforms[rid]
        processed, baseline_val = preprocess_waveform(waveform)

        first_crossing = None
        for i in range(len(processed)):
            if processed[i] < -MAIN_PULSE_HEIGHT_THRESHOLD:
                first_crossing = i
                break
        if first_crossing is None:
            continue

        search_end = min(len(processed), first_crossing + 200)
        min_idx = first_crossing
        for i in range(first_crossing + 1, search_end):
            if processed[i] < processed[min_idx]:
                min_idx = i
            if i > first_crossing + 5 and processed[i] > -MAIN_PULSE_HEIGHT_THRESHOLD:
                break

        abs_min = int(np.argmin(processed))
        if abs(abs_min - first_crossing) < 300 and processed[abs_min] < processed[min_idx]:
            min_idx = abs_min

        if abs(float(processed[min_idx])) < MAIN_PULSE_HEIGHT_THRESHOLD:
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

        mp = MainPulseRecord(
            event_index=rid,
            channel_index=CHANNEL,
            sample_index=min_idx,
            height=abs(float(processed[min_idx])),
            start=start_idx,
            end=end_idx + 1,
            baseline=baseline_val,
            metadata={"board": BOARD, "record_id": rid},
        )
        pulses.append(mp)
    return pulses

print("Finding main pulses...", flush=True)
main_pulses = find_main_pulses_modified()
print(f"  {len(main_pulses)} main pulses", flush=True)

# ---------------------------------------------------------------------------
# Collect discarded events (Phase 1 quality filter)
# ---------------------------------------------------------------------------
from scipy.signal import medfilt

DEFAULT_QUALITY_RMS_THRESHOLD = 30.0
DEFAULT_MEDIAN_WINDOW_SIZE = 51
DEFAULT_TRIGGER_SIGMA = 5.0
DEFAULT_SLOPE_THRESHOLD = 0.5
DEFAULT_DEAD_TIME_SAMPLES = 35
NOISE_AP_MIN_INTERVAL = 35

discarded_data: List[dict] = []

for mp in main_pulses:
    rid = mp.metadata.get("record_id")
    waveform = waveforms[rid]
    processed = waveform - mp.baseline
    mp_end = mp.end or len(waveform)

    # Quality check
    ws = mp_end + 150
    we = min(mp_end + 500, len(waveform))
    if ws < we:
        ptp = float(np.ptp(waveform[ws:we]))
    else:
        ptp = 0.0

    if ptp < DEFAULT_QUALITY_RMS_THRESHOLD:
        continue  # passed quality check, skip

    # This event is discarded — save its data
    # Compute baseline + corrected waveform
    mask = np.ones(len(waveform), dtype=bool)
    mask[mp.start or 0:mp_end + 1] = False
    ksize = DEFAULT_MEDIAN_WINDOW_SIZE
    if ksize % 2 == 0:
        ksize += 1
    raw_baseline = medfilt(waveform.astype(np.float64), ksize)
    if not np.all(mask):
        invalid = ~mask
        valid_idx = np.where(mask)[0]
        if len(valid_idx) >= 2:
            raw_baseline[invalid] = np.interp(
                np.where(invalid)[0], valid_idx, raw_baseline[valid_idx],
            )
    corrected = waveform.astype(np.float64) - raw_baseline
    n_baseline = min(50, mp.start or 0)
    noise_rms = float(np.std(corrected[:n_baseline])) if n_baseline >= 3 else 0.5
    if noise_rms < 0.1:
        noise_rms = 0.5

    # Standard afterpulse search
    search_start = mp_end + AFTERPULSE_MIN_INTERVAL
    std_aps = []
    if search_start < len(processed):
        ref_points = []
        above = False
        for j in range(search_start, len(processed)):
            if processed[j] < -AFTERPULSE_AMPLITUDE_THRESHOLD:
                if not above:
                    ref_points.append(j)
                    above = True
            else:
                above = False
        ref_points = filter_points(ref_points, 2)
        for ref_idx in ref_points:
            try:
                st, minp, ed = findpulse_st_ed(processed, 0.0, ref_idx)
            except Exception:
                continue
            if ed >= st and abs(float(processed[minp])) >= AFTERPULSE_AMPLITUDE_THRESHOLD:
                std_aps.append({"start": st, "min": minp, "end": ed, "height": abs(float(processed[minp]))})

    discarded_data.append({
        "record_id": rid,
        "waveform": waveform,
        "processed": processed,
        "baseline_val": mp.baseline,
        "mp_start": mp.start,
        "mp_end": mp_end,
        "mp_min": mp.sample_index,
        "mp_height": mp.height,
        "afterglow_ptp": ptp,
        "baseline_curve": raw_baseline,
        "corrected": corrected,
        "noise_rms": noise_rms,
        "std_aps": std_aps,
    })

    if len(discarded_data) >= 10:
        break

print(f"Collected {len(discarded_data)} discarded events for plotting", flush=True)

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
for idx, dd in enumerate(discarded_data):
    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
    x = np.arange(len(dd["waveform"]))

    # ── Panel 1: Raw waveform with main pulse ──
    ax = axes[0]
    ax.plot(x, dd["waveform"], "k-", linewidth=0.6, label="Raw waveform")
    ax.axvspan(dd["mp_start"], dd["mp_end"], color="yellow", alpha=0.2, label="Main pulse")
    ax.axvline(dd["mp_min"], color="orange", linestyle="--", linewidth=1.0,
               label=f"Main pulse min (sample {dd['mp_min']})")
    ax.axhline(dd["baseline_val"], color="gray", linestyle=":", alpha=0.5)

    # Afterglow window
    ws = dd["mp_end"] + 150
    we = min(dd["mp_end"] + 500, len(dd["waveform"]))
    ax.axvspan(ws, we, color="red", alpha=0.1, label=f"Quality window (PtP={dd['afterglow_ptp']:.1f})")

    ax.set_ylabel("ADC (raw)")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)
    ax.set_title(f"Record {dd['record_id']} — DISCARDED (PtP={dd['afterglow_ptp']:.1f} > 30 ADC)  "
                 f"Main pulse: {dd['mp_height']:.0f} ADC", fontsize=11)

    # ── Panel 2: Raw + baseline + corrected ──
    ax = axes[1]
    ax.plot(x, dd["waveform"], "k-", linewidth=0.6, alpha=0.6, label="Raw waveform")
    ax.plot(x, dd["baseline_curve"], "r-", linewidth=1.2, label="Dynamic baseline (median)")
    ax.plot(x, dd["corrected"], "b-", linewidth=0.8, alpha=0.8, label="Corrected waveform")
    ax.axvspan(dd["mp_start"], dd["mp_end"], color="yellow", alpha=0.1)
    ax.set_ylabel("ADC")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)

    # ── Panel 3: Corrected + standard AP + threshold ──
    ax = axes[2]
    ax.plot(x, dd["corrected"], "b-", linewidth=0.7, alpha=0.8, label="Corrected waveform")
    ax.axhline(0, color="gray", linestyle="--", linewidth=0.5, alpha=0.5)

    threshold = -dd["noise_rms"] * DEFAULT_TRIGGER_SIGMA
    ax.axhline(threshold, color="green", linestyle="--", linewidth=1.0,
               label=f"Dynamic threshold = -5×RMS = {threshold:.1f} ADC")
    ax.axhline(-dd["noise_rms"], color="orange", linestyle=":", linewidth=0.8,
               label=f"Noise RMS = {dd['noise_rms']:.1f} ADC")

    # Standard afterpulse hits
    for ap in dd["std_aps"]:
        ax.axvline(ap["min"], color="red", linestyle="-", linewidth=0.8, alpha=0.5)
        ax.plot(ap["min"], dd["corrected"][ap["min"]], "ro",
                markersize=5, markerfacecolor="none", markeredgewidth=1.2)

    ax.set_xlabel("Sample index")
    ax.set_ylabel("ADC (corrected)")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = OUTPUT_DIR / f"discarded_{idx+1:02d}_rec{dd['record_id']}.png"
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [{idx+1}/10] Saved {out_path}", flush=True)

# ---------------------------------------------------------------------------
# Also plot 10 SURVIVED events for comparison
# ---------------------------------------------------------------------------
print("\nCollecting 10 survived events for comparison...", flush=True)

survived_data: List[dict] = []
gap_count = 0
for mp in main_pulses:
    rid = mp.metadata.get("record_id")
    waveform = waveforms[rid]
    mp_end = mp.end or len(waveform)

    ws = mp_end + 150
    we = min(mp_end + 500, len(waveform))
    ptp = float(np.ptp(waveform[ws:we])) if ws < we else 0.0

    if ptp >= DEFAULT_QUALITY_RMS_THRESHOLD:
        continue  # discarded, skip

    # Survived
    processed = waveform - mp.baseline

    # Baseline + corrected
    mask = np.ones(len(waveform), dtype=bool)
    mask[mp.start or 0:mp_end + 1] = False
    ksize = DEFAULT_MEDIAN_WINDOW_SIZE
    if ksize % 2 == 0:
        ksize += 1
    raw_baseline = medfilt(waveform.astype(np.float64), ksize)
    if not np.all(mask):
        invalid = ~mask
        valid_idx = np.where(mask)[0]
        if len(valid_idx) >= 2:
            raw_baseline[invalid] = np.interp(
                np.where(invalid)[0], valid_idx, raw_baseline[valid_idx],
            )
    corrected = waveform.astype(np.float64) - raw_baseline
    n_baseline = min(50, mp.start or 0)
    noise_rms = float(np.std(corrected[:n_baseline])) if n_baseline >= 3 else 0.5
    if noise_rms < 0.1:
        noise_rms = 0.5

    # Standard APs
    search_start = mp_end + AFTERPULSE_MIN_INTERVAL
    std_aps = []
    if search_start < len(processed):
        ref_points = []
        above = False
        for j in range(search_start, len(processed)):
            if processed[j] < -AFTERPULSE_AMPLITUDE_THRESHOLD:
                if not above:
                    ref_points.append(j)
                    above = True
            else:
                above = False
        ref_points = filter_points(ref_points, 2)
        for ref_idx in ref_points:
            try:
                st, minp, ed = findpulse_st_ed(processed, 0.0, ref_idx)
            except Exception:
                continue
            if ed >= st and abs(float(processed[minp])) >= AFTERPULSE_AMPLITUDE_THRESHOLD:
                std_aps.append({"start": st, "min": minp, "end": ed, "height": abs(float(processed[minp]))})

    survived_data.append({
        "record_id": rid,
        "waveform": waveform,
        "processed": processed,
        "baseline_val": mp.baseline,
        "mp_start": mp.start,
        "mp_end": mp_end,
        "mp_min": mp.sample_index,
        "mp_height": mp.height,
        "afterglow_ptp": ptp,
        "baseline_curve": raw_baseline,
        "corrected": corrected,
        "noise_rms": noise_rms,
        "std_aps": std_aps,
    })

    if len(survived_data) >= 10:
        break

SURVIVED_DIR = OUTPUT_DIR.parent / "survived_plots"  # analysis_v3/survived_plots
SURVIVED_DIR.mkdir(parents=True, exist_ok=True)

for idx, dd in enumerate(survived_data):
    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
    x = np.arange(len(dd["waveform"]))

    ax = axes[0]
    ax.plot(x, dd["waveform"], "k-", linewidth=0.6, label="Raw waveform")
    ax.axvspan(dd["mp_start"], dd["mp_end"], color="yellow", alpha=0.2, label="Main pulse")
    ax.axvline(dd["mp_min"], color="orange", linestyle="--", linewidth=1.0,
               label=f"Main pulse min (sample {dd['mp_min']})")
    ax.axhline(dd["baseline_val"], color="gray", linestyle=":", alpha=0.5)
    ws = dd["mp_end"] + 150
    we = min(dd["mp_end"] + 500, len(dd["waveform"]))
    ax.axvspan(ws, we, color="green", alpha=0.1, label=f"Quality window (PtP={dd['afterglow_ptp']:.1f})")
    ax.set_ylabel("ADC (raw)")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)
    ax.set_title(f"Record {dd['record_id']} — SURVIVED (PtP={dd['afterglow_ptp']:.1f} <= 30 ADC)  "
                 f"Main pulse: {dd['mp_height']:.0f} ADC", fontsize=11)

    ax = axes[1]
    ax.plot(x, dd["waveform"], "k-", linewidth=0.6, alpha=0.6, label="Raw waveform")
    ax.plot(x, dd["baseline_curve"], "r-", linewidth=1.2, label="Dynamic baseline (median)")
    ax.plot(x, dd["corrected"], "b-", linewidth=0.8, alpha=0.8, label="Corrected waveform")
    ax.axvspan(dd["mp_start"], dd["mp_end"], color="yellow", alpha=0.1)
    ax.set_ylabel("ADC")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    ax.plot(x, dd["corrected"], "b-", linewidth=0.7, alpha=0.8, label="Corrected waveform")
    ax.axhline(0, color="gray", linestyle="--", linewidth=0.5, alpha=0.5)
    threshold = -dd["noise_rms"] * DEFAULT_TRIGGER_SIGMA
    ax.axhline(threshold, color="green", linestyle="--", linewidth=1.0,
               label=f"Dynamic threshold = -5×RMS = {threshold:.1f} ADC")
    ax.axhline(-dd["noise_rms"], color="orange", linestyle=":", linewidth=0.8,
               label=f"Noise RMS = {dd['noise_rms']:.1f} ADC")
    for ap in dd["std_aps"]:
        ax.axvline(ap["min"], color="red", linestyle="-", linewidth=0.8, alpha=0.5)
        ax.plot(ap["min"], dd["corrected"][ap["min"]], "ro",
                markersize=5, markerfacecolor="none", markeredgewidth=1.2)
    ax.set_xlabel("Sample index")
    ax.set_ylabel("ADC (corrected)")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = SURVIVED_DIR / f"survived_{idx+1:02d}_rec{dd['record_id']}.png"
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [{idx+1}/10] Saved {out_path}", flush=True)

print(f"\nDiscarded plots: {OUTPUT_DIR}/")
print(f"Survived plots:  {SURVIVED_DIR}/")
print("Done.", flush=True)
