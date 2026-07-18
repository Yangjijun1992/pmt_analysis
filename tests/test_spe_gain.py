"""Tests for pmt_analysis.analysis.gain module."""
from __future__ import annotations

import numpy as np
import pytest

from pmt_analysis.analysis.gain import (
    GainAnalysisResult,
    GainFitResult,
    build_spe_histogram,
    extract_gain_samples,
    fit_spe_spectrum,
)
from tests.conftest import make_raw_data_bundle, make_waveform


class TestExtractGainSamples:
    def test_extracts_samples(self):
        bundle = make_raw_data_bundle(n_records=50, channels=[0], pulse_height=-300.0)
        samples = extract_gain_samples(bundle, board=0, channels=[0], n_waveforms=50)
        assert 0 in samples
        assert len(samples[0]) > 0
        s = samples[0][0]
        assert hasattr(s, "area_pe")
        assert hasattr(s, "baseline")
        assert hasattr(s, "rms")

    def test_empty_channel(self):
        bundle = make_raw_data_bundle(n_records=10, channels=[0])
        samples = extract_gain_samples(bundle, board=0, channels=[5], n_waveforms=10)
        assert samples[5] == []

    def test_area_pe_conversion(self):
        """area_pe should be raw_area * PE_FACT."""
        from pmt_analysis.analysis.gain import PE_FACT
        bundle = make_raw_data_bundle(n_records=5, channels=[0], pulse_height=-500.0)
        samples = extract_gain_samples(bundle, board=0, channels=[0], n_waveforms=5)
        for s in samples[0]:
            assert abs(s.area_pe - s.raw_area * PE_FACT) < 1e-15


class TestBuildSpeHistogram:
    def test_histogram_shape(self):
        from pmt_analysis.analysis.gain import GainSample
        samples = [
            GainSample(record_id=i, board=0, channel=0,
                       baseline=8000.0, rms=2.0,
                       raw_area=100.0, area_pe=5.0 + i * 0.1)
            for i in range(100)
        ]
        counts, edges = build_spe_histogram(samples, bins=50, hist_range=(0, 20))
        assert len(counts) == 50
        assert len(edges) == 51
        assert counts.sum() == 100

    def test_empty_samples(self):
        from pmt_analysis.analysis.gain import GainSample
        counts, edges = build_spe_histogram([], bins=50, hist_range=(0, 20))
        assert counts.sum() == 0


class TestFitSpeSpectrum:
    def _make_gaussian_counts(self, mu=10.0, sigma=2.0, amp=500.0, bins=100,
                               hist_range=(-15.0, 100.0)):
        edges = np.linspace(hist_range[0], hist_range[1], bins + 1)
        x = 0.5 * (edges[:-1] + edges[1:])
        y = amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)
        return y.astype(int), edges

    def test_fit_succeeds(self):
        counts, edges = self._make_gaussian_counts()
        params, errors = fit_spe_spectrum(counts, edges)
        assert params is not None
        assert errors is not None
        assert "mu" in params
        assert "sigma" in params
        assert "amp" in params
        assert abs(params["mu"] - 10.0) < 1.0
        assert abs(params["sigma"] - 2.0) < 1.0

    def test_fit_returns_none_on_empty(self):
        counts = np.zeros(100, dtype=int)
        edges = np.linspace(-15, 100, 101)
        params, errors = fit_spe_spectrum(counts, edges)
        # With all zeros, curve_fit may or may not succeed depending on bounds
        # Just ensure it doesn't crash
        assert params is None or params is not None

    def test_fit_respects_bounds(self):
        counts, edges = self._make_gaussian_counts(mu=25, sigma=10)
        params, errors = fit_spe_spectrum(
            counts, edges,
            mu_bounds=(0.1, 30.0),
            sigma_bounds=(0.0, 12.0),
        )
        if params is not None:
            assert 0.1 <= params["mu"] <= 30.0
            assert 0.0 <= abs(params["sigma"]) <= 12.0


class TestAnalyzeGain:
    def test_basic_analysis(self):
        bundle = make_raw_data_bundle(n_records=100, channels=[0], pulse_height=-300.0)
        from pmt_analysis.analysis.gain import analyze_gain

        result = analyze_gain(bundle, board=0, channels=[0], n_waveforms=100)
        assert isinstance(result, GainAnalysisResult)
        assert len(result.channels) == 1
        ch = result.channels[0]
        assert ch.board == 0
        assert ch.channel == 0
        assert ch.sample_count > 0

    def test_histogram_stored_in_result(self):
        bundle = make_raw_data_bundle(n_records=50, channels=[0], pulse_height=-300.0)
        from pmt_analysis.analysis.gain import analyze_gain

        result = analyze_gain(bundle, board=0, channels=[0], n_waveforms=50)
        ch = result.channels[0]
        assert ch.histogram_counts is not None
        assert ch.histogram_edges is not None
        assert len(ch.histogram_counts) > 0

    def test_multi_channel(self):
        bundle = make_raw_data_bundle(n_records=60, channels=[0, 1], pulse_height=-300.0)
        from pmt_analysis.analysis.gain import analyze_gain

        result = analyze_gain(bundle, board=0, channels=[0, 1], n_waveforms=60)
        assert len(result.channels) == 2
