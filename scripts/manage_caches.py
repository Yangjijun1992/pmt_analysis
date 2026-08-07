#!/usr/bin/env python3
"""Scan, display, and (optionally) delete the per-run waveform_analysis cache
files.

After analysing a run, the ``waveform_analysis`` package writes a ``_cache/``
directory inside the run's data directory containing:
    {run_id}-records-{hash}.bin / .json      # record metadata cache
    {run_id}-wave_pool-{hash}.bin / .json    # raw waveform pool cache
    _run_config_state.json                   # run config fingerprint
    *.tmp                                    # in-progress / orphaned writes

After-Pulse runs produce very large caches (tens of GB). This script lists the
run ``_cache`` files (path / name / size / owner), reports the total, and can
delete them.

The cache directories are usually owned by the DAQ user. When run under a user
that owns the files you can delete directly; otherwise pass ``--sudo`` (under
the ``daq`` user, who has sudo) to remove them via ``sudo rm``.

NOTE: the waveform_analysis staging caches written to ``/tmp`` are handled by
the separate script ``scripts/clean_tmp_caches.py``.

NOTE: this script is deliberately kept free of Python-3-only syntax so that a
bare ``python`` (which may be Python 2, e.g. under ``sudo``) can still print a
clear version error instead of a confusing SyntaxError.

Usage:
    # List all run _cache files under a data root
    python3 scripts/manage_caches.py

    # List run _cache files for a single run
    python3 scripts/manage_caches.py --run-id 00373

    # Preview deletion (no actual deletion)
    python3 scripts/manage_caches.py --run-id 00373 --delete --dry-run

    # Actually delete the cache files for a run
    python3 scripts/manage_caches.py --run-id 00373 --delete

    # Delete via sudo (when not the file owner)
    python3 scripts/manage_caches.py --delete --sudo

    # Delete all run caches and remove empty cache dirs
    python3 scripts/manage_caches.py --delete --purge-empty-dirs
"""
import sys

# Fail fast with a clear message under Python < 3.7. This guard and the rest
# of the file use only Python-2/3-compatible syntax so this message is shown
# even when invoked as `python` (Python 2).
if sys.version_info[0] < 3:
    sys.exit(
        "This script requires Python 3.7+. You are running Python 2 "
        "(`python` may point to it, e.g. under sudo).\n"
        "Use: sudo python3 scripts/manage_caches.py ... "
        "or an absolute python3 path (e.g. the py12/pyth12 conda env)."
    )
if sys.version_info < (3, 7):
    sys.exit(
        "This script requires Python 3.7+ "
        "(you are running Python {}.{}).\n".format(
            sys.version_info[0], sys.version_info[1]
        ) +
        "Use: sudo python3 scripts/manage_caches.py ... or an absolute "
        "python3 path."
    )

import argparse
import grp
import pwd
import subprocess
from pathlib import Path

DEFAULT_DATA_ROOT = "/mnt/data/TPC"
CACHE_DIRNAME = "_cache"


def owner_of(path):
    """Return 'user:group' for a path, or '?' if it cannot be stat'd."""
    try:
        st = path.stat()
        return "{}:{}".format(
            pwd.getpwuid(st.st_uid).pw_name,
            grp.getgrgid(st.st_gid).gr_name,
        )
    except (OSError, KeyError):
        return "?"


def human_size(num_bytes):
    """Format a byte count as a human-readable string."""
    num_bytes = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024.0:
            return "{:.2f} {}".format(num_bytes, unit)
        num_bytes /= 1024.0
    return "{:.2f} PB".format(num_bytes)


def find_cache_dirs(data_root):
    """Return all ``_cache`` directories under data_root."""
    if not data_root.exists():
        return []
    return sorted(data_root.rglob(CACHE_DIRNAME))


def iter_cache_files(cache_dir):
    """Return all files inside a cache directory."""
    if not cache_dir.exists():
        return []
    return sorted([p for p in cache_dir.iterdir() if p.is_file()])


def summarize(files):
    """Pretty-print each cache file and the total."""
    if not files:
        print("  (no cache files found)")
        return

    total = 0
    print("  {:<48} {:<42} {:<14} {:>9}".format("Path", "Name", "Owner", "Size"))
    print("  " + "-" * 116)
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        total += size
        print("  {:<48} {:<42} {:<14} {:>9}".format(
            str(f.parent), f.name, owner_of(f), human_size(size)))
    print("  " + "-" * 116)
    print("  TOTAL: {} file(s), {}".format(len(files), human_size(total)))


def delete_files(files, dry_run, use_sudo=False):
    """Delete the given files (or report them in dry-run).

    Individual files are removed with ``unlink``; ``rm -f`` is used when
    ``--sudo`` is set (for files owned by other users). Print the owner on a
    permission error.

    Returns the number of files deleted/scheduled.
    """
    n = 0
    for f in files:
        if not f.exists():
            continue
        if dry_run:
            print("  [dry-run] would delete {} ({})".format(f, human_size(f.stat().st_size)))
            continue
        try:
            f.unlink()
            n += 1
        except PermissionError:
            if use_sudo:
                try:
                    subprocess.run(["sudo", "rm", "-f", str(f)], check=True,
                                   capture_output=True)
                    n += 1
                except subprocess.CalledProcessError as e:
                    err = e.stderr.decode(errors="replace") if e.stderr else str(e)
                    print("  [error] sudo rm failed for {}: {}".format(f, err))
            else:
                print("  [error] no permission to delete {} "
                      "(owner {}). Re-run with --sudo.".format(f, owner_of(f)))
        except OSError as e:
            print("  [error] failed to delete {}: {}".format(f, e))
    return n


def prune_empty_cache_dirs(cache_dirs):
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


def _resolve_run_cache_dir(data_root, run_id):
    """Find the _cache directory for a run id across supported layouts."""
    candidates = [
        data_root / "run_{}".format(run_id) / CACHE_DIRNAME,
        data_root / run_id / CACHE_DIRNAME,
    ]
    for c in candidates:
        if (c).exists():
            return c

    # Some layouts nest under a runtype dir (e.g. run_R8520/<run_id>/_cache)
    hits = [d / CACHE_DIRNAME for d in data_root.rglob(run_id)
            if d.is_dir() and (d / CACHE_DIRNAME).is_dir()]
    if hits:
        return sorted(hits)[0]
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(
        description="Scan/display/delete per-run waveform_analysis _cache files.",
    )
    parser.add_argument(
        "--data-root",
        default=DEFAULT_DATA_ROOT,
        help="Data root directory (default: {})".format(DEFAULT_DATA_ROOT),
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
        "--sudo",
        action="store_true",
        default=False,
        help="Delete via sudo (use under the daq user for cache files owned "
             "by other users).",
    )
    args = parser.parse_args()

    if args.delete and args.dry_run:
        print("Dry-run mode: no files will actually be deleted.\n")
    if args.sudo and not args.delete:
        print("NOTE: --sudo only affects deletion; add --delete to remove.\n")

    data_root = Path(args.data_root)
    if not data_root.exists():
        print("ERROR: data root does not exist: {}".format(data_root))
        sys.exit(1)

    if args.run_id:
        cache_dir = _resolve_run_cache_dir(data_root, args.run_id)
        if not cache_dir.exists():
            print("No cache found for run id '{}' under {}".format(args.run_id, data_root))
            sys.exit(0)
        affected_dirs = [cache_dir]
    else:
        affected_dirs = find_cache_dirs(data_root)

    all_files = []
    for cd in affected_dirs:
        all_files.extend(iter_cache_files(cd))

    if not args.delete:
        print("Run _cache files under {} ({} cache dir(s), {}):\n".format(
            data_root, len(affected_dirs), args.run_id or "all runs"))
        summarize(all_files)
        print("\nAdd --delete to remove them, or --delete --dry-run to preview.")
        return

    if args.dry_run:
        print("Previewing deletion of {} cache file(s){}...\n".format(
            len(all_files), " via sudo" if args.sudo else ""))
    else:
        print("Deleting {} cache file(s){}...\n".format(
            len(all_files), " via sudo" if args.sudo else ""))
    n = delete_files(all_files, args.dry_run, use_sudo=args.sudo)

    if args.purge_empty_dirs and not args.dry_run:
        removed = prune_empty_cache_dirs(affected_dirs)
        if removed:
            print("\nRemoved {} empty cache director(ies).".format(removed))

    if not args.dry_run:
        print("\nDone. Deleted {} cache file(s).".format(n))
    else:
        print("\nDone. {} cache file(s) would have been deleted.".format(n))


if __name__ == "__main__":
    main()
