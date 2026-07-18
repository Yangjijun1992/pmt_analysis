"""Tests for pmt_analysis.runinfo module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from pmt_analysis.models import RunInfo
from pmt_analysis.runinfo import (
    R8520_RUNTYPE,
    RunInfoNotFoundError,
    RunInfoNotUniqueError,
    RunInfoParseError,
    RunInfoValidationError,
    build_runinfo,
    discover_runinfo_path,
    load_runinfo_json,
    normalize_run_id,
    parse_datatypes,
    validate_run_tag,
)


def _make_valid_payload(runtype="dark_count", run_comment=None, run_tag="PMT TEST"):
    if run_comment is None:
        run_comment = ["Dark Rate"]
    return {
        "run_info": {
            "runtype": runtype,
            "outfile_name": "data.bin",
            "outfile_path": None,
        },
        "run_option": {
            "run_tag": run_tag,
            "run_comment": run_comment,
        },
    }


class TestNormalizeRunId:
    def test_pads_integer(self):
        assert normalize_run_id(1) == "00001"

    def test_pads_string_number(self):
        assert normalize_run_id("42") == "00042"

    def test_already_padded(self):
        assert normalize_run_id("00123") == "00123"

    def test_large_number(self):
        assert normalize_run_id(12345) == "12345"


class TestLoadRuninfoJson:
    def test_valid_json(self, tmp_path):
        data = {"run_info": {"runtype": "dark_count"}}
        path = tmp_path / "runinfo.json"
        path.write_text(json.dumps(data))

        result = load_runinfo_json(str(path))
        assert result["run_info"]["runtype"] == "dark_count"

    def test_valid_json_path_object(self, tmp_path):
        data = {"run_info": {"runtype": "gain"}}
        path = tmp_path / "runinfo.json"
        path.write_text(json.dumps(data))

        result = load_runinfo_json(path)
        assert result["run_info"]["runtype"] == "gain"

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json {{{")

        with pytest.raises(RunInfoParseError, match="Failed to parse JSON"):
            load_runinfo_json(str(path))

    def test_file_not_found(self):
        with pytest.raises(RunInfoParseError, match="Failed to read file"):
            load_runinfo_json("/nonexistent/runinfo.json")


class TestDiscoverRuninfoPath:
    def test_finds_runinfo_under_run_R8520(self, tmp_path):
        run_dir = tmp_path / R8520_RUNTYPE / "00001"
        run_dir.mkdir(parents=True)
        ri_path = run_dir / "runinfo.json"
        ri_path.write_text("{}")

        found = discover_runinfo_path(1, str(tmp_path))
        assert found == ri_path

    def test_raises_when_not_under_run_R8520(self, tmp_path):
        for sub in ["dark_count", "other_type"]:
            d = tmp_path / sub / "00001"
            d.mkdir(parents=True)
            (d / "runinfo.json").write_text("{}")

        with pytest.raises(RunInfoNotFoundError):
            discover_runinfo_path(1, str(tmp_path))

    def test_raises_on_missing(self, tmp_path):
        with pytest.raises(RunInfoNotFoundError):
            discover_runinfo_path(99999, str(tmp_path))


class TestValidateRunTag:
    def test_valid_tag(self):
        validate_run_tag({"run_option": {"run_tag": "PMT TEST"}})

    def test_valid_tag_case_insensitive(self):
        validate_run_tag({"run_option": {"run_tag": "pmt test"}})
        validate_run_tag({"run_option": {"run_tag": "Pmt Test"}})

    def test_invalid_tag_raises(self):
        with pytest.raises(RunInfoValidationError, match="Invalid run_tag"):
            validate_run_tag({"run_option": {"run_tag": "LED Calibration"}})

    def test_missing_run_option_raises(self):
        with pytest.raises(RunInfoValidationError, match="Invalid run_tag"):
            validate_run_tag({})

    def test_empty_run_tag_raises(self):
        with pytest.raises(RunInfoValidationError, match="Invalid run_tag"):
            validate_run_tag({"run_option": {"run_tag": ""}})


class TestParseDatatypes:
    def test_single_valid_comment(self):
        result = parse_datatypes({"run_option": {"run_comment": ["Dark Rate"]}})
        assert result == ["Dark Rate"]

    def test_multiple_valid_comments(self):
        comments = ["Dark Rate", "SPE Gain", "After Pulse"]
        result = parse_datatypes({"run_option": {"run_comment": comments}})
        assert result == ["Dark Rate", "SPE Gain", "After Pulse"]

    def test_mixed_valid_and_invalid(self):
        comments = ["Dark Rate", "some random note", "After Pulse"]
        result = parse_datatypes({"run_option": {"run_comment": comments}})
        assert result == ["Dark Rate", "After Pulse"]

    def test_case_insensitive_match(self):
        comments = ["dark rate", "SPE gain", "AFTER PULSE"]
        result = parse_datatypes({"run_option": {"run_comment": comments}})
        assert result == ["dark rate", "SPE gain", "AFTER PULSE"]

    def test_no_valid_comment_raises(self):
        with pytest.raises(RunInfoValidationError, match="No valid datatype"):
            parse_datatypes({"run_option": {"run_comment": ["random note"]}})

    def test_empty_comment_list_raises(self):
        with pytest.raises(RunInfoValidationError, match="No valid datatype"):
            parse_datatypes({"run_option": {"run_comment": []}})

    def test_missing_run_option_raises(self):
        with pytest.raises(RunInfoValidationError, match="No valid datatype"):
            parse_datatypes({})


class TestBuildRuninfo:
    def test_basic_fields(self, tmp_path):
        run_dir = tmp_path / R8520_RUNTYPE / "00001"
        run_dir.mkdir(parents=True)
        ri_path = run_dir / "runinfo.json"

        payload = _make_valid_payload(runtype="dark_count", run_comment=["Dark Rate"])

        ri = build_runinfo("1", ri_path, payload)
        assert ri.run_id == "00001"
        assert ri.runtype == R8520_RUNTYPE
        assert ri.outfile_name == "data.bin"
        assert ri.datatype == ["Dark Rate"]

    def test_metadata_preserves_extra_fields(self, tmp_path):
        run_dir = tmp_path / R8520_RUNTYPE / "00001"
        run_dir.mkdir(parents=True)
        ri_path = run_dir / "runinfo.json"

        payload = _make_valid_payload()
        payload["run_info"]["extra_key"] = "extra_val"
        payload["mapping"] = [{"board_id": 0}]

        ri = build_runinfo("1", ri_path, payload)
        assert ri.metadata["extra_key"] == "extra_val"
        assert ri.metadata["mapping"] == [{"board_id": 0}]

    def test_raw_dir_fallback(self, tmp_path):
        run_dir = tmp_path / R8520_RUNTYPE / "00001"
        run_dir.mkdir(parents=True)
        ri_path = run_dir / "runinfo.json"

        payload = _make_valid_payload()
        ri = build_runinfo("1", ri_path, payload)
        assert ri.raw_dir == run_dir / "RAW"

    def test_raw_dir_from_outfile_path(self, tmp_path):
        run_dir = tmp_path / R8520_RUNTYPE / "00001"
        run_dir.mkdir(parents=True)
        ri_path = run_dir / "runinfo.json"
        custom_dir = tmp_path / "custom_raw"
        custom_dir.mkdir()

        payload = _make_valid_payload()
        payload["run_info"]["outfile_path"] = str(custom_dir)
        ri = build_runinfo("1", ri_path, payload)
        assert ri.raw_dir == custom_dir

    def test_raises_on_invalid_run_tag(self, tmp_path):
        run_dir = tmp_path / R8520_RUNTYPE / "00001"
        run_dir.mkdir(parents=True)
        ri_path = run_dir / "runinfo.json"

        payload = {
            "run_info": {"runtype": "test"},
            "run_option": {"run_tag": "LED Calibration", "run_comment": ["Dark Rate"]},
        }
        with pytest.raises(RunInfoValidationError, match="Invalid run_tag"):
            build_runinfo("1", ri_path, payload)

    def test_raises_on_invalid_run_comment(self, tmp_path):
        run_dir = tmp_path / R8520_RUNTYPE / "00001"
        run_dir.mkdir(parents=True)
        ri_path = run_dir / "runinfo.json"

        payload = {
            "run_info": {"runtype": "test"},
            "run_option": {"run_tag": "PMT TEST", "run_comment": ["random note"]},
        }
        with pytest.raises(RunInfoValidationError, match="No valid datatype"):
            build_runinfo("1", ri_path, payload)

    def test_multiple_datatypes(self, tmp_path):
        run_dir = tmp_path / R8520_RUNTYPE / "00001"
        run_dir.mkdir(parents=True)
        ri_path = run_dir / "runinfo.json"

        payload = _make_valid_payload(
            run_comment=["Dark Rate", "SPE Gain", "After Pulse"]
        )
        ri = build_runinfo("1", ri_path, payload)
        assert ri.datatype == ["Dark Rate", "SPE Gain", "After Pulse"]

    def test_runtype_forced_to_run_R8520(self, tmp_path):
        """Even if runinfo.json contains a different runtype, RunInfo.runtype is always run_R8520."""
        run_dir = tmp_path / R8520_RUNTYPE / "00001"
        run_dir.mkdir(parents=True)
        ri_path = run_dir / "runinfo.json"

        payload = _make_valid_payload(runtype="some_other_type")
        ri = build_runinfo("1", ri_path, payload)
        assert ri.runtype == R8520_RUNTYPE
