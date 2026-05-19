#!/usr/bin/env python3
"""Verify a built wheel contains the embedded WebUI bundle."""
from __future__ import annotations

import argparse
import glob
import sys
import zipfile
from pathlib import Path

REQUIRED_FILES = (
    "pythinker/web/dist/index.html",
    "pythinker/web/dist/source-hash.txt",
)


def find_wheel(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    wheels = sorted(glob.glob("dist/*.whl"))
    if not wheels:
        raise SystemExit("no wheel found under dist/; run `python -m build --wheel` first")
    return Path(wheels[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", nargs="?", help="wheel path; defaults to newest dist/*.whl")
    args = parser.parse_args()

    wheel = find_wheel(args.wheel)
    if not wheel.is_file():
        print(f"wheel not found: {wheel}", file=sys.stderr)
        return 2

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = [name for name in REQUIRED_FILES if name not in names]
        asset_count = sum(name.startswith("pythinker/web/dist/assets/") for name in names)

    if missing or asset_count == 0:
        if missing:
            print("wheel is missing WebUI files:", file=sys.stderr)
            for name in missing:
                print(f"  - {name}", file=sys.stderr)
        if asset_count == 0:
            print("wheel contains no pythinker/web/dist/assets/ entries", file=sys.stderr)
        print("fix: cd webui && bun run build, then rebuild the wheel", file=sys.stderr)
        return 1

    print(f"wheel WebUI bundle OK ({asset_count} asset entries): {wheel}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
