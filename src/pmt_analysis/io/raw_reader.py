from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pmt_analysis.models import RunInfo


@dataclass
class RawDataBundle:
    """Unified container for raw data loaded from binary files."""

    runinfo: RunInfo
    source_path: List[Path]
    data: Any  # records structured numpy array
    data_format: str
    event_count: int
    channel_count: int
    waveform_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)


def resolve_raw_input_path(runinfo: RunInfo) -> List[Path]:
    """Resolve raw binary file paths from RunInfo.

    Uses raw_dir from RunInfo and discovers *_raw_*.bin files.
    """
    raw_dir = runinfo.raw_dir
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw directory not found: {raw_dir}")

    bin_files = sorted(raw_dir.glob("*_raw_*.bin"))
    if not bin_files:
        raise FileNotFoundError(
            f"No raw binary files (*_raw_*.bin) found in: {raw_dir}"
        )
    return bin_files


def load_raw_data_from_notebook_logic(
    input_paths: List[Path],
    runinfo: RunInfo,
) -> Any:
    """Load raw data using waveform_analysis package (notebook logic).

    This function replicates the data loading approach from
    example_code/pmt_dark_cout_rate_example.ipynb.

    Requires: waveform_analysis package (pyth12 environment).
    """
    try:
        from waveform_analysis.core.context import Context
        from waveform_analysis.core import records_view
    except ImportError as e:
        raise ImportError(
            "waveform_analysis package is required for raw data loading. "
            "Please install it or use the pyth12 environment. "
            f"Original error: {e}"
        ) from e

    # Derive storage_dir from runinfo: /mnt/data/TPC/{runtype}/
    storage_dir = str(runinfo.run_dir.parent) + "/"

    ctx = Context(storage_dir=storage_dir)

    # Register minimal plugins for data reading
    from waveform_analysis.core.plugins.plugin_sets import (
        plugins_io,
        plugins_waveform,
    )

    ctx.register(*plugins_io())
    ctx.register(*plugins_waveform())

    # Configure for the specific run
    daq_adapter = runinfo.metadata.get("daq_adapter", "V1725").lower()
    ctx.set_config({
        "data_root": storage_dir,
        "daq_adapter": daq_adapter,
        "show_progress": False,
        "use_filtered": False,
        "wave_source": "records",
    })

    run_id = runinfo.run_id
    rv = records_view(ctx, run_id)

    return rv


def summarize_raw_data(data: Any) -> Dict[str, Any]:
    """Extract summary statistics from loaded raw data.

    Returns dict with event_count, channel_count, waveform_count, etc.
    """
    records = data.records

    event_count = len(records)
    channel_count = len(set(records["channel"].tolist()))
    waveform_count = event_count  # Each record is one waveform

    # Get unique boards
    boards = sorted(set(records["board"].tolist()))

    # Time range
    time_min = int(records["time"].min())
    time_max = int(records["time"].max())
    daq_time_s = (time_max - time_min) * 1e-9

    # Waveform length
    event_lengths = records["event_length"]
    avg_waveform_length = float(event_lengths.mean()) if len(event_lengths) > 0 else 0

    return {
        "event_count": event_count,
        "channel_count": channel_count,
        "waveform_count": waveform_count,
        "board_count": len(boards),
        "boards": boards,
        "daq_time_s": daq_time_s,
        "avg_waveform_length": avg_waveform_length,
        "record_dtype_names": list(records.dtype.names or []),
    }


class NotebookBasedRawDataReader:
    """Raw data reader based on notebook waveform_analysis logic."""

    def __init__(self) -> None:
        self._data_cache: Dict[str, Any] = {}

    def read(self, runinfo: RunInfo) -> RawDataBundle:
        """Read raw data for a given RunInfo.

        Steps:
        1. Resolve raw binary file paths
        2. Load data using waveform_analysis (notebook logic)
        3. Summarize and return RawDataBundle
        """
        # 1. Resolve paths
        source_paths = resolve_raw_input_path(runinfo)

        # 2. Load data
        rv = load_raw_data_from_notebook_logic(source_paths, runinfo)

        # 3. Summarize
        summary = summarize_raw_data(rv)

        return RawDataBundle(
            runinfo=runinfo,
            source_path=source_paths,
            data=rv,
            data_format="waveform_analysis_records",
            event_count=summary["event_count"],
            channel_count=summary["channel_count"],
            waveform_count=summary["waveform_count"],
            metadata=summary,
        )
