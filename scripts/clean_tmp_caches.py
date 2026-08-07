#!/usr/bin/env python3
"""Scan, display, and (optionally) delete the /tmp waveform_analysis staging
caches.

While parsing raw data, the ``waveform_analysis`` package writes staging
directories under /tmp that are not always cleaned up afterwards. Common
leftovers are whole directories:

    /tmp/v1725_parts_<8chars>/        # per-channel records_part_*.dat
    /tmp/records_parts_<8chars>/      # multi-process records staging
    /tmp/records_bundle_ref_<8chars>/ # indexed merge staging
    /tmp/waveform-mpl-cache           # matplotlib cache

After-Pulse runs leave very large staging dirs (tens of GB each; the /tmp
leftovers can total hundreds of GB). This standalone script detects every such
directory, prints its path / name / size and the grand total, and can delete
them (directories are removed recursively).

This is intentionally separate from ``manage_caches.py`` (which handles the
per-run ``_cache/`` directories inside the DAQ data tree).

Usage:
    # List all detected staging caches under /tmp
    python scripts/clean_tmp_caches.py

    # List from a custom directory
    python scripts/clean_tmp_caches.py --root /tmp

    # Preview deletion (list only, nothing removed)
    python scripts/clean_tmp_caches.py --delete --dry-run

    # Actually delete them
    python scripts/clean_tmp_caches.py --delete
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import List

DEFAULT_ROOT = "/tmp"
# Directories produced by waveform_analysis staging in /tmp (leftover caches)
DIR_PREFIXES = ("v1725_parts_", "records_parts_", "records_bundle_ref_")
DIR_NAMES = ("waveform-mpl-cache",)


def human_size(num_bytes: float) -> str:
    num_bytes = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"


def find_tmp_cache_dirs(root: Path) -> List[Path]:
    if not root.exists():
        return []
    found: List[Path] = []
    try:
        for name in sorted(root.iterdir()):
            if not name.is_dir():
                continue
            if any(name.name.startswith(p) for p in DIR_PREFIXES) or \
               name.name in DIR_NAMES:
                found.append(name)
    except OSError:
        pass
    return found


def dir_size(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        pass
    return total


def summarize(dirs: List[Path]) -> None:
    if not dirs:
        print("  (no staging caches found)")
        return
    total = 0
    print(f"  {'Location':<52} {'Name':<46} {'Size':>10}")
    print("  " + "-" * 110)
    for d in dirs:
        size = dir_size(d)
        total += size
        print(f"  {str(d.parent):<52} {d.name:<46} {human_size(size):>10}")
    print("  " + "-" * 110)
    print(f"  TOTAL: {len(dirs)} dir(s), {human_size(total)}")


def delete_paths(paths: List[Path], dry_run: bool) -> int:
    n = 0
    for p in paths:
        if not p.exists():
            continue
        if dry_run:
            print(f"  [dry-run] would delete {p} ({human_size(dir_size(p))})")
            continue
        try:
            shutil.rmtree(p)
            n += 1
        except OSError as e:
            print(f"  [error] failed to delete {p}: {e}")
    return n


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan/display/delete waveform_analysis /tmp staging caches.",
    )
    parser.add_argument(
        "--root",
        default=DEFAULT_ROOT,
        help=f"Directory to scan (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        default=False,
        help="Actually delete the staging caches (default: list only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="With --delete, show what would be deleted without deleting.",
    )
    args = parser.parse_args()

    if args.delete and args.dry_run:
        print("Dry-run mode: no directories will actually be deleted.\n")

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: directory does not exist: {root}")
        sys.exit(1)

    dirs = find_tmp_cache_dirs(root)

    if not args.delete:
        print(f"waveform_analysis /tmp staging caches under {root} "
              f"({len(dirs)} dir(s)):\n")
        summarize(dirs)
        print("\nAdd --delete to remove them, or --delete --dry-run to preview.")
        return

    if args.dry_run:
        print(f"Previewing deletion of {len(dirs)} staging cache dir(s)...\n")
    else:
        print(f"Deleting {len(dirs)} staging cache dir(s)...\n")
    n = delete_paths(dirs, args.dry_run)

    if not args.dry_run:
        print(f"\nDone. Deleted {n} staging cache dir(s).")
    else:
        print(f"\nDone. {n} staging cache dir(s) would have been deleted.")


if __name__ == "__main__":
    main()
