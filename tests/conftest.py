"""Shared fixtures for all Pythinker tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pythinker.cli.onboard import _BACK_PRESSED


@pytest.fixture(scope="session", autouse=True)
def isolate_git_config_for_tests(tmp_path_factory):
    """Keep throwaway test repos from inheriting host git signing policy.

    Some remote execution environments force commit or tag signing through global,
    system, or injected git config. Tests create temporary repos and make disposable
    commits, so those repos should use a clean git configuration regardless of the
    host running the suite.
    """
    empty_config = tmp_path_factory.mktemp("git-config") / "config"
    empty_config.write_text("", encoding="utf-8")
    xdg_config_home = tmp_path_factory.mktemp("xdg-config")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    for key in list(os.environ):
        if key == "GIT_CONFIG_COUNT" or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            monkeypatch.delenv(key, raising=False)

    yield

    monkeypatch.undo()


@pytest.fixture
def make_fake_select():
    """Factory: returns a _select_with_back stand-in that consumes a token list.

    Tokens:
      - "first" → first non-action choice in the list (skips bracketed actions
                  like "[Done]")
      - "done"  → "[Done]" (the commit sentinel used by _configure_pydantic_model)
      - "back"  → _BACK_PRESSED
      - "back-exit" → "<- Back" (the loop-exit string used in section pickers)
      - any other string → returned as-is (use this to pick a specific label)
    """

    def _factory(tokens):
        sequence = iter(tokens)

        def _fake(_prompt, choices, default=None):
            token = next(sequence)
            if token == "first":
                return next(c for c in choices if not c.strip().startswith("["))
            if token == "done":
                return "[Done]"
            if token == "back":
                return _BACK_PRESSED
            if token == "back-exit":
                return "<- Back"
            return token

        return _fake

    return _factory


@pytest.fixture(scope="module")
def browser_http_fixture():
    """Module-scoped: serves tests/fixtures/browser/ over HTTP on 0.0.0.0:<port>."""
    from tests.fixtures.browser.server import serve

    fixture_dir = Path(__file__).parent / "fixtures" / "browser"
    yield from serve(fixture_dir)
