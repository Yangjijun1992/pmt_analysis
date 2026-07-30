from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import numpy as np

from pmt_analysis.io.raw_reader import RawDataBundle


DEFAULT_BASELINE_SAMPLES = 10
DEFAULT_BASELINE_DEVIATION_THRESHOLD = 15200.0  # ADC

# Rising-edge sharpness thresholds for sin/cos noise rejection.
# Oscillation noise has a smooth, continuous waveform where the steepest
# falling edge is similar in magnitude to adjacent edges. A real PMT
# pulse has a much sharper falling edge that stands out.
#
# edge_sharpness = max_neg_slope / rms_of_diff
#   where max_neg_slope = max(-diff(wave))  (steepest single-sample drop)
#         rms_of_diff   = std(diff(wave))   (typical edge variation)
#
# For oscillation noise:    edge_sharpness ~ 2-4
# For real PMT dark pulse:  edge_sharpness > 6
DEFAULT_EDGE_SHARPNESS_THRESHOLD = 6.0

# Rising-edge prominence: max_neg_slope / pulse_height
# For oscillation noise with low amplitude (<80 ADC), the falling edge
# is gradual relative to pulse_height.
# For real PMT pulses, the edge is very steep relative to pulse_height.
# Used only when pulse_height < 80 ADC (low-amplitude ambiguous region).
DEFAULT_EDGE_PROMINENCE_LOW = 0.8
DEFAULT_LOW_HEIGHT_THRESHOLD = 80.0  # ADC

# For validation plot: channels with noise/dark ratio > this are flagged
# as noise-dominated channels and plotted with distinct colors.
DEFAULT_NOISE_DARK_RATIO_THRESHOLD = 3.0


@dataclass
class PulseRecord:
    """Single pulse analysis result."""

    record_id: int
    board: int
    channel: int
    pulse_height: float
    pulse_range: float
    asymmetry: float
    is_dark_count: bool
    baseline_deviation: float = 0.0
    edge_sharpness: float = 0.0
    edge_prominence: float = 0.0


@dataclass
class ChannelDarkCountResult:
    """Dark count analysis result for a single channel."""

    board: int
    channel: int
    total_pulses: int
    dark_count: int
    noise_count: int
    dark_count_rate_hz: Optional[float] = None
    asymmetry_values: List[float] = field(default_factory=list)
    baseline_deviations: List[float] = field(default_factory=list)
    edge_sharpness_values: List[float] = field(default_factory=list)
    edge_prominence_values: List[float] = field(default_factory=list)
    rms_values: List[float] = field(default_factory=list)
    is_dark_count_list: List[bool] = field(default_factory=list)


@dataclass
class DarkCountResult:
    """Complete dark count analysis result."""

    asymmetry_threshold: float
    total_pulse_count: int
    total_dark_count: int
    total_noise_count: int
    total_daq_run_time_length_s: Optional[float] = None
    dark_count_rate_hz: Optional[float] = None
    channels: List[ChannelDarkCountResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    noisy_channels: Set[tuple] = field(default_factory=set)


def estimate_total_daq_run_time_length(bundle: RawDataBundle) -> Optional[float]:
    """Estimate total DAQ run time length from records.

    Uses the notebook method: (time_max - time_min) * 1e-9

    Returns time in seconds, or None if无法计算.
    """
    rv = bundle.data
    records = rv.records

    if len(records) == 0:
        return None

    time_min = int(records["time"].min())
    time_max = int(records["time"].max())

    if time_max <= time_min:
        return None

    daq_time_s = (time_max - time_min) * 1e-9
    return daq_time_s


def _compute_edge_features(wave: np.ndarray) -> tuple:
    """Compute rising-edge sharpness features for sin/cos noise rejection.

    Returns:
        (edge_sharpness, edge_prominence) tuple.

    edge_sharpness = max_neg_slope / rms_of_diff
        Measures how much the steepest falling edge stands out from
        the waveform's typical edge variation. Real PMT pulses have
        a dominant sharp edge; oscillation noise has uniform edges.

    edge_prominence = max_neg_slope / pulse_height
        Measures how steep the falling edge is relative to the full
        pulse amplitude. For oscillation noise misclassified as dark
        count (low amplitude, asym > 0.7), this ratio tends to be
        below 0.8 because the "pulse" is really a trough in an
        oscillation.
    """
    d = np.diff(wave)
    max_neg_slope = float(np.max(-d))
    rms_diff = float(np.std(d))
    edge_sharpness = max_neg_slope / max(rms_diff, 0.1)
    edge_prominence = max_neg_slope / max(abs(float(np.min(wave))), 0.1)
    return edge_sharpness, edge_prominence


def _classify_dark_count_with_noise_filter(
    asymmetry: float,
    pulse_height: float,
    edge_sharpness: float,
    edge_prominence: float,
    asymmetry_threshold: float,
    edge_sharpness_threshold: float,
    edge_prominence_low: float,
    low_height_threshold: float,
) -> bool:
    """Classify a waveform as dark count or noise using three-dimensional filter.

    Primary classification: asymmetry > threshold

    Noise filter (for low-amplitude ambiguous region, pulse_height < 80 ADC):
        Additionally requires edge_sharpness > threshold (sharp falling edge)
        AND edge_prominence > threshold (steep edge relative to pulse height).

    Rationale:
        Sin/cos oscillation noise at low amplitude may randomly exceed
        the asymmetry threshold due to phase bias, but its falling edge
        is smooth and continuous (no sharp single-sample drop).
        A real PMT dark pulse always has a sharp, fast falling edge.
    """
    if asymmetry <= asymmetry_threshold:
        return False

    if pulse_height < low_height_threshold:
        return (
            edge_sharpness > edge_sharpness_threshold
            and edge_prominence > edge_prominence_low
        )

    return True


def compute_pulse_record(
    wave: np.ndarray,
    record_id: int,
    board: int,
    channel: int,
    asymmetry_threshold: float = 0.7,
    record_baseline: Optional[float] = None,
    baseline_samples: int = DEFAULT_BASELINE_SAMPLES,
    baseline_deviation_threshold: float = DEFAULT_BASELINE_DEVIATION_THRESHOLD,
    edge_sharpness_threshold: float = DEFAULT_EDGE_SHARPNESS_THRESHOLD,
    edge_prominence_low: float = DEFAULT_EDGE_PROMINENCE_LOW,
    low_height_threshold: float = DEFAULT_LOW_HEIGHT_THRESHOLD,
) -> Optional[PulseRecord]:
    """Compute pulse record for a single waveform.

    Baseline deviation:
        If record_baseline (DAQ upstream) is provided, compute local
        baseline from the first baseline_samples points of the waveform.
        If |local_baseline - record_baseline| < baseline_deviation_threshold,
        the waveform is rejected (returns None).

    Three-dimensional noise filter:
        1. Asymmetry = pulse_height / pulse_range (fixed cut at 0.7)
           asymmetry > threshold -> candidate dark count

        2. Rising-edge sharpness (edge_sharpness):
           max_neg_slope / rms_of_diff > threshold
           Filters sin/cos oscillation noise whose falling edges are
           smooth and continuous (no sharp single-sample drop).

        3. Rising-edge prominence (edge_prominence):
           max_neg_slope / pulse_height > threshold
           Filters low-amplitude oscillation noise whose "pulse" is
           actually a trough in an oscillation.

        Steps 2+3 are applied only for pulse_height < low_height_threshold
        (default 80 ADC), the ambiguous region where oscillation noise
        can mimic dark count asymmetry.

    Asymmetry formula (from notebook):
        pulse_height = abs(min(wave))  # assuming negative pulse
        overshoot = max(wave)          # positive component
        pulse_range = pulse_height + overshoot
        asymmetry = pulse_height / pulse_range

    Classification:
        asymmetry > 0.7 AND passes noise filter -> dark count
        otherwise -> noise

    Returns:
        PulseRecord, or None if the waveform is filtered out.
    """
    deviation = 0.0
    if record_baseline is not None:
        local_baseline = float(np.mean(wave[:baseline_samples]))
        deviation = local_baseline - record_baseline
        if abs(deviation) > baseline_deviation_threshold:
            return None

    pulse_height = abs(float(np.min(wave)))
    overshoot = float(np.max(wave))
    pulse_range = pulse_height + overshoot

    if pulse_range > 0:
        asymmetry = pulse_height / pulse_range
    else:
        asymmetry = 0.0

    edge_sharpness, edge_prominence = _compute_edge_features(wave)

    is_dark_count = _classify_dark_count_with_noise_filter(
        asymmetry=asymmetry,
        pulse_height=pulse_height,
        edge_sharpness=edge_sharpness,
        edge_prominence=edge_prominence,
        asymmetry_threshold=asymmetry_threshold,
        edge_sharpness_threshold=edge_sharpness_threshold,
        edge_prominence_low=edge_prominence_low,
        low_height_threshold=low_height_threshold,
    )

    return PulseRecord(
        record_id=record_id,
        board=board,
        channel=channel,
        pulse_height=pulse_height,
        pulse_range=pulse_range,
        asymmetry=asymmetry,
        is_dark_count=is_dark_count,
        baseline_deviation=deviation,
        edge_sharpness=edge_sharpness,
        edge_prominence=edge_prominence,
    )


def extract_pulses(bundle: RawDataBundle) -> List[PulseRecord]:
    """Extract pulses from all waveforms in the bundle.

    Iterates over all records, loads waveforms, and computes pulse records.
    """
    rv = bundle.data
    records = rv.records

    pulses: List[PulseRecord] = []

    for i in range(len(records)):
        rec = records[i]
        record_id = int(rec["record_id"])
        board = int(rec["board"])
        channel = int(rec["channel"])

        wave = rv.signals(np.array([record_id]))[0]

        pulse = compute_pulse_record(
            wave=wave,
            record_id=record_id,
            board=board,
            channel=channel,
        )
        pulses.append(pulse)

    return pulses


def analyze_dark_count(
    bundle: RawDataBundle,
    asymmetry_threshold: float = 0.7,
    edge_sharpness_threshold: float = DEFAULT_EDGE_SHARPNESS_THRESHOLD,
    edge_prominence_low: float = DEFAULT_EDGE_PROMINENCE_LOW,
    low_height_threshold: float = DEFAULT_LOW_HEIGHT_THRESHOLD,
    noise_dark_ratio_threshold: float = DEFAULT_NOISE_DARK_RATIO_THRESHOLD,
) -> DarkCountResult:
    """Perform dark count analysis on a RawDataBundle.

    Noise filter (applied after asymmetry > 0.7 classification):
        For low-amplitude pulses (< 80 ADC), additionally requires:
          - edge_sharpness > threshold (rising-edge steepness metric)
          - edge_prominence > threshold (edge vs pulse height ratio)

        This rejects sin/cos oscillation noise whose smooth edges
        mimic a dark pulse shape at low amplitude.

    Asymmetry threshold (0.7) is fixed — edge features provide the
    additional noise discrimination without changing the asymmetry cut.

    This is the main entry point for dark count analysis.
    """
    rv = bundle.data
    records = rv.records

    boards = sorted(set(records["board"].tolist()))
    channels_per_board: Dict[int, List[int]] = {}
    for b in boards:
        chs = sorted(set(
            records[records["board"] == b]["channel"].tolist()
        ))
        channels_per_board[b] = chs

    daq_time_s = estimate_total_daq_run_time_length(bundle)

    channel_results: List[ChannelDarkCountResult] = []
    total_pulses = 0
    total_dark = 0
    total_noise = 0
    noisy_channels: Set[tuple] = set()

    for board in boards:
        for channel in channels_per_board[board]:
            mask = (records["board"] == board) & (records["channel"] == channel)
            rec_slice = records[mask]
            rec_ids = rec_slice["record_id"]
            rec_baselines = rec_slice["baseline"]

            if len(rec_ids) == 0:
                continue

            waves = rv.signals(rec_ids)

            dark_count = 0
            noise_count = 0
            asym_values: List[float] = []
            baseline_deviations: List[float] = []
            edge_sharpness_values: List[float] = []
            edge_prominence_values: List[float] = []
            rms_values: List[float] = []
            is_dark_list: List[bool] = []

            for i in range(len(waves)):
                wave = waves[i]
                record_id = int(rec_ids[i])
                record_baseline = float(rec_baselines[i])

                pulse = compute_pulse_record(
                    wave=wave,
                    record_id=record_id,
                    board=board,
                    channel=channel,
                    asymmetry_threshold=asymmetry_threshold,
                    record_baseline=record_baseline,
                    edge_sharpness_threshold=edge_sharpness_threshold,
                    edge_prominence_low=edge_prominence_low,
                    low_height_threshold=low_height_threshold,
                )

                if pulse is None:
                    continue

                asym_values.append(pulse.asymmetry)
                baseline_deviations.append(pulse.baseline_deviation)
                edge_sharpness_values.append(pulse.edge_sharpness)
                edge_prominence_values.append(pulse.edge_prominence)
                rms_values.append(float(np.std(wave)))
                is_dark_list.append(pulse.is_dark_count)

                if pulse.is_dark_count:
                    dark_count += 1
                else:
                    noise_count += 1

            total_ch_pulses = dark_count + noise_count
            total_pulses += total_ch_pulses
            total_dark += dark_count
            total_noise += noise_count

            # Flag noisy channels (for validation plot coloring)
            if dark_count > 0 and (noise_count / dark_count) > noise_dark_ratio_threshold:
                noisy_channels.add((board, channel))

            dcr_hz = None
            if daq_time_s is not None and daq_time_s > 0:
                dcr_hz = dark_count / daq_time_s

            channel_results.append(ChannelDarkCountResult(
                board=board,
                channel=channel,
                total_pulses=total_ch_pulses,
                dark_count=dark_count,
                noise_count=noise_count,
                dark_count_rate_hz=dcr_hz,
                asymmetry_values=asym_values,
                baseline_deviations=baseline_deviations,
                edge_sharpness_values=edge_sharpness_values,
                edge_prominence_values=edge_prominence_values,
                rms_values=rms_values,
                is_dark_count_list=is_dark_list,
            ))

    overall_dcr = None
    if daq_time_s is not None and daq_time_s > 0:
        overall_dcr = total_dark / daq_time_s

    return DarkCountResult(
        asymmetry_threshold=asymmetry_threshold,
        total_pulse_count=total_pulses,
        total_dark_count=total_dark,
        total_noise_count=total_noise,
        total_daq_run_time_length_s=daq_time_s,
        dark_count_rate_hz=overall_dcr,
        channels=channel_results,
        metadata={
            "run_id": bundle.runinfo.run_id,
            "runtype": bundle.runinfo.runtype,
            "edge_sharpness_threshold": edge_sharpness_threshold,
            "edge_prominence_low": edge_prominence_low,
            "low_height_threshold": low_height_threshold,
        },
        noisy_channels=noisy_channels,
    )
