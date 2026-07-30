"""Tests for pmt_analysis.analysis.dark_count module."""
from __future__ import annotations

import numpy as np
import pytest

from pmt_analysis.analysis.dark_count import (
    ChannelDarkCountResult,
    DarkCountResult,
    PulseRecord,
    compute_pulse_record,
    estimate_total_daq_run_time_length,
)
from tests.conftest import FakeRecordsView, make_raw_data_bundle, make_waveform


class TestComputePulseRecord:
    def test_dark_count_pulse(self):
        """Pulse with high asymmetry should be classified as dark count."""
        wave = make_waveform(pulse_height=-500.0, overshoot_fraction=0.1)
        pr = compute_pulse_record(wave, record_id=0, board=0, channel=0)
        assert pr.is_dark_count is True
        assert pr.asymmetry > 0.7
        assert pr.pulse_height > 0

    def test_noise_pulse(self):
        """Pulse with low asymmetry should be classified as noise."""
        wave = make_waveform(pulse_height=-200.0, overshoot_fraction=0.8)
        pr = compute_pulse_record(wave, record_id=0, board=0, channel=0)
        assert pr.is_dark_count is False
        assert pr.asymmetry <= 0.7

    def test_empty_waveform(self):
        """Waveform with zero amplitude gives asymmetry 0."""
        wave = np.zeros(200)
        pr = compute_pulse_record(wave, record_id=0, board=0, channel=0)
        assert pr.asymmetry == 0.0
        assert pr.is_dark_count is False

    def test_symmetric_pulse(self):
        """Pulse where height equals overshoot gives asymmetry ~0.5."""
        wave = np.zeros(200)
        wave[97] = -100
        wave[107] = 100
        pr = compute_pulse_record(wave, record_id=0, board=0, channel=0)
        assert 0.4 < pr.asymmetry < 0.6

    def test_pure_negative_pulse(self):
        """Pulse with no overshoot gives asymmetry 1.0."""
        wave = np.zeros(200)
        wave[97] = -500
        pr = compute_pulse_record(wave, record_id=0, board=0, channel=0)
        assert pr.asymmetry == 1.0
        assert pr.is_dark_count is True

    def test_baseline_deviation_filtered(self):
        """Waveform with |deviation| < 15200 is filtered out (returns None)."""
        wave = make_waveform(pulse_height=-500.0, baseline=2.0)
        pr = compute_pulse_record(
            wave, record_id=0, board=0, channel=0,
            record_baseline=0.0,
        )
        assert pr is None

    def test_baseline_deviation_passed(self):
        """Waveform with |deviation| >= 15200 passes the filter."""
        wave = make_waveform(pulse_height=-500.0, baseline=16000.0)
        pr = compute_pulse_record(
            wave, record_id=0, board=0, channel=0,
            record_baseline=0.0,
        )
        assert pr is not None
        assert pr.baseline_deviation > 15000.0

    def test_baseline_check_disabled(self):
        """When record_baseline is None, no filter is applied."""
        wave = make_waveform(pulse_height=-500.0, baseline=2.0)
        pr = compute_pulse_record(
            wave, record_id=0, board=0, channel=0,
            record_baseline=None,
        )
        assert pr is not None
        assert pr.baseline_deviation == 0.0


class TestEstimateTotalDaqRunTimeLength:
    def test_normal_case(self):
        records = np.zeros(10, dtype=[("time", "i8")])
        records["time"] = np.arange(10) * 1000 + 1000000000

        class FakeBundle:
            data = type("D", (), {"records": records})()

        result = estimate_total_daq_run_time_length(FakeBundle())
        expected_s = (records["time"].max() - records["time"].min()) * 1e-9
        assert result is not None
        assert abs(result - expected_s) < 1e-12

    def test_single_record(self):
        records = np.zeros(1, dtype=[("time", "i8")])
        records["time"][0] = 1000000000

        class FakeBundle:
            data = type("D", (), {"records": records})()

        result = estimate_total_daq_run_time_length(FakeBundle())
        assert result is None

    def test_empty_records(self):
        records = np.zeros(0, dtype=[("time", "i8")])

        class FakeBundle:
            data = type("D", (), {"records": records})()

        result = estimate_total_daq_run_time_length(FakeBundle())
        assert result is None


class TestAnalyzeDarkCount:
    def test_single_channel(self):
        """Run analysis on a bundle with one channel of dark-count-like pulses."""
        bundle = make_raw_data_bundle(
            n_records=50,
            channels=[0],
            pulse_height=-500.0,
        )
        from pmt_analysis.analysis.dark_count import analyze_dark_count

        result = analyze_dark_count(bundle)

        assert isinstance(result, DarkCountResult)
        assert result.total_pulse_count == 50
        assert result.total_dark_count + result.total_noise_count == 50
        assert result.asymmetry_threshold == 0.7
        assert len(result.channels) == 1
        assert result.channels[0].channel == 0

    def test_dark_count_rate_computed(self):
        """DAQ time should be estimated and rate computed when possible."""
        bundle = make_raw_data_bundle(
            n_records=20,
            channels=[0],
            pulse_height=-500.0,
        )
        from pmt_analysis.analysis.dark_count import analyze_dark_count

        result = analyze_dark_count(bundle)
        assert result.total_daq_run_time_length_s is not None
        assert result.dark_count_rate_hz is not None
        assert result.dark_count_rate_hz >= 0

    def test_multi_channel(self):
        bundle = make_raw_data_bundle(
            n_records=60,
            channels=[0, 1, 2],
            pulse_height=-500.0,
        )
        from pmt_analysis.analysis.dark_count import analyze_dark_count

        result = analyze_dark_count(bundle)
        assert len(result.channels) == 3
        ch_channels = {ch.channel for ch in result.channels}
        assert ch_channels == {0, 1, 2}

    def test_noise_dominated(self):
        """Pulses with high overshoot should be mostly noise."""
        bundle = make_raw_data_bundle(
            n_records=30,
            channels=[0],
            pulse_height=-10.0,  # Very small pulse, comparable to noise
            noise_rms=8.0,  # High noise to create symmetric fluctuations
        )
        from pmt_analysis.analysis.dark_count import analyze_dark_count

        result = analyze_dark_count(bundle)
        # With small pulses and high noise, many pulses should be noise
        assert result.total_noise_count > 0

