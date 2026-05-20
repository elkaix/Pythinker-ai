#!/usr/bin/env python3
"""WebUI source-hash guard.

Computes a deterministic SHA256 over the WebUI source tree and compares it to
the value baked into the built bundle at `pythinker/web/dist/source-hash.txt`.

Usage:
    python scripts/webui_hash.py --write   # invoked from `bun run build`
    python scripts/webui_hash.py --check   # invoked from CI / pre-commit

Exit codes:
    0 — hash matches (or --write completed)
    1 — hash mismatch: webui sources changed without rebuilding dist
    2 — dist or sources missing
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBUI = REPO_ROOT / "webui"
DIST = REPO_ROOT / "pythinker" / "web" / "dist"
HASH_FILE = DIST / "source-hash.txt"

# Files that, when changed, require a rebuild. Globs are relative to WEBUI.
SOURCE_GLOBS: tuple[str, ...] = (
    "src/**/*.ts",
    "src/**/*.tsx",
    "src/**/*.js",
    "src/**/*.jsx",
    "src/**/*.css",
    "src/**/*.json",
    "src/**/*.svg",
    "src/**/*.html",
    "index.html",
    "package.json",
    "bun.lock",
    "tsconfig.json",
    "tsconfig.build.json",
    "vite.config.ts",
    "biome.json",
    "postcss.config.cjs",
    "postcss.config.js",
    "tailwind.config.cjs",
    "tailwind.config.js",
    "tailwind.config.ts",
)


def collect_files() -> list[Path]:
    seen: set[Path] = set()
    for glob in SOURCE_GLOBS:
        for path in WEBUI.glob(glob):
            if path.is_file():
                seen.add(path)
    return sorted(seen)


def compute_hash() -> str:
    files = collect_files()
    if not files:
        raise SystemExit("no webui source files matched; check SOURCE_GLOBS")
    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(WEBUI).as_posix().encode()
        digest.update(rel)
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def cmd_write() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    # Vite's `emptyOutDir: true` clears DIST on every build, including the
    # tracked .gitkeep placeholder. Re-write it here so the dir keeps existing
    # on fresh checkouts after a local rebuild.
    gitkeep = DIST / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text(
            "# Placeholder so the WebUI dist directory always exists on fresh\n"
            "# checkouts. `bun run build` (cd webui && bun run build) populates\n"
            "# this directory with the real bundle.\n"
        )
    h = compute_hash()
    HASH_FILE.write_text(h + "\n")
    print(f"wrote {HASH_FILE.relative_to(REPO_ROOT)}: {h[:16]}…", file=sys.stderr)
    return 0


def cmd_check() -> int:
    if not HASH_FILE.exists():
        print(
            f"missing {HASH_FILE.relative_to(REPO_ROOT)} — run `cd webui && bun run build`",
            file=sys.stderr,
        )
        return 2
    expected = HASH_FILE.read_text().strip()
    actual = compute_hash()
    if expected == actual:
        print(f"webui freshness OK ({actual[:16]}…)", file=sys.stderr)
        return 0
    print(
        "webui source changed without rebuilding dist:\n"
        f"  expected (dist): {expected}\n"
        f"  actual (source): {actual}\n"
        "  fix: cd webui && bun run build",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="write current source hash to dist")
    group.add_argument("--check", action="store_true", help="verify dist hash matches sources")
    args = parser.parse_args()
    return cmd_write() if args.write else cmd_check()


if __name__ == "__main__":
    raise SystemExit(main())
