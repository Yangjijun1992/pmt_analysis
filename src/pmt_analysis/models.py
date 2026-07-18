from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class RunInfo:
    run_id: str
    runtype: str
    run_dir: Path
    runinfo_path: Path
    raw_dir: Path
    outfile_name: str
    source: str
    datatype: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
