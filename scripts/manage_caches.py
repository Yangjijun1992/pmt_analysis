#!/usr/bin/env python3
"""Scan, display, and (optionally) delete waveform_analysis cache files.

Two kinds of cache are produced when analysing runs:

1. In-run caches — a ``_cache/`` directory is written inside the run's data
   directory:
       {run_id}-records-{hash}.bin / .json      # record metadata cache
       {run_id}-wave_pool-{hash}.bin / .json    # raw waveform pool cache
       _run_config_state.json                   # run config fingerprint
       *.tmp                                    # in-progress / orphaned writes

2. /tmp staging caches — written by ``waveform_analysis`` during raw-data
   parsing (not always cleaned up). Common leftovers include whole
   directories such as:
       /tmp/v1725_parts_<8chars>/       # per-channel records_part_*.dat
       /tmp/records_parts_<8chars>/     # multi-process records staging
       /tmp/records_bundle_ref_<8chars>/ # indexed merge staging
       /tmp/waveform-mpl-cache          # matplotlib cache

After-Pulse runs produce very large caches (tens of GB). This script lists all
cache files/dirs (path / name / size), reports the total, and can delete them.

Usage:
    # List all run _cache files under a data root
    python scripts/manage_caches.py

    # List run _cache files for a single run
    python scripts/manage_caches.py --run-id 00373

    # Also include the /tmp waveform_analysis staging caches when listing
    python scripts/manage_caches.py --tmp

    # Preview deletion of run caches (+ /tmp staging with --tmp)
    python scripts/manage_caches.py --run-id 00373 --delete --dry-run
    python scripts/manage_caches.py --tmp --delete --dry-run

    # Actually delete them
    python scripts/manage_caches.py --run-id 00373 --delete
    python scripts/manage_caches.py --tmp --delete
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

DEFAULT_DATA_ROOT = "/mnt/data/TPC"
DEFAULT_TMP_ROOT = "/tmp"
CACHE_DIRNAME = "_cache"
# Directories produced by waveform_analysis staging in /tmp (leftover caches)
TMP_CACHE_DIR_PREFIXES = ("v1725_parts_", "records_parts_", "records_bundle_ref_")
TMP_CACHE_DIR_NAMES = ("waveform-mpl-cache",)


def human_size(num_bytes: float) -> str:
    """Format a byte count as a human-readable string."""
    num_bytes = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"


def find_cache_dirs(data_root: Path) -> List[Path]:
    """Return all ``_cache`` directories under data_root."""
    if not data_root.exists():
        return []
    return sorted(data_root.rglob(CACHE_DIRNAME))


def iter_cache_files(cache_dir: Path) -> List[Path]:
    """Return all files inside a cache directory."""
    if not cache_dir.exists():
        return []
    return sorted([p for p in cache_dir.iterdir() if p.is_file()])


def collect_for_run(run_dir: Path) -> List[Path]:
    """Collect cache files for a single run directory (its _cache subdir)."""
    cache_dir = run_dir / CACHE_DIRNAME
    return iter_cache_files(cache_dir)


def summarize(paths: List[Path]) -> None:
    """Pretty-print each cache file/dir and the total."""
    if not paths:
        print("  (no caches found)")
        return

    total = 0
    print(f"  {'Location':<52} {'Name':<46} {'Size':>10}")
    print("  " + "-" * 110)
    for p in paths:
        size = dir_size(p)
        total += size
        kind = "dir " if p.is_dir() else "file"
        print(f"  {str(p.parent):<52} {p.name:<46} [{kind}] {human_size(size):>6}")
    print("  " + "-" * 110)
    print(f"  TOTAL: {len(paths)} path(s), {human_size(total)}")


def delete_paths(paths: List[Path], dry_run: bool) -> int:
    """Delete the given files and/or directories.

    Whole directories are removed recursively (``shutil.rmtree``); individual
    files via ``unlink``. In dry-run mode nothing is removed.

    Returns the number of paths deleted/scheduled.
    """
    n = 0
    for p in paths:
        if not p.exists():
            continue
        if dry_run:
            size = dir_size(p)
            print(f"  [dry-run] would delete {p} ({human_size(size)})")
            continue
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            n += 1
        except OSError as e:
            print(f"  [error] failed to delete {p}: {e}")
    return n


def prune_empty_cache_dirs(cache_dirs: List[Path]) -> int:
    """Remove now-empty cache directories. Returns number removed."""
    removed = 0
    for d in cache_dirs:
        try:
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
                removed += 1
        except OSError:
            pass
    return removed


def find_tmp_cache_dirs(tmp_root: Path) -> List[Path]:
    """Return waveform_analysis staging cache directories in /tmp.

    Matches whole directories by prefix or exact name (top-level only).
    """
    if not tmp_root.exists():
        return []
    found: List[Path] = []
    try:
        for name in sorted(tmp_root.iterdir()):
            if not name.is_dir():
                continue
            if any(name.name.startswith(p) for p in TMP_CACHE_DIR_PREFIXES) or \
               name.name in TMP_CACHE_DIR_NAMES:
                found.append(name)
    except OSError:
        pass
    return found


def dir_size(path: Path) -> int:
    """Total byte size of a file or a directory tree."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        pass
    return total


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan/display/delete waveform_analysis cache files.",
    )
    parser.add_argument(
        "--data-root",
        default=DEFAULT_DATA_ROOT,
        help=f"Data root directory (default: {DEFAULT_DATA_ROOT})",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="5-digit run id to target. Empty = all runs under data-root.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        default=False,
        help="Actually delete cache files (default: only list).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="With --delete, show what would be deleted without deleting.",
    )
    parser.add_argument(
        "--purge-empty-dirs",
        action="store_true",
        default=False,
        help="Remove cache directories that become empty after deletion.",
    )
    parser.add_argument(
        "--tmp",
        action="store_true",
        default=False,
        help="Also include the /tmp waveform_analysis staging caches "
             "(v1725_parts_*, records_parts_*, records_bundle_ref_*, "
             "waveform-mpl-cache). Compatible with --run-id for listing only.",
    )
    parser.add_argument(
        "--tmp-root",
        default=DEFAULT_TMP_ROOT,
        help=f"Directory to scan for staging caches (default: {DEFAULT_TMP_ROOT})",
    )
    args = parser.parse_args()

    if args.delete and args.dry_run:
        print("Dry-run mode: no files will actually be deleted.\n")

    data_root = Path(args.data_root)
    if not data_root.exists():
        print(f"ERROR: data root does not exist: {data_root}")
        sys.exit(1)

    # Determine target files/dirs
    all_paths: List[Path] = []
    affected_dirs: List[Path] = []

    if args.run_id:
        # Run _cache only; per-run /tmp staging cannot be reliably attributed
        if args.tmp:
            print("NOTE: --tmp staging cannot be attributed to a specific "
                  "--run-id; scanning /tmp independently (see below).")
        run_dir = data_root / f"run_{args.run_id}" if not (data_root / args.run_id).exists() \
            else data_root / args.run_id
        # Also try direct run dir layout variants
        candidates = [
            run_dir,
            data_root / args.run_id,
        ]
        # Some layouts nest under a runtype dir (e.g. run_R8520/<run_id>)
        found_run_dir = None
        for c in candidates:
            if (c / CACHE_DIRNAME).exists():
                found_run_dir = c
                break
        if found_run_dir is None:
            # search precisely
            hits = [d for d in data_root.rglob(args.run_id)
                    if d.is_dir() and (d / CACHE_DIRNAME).exists()]
            found_run_dir = hits[0] if hits else None
        if found_run_dir is None:
            print(f"No cache found for run id '{args.run_id}' under {data_root}")
            sys.exit(0)
        affected_dirs = [found_run_dir / CACHE_DIRNAME]
    else:
        affected_dirs = find_cache_dirs(data_root)

    run_paths: List[Path] = []
    for cd in affected_dirs:
        run_paths.extend(iter_cache_files(cd))
    all_paths = list(run_paths)

    tmp_dirs: List[Path] = []
    if args.tmp:
        tmp_dirs = find_tmp_cache_dirs(Path(args.tmp_root))
        all_paths.extend(tmp_dirs)

    if not args.delete:
        print(f"Run _cache files under {data_root} "
              f"({len(affected_dirs)} cache dir(s), {args.run_id or 'all runs'}):\n")
        summarize(run_paths)
        if args.tmp:
            print(f"\n/tmp staging caches under {args.tmp_root} "
                  f"({len(tmp_dirs)} dir(s)):\n")
            summarize(tmp_dirs)
        print("\nAdd --delete to remove, or --delete --dry-run to preview.")
        return

    # Delete
    if args.dry_run:
        print(f"Previewing deletion of {len(all_paths)} cache path(s)...\n")
    else:
        print(f"Deleting {len(all_paths)} cache path(s)...\n")
    n = delete_paths(all_paths, args.dry_run)

    if args.purge_empty_dirs and not args.dry_run:
        removed = prune_empty_cache_dirs(affected_dirs)
        if removed:
            print(f"\nRemoved {removed} empty cache director(ies).")

    if not args.dry_run:
        print(f"\nDone. Deleted {n} cache path(s).")
    else:
        print(f"\nDone. {n} cache path(s) would have been deleted.")


if __name__ == "__main__":
    main()
