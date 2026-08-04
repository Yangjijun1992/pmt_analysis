"""Shared test fixtures for pmt_analysis tests."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import numpy as np
import pytest

from pmt_analysis.models import RunInfo
from pmt_analysis.runinfo import R8520_RUNTYPE


def make_runinfo(
    run_id: str = "00001",
    runtype: str = R8520_RUNTYPE,
    run_dir: Optional[Path] = None,
    data_root: Optional[Path] = None,
    metadata: Optional[Dict[str, Any]] = None,
    datatype: Optional[list] = None,
) -> RunInfo:
    """Create a RunInfo instance for testing."""
    if data_root is None:
        data_root = Path(tempfile.mkdtemp())
    if run_dir is None:
        run_dir = data_root / runtype / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = run_dir / "RAW"
    raw_dir.mkdir(exist_ok=True)

    return RunInfo(
        run_id=run_id,
        runtype=runtype,
        run_dir=run_dir,
        runinfo_path=run_dir / "runinfo.json",
        raw_dir=raw_dir,
        outfile_name=f"{run_id}.bin",
        source="test",
        datatype=datatype or [],
        metadata=metadata or {},
    )


def make_records(
    n_records: int = 100,
    board: int = 0,
    channels: Optional[list] = None,
    time_start: int = 1000000000,
    time_step: int = 1000,
) -> np.ndarray:
    """Create a structured numpy array mimicking records_view.records."""
    if channels is None:
        channels = [0]

    dtype = np.dtype([
        ("record_id", "i4"),
        ("board", "i4"),
        ("channel", "i4"),
        ("time", "i8"),
        ("event_length", "i4"),
        ("baseline", "f8"),
        ("dt", "f8"),
    ])

    records = np.zeros(n_records, dtype=dtype)
    for i in range(n_records):
        records[i]["record_id"] = i
        records[i]["board"] = board
        records[i]["channel"] = channels[i % len(channels)]
        records[i]["time"] = time_start + i * time_step
        records[i]["event_length"] = 200
        records[i]["baseline"] = 0.0
        records[i]["dt"] = 4.0

    return records


def make_waveform(
    length: int = 200,
    baseline: float = 0.0,
    pulse_position: int = 97,
    pulse_height: float = -500.0,
    noise_rms: float = 2.0,
    overshoot_fraction: float = 0.3,
) -> np.ndarray:
    """Create a synthetic PMT waveform with optional dark pulse.

    The waveform is negative-going (pulse_height < 0).
    compute_pulse_record uses abs(min(wave)) as pulse_height, so baseline
    should be 0 for correct asymmetry calculation.
    """
    wave = np.random.normal(baseline, noise_rms, size=length).astype(np.float64)
    if pulse_height is not None and pulse_height != 0:
        width = 5
        start = max(0, pulse_position - width)
        end = min(length, pulse_position + width)
        for i in range(start, end):
            dist = abs(i - pulse_position)
            wave[i] += pulse_height * np.exp(-0.5 * (dist / 2.0) ** 2)
        overshoot_end = min(length, end + 10)
        for i in range(end, overshoot_end):
            dist = i - end
            wave[i] += abs(pulse_height) * overshoot_fraction * np.exp(-0.5 * (dist / 3.0) ** 2)
    return wave


class FakeRecordsView:
    """Minimal mock of waveform_analysis records_view for testing."""

    def __init__(self, records: np.ndarray, waveforms: Dict[int, np.ndarray]) -> None:
        self.records = records
        self._waveforms = waveforms

    def signals(self, record_ids: np.ndarray) -> np.ndarray:
        waves = []
        for rid in record_ids:
            rid_int = int(rid)
            if rid_int in self._waveforms:
                waves.append(self._waveforms[rid_int])
            else:
                raise KeyError(f"record_id {rid_int} not found in mock data")
        return np.array(waves)


def make_raw_data_bundle(
    runinfo: Optional[RunInfo] = None,
    n_records: int = 100,
    channels: Optional[list] = None,
    pulse_height: float = -500.0,
    noise_rms: float = 2.0,
) -> MagicMock:
    """Create a mock RawDataBundle with synthetic waveforms."""
    if runinfo is None:
        runinfo = make_runinfo()
    if channels is None:
        channels = [0]

    records = make_records(n_records=n_records, channels=channels)
    waveforms = {}
    for i in range(n_records):
        waveforms[i] = make_waveform(pulse_height=pulse_height, noise_rms=noise_rms)

    fake_rv = FakeRecordsView(records, waveforms)

    bundle = MagicMock()
    bundle.runinfo = runinfo
    bundle.data = fake_rv
    bundle.source_path = [Path("/fake/path.bin")]
    bundle.data_format = "test"
    bundle.event_count = n_records
    bundle.channel_count = len(channels)
    bundle.waveform_count = n_records
    bundle.metadata = {
        "board_count": 1,
        "boards": [0],
        "daq_time_s": 0.1,
    }
    return bundle
