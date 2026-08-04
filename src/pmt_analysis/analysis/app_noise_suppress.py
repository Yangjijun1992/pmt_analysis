"""Afterpulse noise suppression module.

Implements dynamic baseline extraction and correction for channels with
large baseline drift (big-wave noise), following the algorithm described in
docs/after_pulse_noise_supress.md.

The noise suppression is only applied to channels whose baseline RMS >= 5 ADC
(as measured in the pre-main-pulse region). This avoids unnecessary computation
on clean channels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Default parameter constants
# ---------------------------------------------------------------------------

DEFAULT_NOISE_CHANNEL_RMS_THRESHOLD = 5.0       # ADC — channels above this are "noisy"
DEFAULT_QUALITY_RMS_THRESHOLD = 30.0            # ADC — discard individual events above this
DEFAULT_MEDIAN_WINDOW_SIZE = 51                 # samples — sliding median window size
DEFAULT_TRIGGER_SIGMA = 5.0                     # N — trigger = -N * noise_RMS
DEFAULT_SLOPE_THRESHOLD = 0.5                   # ADC/sample — minimum falling slope
DEFAULT_DEAD_TIME_SAMPLES = 35                  # samples — dead time between afterpulses
DEFAULT_AFTERPULSE_MIN_INTERVAL_SAMPLES = 35    # samples — afterpulse search gap after main pulse

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class NoiseSuppressionResult:
    """Per-channel result of noise detection and suppression parameters."""
    channel: int
    is_noisy: bool = False
    baseline_rms: float = 0.0
    median_window_size: int = DEFAULT_MEDIAN_WINDOW_SIZE
    trigger_sigma: float = DEFAULT_TRIGGER_SIGMA
    slope_threshold: float = DEFAULT_SLOPE_THRESHOLD
    quality_rms_threshold: float = DEFAULT_QUALITY_RMS_THRESHOLD
    dead_time_samples: int = DEFAULT_DEAD_TIME_SAMPLES
    event_count: int = 0
    valid_event_count: int = 0
    rejected_event_count: int = 0


@dataclass
class NoiseSuppressedAfterpulse:
    """A single afterpulse found via noise-suppressed search."""
    start: int
    end: int
    min_point: int
    height: float
    delay_time_ns: float


@dataclass
class NoiseSuppressedEvent:
    """Result of noise-suppressed afterpulse search for one event/waveform."""
    event_index: int
    record_id: int
    board: int
    channel: int
    raw_waveform: np.ndarray
    baseline_curve: np.ndarray
    corrected_waveform: np.ndarray
    noise_rms: float
    event_valid: bool
    main_pulse_start: int
    main_pulse_end: int
    afterpulses: List[NoiseSuppressedAfterpulse] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 0: Channel noise detection
# ---------------------------------------------------------------------------


def compute_channel_baseline_stats(
    waveforms_by_ch: Dict[int, List[np.ndarray]],
    n_baseline_samples: int = 30,
) -> Dict[int, float]:
    """Compute baseline RMS for each channel from the pre-pulse region.

    Args:
        waveforms_by_ch: Dict mapping channel index to list of raw waveforms.
        n_baseline_samples: Number of samples at the start of each waveform
            to use for baseline RMS estimation.

    Returns:
        Dict mapping channel index to baseline RMS (std of first samples).
    """
    stats: Dict[int, float] = {}
    for ch, waves in waveforms_by_ch.items():
        if not waves:
            stats[ch] = 0.0
            continue
        segments = []
        for w in waves:
            n = min(n_baseline_samples, len(w))
            segments.append(w[:n])
        stacked = np.concatenate(segments)
        stats[ch] = float(np.std(stacked))
    return stats


def detect_noisy_channels(
    waveforms_by_ch: Dict[int, List[np.ndarray]],
    rms_threshold: float = DEFAULT_NOISE_CHANNEL_RMS_THRESHOLD,
    n_baseline_samples: int = 30,
) -> Set[int]:
    """Identify channels whose baseline RMS exceeds the threshold.

    A channel is flagged as "noisy" (needs noise suppression) when the
    standard deviation of the baseline region (first n_baseline_samples)
    is >= rms_threshold (default: 5 ADC).

    Args:
        waveforms_by_ch: Dict mapping channel index -> list of raw waveforms.
        rms_threshold: RMS threshold in ADC for flagging a channel as noisy.
        n_baseline_samples: Samples to use for baseline region.

    Returns:
        Set of channel indices flagged as noisy.
    """
    stats = compute_channel_baseline_stats(
        waveforms_by_ch, n_baseline_samples=n_baseline_samples,
    )
    return {ch for ch, rms in stats.items() if rms >= rms_threshold}


# ---------------------------------------------------------------------------
# Phase 1: Event quality filter
# ---------------------------------------------------------------------------


def _check_event_quality(
    waveform: np.ndarray,
    main_pulse_end: int,
    quality_rms_threshold: float,
    window_start_offset: int = 150,
) -> bool:
    """Check if an event has acceptable quality after the main pulse.

    Computes peak-to-peak (PtP) in the afterglow search window
    [main_pulse_end + window_start_offset, main_pulse_end + 500] and rejects
    events whose PtP exceeds quality_rms_threshold.

    Returns:
        True if event is valid (good quality), False if should be discarded.
    """
    n = len(waveform)
    ws = main_pulse_end + window_start_offset
    we = min(main_pulse_end + 500, n)
    if we <= ws:
        return True  # not enough data to judge — accept
    segment = waveform[int(ws):int(we)]
    ptp = float(np.ptp(segment))
    return ptp < quality_rms_threshold


# ---------------------------------------------------------------------------
# Phase 2: Main pulse mask generation
# ---------------------------------------------------------------------------


def _generate_main_pulse_mask(
    waveform_length: int,
    main_pulse_start: int,
    main_pulse_end: int,
) -> np.ndarray:
    """Generate a boolean mask where True = non-main-pulse region.

    The main pulse region is masked out (False) to prevent it from
    biasing the baseline fit.

    Args:
        waveform_length: Total number of samples.
        main_pulse_start: Start index of the main pulse.
        main_pulse_end: End index of the main pulse.

    Returns:
        1D boolean array of length waveform_length.
    """
    mask = np.ones(waveform_length, dtype=bool)
    mask[main_pulse_start:main_pulse_end + 1] = False
    return mask


# ---------------------------------------------------------------------------
# Phase 2: Dynamic baseline extraction via sliding median
# ---------------------------------------------------------------------------


def _extract_baseline_median(
    waveform: np.ndarray,
    mask: np.ndarray,
    window_size: int = DEFAULT_MEDIAN_WINDOW_SIZE,
) -> np.ndarray:
    """Extract dynamic baseline curve using sliding median filter.

    Only non-masked (True) data points contribute to the median.
    Masked points (main pulse region) are interpolated from neighbouring
    valid median values via linear interpolation.

    Args:
        waveform: Raw waveform samples.
        mask: Boolean mask, True where data is valid for baseline fitting.
        window_size: Sliding median half-window (total window = 2*window_size + 1).

    Returns:
        Baseline curve array, same length as waveform.
    """
    n = len(waveform)
    baseline = np.zeros(n, dtype=np.float64)

    half = window_size // 2

    # Compute median at each point using only valid (masked) samples
    for i in range(n):
        left = max(0, i - half)
        right = min(n, i + half + 1)

        # Gather valid points in this window
        valid_vals = []
        for j in range(left, right):
            if mask[j]:
                valid_vals.append(waveform[j])

        if valid_vals:
            baseline[i] = np.median(valid_vals)
        else:
            baseline[i] = np.nan

    # Interpolate NaN regions (where no valid data was available)
    nan_mask = np.isnan(baseline)
    if np.any(nan_mask):
        x_valid = np.where(~nan_mask)[0]
        y_valid = baseline[~nan_mask]
        if len(x_valid) >= 2:
            baseline[nan_mask] = np.interp(
                np.where(nan_mask)[0], x_valid, y_valid,
            )

    return baseline


# ---------------------------------------------------------------------------
# Phase 3: Afterpulse search with dynamic threshold + slope check
# ---------------------------------------------------------------------------


def _find_afterpulses_with_suppression(
    corrected: np.ndarray,
    search_start: int,
    noise_rms: float,
    trigger_sigma: float = DEFAULT_TRIGGER_SIGMA,
    slope_threshold: float = DEFAULT_SLOPE_THRESHOLD,
    dead_time_samples: int = DEFAULT_DEAD_TIME_SAMPLES,
    dt_ns: float = 4.0,
    main_pulse_end: int = 0,
) -> List[NoiseSuppressedAfterpulse]:
    """Find afterpulses on baseline-corrected waveform.

    Uses dynamic amplitude threshold (-trigger_sigma * noise_rms) and a slope
    check to reject slowly-varying residual baseline drift.

    Args:
        corrected: Baseline-subtracted waveform.
        search_start: Sample index to start searching from.
        noise_rms: Current noise RMS of the corrected waveform.
        trigger_sigma: Multiplier for dynamic threshold.
        slope_threshold: Minimum falling slope (negative derivative) in ADC/sample.
        dead_time_samples: Minimum interval between consecutive afterpulses.
        dt_ns: Time per sample in ns (for delay calculation).
        main_pulse_end: End index of main pulse (for delay calculation).

    Returns:
        List of NoiseSuppressedAfterpulse found.
    """
    n = len(corrected)
    threshold = -trigger_sigma * noise_rms

    afterpulses: List[NoiseSuppressedAfterpulse] = []
    last_trigger_sample: Optional[int] = None

    i = search_start
    while i < n - 2:
        if corrected[i] >= threshold:
            i += 1
            continue

        # Potential trigger — check slope
        # Compute forward difference slope
        slope = float(corrected[i + 1] - corrected[i])
        if slope >= -slope_threshold:
            # Slope too flat — likely residual drift, skip
            i += 1
            continue

        # Dead time check
        if last_trigger_sample is not None and (i - last_trigger_sample) < dead_time_samples:
            i += 1
            continue

        # Find pulse boundaries
        # Walk left to find start (where signal stops falling)
        start = i
        while start > max(0, search_start):
            if corrected[start - 1] <= corrected[start]:
                start -= 1
            else:
                break

        # Find minimum point
        min_point = start
        min_val = corrected[start]
        j = start + 1
        while j < n and corrected[j] <= corrected[j - 1]:
            if corrected[j] < min_val:
                min_val = corrected[j]
                min_point = j
            j += 1

        # Walk right from min_point to find end (where signal returns near zero)
        end = min_point
        while end < n - 1:
            if corrected[end + 1] > corrected[end]:
                end += 1
            elif corrected[end] >= -noise_rms:
                break
            else:
                end += 1
                break

        # Validate minimum height
        height = abs(float(corrected[min_point]))
        if height < abs(threshold):
            i = end + 1
            continue

        delay_ns = float((start - main_pulse_end) * dt_ns)

        afterpulses.append(NoiseSuppressedAfterpulse(
            start=int(start),
            end=int(end + 1),
            min_point=int(min_point),
            height=height,
            delay_time_ns=delay_ns,
        ))

        last_trigger_sample = int(min_point)
        i = end + 1

    return afterpulses


# ---------------------------------------------------------------------------
# Phase 3: Noise RMS estimation on corrected waveform
# ---------------------------------------------------------------------------


def _estimate_noise_rms(
    corrected: np.ndarray,
    n_baseline: int = 50,
    search_start: int = 0,
) -> float:
    """Estimate noise RMS from the corrected waveform's quiet region.

    Uses the first n_baseline samples (pre-trigger region) of the corrected
    waveform, or if search_start > 0, the region before it.

    Args:
        corrected: Baseline-corrected waveform.
        n_baseline: Number of samples for RMS estimation.
        search_start: If > n_baseline, use samples [search_start-n_baseline:search_start].

    Returns:
        Estimated noise RMS.
    """
    if search_start > n_baseline:
        segment = corrected[search_start - n_baseline:search_start]
    else:
        n = min(n_baseline, len(corrected))
        segment = corrected[:n]
    if len(segment) == 0:
        return 1.0
    return float(np.std(segment))


# ---------------------------------------------------------------------------
# Top-level: Noise-suppressed afterpulse search for one event
# ---------------------------------------------------------------------------


def _process_event_with_noise_suppression(
    waveform: np.ndarray,
    main_pulse_start: int,
    main_pulse_end: int,
    event_index: int,
    record_id: int,
    board: int,
    channel: int,
    dt_ns: float,
    quality_rms_threshold: float = DEFAULT_QUALITY_RMS_THRESHOLD,
    median_window_size: int = DEFAULT_MEDIAN_WINDOW_SIZE,
    trigger_sigma: float = DEFAULT_TRIGGER_SIGMA,
    slope_threshold: float = DEFAULT_SLOPE_THRESHOLD,
    dead_time_samples: int = DEFAULT_DEAD_TIME_SAMPLES,
    afterpulse_min_interval: int = DEFAULT_AFTERPULSE_MIN_INTERVAL_SAMPLES,
) -> Optional[NoiseSuppressedEvent]:
    """Apply the full noise-suppression pipeline to a single event.

    Phase 1: Event quality filter (PtP check in afterglow window).
    Phase 2: Main pulse mask -> sliding median baseline -> subtract baseline.
    Phase 3: Dynamic threshold + slope-checked afterpulse search.

    Args:
        waveform: Raw waveform array.
        main_pulse_start: Start index of the main pulse.
        main_pulse_end: End index of the main pulse.
        event_index: Index of this event in the bundle.
        record_id: Record identifier.
        board: Board number.
        channel: Channel number.
        dt_ns: Sampling interval in nanoseconds.
        quality_rms_threshold: Maximum allowed PtP in afterglow window.
        median_window_size: Sliding median window size.
        trigger_sigma: Multiplier for dynamic threshold.
        slope_threshold: Minimum falling slope to accept trigger.
        dead_time_samples: Minimum distance between afterpulses.
        afterpulse_min_interval: Samples between main pulse end and search start.

    Returns:
        NoiseSuppressedEvent or None if event failed quality check.
    """
    n = len(waveform)

    # Phase 1: Event quality filter
    event_valid = _check_event_quality(
        waveform, main_pulse_end, quality_rms_threshold,
    )
    if not event_valid:
        return NoiseSuppressedEvent(
            event_index=event_index,
            record_id=record_id,
            board=board,
            channel=channel,
            raw_waveform=waveform.copy(),
            baseline_curve=np.zeros(n),
            corrected_waveform=waveform.copy(),
            noise_rms=0.0,
            event_valid=False,
            main_pulse_start=main_pulse_start,
            main_pulse_end=main_pulse_end,
        )

    # Phase 2: Mask and baseline extraction
    mask = _generate_main_pulse_mask(n, main_pulse_start, main_pulse_end)

    baseline_curve = _extract_baseline_median(
        waveform, mask, window_size=median_window_size,
    )

    # Subtract baseline
    corrected = waveform.astype(np.float64) - baseline_curve

    # Phase 3: Noise RMS estimation (using pre-pulse region of corrected)
    noise_rms = _estimate_noise_rms(corrected, n_baseline=50)

    # Search window start
    search_start = main_pulse_end + afterpulse_min_interval
    if search_start >= n:
        search_start = n - 1

    # Phase 3: Afterpulse search with dynamic threshold + slope check
    afterpulses = _find_afterpulses_with_suppression(
        corrected,
        search_start=search_start,
        noise_rms=noise_rms,
        trigger_sigma=trigger_sigma,
        slope_threshold=slope_threshold,
        dead_time_samples=dead_time_samples,
        dt_ns=dt_ns,
        main_pulse_end=main_pulse_end,
    )

    return NoiseSuppressedEvent(
        event_index=event_index,
        record_id=record_id,
        board=board,
        channel=channel,
        raw_waveform=waveform.copy(),
        baseline_curve=baseline_curve,
        corrected_waveform=corrected,
        noise_rms=noise_rms,
        event_valid=True,
        main_pulse_start=main_pulse_start,
        main_pulse_end=main_pulse_end,
        afterpulses=afterpulses,
    )


def find_afterpulses_with_noise_suppression(
    bundle: Any,
    main_pulses_by_ch: Dict[Tuple[int, int], List[Any]],
    noisy_channels: Set[int],
    noise_results: Dict[int, NoiseSuppressionResult],
    amplitude_threshold: float = 20.0,
    afterpulse_min_interval: int = DEFAULT_AFTERPULSE_MIN_INTERVAL_SAMPLES,
    quality_rms_threshold: float = DEFAULT_QUALITY_RMS_THRESHOLD,
    median_window_size: int = DEFAULT_MEDIAN_WINDOW_SIZE,
    trigger_sigma: float = DEFAULT_TRIGGER_SIGMA,
    slope_threshold: float = DEFAULT_SLOPE_THRESHOLD,
    dead_time_samples: int = DEFAULT_DEAD_TIME_SAMPLES,
) -> Dict[Tuple[int, int], List[Any]]:
    """Run noise-suppressed afterpulse search on noisy channels.

    For each main pulse on a noisy channel, applies:
      1. Event quality pre-filter (PtP in afterglow window)
      2. Main pulse masking
      3. Sliding median baseline extraction
      4. Baseline subtraction
      5. Dynamic threshold afterpulse search with slope check

    Args:
        bundle: RawDataBundle.
        main_pulses_by_ch: Dict from find_main_pulses_per_channel.
        noisy_channels: Set of channel indices flagged as noisy.
        noise_results: Per-channel NoiseSuppressionResult dict.
        amplitude_threshold: Not used directly (replaced by dynamic threshold).
        afterpulse_min_interval: Samples between main pulse end and search.
        quality_rms_threshold: PtP threshold for event rejection.
        median_window_size: Sliding median window size.
        trigger_sigma: Dynamic threshold multiplier.
        slope_threshold: Minimum falling slope.
        dead_time_samples: Minimum interval between afterpulses.

    Returns:
        Dict mapping (board, channel) -> list of AfterpulseRecord.
    """
    from pmt_analysis.analysis.app import AfterpulseRecord, cal_area

    rv = bundle.data
    records = rv.records

    # Build record_id lookup for all main pulses on noisy channels
    mp_by_record: Dict[int, List[Any]] = {}
    for (board, channel), pulses in main_pulses_by_ch.items():
        if channel not in noisy_channels:
            continue
        for mp in pulses:
            rid = mp.metadata.get("record_id")
            if rid is not None:
                if rid not in mp_by_record:
                    mp_by_record[rid] = []
                mp_by_record[rid].append((board, channel, mp))

    grouped: Dict[Tuple[int, int], List[Any]] = {}

    for i in range(len(records)):
        rec = records[i]
        record_id = int(rec["record_id"])
        if record_id not in mp_by_record:
            continue

        dt_ns = float(rec["dt"])
        waveform = rv.signals(np.array([record_id]))[0]

        for board, channel, mp in mp_by_record[record_id]:
            if channel not in noisy_channels:
                continue

            ch_key = (board, channel)

            result = _process_event_with_noise_suppression(
                waveform=waveform,
                main_pulse_start=mp.start or 0,
                main_pulse_end=mp.end or len(waveform),
                event_index=mp.event_index or i,
                record_id=record_id,
                board=board,
                channel=channel,
                dt_ns=dt_ns,
                quality_rms_threshold=quality_rms_threshold,
                median_window_size=median_window_size,
                trigger_sigma=trigger_sigma,
                slope_threshold=slope_threshold,
                dead_time_samples=dead_time_samples,
                afterpulse_min_interval=afterpulse_min_interval,
            )

            if result is None or not result.event_valid:
                continue

            if ch_key not in grouped:
                grouped[ch_key] = []

            corrected = result.corrected_waveform

            for idx, ap in enumerate(result.afterpulses):
                try:
                    charge = cal_area(corrected, ap.start, ap.end, 0.0)
                except Exception:
                    continue

                ap_record = AfterpulseRecord(
                    event_index=mp.event_index,
                    channel_index=channel,
                    delay_time=ap.delay_time_ns,
                    height=ap.height,
                    charge=charge,
                    start=ap.start,
                    end=ap.end,
                    min_point=ap.min_point,
                    metadata={
                        "board": board,
                        "record_id": record_id,
                        "pulse_index": idx + 1,
                        "main_pulse_end": mp.end,
                        "dt_ns": dt_ns,
                        "noise_suppressed": True,
                        "noise_rms": result.noise_rms,
                    },
                )
                grouped[ch_key].append(ap_record)

    return grouped


# ---------------------------------------------------------------------------
# Phase 4: Debug visualization (Section 4.1 of requirements)
# ---------------------------------------------------------------------------


def plot_noise_suppression_debug(
    event: NoiseSuppressedEvent,
    output_path: str,
    title: str = "",
    max_events_to_show: int = 1,
) -> Optional[str]:
    """Generate a debug plot showing the noise suppression pipeline stages.

    The figure contains:
      1. Raw waveform (black)
      2. Extracted dynamic baseline (red)
      3. Corrected waveform (blue)
      4. Dynamic trigger threshold (green dashed)
      5. Detected afterpulse trigger points (red circles / vertical lines)

    This implements Section 4.1 of docs/after_pulse_noise_supress.md.

    Args:
        event: NoiseSuppressedEvent to visualize.
        output_path: Path to save the figure.
        title: Optional title override.
        max_events_to_show: Unused (reserved for batch mode).

    Returns:
        Path to saved figure, or None if event is not valid for plotting.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path

    if not event.event_valid:
        return None

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    n = len(event.raw_waveform)
    x = np.arange(n)

    # --- Top panel: Raw waveform + baseline ---
    ax1.plot(x, event.raw_waveform, "k-", linewidth=0.8, alpha=0.8, label="Raw waveform")
    ax1.plot(x, event.baseline_curve, "r-", linewidth=1.5, alpha=0.9, label="Dynamic baseline (median)")
    ax1.fill_between(
        x,
        _min(event.main_pulse_start, n),
        _min(event.main_pulse_end, n),
        color="yellow",
        alpha=0.15,
        label="Main pulse region (masked)",
    )
    ax1.set_ylabel("ADC (raw)", fontsize=11)
    ax1.legend(fontsize=8, loc="upper right")
    ax1.grid(True, alpha=0.3)
    ax1.set_title(title or f"CH{event.channel} Event {event.record_id} — Noise Suppression Debug", fontsize=11)

    # --- Bottom panel: Corrected waveform + triggers ---
    ax2.plot(x, event.corrected_waveform, "b-", linewidth=0.8, alpha=0.8, label="Corrected waveform")
    ax2.axhline(y=0, color="gray", linestyle="--", linewidth=0.5, alpha=0.5)

    threshold = -event.noise_rms * DEFAULT_TRIGGER_SIGMA
    ax2.axhline(
        y=threshold, color="green", linestyle="--", linewidth=1.0,
        label=f"Threshold = -{DEFAULT_TRIGGER_SIGMA}*RMS = {threshold:.1f} ADC",
    )
    ax2.axhline(
        y=-event.noise_rms, color="orange", linestyle=":", linewidth=0.8,
        label=f"Noise RMS = {event.noise_rms:.1f} ADC",
    )

    for ap in event.afterpulses:
        ax2.axvline(x=ap.min_point, color="red", linestyle="-", linewidth=1.0, alpha=0.7)
        ax2.plot(
            ap.min_point, event.corrected_waveform[ap.min_point],
            "ro", markersize=6, markerfacecolor="none", markeredgewidth=1.5,
        )

    ax2.set_xlabel("Sample index", fontsize=11)
    ax2.set_ylabel("ADC (corrected)", fontsize=11)
    ax2.legend(fontsize=8, loc="upper right")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = Path(output_path) if output_path else Path("noise_suppression_debug.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)


def _min(a: int, b: int) -> int:
    return a if a < b else b
