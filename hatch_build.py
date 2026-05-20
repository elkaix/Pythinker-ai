"""Hatchling build hooks for Pythinker.

Currently provides a wheel-time WebUI freshness guard: fail the build if
``pythinker/web/dist/source-hash.txt`` doesn't match the current ``webui/``
sources. Skipped when building from an sdist (no ``webui/`` checkout).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebUIFreshnessHook(BuildHookInterface):
    PLUGIN_NAME = "webui-freshness"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:  # noqa: ARG002
        root = Path(self.root)
        webui_dir = root / "webui"
        dist_dir = root / "pythinker" / "web" / "dist"
        hash_file = dist_dir / "source-hash.txt"
        script = root / "scripts" / "webui_hash.py"

        if not webui_dir.is_dir():
            # sdist install or release tarball checkout — no sources to compare.
            return

        if not script.is_file():
            # Repo without the hash script (older checkout). Skip.
            return

        if not dist_dir.is_dir() or not hash_file.is_file():
            # No dist yet — either an editable install in CI before the WebUI
            # bundle is built, or someone running `pip install .` without first
            # running `bun run build`. This hook only catches *stale* dist; the
            # missing-bundle case is enforced separately by
            # `scripts/check_wheel_webui.py` against built wheels before publish.
            return

        # Import the hash function directly to avoid a subprocess hop.
        sys.path.insert(0, str(root / "scripts"))
        try:
            import webui_hash  # type: ignore[import-not-found]
        finally:
            sys.path.pop(0)

        expected = hash_file.read_text().strip()
        try:
            actual = webui_hash.compute_hash()
        except SystemExit as exc:
            sys.stderr.write(f"WebUIFreshnessHook: hash computation failed: {exc}\n")
            raise

        if expected != actual:
            sys.stderr.write(
                "WebUIFreshnessHook: pythinker/web/dist is stale relative to webui/ sources.\n"
                f"  expected (dist): {expected}\n"
                f"  actual (source): {actual}\n"
                "  fix: cd webui && bun run build\n"
            )
            raise SystemExit(1)
