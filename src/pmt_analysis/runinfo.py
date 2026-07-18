from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set

from pmt_analysis.models import RunInfo

STANDARD_FIELDS = frozenset({"run_id", "runtype", "outfile_path", "outfile_name"})

VALID_DATATYPES: Set[str] = frozenset({
    "dark rate",
    "spe gain",
    "after pulse",
})

VALID_RUN_TAG = "pmt test"

R8520_RUNTYPE = "run_R8520"


class RunInfoError(Exception):
    """Base exception for runinfo discovery and parsing."""


class RunInfoNotFoundError(RunInfoError):
    """No runinfo.json found for the given run_id."""


class RunInfoNotUniqueError(RunInfoError):
    """Multiple runinfo.json files found for the same run_id."""


class RunInfoParseError(RunInfoError):
    """Failed to parse runinfo.json content."""


class RunInfoValidationError(RunInfoError):
    """runinfo.json failed validation (e.g. wrong run_tag or run_comment)."""


def normalize_run_id(run_id: int | str) -> str:
    return str(run_id).zfill(5)


def validate_run_tag(payload: Dict[str, Any]) -> None:
    run_option = payload.get("run_option", {})
    run_tag = run_option.get("run_tag", "")
    if run_tag.strip().lower() != VALID_RUN_TAG:
        raise RunInfoValidationError(
            f"Invalid run_tag '{run_tag}', expected '{VALID_RUN_TAG}'"
        )


def parse_datatypes(payload: Dict[str, Any]) -> List[str]:
    run_option = payload.get("run_option", {})
    run_comment = run_option.get("run_comment", [])
    if not isinstance(run_comment, list):
        run_comment = [run_comment]

    matched: List[str] = []
    for comment in run_comment:
        normalized = re.sub(r"\s+", " ", comment.strip().lower())
        if normalized in VALID_DATATYPES:
            matched.append(comment.strip())

    if not matched:
        raise RunInfoValidationError(
            f"No valid datatype found in run_comment: {run_comment}"
        )

    return matched


def discover_runinfo_path(
    run_id: int | str, data_root: str | Path = "/mnt/data/TPC"
) -> Path:
    rid = normalize_run_id(run_id)
    root = Path(data_root)
    target = root / R8520_RUNTYPE / rid / "runinfo.json"

    if not target.exists():
        raise RunInfoNotFoundError(
            f"No runinfo.json found for run_id={rid} under {root / R8520_RUNTYPE}"
        )

    return target


def load_runinfo_json(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise RunInfoParseError(f"Failed to parse JSON: {p}\n  {e}") from e
    except OSError as e:
        raise RunInfoParseError(f"Failed to read file: {p}\n  {e}") from e


def build_runinfo(
    run_id: int | str,
    runinfo_path: Path,
    payload: Dict[str, Any],
) -> RunInfo:
    rid = normalize_run_id(run_id)
    run_dir = runinfo_path.parent
    run_info_section = payload.get("run_info", {})

    runtype = run_info_section.get("runtype", "")
    outfile_name = run_info_section.get("outfile_name", "")
    outfile_path_raw = run_info_section.get("outfile_path")

    raw_dir_fallback = run_dir / "RAW"
    raw_dir_source = "runinfo.outfile_path"
    if outfile_path_raw:
        raw_dir = Path(outfile_path_raw)
    else:
        raw_dir = raw_dir_fallback
        raw_dir_source = "fallback (run_dir/RAW)"

    extra_metadata: Dict[str, Any] = {}
    for key, value in run_info_section.items():
        if key not in STANDARD_FIELDS:
            extra_metadata[key] = value

    extra_metadata["raw_dir_source"] = raw_dir_source

    # Preserve ALL top-level sections except run_info
    for key, value in payload.items():
        if key == "run_info":
            continue
        extra_metadata[key] = value

    validate_run_tag(payload)
    datatype = parse_datatypes(payload)

    return RunInfo(
        run_id=rid,
        runtype=R8520_RUNTYPE,
        run_dir=run_dir,
        runinfo_path=runinfo_path,
        raw_dir=raw_dir,
        outfile_name=outfile_name,
        source=str(runinfo_path),
        datatype=datatype,
        metadata=extra_metadata,
    )


def get_runinfo(
    run_id: int | str, data_root: str | Path = "/mnt/data/TPC"
) -> RunInfo:
    path = discover_runinfo_path(run_id, data_root)
    payload = load_runinfo_json(path)
    return build_runinfo(run_id, path, payload)
