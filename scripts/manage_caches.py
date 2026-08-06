#!/usr/bin/env python3
"""Scan, display, and (optionally) delete the waveform_analysis cache files.

After analysing a run, the ``waveform_analysis`` package writes a ``_cache/``
directory inside the run's data directory containing:
    {run_id}-records-{hash}.bin / .json      # record metadata cache
    {run_id}-wave_pool-{hash}.bin / .json    # raw waveform pool cache
    _run_config_state.json                   # run config fingerprint
    *.tmp                                    # in-progress / orphaned cache writes

After-Pulse runs produce very large caches (tens of GB). This script lists all
cache files (path / name / size), reports the total, and can delete them.

Usage:
    # List all cache files under a data root
    python scripts/manage_caches.py

    # List cache files for a single run
    python scripts/manage_caches.py --run-id 00373

    # Dry-run (show what would be deleted, don't actually delete)
    python scripts/manage_caches.py --run-id 00373 --delete --dry-run

    # Actually delete cache files for a run
    python scripts/manage_caches.py --run-id 00373 --delete

    # Delete all caches under the data root
    python scripts/manage_caches.py --delete all
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

DEFAULT_DATA_ROOT = "/mnt/data/TPC"
CACHE_DIRNAME = "_cache"


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


def summarize(files: List[Path]) -> None:
    """Pretty-print each cache file and the total."""
    if not files:
        print("  (no files found)")
        return

    total = 0
    # One row of headers
    print(f"  {'Path':<52} {'Name':<46} {'Size':>10}")
    print("  " + "-" * 110)
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        total += size
        print(f"  {str(f.parent):<52} {f.name:<46} {human_size(size):>10}")
    print("  " + "-" * 110)
    print(f"  TOTAL: {len(files)} file(s), {human_size(total)}")


def delete_files(files: List[Path], dry_run: bool) -> int:
    """Delete the given files (or report them in dry-run).

    Returns the number of files deleted/scheduled.
    """
    n = 0
    for f in files:
        if f.exists():
            if dry_run:
                print(f"  [dry-run] would delete {f} ({human_size(f.stat().st_size)})")
            else:
                f.unlink()
                n += 1
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
    args = parser.parse_args()

    if args.delete and args.dry_run:
        print("Dry-run mode: no files will actually be deleted.\n")

    data_root = Path(args.data_root)
    if not data_root.exists():
        print(f"ERROR: data root does not exist: {data_root}")
        sys.exit(1)

    # Determine target files
    all_files: List[Path] = []
    affected_dirs: List[Path] = []

    if args.run_id:
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

    for cd in affected_dirs:
        all_files.extend(iter_cache_files(cd))

    if not args.delete:
        print(f"Cache files found under {data_root} "
              f"({len(affected_dirs)} cache dir(s), {args.run_id or 'all runs'}):\n")
        summarize(all_files)
        print("\nUse --delete to remove these files, or --delete --dry-run to preview.")
        return

    # Delete
    if args.dry_run:
        print(f"Previewing deletion of {len(all_files)} cache file(s)...\n")
    else:
        print(f"Deleting {len(all_files)} cache file(s)...\n")
    n = delete_files(all_files, args.dry_run)

    if args.purge_empty_dirs and not args.dry_run:
        removed = prune_empty_cache_dirs(affected_dirs)
        if removed:
            print(f"\nRemoved {removed} empty cache director(ies).")

    if not args.dry_run:
        print(f"\nDone. Deleted {n} cache file(s).")
    else:
        print(f"\nDone. {n} cache file(s) would have been deleted.")


if __name__ == "__main__":
    main()
