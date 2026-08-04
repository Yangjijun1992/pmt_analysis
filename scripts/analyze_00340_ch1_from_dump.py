#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PMT Afterpulse Analysis Framework — Run 00340 CH1 (LV2387)

================================================================================
                    FULL ANALYSIS PIPELINE OVERVIEW
================================================================================

STEP 0: Noise channel detection (OPTIONAL — disabled in this script)
  ─ Take 100 waveforms per channel, compute baseline RMS from first 30 samples.
  ─ If RMS >= threshold (default 5 ADC), channel is "noisy".
  ─ Noisy channels trigger noise-suppressed afterpulse search (Step 2b).
  ─ Clean channels use simple threshold-based search (Step 2a).
  ─ Disabled here: no RMS detection, all channels use same path.

STEP 1: Find main pulses
  ─ Modified from find_main_pulses_per_channel():
    • First sample crossing -500 ADC threshold → defines the main pulse.
    • Find minimum within ±200 samples from the crossing.
    • Start: backtrack from minimum to baseline (processed signal >= 0).
    • End: forward from minimum to baseline (processed signal >= 0).
  ─ Record: (start, end, min_point, height, charge, baseline).

STEP 2a: Standard afterpulse search
  ─ Search region: from main_pulse.end + 35 samples to end of waveform.
   ─ Threshold: signal < -50 ADC → potential afterpulse candidate.
  ─ For each candidate: findpulse_st_ed() locates start/min/end.
  ─ Filter: min interval 2 samples between crossings.
  ─ Record: (delay_time, height, charge, start, min_point, end).

STEP 2b: Noise-suppressed afterpulse search
  ─ Applied to noise-prone channels. A 5-phase pipeline:

    PHASE 1 — Main pulse masking
      • Create boolean mask: main pulse region = False, rest = True.
      • Prevents the main pulse from biasing the baseline fit.

    PHASE 2 — Dynamic baseline extraction
      • Apply sliding median filter (window=51 samples) to waveform.
      • Only valid (non-masked) points contribute to median.
      • Masked region (main pulse) is linearly interpolated.
      • Corrected waveform = raw waveform - baseline curve.

    PHASE 3 — Noise RMS estimation
      • Take first 50 samples of corrected waveform (pre-pulse region).
      • Compute std dev → noise_rms.

    PHASE 4 — Dynamic threshold search
      • Dynamic trigger = -(trigger_sigma × noise_rms) = -(5 × noise_rms).
      • Scan corrected waveform. Two criteria for a hit:
        a. Amplitude < dynamic threshold.
        b. Falling slope (forward diff) >= slope_threshold (0.5 ADC/sample)
           → rejects slowly-varying residual drift.
      • Once triggered: walk left to find true start, walk right to min,
        then walk right from min to find end (returns near -noise_rms).

    PHASE 5 — Dead-time deduplication
      • Minimum 35 samples between consecutive afterpulses.

STEP 3: Afterpulse deduplication (select_afterpulses_per_channel)
  ─ Group afterpulse candidates by record_id.
  ─ Within each event, sort by min_point.
  ─ Keep only pulses spaced >= 10 samples apart.

STEP 4: SPE gain loading
  ─ Load per-PMT single-photoelectron gain from database.
  ─ pmtdata client → fallback: local SQLite DB.

STEP 5: PE normalization
  ─ Divide all charges (main + afterpulse) by SPE gain → photoelectrons.

STEP 6: APP computation
  ─ APP = Σ(afterpulse_charge) / Σ(main_pulse_charge).
  ─ APP_PE = Σ(afterpulse_charge_PE) / Σ(main_pulse_charge_PE).

================================================================================
"""

import sys, time, json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import medfilt

sys.path.insert(0, "/home/yjj/pmt_analysis/src")
from pmt_analysis.runinfo import get_runinfo
from pmt_analysis.analysis.app import (
    MainPulseRecord, AfterpulseRecord,
    preprocess_waveform, cal_area, findpulse_st_ed, filter_points,
    select_afterpulses_per_channel, load_spe_gains_by_pmt_id,
    normalize_to_pe_per_channel, compute_app_per_channel,
    DEFAULT_MIN_INTERVAL_BETWEEN_PULSES,
)
from pmt_analysis.analysis.app_noise_suppress import (
    DEFAULT_MEDIAN_WINDOW_SIZE, DEFAULT_TRIGGER_SIGMA,
    DEFAULT_SLOPE_THRESHOLD, DEFAULT_DEAD_TIME_SAMPLES,
    DEFAULT_AFTERPULSE_MIN_INTERVAL_SAMPLES,
)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
DUMP_DIR         = Path("/home/yjj/pmt_analysis/output/00340_ch1_dump")
WAVEFORM_DIR     = DUMP_DIR / "waveforms"
OUTPUT_DIR       = DUMP_DIR / "analysis_v4"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAIN_PULSE_THR   = 500   # ADC — height threshold for main pulse
AP_AMP_THR       = 50    # ADC — height threshold for standard afterpulse search
AP_MIN_INTERVAL  = 35    # samples — gap after main pulse before AP search
AP_DEDUP_INTERVAL = 10   # samples — min gap between two afterpulses

BOARD    = 0
CHANNEL  = 1
DT_NS    = 4.0            # 250 MHz → 4 ns/sample
WAVEFORM_LEN = 1500

# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════
print("=" * 80)
print("PMT Afterpulse Analysis — Run 00340 CH1 (LV2387)")
print("=" * 80)

t0 = time.time()
with open(DUMP_DIR / "record_ids.txt") as f:
    record_ids = [int(line.strip()) for line in f if line.strip()]
print(f"\nLoaded {len(record_ids)} record IDs")

waveforms: Dict[int, np.ndarray] = {}
for rid in record_ids:
    waveforms[rid] = np.load(WAVEFORM_DIR / f"{rid}.npy")
print(f"Loaded {len(waveforms)} waveforms ({time.time() - t0:.1f}s)")

ri = get_runinfo("00340", "/mnt/data/TPC")
pmt_id_map: Dict[Tuple[int, int], str] = {}
for bi in ri.metadata.get("mapping", []):
    for ch_info in bi.get("channels", []):
        pmt_id_map[(bi["board_id"], ch_info["ch"])] = ch_info["pmt"]
PMT_ID = pmt_id_map.get((BOARD, CHANNEL), "?")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: FIND MAIN PULSES
# ═══════════════════════════════════════════════════════════════════════════════
def step1_find_main_pulses(
    record_ids, waveforms, height_threshold=MAIN_PULSE_THR
) -> Tuple[List[MainPulseRecord], Dict[int, MainPulseRecord]]:
    """
    Locate the main pulse in each waveform.

    Algorithm:
      1. For each waveform, subtract initial baseline (mean of first 30 samples).
      2. Find the FIRST sample where processed[i] < -height_threshold.
      3. Search ±200 samples from crossing to find the true minimum.
      4. Backtrack from minimum to baseline (processed[i] >= 0) → start.
      5. Forward from minimum to baseline (processed[i] >= 0) → end.
      6. Compute charge = ∫ (baseline − signal) × PE_FACT over [start, end].
    """
    pulses: List[MainPulseRecord] = []
    rid_to_mp: Dict[int, MainPulseRecord] = {}

    for rid in record_ids:
        wf = waveforms[rid]
        processed, baseline_val = preprocess_waveform(wf)

        # (a) Find first threshold crossing
        first_crossing = None
        for i in range(len(processed)):
            if processed[i] < -height_threshold:
                first_crossing = i
                break
        if first_crossing is None:
            continue

        # (b) Find minimum near the crossing
        search_end = min(len(processed), first_crossing + 200)
        min_idx = first_crossing
        for i in range(first_crossing + 1, search_end):
            if processed[i] < processed[min_idx]:
                min_idx = i
            if i > first_crossing + 5 and processed[i] > -height_threshold:
                break
        # Cross-check with global argmin within 300 samples
        abs_min = int(np.argmin(processed))
        if abs(abs_min - first_crossing) < 300 and processed[abs_min] < processed[min_idx]:
            min_idx = abs_min

        pulse_height = abs(float(processed[min_idx]))
        if pulse_height < height_threshold:
            continue

        # (c) Backtrack from minimum to baseline crossover
        start_idx = min_idx
        for i in range(min_idx - 1, -1, -1):
            if processed[i] >= 0:
                start_idx = i + 1
                break
        else:
            start_idx = 0

        # (d) Forward from minimum to baseline crossover
        end_idx = min_idx
        for i in range(min_idx + 1, len(processed)):
            if processed[i] >= 0:
                end_idx = i
                break
        else:
            end_idx = len(processed) - 1
        if end_idx <= start_idx:
            continue

        charge = cal_area(processed, start_idx, end_idx + 1, 0.0)

        mp = MainPulseRecord(
            event_index=rid, channel_index=CHANNEL,
            sample_index=min_idx, height=pulse_height, charge=charge,
            start=start_idx, end=end_idx + 1, baseline=baseline_val,
            metadata={"board": BOARD, "record_id": rid},
        )
        pulses.append(mp)
        rid_to_mp[rid] = mp

    return pulses, rid_to_mp


print(f"\n{'─' * 80}")
print(f"STEP 1: Find main pulses (threshold={MAIN_PULSE_THR} ADC)")
print(f"{'─' * 80}")
t0 = time.time()
main_pulses, rid_to_mp = step1_find_main_pulses(record_ids, waveforms)
n_main = len(main_pulses)
print(f"  Found {n_main} main pulses from {len(record_ids)} waveforms "
      f"({time.time() - t0:.1f}s)")
print(f"  Rate: {n_main / len(record_ids) * 100:.1f}% of waveforms have a main pulse")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2a: STANDARD AFTERPULSE SEARCH
# ═══════════════════════════════════════════════════════════════════════════════
def step2a_standard_ap_search(
    record_ids, waveforms, rid_to_mp,
    amp_threshold=AP_AMP_THR, min_interval=AP_MIN_INTERVAL,
) -> List[AfterpulseRecord]:
    """
    Simple fixed-threshold afterpulse search.

    For each main pulse:
      1. Take the processed (baseline-subtracted) waveform.
      2. Search from (main_pulse.end + 35) to end of waveform.
      3. Every region where signal < -20 ADC → candidate afterpulse.
      4. Use findpulse_st_ed() to locate pulse boundaries.
      5. Filter: at least 2 samples between consecutive crossings.
    """
    aps: List[AfterpulseRecord] = []

    for rid in record_ids:
        if rid not in rid_to_mp:
            continue
        mp = rid_to_mp[rid]
        if mp.end is None:
            continue

        wf = waveforms[rid]
        processed, _ = preprocess_waveform(wf)

        search_start = mp.end + min_interval
        if search_start >= len(processed):
            continue

        # Find all threshold crossings
        ref_points: List[int] = []
        above = False
        for j in range(search_start, len(processed)):
            if processed[j] < -amp_threshold:
                if not above:
                    ref_points.append(j)
                    above = True
            else:
                above = False
        ref_points = filter_points(ref_points, 2)

        # For each crossing, find pulse boundaries
        for idx, ref_idx in enumerate(ref_points):
            try:
                st, minp, ed = findpulse_st_ed(processed, 0.0, ref_idx)
            except Exception:
                continue
            if ed < st:
                continue
            height = abs(float(processed[minp]))
            if height < amp_threshold:
                continue

            charge = cal_area(processed, st, ed + 1, 0.0)
            delay_ns = (st - mp.end) * DT_NS

            ap = AfterpulseRecord(
                event_index=rid, channel_index=CHANNEL,
                delay_time=float(delay_ns), height=height, charge=charge,
                start=st, end=ed + 1, min_point=minp,
                metadata={
                    "board": BOARD, "record_id": rid,
                    "pulse_index": idx + 1, "main_pulse_end": mp.end, "dt_ns": DT_NS,
                },
            )
            aps.append(ap)

    return aps


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2b: NOISE-SUPPRESSED AFTERPULSE SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

# --- Phase 2 & 3: Mask + dynamic baseline ---
def _phase23_baseline_correction(
    waveform: np.ndarray, mp_start: int, mp_end: int, window_size: int,
) -> np.ndarray:
    """
    Extract dynamic baseline and produce corrected waveform.

    1. Create mask: main pulse region = False, rest = True.
    2. Apply sliding median filter (scipy.signal.medfilt) to whole waveform.
    3. Re-interpolate masked (main pulse) region from neighboring valid values.
    4. Corrected = raw − baseline.
    """
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

    corrected = waveform.astype(np.float64) - baseline
    return corrected


# --- Phase 4: Noise RMS estimation ---
def _phase4_estimate_noise_rms(
    corrected: np.ndarray, mp_start: int, n_baseline: int = 50,
) -> float:
    """
    Estimate noise level from pre-pulse region of corrected waveform.
    """
    n = min(n_baseline, mp_start)
    if n < 3:
        return 0.5
    rms = float(np.std(corrected[:n]))
    return max(rms, 0.5)  # prevent degenerate threshold


# --- Phase 5 & 6: Dynamic threshold search ---
def _phase56_find_afterpulses(
    corrected: np.ndarray,
    search_start: int,
    noise_rms: float,
    trigger_sigma: float,
    slope_threshold: float,
    dead_time: int,
    dt_ns: float,
    mp_end: int,
) -> List[dict]:
    """
    Search for afterpulses on baseline-corrected waveform.

    Dynamic amplitude threshold = -(trigger_sigma × noise_rms).
    Two-pass validation:
      a. Signal < dynamic threshold.
      b. Forward-difference slope <= -slope_threshold (rejects slow drift).

    On trigger:
      - Walk left to find true start.
      - Walk right to find minimum point.
      - Walk right from minimum to find end (returns near -noise_rms).
      - Dead-time: skip next (dead_time) samples after each hit.
    """
    n = len(corrected)
    threshold = -(trigger_sigma * noise_rms)
    results: List[dict] = []
    last_trigger: Optional[int] = None
    i = search_start

    while i < n - 2:
        # (a) Amplitude check
        if corrected[i] >= threshold:
            i += 1
            continue

        # (b) Slope check
        slope = float(corrected[i + 1] - corrected[i])
        if slope >= -slope_threshold:
            i += 1
            continue

        # (c) Dead-time check
        if last_trigger is not None and (i - last_trigger) < dead_time:
            i += 1
            continue

        # Find pulse start (walk left)
        start = i
        while start > max(0, search_start):
            if corrected[start - 1] <= corrected[start]:
                start -= 1
            else:
                break

        # Find minimum
        min_point = start
        min_val = corrected[start]
        j = start + 1
        while j < n and corrected[j] <= corrected[j - 1]:
            if corrected[j] < min_val:
                min_val, min_point = corrected[j], j
            j += 1

        # Find end (walk right from min until returning near -noise_rms)
        end = min_point
        for e in range(min_point + 1, n):
            if corrected[e] >= -noise_rms * 0.3:
                end = e
                break
        else:
            end = n - 1

        # Validate minimum height
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
        continue

    return results


def step2b_noise_suppressed_ap_search(
    record_ids, waveforms, rid_to_mp,
    med_win=DEFAULT_MEDIAN_WINDOW_SIZE,
    trig_sigma=DEFAULT_TRIGGER_SIGMA,
    slope_thr=DEFAULT_SLOPE_THRESHOLD,
    dead_time=DEFAULT_DEAD_TIME_SAMPLES,
    ap_min_interval=DEFAULT_AFTERPULSE_MIN_INTERVAL_SAMPLES,
) -> List[AfterpulseRecord]:
    """
    Full noise-suppressed afterpulse search.

    For each main pulse event:
      Phase 1: Generate main pulse mask.
      Phase 2: Sliding median baseline extraction → subtract → corrected waveform.
      Phase 3: Estimate noise RMS from pre-pulse region.
      Phase 4: Dynamic threshold search with slope validation.
      Phase 5: Dead-time deduplication.
    """
    aps: List[AfterpulseRecord] = []

    for rid in record_ids:
        if rid not in rid_to_mp:
            continue
        mp = rid_to_mp[rid]
        wf = waveforms[rid]
        mp_start = mp.start or 0
        mp_end = mp.end or WAVEFORM_LEN

        # Phase 1 & 2: mask + baseline correction
        corrected = _phase23_baseline_correction(wf, mp_start, mp_end, med_win)

        # Phase 3: noise RMS estimation
        noise_rms = _phase4_estimate_noise_rms(corrected, mp_start)

        # Search window
        search_start = mp_end + ap_min_interval
        if search_start >= WAVEFORM_LEN:
            search_start = WAVEFORM_LEN - 1

        # Phase 4 & 5: dynamic threshold search + dead-time
        found = _phase56_find_afterpulses(
            corrected, search_start, noise_rms,
            trig_sigma, slope_thr, dead_time, DT_NS, mp_end,
        )

        for idx, ap in enumerate(found):
            try:
                charge = cal_area(corrected, ap["start"], ap["end"], 0.0)
            except Exception:
                continue

            ap_record = AfterpulseRecord(
                event_index=rid, channel_index=CHANNEL,
                delay_time=ap["delay_time_ns"], height=ap["height"],
                charge=charge,
                start=ap["start"], end=ap["end"], min_point=ap["min_point"],
                metadata={
                    "board": BOARD, "record_id": rid,
                    "pulse_index": idx + 1, "main_pulse_end": mp_end,
                    "dt_ns": DT_NS,
                    "noise_suppressed": True, "noise_rms": noise_rms,
                },
            )
            aps.append(ap_record)

    return aps


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

# --- Standard afterpulse search ---
print(f"\n{'─' * 80}")
print(f"STEP 2a: Standard afterpulse search "
      f"(threshold={AP_AMP_THR} ADC, min_interval={AP_MIN_INTERVAL})")
print(f"{'─' * 80}")
t0 = time.time()
std_aps = step2a_standard_ap_search(record_ids, waveforms, rid_to_mp)
print(f"  Found {len(std_aps)} candidates ({time.time() - t0:.1f}s)")

# --- Noise-suppressed afterpulse search ---
print(f"\n{'─' * 80}")
print(f"STEP 2b: Noise-suppressed afterpulse search")
print(f"  Phase 1: mask main pulse region")
print(f"  Phase 2: sliding median baseline, window = {DEFAULT_MEDIAN_WINDOW_SIZE} samples")
print(f"  Phase 3: noise RMS from pre-pulse (first 50 samples)")
print(f"  Phase 4: dynamic threshold = -{DEFAULT_TRIGGER_SIGMA}×RMS, "
      f"slope >= {DEFAULT_SLOPE_THRESHOLD} ADC/sample")
print(f"  Phase 5: dead time = {DEFAULT_DEAD_TIME_SAMPLES} samples")
print(f"{'─' * 80}")
t0 = time.time()
ns_aps = step2b_noise_suppressed_ap_search(
    record_ids, waveforms, rid_to_mp,
)
print(f"  Processed {n_main} events")
print(f"  Found {len(ns_aps)} candidates ({time.time() - t0:.1f}s)")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: AFTERPULSE DEDUPLICATION
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{'─' * 80}")
print(f"STEP 3: Afterpulse deduplication "
      f"(min interval={DEFAULT_MIN_INTERVAL_BETWEEN_PULSES} samples)")
print(f"{'─' * 80}")

def dedup(aps_list, label):
    by_ch = {(BOARD, CHANNEL): aps_list}
    selected = select_afterpulses_per_channel(by_ch)
    final = selected.get((BOARD, CHANNEL), [])
    print(f"  [{label}] {len(aps_list)} → {len(final)} after dedup")
    return final

std_final = dedup(std_aps, "Standard")
ns_final = dedup(ns_aps, "Noise-suppressed")


# ═══════════════════════════════════════════════════════════════════════════════
# STEPS 4-6: SPE GAIN + PE NORMALIZATION + APP
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{'─' * 80}")
print(f"STEPS 4-6: SPE gain loading → PE normalization → APP computation")
print(f"{'─' * 80}")

spe_gains = load_spe_gains_by_pmt_id(pmt_id_map)
main_by_ch = {(BOARD, CHANNEL): main_pulses}

def compute_app(aps_list, label):
    by_ch = {(BOARD, CHANNEL): aps_list}
    normalize_to_pe_per_channel(main_by_ch, by_ch, spe_gains)
    results = compute_app_per_channel(main_by_ch, by_ch, spe_gains)
    ch_r = results[0] if results else None
    if ch_r:
        gs = f"{ch_r.spe_gain:.4f}" if ch_r.spe_gain else "N/A"
        ar = f"{ch_r.app_value:.6f}" if ch_r.app_value else "N/A"
        ap = f"{ch_r.app_value_pe:.6f}" if ch_r.app_value_pe else "N/A"
        print(f"\n  [{label}] CH{CHANNEL} ({PMT_ID})")
        print(f"    Main pulses:       {ch_r.main_pulse_count:>8}")
        print(f"    Afterpulses:       {ch_r.afterpulse_count:>8}")
        print(f"    Main pulses w/ AP: {ch_r.main_pulse_with_afterpulse_count:>8}")
        print(f"    Main charge:       {ch_r.main_pulse_charge:>14.6f}")
        print(f"    AP charge:         {ch_r.afterpulse_charge:>14.6f}")
        print(f"    APP_raw:           {ar:>14}")
        print(f"    APP_PE:            {ap:>14}")
        print(f"    SPE gain:          {gs:>14}")
    return results

std_results = compute_app(std_final, "Standard")
ns_results = compute_app(ns_final, "Noise-suppressed")


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY TABLE
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{'═' * 80}")
print(f"SUMMARY — CH{CHANNEL} ({PMT_ID})")
print(f"{'═' * 80}")
header = (f"{'Method':<20} {'Main':>7} {'AP_cand':>8} {'AP_sel':>7} "
          f"{'Main_w_AP':>10} {'APP_raw':>12} {'APP_PE':>12}")
print(header)
print("-" * 80)
for label, aps_cand, aps_sel, results in [
    ("Standard", std_aps, std_final, std_results),
    ("Noise-suppressed", ns_aps, ns_final, ns_results),
]:
    ch_r = results[0] if results else None
    if ch_r:
        ar = f"{ch_r.app_value:.6f}" if ch_r.app_value else "N/A"
        ap = f"{ch_r.app_value_pe:.6f}" if ch_r.app_value_pe else "N/A"
        print(f"{label:<20} {ch_r.main_pulse_count:>7} "
              f"{len(aps_cand):>8} {len(aps_sel):>7} "
              f"{ch_r.main_pulse_with_afterpulse_count:>10} {ar:>12} {ap:>12}")


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{'─' * 80}")
print("EXPORT")
print(f"{'─' * 80}")

for method, aps, ch_results in [
    ("standard", std_final, std_results),
    ("noise_suppressed", ns_final, ns_results),
]:
    method_dir = OUTPUT_DIR / method
    method_dir.mkdir(parents=True, exist_ok=True)
    ch_r = ch_results[0] if ch_results else None

    config = {
        "run_id": "00340", "pmt_id": PMT_ID,
        "channel": CHANNEL, "board": BOARD,
        "main_pulse_threshold": MAIN_PULSE_THR,
        "main_pulse_algorithm": "first_crossing_500adc_baseline_bounds",
        "method": method,
        "total_waveforms": len(record_ids),
    }
    if method == "noise_suppressed":
        config["noise_suppression"] = {
            "median_window": DEFAULT_MEDIAN_WINDOW_SIZE,
            "trigger_sigma": DEFAULT_TRIGGER_SIGMA,
            "slope_threshold": DEFAULT_SLOPE_THRESHOLD,
            "dead_time": DEFAULT_DEAD_TIME_SAMPLES,
        }

    results_json = {
        "config": config,
        "results": {
            "main_pulse_count": ch_r.main_pulse_count if ch_r else 0,
            "afterpulse_candidate_count": len(aps),
            "afterpulse_selected_count": ch_r.afterpulse_count if ch_r else 0,
            "main_pulse_with_afterpulse_count": ch_r.main_pulse_with_afterpulse_count if ch_r else 0,
            "app_raw": ch_r.app_value if ch_r else None,
            "app_pe": ch_r.app_value_pe if ch_r else None,
            "spe_gain": ch_r.spe_gain if ch_r else None,
        },
    }
    (method_dir / "results.json").write_text(json.dumps(results_json, indent=2))

    ap_data = []
    for ap in aps:
        ap_data.append({
            "record_id":   ap.metadata.get("record_id"),
            "delay_ns":    ap.delay_time,
            "height_adc":  ap.height,
            "charge_raw":  ap.charge,
            "charge_pe":   ap.charge_pe,
            "start":       ap.start,
            "min_point":   ap.min_point,
            "end":         ap.end,
            "noise_rms":   ap.metadata.get("noise_rms"),
        })
    (method_dir / "afterpulses.json").write_text(json.dumps(ap_data, indent=2))
    print(f"  {method_dir}/")

print(f"\nDone.")
