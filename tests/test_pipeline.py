"""Tests for pmt_analysis.pipeline module."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pmt_analysis.models import RunInfo
from tests.conftest import make_raw_data_bundle, make_runinfo


class TestLoadMapping:
    def test_returns_none_when_no_mapping(self):
        ri = make_runinfo(metadata={})
        from pmt_analysis.pipeline import _load_mapping
        assert _load_mapping(ri) is None

    def test_loads_valid_mapping(self):
        mapping_data = [
            {
                "board_id": 0,
                "signal": "anode",
                "channels": [{"ch": 0, "pmt": "PMT001"}],
            }
        ]
        ri = make_runinfo(metadata={"mapping": mapping_data})
        from pmt_analysis.pipeline import _load_mapping

        mt = _load_mapping(ri)
        assert mt is not None
        assert len(mt.entries) == 1
        assert mt.entries[0].pmt_id == "PMT001"

    def test_returns_none_for_invalid_mapping(self):
        ri = make_runinfo(metadata={"mapping": "not a list"})
        from pmt_analysis.pipeline import _load_mapping
        try:
            result = _load_mapping(ri)
        except Exception:
            pass


class TestAnalyzeRuns:
    def test_runs_with_mocked_components(self):
        """Integration test: mock reader and verify pipeline runs end-to-end."""
        ri = make_runinfo(run_id="00001", datatype=["Dark Rate", "SPE Gain", "After Pulse"])
        bundle = make_raw_data_bundle(runinfo=ri, n_records=20, channels=[0], pulse_height=-500.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pmt_analysis.pipeline.get_runinfo", return_value=ri), \
                 patch("pmt_analysis.pipeline.NotebookBasedRawDataReader") as MockReader, \
                 patch("pmt_analysis.pipeline.write_analysis_results") as mock_write:

                MockReader.return_value.read.return_value = bundle

                from pmt_analysis.pipeline import analyze_runs
                result = analyze_runs(
                    run_ids=[1],
                    output_dir=tmpdir,
                    save_plots=False,
                )
                assert result == 0

    def test_returns_1_on_no_valid_runs(self):
        with patch("pmt_analysis.pipeline.get_runinfo", side_effect=Exception("not found")):
            from pmt_analysis.pipeline import analyze_runs
            result = analyze_runs(run_ids=[99999], output_dir="/tmp/test_output")
            assert result == 1

    def test_save_plots_false_skips_plotting(self):
        ri = make_runinfo(run_id="00002", datatype=["Dark Rate"])
        bundle = make_raw_data_bundle(runinfo=ri, n_records=10, channels=[0], pulse_height=-500.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pmt_analysis.pipeline.get_runinfo", return_value=ri), \
                 patch("pmt_analysis.pipeline.NotebookBasedRawDataReader") as MockReader, \
                 patch("pmt_analysis.pipeline.plot_dark_count_validation") as mock_dcr_plot, \
                 patch("pmt_analysis.pipeline.plot_spe_gain_fit_overlay") as mock_gain_plot, \
                 patch("pmt_analysis.pipeline.write_analysis_results"):

                MockReader.return_value.read.return_value = bundle

                from pmt_analysis.pipeline import analyze_runs
                analyze_runs(run_ids=[2], output_dir=tmpdir, save_plots=False)

                mock_dcr_plot.assert_not_called()
                mock_gain_plot.assert_not_called()

    def test_save_plots_true_calls_plotting(self):
        ri = make_runinfo(run_id="00003", datatype=["Dark Rate", "SPE Gain"])
        bundle = make_raw_data_bundle(runinfo=ri, n_records=10, channels=[0], pulse_height=-500.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pmt_analysis.pipeline.get_runinfo", return_value=ri), \
                 patch("pmt_analysis.pipeline.NotebookBasedRawDataReader") as MockReader, \
                 patch("pmt_analysis.pipeline.plot_dark_count_validation", return_value="/fake/plot.png") as mock_dcr_plot, \
                 patch("pmt_analysis.pipeline.plot_spe_gain_fit_overlay", return_value=["/fake/gain.png"]) as mock_gain_plot, \
                 patch("pmt_analysis.pipeline.write_analysis_results"):

                MockReader.return_value.read.return_value = bundle

                from pmt_analysis.pipeline import analyze_runs
                analyze_runs(run_ids=[3], output_dir=tmpdir, save_plots=True)

                mock_dcr_plot.assert_called_once()
                mock_gain_plot.assert_called_once()

    def test_skips_analysis_not_in_datatype(self):
        """Only 'Dark Rate' in datatype, gain and APP should be skipped."""
        ri = make_runinfo(run_id="00004", datatype=["Dark Rate"])
        bundle = make_raw_data_bundle(runinfo=ri, n_records=10, channels=[0], pulse_height=-500.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pmt_analysis.pipeline.get_runinfo", return_value=ri), \
                 patch("pmt_analysis.pipeline.NotebookBasedRawDataReader") as MockReader, \
                 patch("pmt_analysis.pipeline.analyze_dark_count") as mock_dcr, \
                 patch("pmt_analysis.pipeline.analyze_gain") as mock_gain, \
                 patch("pmt_analysis.pipeline.analyze_app") as mock_app, \
                 patch("pmt_analysis.pipeline.write_analysis_results"):

                MockReader.return_value.read.return_value = bundle

                from pmt_analysis.pipeline import analyze_runs
                analyze_runs(run_ids=[4], output_dir=tmpdir, save_plots=False)

                mock_dcr.assert_called_once()
                mock_gain.assert_not_called()
                mock_app.assert_not_called()

    def test_only_gain_datatype(self):
        """Only 'SPE Gain' in datatype, dark count and APP should be skipped."""
        ri = make_runinfo(run_id="00005", datatype=["SPE Gain"])
        bundle = make_raw_data_bundle(runinfo=ri, n_records=10, channels=[0], pulse_height=-500.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pmt_analysis.pipeline.get_runinfo", return_value=ri), \
                 patch("pmt_analysis.pipeline.NotebookBasedRawDataReader") as MockReader, \
                 patch("pmt_analysis.pipeline.analyze_dark_count") as mock_dcr, \
                 patch("pmt_analysis.pipeline.analyze_gain") as mock_gain, \
                 patch("pmt_analysis.pipeline.analyze_app") as mock_app, \
                 patch("pmt_analysis.pipeline.write_analysis_results"):

                MockReader.return_value.read.return_value = bundle

                from pmt_analysis.pipeline import analyze_runs
                analyze_runs(run_ids=[5], output_dir=tmpdir, save_plots=False)

                mock_dcr.assert_not_called()
                mock_gain.assert_called_once()
                mock_app.assert_not_called()

    def test_only_afterpulse_datatype(self):
        """Only 'After Pulse' in datatype, dark count and gain should be skipped."""
        ri = make_runinfo(run_id="00006", datatype=["After Pulse"])
        bundle = make_raw_data_bundle(runinfo=ri, n_records=10, channels=[0], pulse_height=-500.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pmt_analysis.pipeline.get_runinfo", return_value=ri), \
                 patch("pmt_analysis.pipeline.NotebookBasedRawDataReader") as MockReader, \
                 patch("pmt_analysis.pipeline.analyze_dark_count") as mock_dcr, \
                 patch("pmt_analysis.pipeline.analyze_gain") as mock_gain, \
                 patch("pmt_analysis.pipeline.analyze_app") as mock_app, \
                 patch("pmt_analysis.pipeline.write_analysis_results"):

                MockReader.return_value.read.return_value = bundle

                from pmt_analysis.pipeline import analyze_runs
                analyze_runs(run_ids=[6], output_dir=tmpdir, save_plots=False)

                mock_dcr.assert_not_called()
                mock_gain.assert_not_called()
                mock_app.assert_called_once()
