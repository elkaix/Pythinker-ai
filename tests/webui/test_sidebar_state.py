"""Tests for ``pythinker.webui.sidebar_state``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pythinker.webui import sidebar_state as ss


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``get_data_dir`` at *tmp_path* so writes never touch the host."""
    monkeypatch.setattr(
        "pythinker.config.paths.get_data_dir",
        lambda: tmp_path,
    )
    return tmp_path


def test_default_state_carries_schema_and_view_defaults() -> None:
    state = ss.default_webui_sidebar_state()
    assert state["schema_version"] == ss.WEBUI_SIDEBAR_STATE_SCHEMA_VERSION
    assert state["pinned_keys"] == []
    assert state["view"] == {
        "density": "comfortable",
        "show_previews": False,
        "show_timestamps": False,
        "show_archived": False,
        "sort": "updated_desc",
    }


def test_read_returns_default_when_file_absent() -> None:
    state = ss.read_webui_sidebar_state()
    assert state == ss.default_webui_sidebar_state()


def test_write_then_read_roundtrips() -> None:
    written = ss.write_webui_sidebar_state({
        "pinned_keys": ["websocket:abc"],
        "archived_keys": ["websocket:def"],
        "title_overrides": {"websocket:abc": "Custom title"},
        "tags_by_key": {"websocket:abc": ["work", "important"]},
        "collapsed_groups": {"yesterday": True},
        "view": {"density": "compact", "sort": "title_asc"},
    })

    assert written["pinned_keys"] == ["websocket:abc"]
    assert written["updated_at"] is not None  # always set on write

    re_read = ss.read_webui_sidebar_state()
    assert re_read["pinned_keys"] == ["websocket:abc"]
    assert re_read["title_overrides"] == {"websocket:abc": "Custom title"}
    assert re_read["tags_by_key"] == {"websocket:abc": ["work", "important"]}
    assert re_read["collapsed_groups"] == {"yesterday": True}
    assert re_read["view"]["density"] == "compact"
    assert re_read["view"]["sort"] == "title_asc"


def test_normalize_drops_invalid_view_density_and_sort() -> None:
    state = ss.normalize_webui_sidebar_state({
        "view": {"density": "ginormous", "sort": "by-vibes"},
    })
    assert state["view"]["density"] == "comfortable"
    assert state["view"]["sort"] == "updated_desc"


def test_normalize_drops_duplicate_pinned_keys() -> None:
    state = ss.normalize_webui_sidebar_state({
        "pinned_keys": ["a", "a", "b", "", None, "  ", "a"],
    })
    assert state["pinned_keys"] == ["a", "b"]


def test_normalize_truncates_title_overrides_over_max_len() -> None:
    long_title = "T" * 500
    state = ss.normalize_webui_sidebar_state({
        "title_overrides": {"k": long_title},
    })
    assert len(state["title_overrides"]["k"]) == 160


def test_normalize_caps_tags_per_key() -> None:
    state = ss.normalize_webui_sidebar_state({
        "tags_by_key": {"k": [f"tag-{i}" for i in range(30)]},
    })
    assert len(state["tags_by_key"]["k"]) == 12  # _MAX_TAGS_PER_KEY


def test_normalize_drops_non_dict_input() -> None:
    state = ss.normalize_webui_sidebar_state("not a dict")
    assert state == ss.default_webui_sidebar_state()


def test_write_rejects_oversized_state(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the cap to a small value so we don't have to construct 256 KiB of data.
    monkeypatch.setattr(ss, "_MAX_STATE_FILE_BYTES", 64)
    with pytest.raises(ValueError, match="too large"):
        ss.write_webui_sidebar_state({
            "pinned_keys": [f"long-key-{i}" for i in range(200)],
        })


def test_oversized_existing_file_is_ignored(tmp_path: Path) -> None:
    path = ss.webui_sidebar_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pinned_keys": ["x"], "padding": "y" * 300_000}))
    state = ss.read_webui_sidebar_state()
    # Oversized file → fall back to defaults.
    assert state == ss.default_webui_sidebar_state()


def test_atomic_write_creates_no_tmp_residue(tmp_path: Path) -> None:
    ss.write_webui_sidebar_state({"pinned_keys": ["a"]})
    path = ss.webui_sidebar_state_path()
    tmp_residue = path.with_suffix(".json.tmp")
    assert not tmp_residue.exists()
