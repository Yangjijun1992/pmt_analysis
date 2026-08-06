"""Tests for the parallel (multi-process) APP analysis framework."""
from __future__ import annotations

import numpy as np
import pytest

from pmt_analysis.analysis.app import analyze_app
from pmt_analysis.analysis.app_parallel import (
    analyze_app_parallel,
    bulk_load_waveforms,
)
from tests.conftest import make_raw_data_bundle


def _make_pmt_map() -> dict:
    # Fake mapping: board 0, channels 0..6
    return {(0, ch): f"LV{100+ch}" for ch in range(7)}


class TestBulkLoadWaveforms:
    def test_shape(self):
        bundle = make_raw_data_bundle(n_records=50, channels=[0], pulse_height=-500.0)
        waveforms, records = bulk_load_waveforms(bundle)
        assert waveforms.ndim == 2
        assert waveforms.shape[0] == 50
        assert records.shape[0] == 50
        # Floating values present (not all padding)
        assert np.isfinite(waveforms).any()


class TestAnalyzeAppParallel:
    def test_matches_serial_counts(self):
        bundle = make_raw_data_bundle(
            n_records=60,
            channels=[0, 1, 2],
            pulse_height=-500.0,
        )
        pmt_map = _make_pmt_map()

        serial = analyze_app(
            bundle,
            pmt_id_map=pmt_map,
            noise_suppression_enabled=False,
        )

        parallel = analyze_app_parallel(
            bundle,
            n_workers=2,
            pmt_id_map=pmt_map,
        )

        assert parallel.main_pulse_count == serial.main_pulse_count
        assert parallel.afterpulse_count == serial.afterpulse_count

        s_by_ch = {ch.channel: ch for ch in serial.channels}
        p_by_ch = {ch.channel: ch for ch in parallel.channels}
        assert set(p_by_ch) == set(s_by_ch)
        for ch in s_by_ch:
            assert p_by_ch[ch].main_pulse_count == s_by_ch[ch].main_pulse_count
            assert p_by_ch[ch].afterpulse_count == s_by_ch[ch].afterpulse_count

    def test_app_values_close(self):
        bundle = make_raw_data_bundle(
            n_records=60,
            channels=[0, 1, 2],
            pulse_height=-500.0,
        )
        pmt_map = _make_pmt_map()

        serial = analyze_app(
            bundle, pmt_id_map=pmt_map, noise_suppression_enabled=False,
        )
        parallel = analyze_app_parallel(
            bundle, n_workers=2, pmt_id_map=pmt_map,
        )

        s_by_ch = {ch.channel: ch for ch in serial.channels}
        p_by_ch = {ch.channel: ch for ch in parallel.channels}
        for ch in s_by_ch:
            s_app = s_by_ch[ch].app_value
            p_app = p_by_ch[ch].app_value
            if s_app is None and p_app is None:
                continue
            assert p_app is not None and s_app is not None
            assert abs(p_app - s_app) < 1e-9

    def test_single_worker_matches_multi_worker(self):
        bundle = make_raw_data_bundle(
            n_records=90,
            channels=[0, 1, 2, 3, 4],
            pulse_height=-500.0,
        )
        pmt_map = _make_pmt_map()

        p1 = analyze_app_parallel(bundle, n_workers=1, pmt_id_map=pmt_map)
        p4 = analyze_app_parallel(bundle, n_workers=4, pmt_id_map=pmt_map)

        assert p1.main_pulse_count == p4.main_pulse_count
        assert p1.afterpulse_count == p4.afterpulse_count
        assert abs((p1.afterpulse_count or 0) - (p4.afterpulse_count or 0)) == 0

    def test_empty_run(self):
        bundle = make_raw_data_bundle(n_records=0, channels=[0])
        result = analyze_app_parallel(bundle, n_workers=2)
        assert result.main_pulse_count == 0
        assert result.afterpulse_count == 0
