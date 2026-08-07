#!/usr/bin/env python3
"""Scan, display, and (optionally) delete /tmp waveform_analysis staging caches.

Leftovers are whole directories often owned by other users (root / daq / yjj),
so a normal user may not be able to delete them. When run under a user with
sudo (e.g. the ``daq`` user), pass ``--sudo`` to remove them via ``sudo rm``.

Usage:
    python scripts/clean_tmp_caches.py                    # list only
    python scripts/clean_tmp_caches.py --delete --dry-run # preview
    python scripts/clean_tmp_caches.py --delete           # as owner
    python scripts/clean_tmp_caches.py --delete --sudo    # as daq user (sudo)
"""
from __future__ import annotations

import argparse
import grp
import pwd
import shutil
import subprocess
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


def owner_of(path: Path) -> str:
    """Return 'user:group' for a path, or '?' if it cannot be stat'd."""
    try:
        st = path.stat()
        return f"{pwd.getpwuid(st.st_uid).pw_name}:{grp.getgrgid(st.st_gid).gr_name}"
    except (OSError, KeyError):
        return "?"


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


def is_dangerous(path: Path, root: Path) -> bool:
    """Guard against deleting the scan root, '/', or empty paths."""
    if not str(path) or path == Path("/") or path == root:
        print(f"  [abort] refusing dangerous path: {path}")
        return True
    return False


def delete_one(path: Path, use_sudo: bool) -> bool:
    """Delete one file/dir (recursively), optionally via sudo.

    Returns True on success, False on failure/abort.
    """
    if is_dangerous(path, path.parent):
        return False

    if not use_sudo:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return True
        except PermissionError:
            print(f"  [error] no permission to delete {path} "
                  f"(owner {owner_of(path)}). Re-run with --sudo.")
            return False
        except OSError as e:
            print(f"  [error] failed to delete {path}: {e}")
            return False

    # sudo path
    cmd = (["sudo", "rm", "-rf", str(path)] if path.is_dir()
           else ["sudo", "rm", "-f", str(path)])
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode(errors="replace") if e.stderr else str(e)
        print(f"  [error] sudo rm failed for {path}: {err}")
        return False


def summarize(dirs: List[Path]) -> None:
    if not dirs:
        print("  (no staging caches found)")
        return
    total = 0
    print(f"  {'Location':<48} {'Name':<42} {'Owner':<14} {'Size':>9}")
    print("  " + "-" * 116)
    for d in dirs:
        size = dir_size(d)
        total += size
        print(f"  {str(d.parent):<48} {d.name:<42} {owner_of(d):<14} {human_size(size):>9}")
    print("  " + "-" * 116)
    print(f"  TOTAL: {len(dirs)} dir(s), {human_size(total)}")


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
    parser.add_argument(
        "--sudo",
        action="store_true",
        default=False,
        help="Delete via sudo (use under the daq user for caches owned by "
             "root/other users).",
    )
    args = parser.parse_args()

    if args.delete and args.dry_run:
        print("Dry-run mode: no directories will actually be deleted.\n")
    if args.sudo and not args.delete:
        print("NOTE: --sudo only affects deletion; add --delete to remove.\n")

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

    mode = " via sudo" if args.sudo else ""
    if args.dry_run:
        print(f"Previewing deletion of {len(dirs)} staging cache dir(s){mode}...\n")
        for d in dirs:
            print(f"  [dry-run] would delete {d} ({human_size(dir_size(d))})")
        print(f"\nDone. {len(dirs)} dir(s) would have been deleted.")
        return

    print(f"Deleting {len(dirs)} staging cache dir(s){mode}...\n")
    n = sum(1 for d in dirs if delete_one(d, use_sudo=args.sudo))
    print(f"\nDone. Deleted {n} staging cache dir(s).")


if __name__ == "__main__":
    main()
