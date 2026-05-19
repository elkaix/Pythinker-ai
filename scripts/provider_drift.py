#!/usr/bin/env python3
"""Detect drift in provider model catalogs.

Fetches the list-models endpoint of each enabled provider, diffs against the
committed snapshot under `tests/snapshots/provider-models/<provider>.json`,
and writes an updated snapshot only when `--write` is passed.

Designed for the scheduled `provider-smoke` workflow: in CI it runs in
`--check` mode and exits non-zero on drift (so the workflow can open an
issue). Locally you can run `--write` to refresh the snapshot.

Auth is via env vars: skips a provider silently if its key is unset, so the
script is safe to run on forks without secrets.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO_ROOT / "tests" / "snapshots" / "provider-models"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def fetch_openai() -> list[str] | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    r = httpx.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return sorted({item["id"] for item in r.json().get("data", [])})


def fetch_anthropic() -> list[str] | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    r = httpx.get(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return sorted({item["id"] for item in r.json().get("data", [])})


PROVIDERS: dict[str, Callable[[], list[str] | None]] = {
    "openai": fetch_openai,
    "anthropic": fetch_anthropic,
}


def load_snapshot(provider: str) -> list[str] | None:
    path = SNAPSHOT_DIR / f"{provider}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())["models"]


def write_snapshot(provider: str, models: list[str]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{provider}.json"
    path.write_text(json.dumps({"models": models}, indent=2) + "\n")


def diff(prev: list[str] | None, current: list[str]) -> tuple[list[str], list[str]]:
    prev_set = set(prev or [])
    curr_set = set(current)
    added = sorted(curr_set - prev_set)
    removed = sorted(prev_set - curr_set)
    return added, removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="overwrite snapshots with fresh data")
    parser.add_argument("--check", action="store_true", help="exit 1 on any drift")
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDERS),
        help="limit to a single provider (default: all available)",
    )
    args = parser.parse_args()
    if not (args.write or args.check):
        parser.error("one of --write / --check is required")

    selected = [args.provider] if args.provider else list(PROVIDERS)
    overall_drift = False
    overall_error = False
    summary: dict[str, dict[str, Any]] = {}

    for provider in selected:
        fetcher = PROVIDERS[provider]
        try:
            current = fetcher()
        except httpx.HTTPError as exc:
            print(f"{provider}: fetch failed ({exc!r})", file=sys.stderr)
            summary[provider] = {"added": [], "removed": [], "error": repr(exc)}
            overall_error = True
            continue
        if current is None:
            print(f"{provider}: no credential in env — skipping", file=sys.stderr)
            continue

        prev = load_snapshot(provider)
        added, removed = diff(prev, current)
        summary[provider] = {"added": added, "removed": removed}

        if args.write:
            write_snapshot(provider, current)
            print(
                f"{provider}: wrote {len(current)} models (+{len(added)} / -{len(removed)})",
                file=sys.stderr,
            )
            continue

        if prev is None:
            print(f"{provider}: no baseline snapshot — run with --write first", file=sys.stderr)
            overall_drift = True
            continue
        if added or removed:
            overall_drift = True
            print(
                f"{provider}: drift detected (+{len(added)} / -{len(removed)})",
                file=sys.stderr,
            )

    # Emit machine-readable summary to stdout for the workflow to consume.
    print(json.dumps(summary, indent=2))
    if overall_error:
        return 1
    if args.check and overall_drift:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
