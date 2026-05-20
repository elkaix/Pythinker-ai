"""Tests for ``pythinker.webui.activity_transcript``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pythinker.webui import activity_transcript as at


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``get_data_dir`` at *tmp_path* so writes never touch the host."""
    monkeypatch.setattr(
        "pythinker.config.paths.get_data_dir",
        lambda: tmp_path,
    )
    return tmp_path


def _file_activity_payload(call_id: str = "call-1", *, path: str = "out.txt") -> dict:
    return {
        "version": 1,
        "call_id": call_id,
        "tool": "write_file",
        "path": path,
        "phase": "end",
        "status": "done",
        "added": 12,
        "deleted": 3,
        "approximate": False,
        "binary": False,
    }


def test_path_helper_rejects_invalid_chat_id() -> None:
    assert at.webui_activity_transcript_path("") is None
    assert at.webui_activity_transcript_path("has space") is None
    assert at.webui_activity_transcript_path("a" * 100) is None
    # Slashes and dots would let a caller escape the activity dir.
    assert at.webui_activity_transcript_path("../etc/passwd") is None
    assert at.webui_activity_transcript_path("ws/abc") is None


def test_path_helper_maps_colon_to_double_underscore() -> None:
    path = at.webui_activity_transcript_path("websocket:abc-123")
    assert path is not None
    assert path.name == "websocket__abc-123.jsonl"
    # Sits under the webui activity directory, not at the data-dir root.
    assert path.parent.name == "activity"


def test_append_then_read_roundtrips_file_activity() -> None:
    cid = "websocket:abc"
    assert at.append_webui_activity(cid, "file_activity", _file_activity_payload())
    events = at.read_webui_activity_transcript(cid)
    assert len(events) == 1
    rec = events[0]
    assert rec["kind"] == "file_activity"
    assert rec["v"] == at.WEBUI_ACTIVITY_TRANSCRIPT_SCHEMA_VERSION
    assert rec["ts"]  # ISO timestamp present
    assert rec["activity"]["call_id"] == "call-1"
    assert rec["activity"]["added"] == 12


def test_append_provider_failover_and_turn_boundary_preserve_order() -> None:
    cid = "websocket:abc"
    assert at.append_webui_activity(cid, "file_activity", _file_activity_payload("c1"))
    assert at.append_webui_activity(
        cid,
        "provider_failover",
        {"version": 1, "primary": "openai/gpt-5", "fallback": "anth/sonnet", "reason": "429"},
    )
    assert at.append_webui_activity(cid, "turn_boundary")
    assert at.append_webui_activity(cid, "file_activity", _file_activity_payload("c2"))

    events = at.read_webui_activity_transcript(cid)
    kinds = [e["kind"] for e in events]
    assert kinds == ["file_activity", "provider_failover", "turn_boundary", "file_activity"]
    assert events[1]["info"]["primary"] == "openai/gpt-5"
    # turn_boundary carries no payload — no spurious keys.
    assert "activity" not in events[2]
    assert "info" not in events[2]


def test_append_rejects_unknown_kind_and_returns_false() -> None:
    assert at.append_webui_activity("websocket:abc", "rogue_event", {"x": 1}) is False
    assert at.read_webui_activity_transcript("websocket:abc") == []


def test_append_rejects_invalid_chat_id_silently() -> None:
    assert at.append_webui_activity("..", "file_activity", _file_activity_payload()) is False
    # No file should have been created at the activity dir.
    assert not at.webui_activity_dir().exists() or not any(
        at.webui_activity_dir().iterdir()
    )


def test_read_returns_empty_for_unknown_chat_or_missing_file() -> None:
    assert at.read_webui_activity_transcript("websocket:never-seen") == []
    assert at.read_webui_activity_transcript("invalid id") == []


def test_read_caps_to_max_events_returning_most_recent() -> None:
    cid = "websocket:abc"
    for i in range(120):
        at.append_webui_activity(
            cid, "file_activity", _file_activity_payload(f"c{i}")
        )
    events = at.read_webui_activity_transcript(cid, max_events=10)
    assert len(events) == 10
    # We get the last 10 in append order.
    assert [e["activity"]["call_id"] for e in events] == [f"c{i}" for i in range(110, 120)]


def test_read_skips_malformed_lines(tmp_path: Path) -> None:
    cid = "websocket:abc"
    at.append_webui_activity(cid, "file_activity", _file_activity_payload("c1"))
    path = at.webui_activity_transcript_path(cid)
    assert path is not None
    # Inject a bad line between two good ones.
    with open(path, "ab") as f:
        f.write(b"this is not json\n")
    at.append_webui_activity(cid, "file_activity", _file_activity_payload("c2"))
    events = at.read_webui_activity_transcript(cid)
    call_ids = [e["activity"]["call_id"] for e in events]
    assert call_ids == ["c1", "c2"]


def test_append_trims_file_when_cap_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    # Shrink the cap so the test stays fast; the trim logic is identical.
    monkeypatch.setattr(at, "_MAX_FILE_BYTES", 4 * 1024)
    monkeypatch.setattr(at, "_TRIM_TARGET_BYTES", 2 * 1024)
    cid = "websocket:abc"
    for i in range(200):
        at.append_webui_activity(
            cid, "file_activity", _file_activity_payload(f"c{i:03d}")
        )
    path = at.webui_activity_transcript_path(cid)
    assert path is not None
    size = path.stat().st_size
    assert size <= at._MAX_FILE_BYTES, size

    events = at.read_webui_activity_transcript(cid, max_events=500)
    # The oldest events were dropped by trim; the most recent are preserved.
    last_call_id = events[-1]["activity"]["call_id"]
    assert last_call_id == "c199"
    # All surviving records still parse cleanly (line boundary preserved).
    for rec in events:
        assert rec["kind"] == "file_activity"
        assert "call_id" in rec["activity"]


def test_clear_removes_transcript_file() -> None:
    cid = "websocket:abc"
    at.append_webui_activity(cid, "file_activity", _file_activity_payload())
    assert at.clear_webui_activity_transcript(cid) is True
    assert at.read_webui_activity_transcript(cid) == []
    # Idempotent: clearing again is a no-op.
    assert at.clear_webui_activity_transcript(cid) is False


def test_encoded_line_is_valid_jsonl() -> None:
    """Sanity check: the bytes written are valid JSON-per-line."""
    cid = "websocket:abc"
    at.append_webui_activity(cid, "file_activity", _file_activity_payload())
    at.append_webui_activity(cid, "turn_boundary")
    path = at.webui_activity_transcript_path(cid)
    assert path is not None
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        record = json.loads(line)
        assert record["v"] == 1
        assert record["kind"] in {"file_activity", "turn_boundary"}
