from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from pmt_analysis.io.raw_reader import RawDataBundle


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


@dataclass
class ChannelDarkCountResult:
    """Dark count analysis result for a single channel."""

    board: int
    channel: int
    total_pulses: int
    dark_count: int
    noise_count: int
    dark_count_rate_hz: Optional[float]
    asymmetry_values: List[float] = field(default_factory=list)


@dataclass
class DarkCountResult:
    """Complete dark count analysis result."""

    asymmetry_threshold: float
    total_pulse_count: int
    total_dark_count: int
    total_noise_count: int
    total_daq_run_time_length_s: Optional[float]
    dark_count_rate_hz: Optional[float]
    channels: List[ChannelDarkCountResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


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


def compute_pulse_record(
    wave: np.ndarray,
    record_id: int,
    board: int,
    channel: int,
    asymmetry_threshold: float = 0.7,
) -> PulseRecord:
    """Compute pulse record for a single waveform.

    Asymmetry formula (from notebook):
        pulse_height = abs(min(wave))  # assuming negative pulse
        overshoot = max(wave)          # positive component
        pulse_range = pulse_height + overshoot
        asymmetry = pulse_height / pulse_range

    Classification:
        asymmetry > threshold -> dark count
        asymmetry <= threshold -> noise
    """
    pulse_height = abs(float(np.min(wave)))
    overshoot = float(np.max(wave))
    pulse_range = pulse_height + overshoot

    if pulse_range > 0:
        asymmetry = pulse_height / pulse_range
    else:
        asymmetry = 0.0

    is_dark_count = asymmetry > asymmetry_threshold

    return PulseRecord(
        record_id=record_id,
        board=board,
        channel=channel,
        pulse_height=pulse_height,
        pulse_range=pulse_range,
        asymmetry=asymmetry,
        is_dark_count=is_dark_count,
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

        # Load waveform using signals method
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
) -> DarkCountResult:
    """Perform dark count analysis on a RawDataBundle.

    This is the main entry point for dark count analysis.
    """
    rv = bundle.data
    records = rv.records

    # Get unique boards and channels
    boards = sorted(set(records["board"].tolist()))
    channels_per_board: Dict[int, List[int]] = {}
    for b in boards:
        chs = sorted(set(
            records[records["board"] == b]["channel"].tolist()
        ))
        channels_per_board[b] = chs

    # Estimate DAQ time
    daq_time_s = estimate_total_daq_run_time_length(bundle)

    # Analyze each channel
    channel_results: List[ChannelDarkCountResult] = []
    total_pulses = 0
    total_dark = 0
    total_noise = 0

    for board in boards:
        for channel in channels_per_board[board]:
            # Get record IDs for this channel
            mask = (records["board"] == board) & (records["channel"] == channel)
            rec_ids = records[mask]["record_id"]

            if len(rec_ids) == 0:
                continue

            # Load waveforms for this channel
            waves = rv.signals(rec_ids)

            dark_count = 0
            noise_count = 0
            asym_values: List[float] = []

            for i in range(len(waves)):
                wave = waves[i]
                record_id = int(rec_ids[i])

                pulse = compute_pulse_record(
                    wave=wave,
                    record_id=record_id,
                    board=board,
                    channel=channel,
                    asymmetry_threshold=asymmetry_threshold,
                )

                asym_values.append(pulse.asymmetry)

                if pulse.is_dark_count:
                    dark_count += 1
                else:
                    noise_count += 1

            total_ch_pulses = dark_count + noise_count
            total_pulses += total_ch_pulses
            total_dark += dark_count
            total_noise += noise_count

            # Calculate dark count rate
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
            ))

    # Overall dark count rate
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
        },
    )
