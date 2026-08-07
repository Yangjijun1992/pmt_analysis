#!/usr/bin/env python3
"""Scan, display, and (optionally) delete /tmp waveform_analysis staging caches.

Leftovers are whole directories often owned by other users (root / daq / yjj),
so a normal user may not be able to delete them. When run under a user with
sudo (e.g. the ``daq`` user), pass ``--sudo`` to remove them via ``sudo rm``.

NOTE: this script is deliberately kept free of Python-3-only syntax so that a
bare ``python`` (which may be Python 2, e.g. under ``sudo``) can still print a
clear version error instead of a confusing SyntaxError.

Usage:
    python3 scripts/clean_tmp_caches.py                    # list only
    python3 scripts/clean_tmp_caches.py --delete --dry-run # preview
    python3 scripts/clean_tmp_caches.py --delete           # as owner
    python3 scripts/clean_tmp_caches.py --delete --sudo    # as daq user
"""
import sys

# Fail fast with a clear message under Python < 3.7. This guard and the rest
# of the file use only Python-2/3-compatible syntax so this message is shown
# even when invoked as `python` (Python 2).
if sys.version_info[0] < 3:
    sys.exit(
        "This script requires Python 3.7+. You are running Python 2 "
        "(`python` may point to it, e.g. under sudo).\n"
        "Use: sudo python3 scripts/clean_tmp_caches.py ... "
        "or an absolute python3 path (e.g. the py12/pyth12 conda env)."
    )
if sys.version_info < (3, 7):
    sys.exit(
        "This script requires Python 3.7+ "
        "(you are running Python {}.{}).\n".format(
            sys.version_info[0], sys.version_info[1]
        ) +
        "Use: sudo python3 scripts/clean_tmp_caches.py ... or an absolute "
        "python3 path."
    )

import argparse
import grp
import pwd
import shutil
import subprocess
from pathlib import Path

DEFAULT_ROOT = "/tmp"
# Directories produced by waveform_analysis staging in /tmp (leftover caches)
DIR_PREFIXES = ("v1725_parts_", "records_parts_", "records_bundle_ref_")
DIR_NAMES = ("waveform-mpl-cache",)


def human_size(num_bytes):
    num_bytes = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024.0:
            return "{:.2f} {}".format(num_bytes, unit)
        num_bytes /= 1024.0
    return "{:.2f} PB".format(num_bytes)


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


def find_tmp_cache_dirs(root):
    if not root.exists():
        return []
    found = []
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


def dir_size(path):
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        pass
    return total


def is_dangerous(path, root):
    """Guard against deleting the scan root, '/', or empty paths."""
    if not str(path) or path == Path("/") or path == root:
        print("  [abort] refusing dangerous path: {}".format(path))
        return True
    return False


def delete_one(path, use_sudo):
    """Delete one file/dir (recursively), optionally via sudo."""
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
            print("  [error] no permission to delete {} "
                  "(owner {}). Re-run with --sudo.".format(path, owner_of(path)))
            return False
        except OSError as e:
            print("  [error] failed to delete {}: {}".format(path, e))
            return False

    cmd = (["sudo", "rm", "-rf", str(path)] if path.is_dir()
           else ["sudo", "rm", "-f", str(path)])
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode(errors="replace") if e.stderr else str(e)
        print("  [error] sudo rm failed for {}: {}".format(path, err))
        return False


def summarize(dirs):
    if not dirs:
        print("  (no staging caches found)")
        return
    total = 0
    print("  {:<48} {:<42} {:<14} {:>9}".format("Location", "Name", "Owner", "Size"))
    print("  " + "-" * 116)
    for d in dirs:
        size = dir_size(d)
        total += size
        print("  {:<48} {:<42} {:<14} {:>9}".format(
            str(d.parent), d.name, owner_of(d), human_size(size)))
    print("  " + "-" * 116)
    print("  TOTAL: {} dir(s), {}".format(len(dirs), human_size(total)))


def main():
    parser = argparse.ArgumentParser(
        description="Scan/display/delete waveform_analysis /tmp staging caches.",
    )
    parser.add_argument(
        "--root",
        default=DEFAULT_ROOT,
        help="Directory to scan (default: {})".format(DEFAULT_ROOT),
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
        print("ERROR: directory does not exist: {}".format(root))
        sys.exit(1)

    dirs = find_tmp_cache_dirs(root)

    if not args.delete:
        print("waveform_analysis /tmp staging caches under {} "
              "({} dir(s)):\n".format(root, len(dirs)))
        summarize(dirs)
        print("\nAdd --delete to remove them, or --delete --dry-run to preview.")
        return

    mode = " via sudo" if args.sudo else ""
    if args.dry_run:
        print("Previewing deletion of {} staging cache dir(s){}...\n".format(len(dirs), mode))
        for d in dirs:
            print("  [dry-run] would delete {} ({})".format(d, human_size(dir_size(d))))
        print("\nDone. {} dir(s) would have been deleted.".format(len(dirs)))
        return

    print("Deleting {} staging cache dir(s){}...\n".format(len(dirs), mode))
    n = sum(1 for d in dirs if delete_one(d, use_sudo=args.sudo))
    print("\nDone. Deleted {} staging cache dir(s).".format(n))


if __name__ == "__main__":
    main()
