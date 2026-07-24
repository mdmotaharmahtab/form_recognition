"""One-time migration: move flat per-document artifacts into the type buckets
(stage0/ prompts/ extractors/ fields/ trails/ llm_calls/ timings/ replies/)
using the SAME routing the pipeline now writes with (common.artifact_bucket).

Run roots processed are passed as arguments (repeatable). Snapshots under
data/runs/snapshots are intentionally NOT migrated - they are frozen historical
copies and stay in their original flat layout.

Usage:
  python migrate_to_buckets.py <run_root> [<run_root> ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src", "pipeline"))

from common import ART_BUCKETS, artifact_bucket  # noqa: E402


def migrate_root(root: str, dry_run: bool) -> tuple[int, int]:
    """Bucket every artifact file under one run root. Returns (moved, dirs)."""
    if not os.path.isdir(root):
        print(f"  (skip, missing) {root}")
        return (0, 0)
    # collect directories BEFORE we create any bucket subdirs, so freshly made
    # bucket dirs are never themselves treated as artifact dirs
    all_dirs = [dp for dp, _dn, _fn in os.walk(root)]
    moved = touched = 0
    for d in all_dirs:
        if os.path.basename(d) in ART_BUCKETS:
            continue  # already a bucket (or a re-run)
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        files = [f for f in entries if os.path.isfile(os.path.join(d, f))]
        dir_moved = 0
        for fn in files:
            bucket = artifact_bucket(fn)
            if not bucket:
                continue  # run-root file (summary/report/xlsx) stays put
            dest_dir = os.path.join(d, bucket)
            src = os.path.join(d, fn)
            dst = os.path.join(dest_dir, fn)
            if dry_run:
                dir_moved += 1
                continue
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(src, dst)
            dir_moved += 1
        if dir_moved:
            touched += 1
            moved += dir_moved
    print(f"  {root}: {moved} file(s) across {touched} doc dir(s)"
          f"{' [dry-run]' if dry_run else ''}")
    return (moved, touched)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    total = 0
    for root in args.roots:
        total += migrate_root(root, args.dry_run)[0]
    print(f"TOTAL {total} file(s) migrated{' [dry-run]' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
