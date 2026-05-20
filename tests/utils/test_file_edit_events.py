"""Tests for the file-edit activity helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pythinker.utils.file_edit_events import (
    FileSnapshot,
    StreamingFileEditTracker,
    _extract_complete_json_string,
    _stream_key,
    _StreamingFileEditState,
    _StreamingJsonStringField,
    build_file_edit_end_event,
    build_file_edit_error_event,
    build_file_edit_pending_event,
    build_file_edit_start_event,
    display_file_edit_path,
    is_file_edit_tool,
    line_diff_stats,
    prepare_file_edit_tracker,
    read_file_snapshot,
    resolve_file_edit_path,
)


def test_is_file_edit_tool_recognizes_tracked_set() -> None:
    assert is_file_edit_tool("write_file") is True
    assert is_file_edit_tool("edit_file") is True
    assert is_file_edit_tool("notebook_edit") is True
    assert is_file_edit_tool("read_file") is False
    assert is_file_edit_tool(None) is False


def test_resolve_file_edit_path_uses_tool_resolve_helper(tmp_path: Path) -> None:
    class _FakeTool:
        def _resolve(self, path: str) -> Path:
            return tmp_path / path

    resolved = resolve_file_edit_path(_FakeTool(), tmp_path, {"path": "x/y.py"})
    assert resolved == tmp_path / "x/y.py"


def test_resolve_file_edit_path_falls_back_to_workspace_join(tmp_path: Path) -> None:
    resolved = resolve_file_edit_path(object(), tmp_path, {"path": "x.py"})
    assert resolved == (tmp_path / "x.py")


def test_resolve_file_edit_path_returns_none_for_missing_path() -> None:
    assert resolve_file_edit_path(object(), None, {}) is None
    assert resolve_file_edit_path(object(), None, {"path": ""}) is None
    assert resolve_file_edit_path(object(), None, {"path": "   "}) is None


def test_display_file_edit_path_relative_to_workspace(tmp_path: Path) -> None:
    path = tmp_path / "pkg" / "mod.py"
    assert display_file_edit_path(path, tmp_path) == "pkg/mod.py"


def test_display_file_edit_path_falls_back_to_absolute_when_outside(tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere.py"
    rendered = display_file_edit_path(outside, tmp_path)
    assert rendered.endswith("elsewhere.py")


def test_read_file_snapshot_missing_returns_empty_text(tmp_path: Path) -> None:
    snap = read_file_snapshot(tmp_path / "no-such-file.py")
    assert snap.exists is False
    assert snap.text == ""
    assert snap.countable is True


def test_read_file_snapshot_binary_marks_binary(tmp_path: Path) -> None:
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02")
    snap = read_file_snapshot(binary)
    assert snap.binary is True
    assert snap.text is None
    assert snap.countable is False


def test_read_file_snapshot_oversized_marks_oversized(tmp_path: Path) -> None:
    big = tmp_path / "big.txt"
    big.write_text("x" * 32, encoding="utf-8")
    snap = read_file_snapshot(big, max_bytes=8)
    assert snap.oversized is True
    assert snap.countable is False


def test_read_file_snapshot_normalizes_crlf(tmp_path: Path) -> None:
    p = tmp_path / "win.txt"
    p.write_bytes(b"alpha\r\nbeta\r\n")
    snap = read_file_snapshot(p)
    assert snap.text == "alpha\nbeta\n"


def test_line_diff_stats_pure_addition() -> None:
    added, deleted = line_diff_stats("", "one\ntwo\nthree\n")
    assert added == 3
    assert deleted == 0


def test_line_diff_stats_pure_deletion() -> None:
    added, deleted = line_diff_stats("one\ntwo\nthree\n", "")
    assert added == 0
    assert deleted == 3


def test_line_diff_stats_replace_in_middle() -> None:
    added, deleted = line_diff_stats("a\nb\nc\n", "a\nB\nc\n")
    assert added == 1
    assert deleted == 1


def test_line_diff_stats_none_inputs_are_zero() -> None:
    assert line_diff_stats(None, "x") == (0, 0)
    assert line_diff_stats("x", None) == (0, 0)


def test_prepare_file_edit_tracker_unrecognized_tool_returns_none(tmp_path: Path) -> None:
    tracker = prepare_file_edit_tracker(
        call_id="c1",
        tool_name="read_file",
        tool=object(),
        workspace=tmp_path,
        params={"path": "a.py"},
    )
    assert tracker is None


def test_prepare_file_edit_tracker_captures_before_snapshot(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")

    class _Tool:
        def _resolve(self, path: str) -> Path:
            return tmp_path / path

    tracker = prepare_file_edit_tracker(
        call_id="c1",
        tool_name="write_file",
        tool=_Tool(),
        workspace=tmp_path,
        params={"path": "a.py"},
    )
    assert tracker is not None
    assert tracker.tool == "write_file"
    assert tracker.display_path == "a.py"
    assert tracker.before.text == "hello\n"


def test_build_start_event_emits_zero_counts(tmp_path: Path) -> None:
    snapshot = FileSnapshot(path=tmp_path / "a", exists=False, text="")
    from dataclasses import replace as _replace  # noqa: F401  (ensure dataclass import works)

    from pythinker.utils.file_edit_events import FileEditTracker

    tracker = FileEditTracker(
        call_id="c1",
        tool="write_file",
        path=tmp_path / "a",
        display_path="a",
        before=snapshot,
    )
    event = build_file_edit_start_event(tracker)
    assert event["phase"] == "start"
    assert event["status"] == "editing"
    assert event["added"] == 0
    assert event["deleted"] == 0
    assert event["approximate"] is True
    assert event["tool"] == "write_file"
    assert event["call_id"] == "c1"


def test_build_end_event_computes_real_diff(tmp_path: Path) -> None:
    file = tmp_path / "code.py"
    file.write_text("a\nb\nc\n", encoding="utf-8")

    from pythinker.utils.file_edit_events import FileEditTracker

    before = read_file_snapshot(file)
    file.write_text("a\nB\nc\nd\n", encoding="utf-8")  # 1 replace + 1 insert

    tracker = FileEditTracker(
        call_id="c1",
        tool="edit_file",
        path=file,
        display_path="code.py",
        before=before,
    )
    event = build_file_edit_end_event(tracker)
    assert event["phase"] == "end"
    assert event["status"] == "done"
    assert event["added"] == 2
    assert event["deleted"] == 1
    assert event["approximate"] is False
    assert event["binary"] is False


def test_build_error_event_truncates_long_messages(tmp_path: Path) -> None:
    from pythinker.utils.file_edit_events import FileEditTracker

    tracker = FileEditTracker(
        call_id="c1",
        tool="write_file",
        path=tmp_path / "a",
        display_path="a",
        before=FileSnapshot(path=tmp_path / "a", exists=False, text=""),
    )
    long_err = "x" * 1000
    event = build_file_edit_error_event(tracker, long_err)
    assert event["phase"] == "error"
    assert event["status"] == "error"
    assert len(event["error"]) <= 240


# ---------------------------------------------------------------------------
# Streaming tracker (Phase 2)
# ---------------------------------------------------------------------------


@dataclass
class _FinalToolCall:
    """Minimal stand-in for ``ToolCallRequest`` used by the streaming tracker."""

    id: str
    name: str
    arguments: dict[str, Any]


class _ToolRegistryStub:
    """Mimic ``ToolRegistry.get(name)`` returning a workspace-aware resolver."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def get(self, _name: str) -> "_ToolRegistryStub":
        return self

    def _resolve(self, path: str) -> Path:
        return self._workspace / path


async def _drain(tracker: StreamingFileEditTracker, payloads: list[dict[str, Any]]) -> None:
    for p in payloads:
        await tracker.update(p)


def test_stream_key_prefers_index_over_call_id() -> None:
    assert _stream_key({"index": 0, "call_id": "x"}) == "idx:0"
    assert _stream_key({"index": "tc1"}) == "idx:tc1"
    assert _stream_key({"call_id": "abc"}) == "id:abc"
    assert _stream_key({}) == ""


def test_extract_complete_json_string_handles_escapes() -> None:
    assert _extract_complete_json_string('{"path": "a/b.py"}', "path") == "a/b.py"
    assert (
        _extract_complete_json_string(r'{"path": "a\nbA", "x": 1}', "path") == "a\nbA"
    )
    # Unterminated string returns None.
    assert _extract_complete_json_string('{"path": "incomplete', "path") is None


def test_json_string_field_counts_lines_across_chunks() -> None:
    # The scanner expects the cumulative argument buffer each call and resumes
    # from ``scan_pos``; mirrors how _StreamingFileEditState passes ``arguments``.
    field_obj = _StreamingJsonStringField("content")
    acc = '{"content": "alpha\\n'
    field_obj.scan(acc)
    # "alpha\n" → one full line ended.
    assert field_obj.line_count == 1
    # Split a \uXXXX escape across two scan() calls; the four hex digits 000A
    # decode to a newline character.
    acc += "beta\\u"
    field_obj.scan(acc)
    acc += "000A"
    field_obj.scan(acc)
    assert field_obj.line_count == 2
    acc += 'end"'
    field_obj.scan(acc)
    assert field_obj.closed is True
    # "alpha\n", "beta\n", "end" → 3 lines (final has no trailing newline → +1).
    assert field_obj.line_count == 3


def test_json_string_field_handles_carriage_return_pair() -> None:
    field_obj = _StreamingJsonStringField("content")
    acc = r'{"content": "a\r'
    field_obj.scan(acc)
    acc += r'\nb"'
    field_obj.scan(acc)
    # \r\n collapses to a single newline boundary; "a", "b" → 2 lines.
    assert field_obj.line_count == 2


def test_streaming_state_apply_delta_full_arguments_resets_scanners() -> None:
    state = _StreamingFileEditState(key="idx:0", name="write_file")
    state.apply_delta({"arguments_delta": '{"content": "x\\n'})
    state.live_diff_counts()
    assert state.content.has_chars is True
    state.apply_delta({"arguments": '{"content": "y'})
    # Full snapshot replaces accumulated args and resets scanner state.
    assert state.arguments == '{"content": "y'
    assert state.content.has_chars is False


def test_pending_event_shape() -> None:
    ev = build_file_edit_pending_event(
        call_id="call_42", tool_name="write_file", added=3, deleted=0
    )
    assert ev == {
        "version": 1,
        "call_id": "call_42",
        "tool": "write_file",
        "path": "",
        "phase": "start",
        "status": "editing",
        "added": 3,
        "deleted": 0,
        "approximate": True,
        "binary": False,
        "pending": True,
    }


async def test_tracker_emits_pending_then_live(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []

    async def emit(events: list[dict[str, Any]]) -> None:
        captured.extend(events)

    tracker = StreamingFileEditTracker(
        workspace=tmp_path, tools=_ToolRegistryStub(tmp_path), emit=emit,
    )

    # First delta: name + call_id arrive, but no path yet.
    await tracker.update({
        "index": 0, "call_id": "call_a", "name": "write_file", "arguments_delta": "",
    })
    # Second delta: content streaming, still no path.
    await tracker.update({
        "index": 0, "call_id": "", "name": "", "arguments_delta": '{"content": "alpha\\n',
    })
    assert any(ev.get("pending") for ev in captured), captured
    pending_count = sum(1 for ev in captured if ev.get("pending"))

    # Now the path arrives in the JSON.
    await tracker.update({
        "index": 0, "call_id": "", "name": "",
        "arguments_delta": 'beta\\ngamma", "path": "out.txt"}',
    })
    live = [ev for ev in captured if not ev.get("pending")]
    assert live, "expected at least one live event after path resolves"
    last = live[-1]
    assert last["phase"] == "start"
    assert last["approximate"] is True
    assert last["path"] == "out.txt"
    assert last["call_id"] == "call_a"
    assert last["added"] >= 3
    # canonical_call_id_for now recognises this state.
    canonical = tracker.canonical_call_id_for(
        _FinalToolCall(id="call_a", name="write_file", arguments={"path": "out.txt"})
    )
    assert canonical == "call_a"
    assert "call_a" in tracker.seen_canonical_call_ids()
    assert pending_count >= 1


async def test_tracker_throttles_bursts(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []

    async def emit(events: list[dict[str, Any]]) -> None:
        captured.extend(events)

    tracker = StreamingFileEditTracker(
        workspace=tmp_path, tools=_ToolRegistryStub(tmp_path), emit=emit,
    )
    # Seed name + path so we go straight into the live branch.
    await tracker.update({
        "index": 0, "call_id": "call_b", "name": "write_file",
        "arguments_delta": '{"path": "out.txt", "content": "',
    })
    captured.clear()
    # 100 single-character deltas (each adds < 24 lines and well under 180 ms).
    for _ in range(100):
        await tracker.update({"index": 0, "arguments_delta": "x"})
    # Throttle should collapse the burst into nothing (no line growth).
    assert captured == []
    # A delta that adds 24+ lines must emit.
    await tracker.update({"index": 0, "arguments_delta": "\\n" * 30})
    assert len(captured) == 1


async def test_tracker_flush_emits_final_delta(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []

    async def emit(events: list[dict[str, Any]]) -> None:
        captured.extend(events)

    tracker = StreamingFileEditTracker(
        workspace=tmp_path, tools=_ToolRegistryStub(tmp_path), emit=emit,
    )
    await tracker.update({
        "index": 0, "call_id": "call_c", "name": "write_file",
        "arguments_delta": '{"path": "f.txt", "content": "a\\n',
    })
    captured.clear()
    # Below the throttle threshold; should not emit on update().
    await tracker.update({"index": 0, "arguments_delta": "b"})
    assert captured == []
    # flush() forces a final live event because counts changed since last emit.
    await tracker.flush()
    assert len(captured) == 1
    assert captured[0]["phase"] == "start"
    assert captured[0]["approximate"] is True
    # Calling flush() again with no further deltas is a no-op.
    captured.clear()
    await tracker.flush()
    assert captured == []


async def test_apply_final_call_ids_retrofits_id(tmp_path: Path) -> None:
    async def emit(_events: list[dict[str, Any]]) -> None:
        return

    tracker = StreamingFileEditTracker(
        workspace=tmp_path, tools=_ToolRegistryStub(tmp_path), emit=emit,
    )
    await tracker.update({
        "index": 0, "call_id": "stream_id", "name": "write_file",
        "arguments_delta": '{"path": "f.txt", "content": "x"}',
    })
    # Final tool_call carries a DIFFERENT id (e.g. provider re-assigned it).
    tc = _FinalToolCall(id="other", name="write_file", arguments={"path": "f.txt"})
    tracker.apply_final_call_ids([tc])
    assert tc.id == "stream_id"


async def test_apply_final_call_ids_preserves_responses_composite(
    tmp_path: Path,
) -> None:
    """OpenAI Responses encodes ``"call_id|item_id"`` — must round-trip cleanly.

    Regression: a bare overwrite would lose the ``item_id`` half, and the next
    turn's ``function_call`` item would carry a synthetic ``f"fc_{idx}"``
    instead of the model's actual id.
    """

    async def emit(_events: list[dict[str, Any]]) -> None:
        return

    tracker = StreamingFileEditTracker(
        workspace=tmp_path, tools=_ToolRegistryStub(tmp_path), emit=emit,
    )
    # Live events arrive with the bare call_id (Responses streaming surface).
    await tracker.update({
        "index": 0, "call_id": "resp_abc", "name": "write_file",
        "arguments_delta": '{"path": "f.txt", "content": "x"}',
    })
    # The final response object carries the composite form.
    tc = _FinalToolCall(
        id="resp_abc|fc_77", name="write_file", arguments={"path": "f.txt"},
    )
    tracker.apply_final_call_ids([tc])
    assert tc.id == "resp_abc|fc_77"
    # And seen_canonical_call_ids exposes only the bare id (what live events
    # used as their WebUI merge key).
    assert tracker.seen_canonical_call_ids() == {"resp_abc"}


async def test_error_unmatched_marks_dropped_calls(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []

    async def emit(events: list[dict[str, Any]]) -> None:
        captured.extend(events)

    tracker = StreamingFileEditTracker(
        workspace=tmp_path, tools=_ToolRegistryStub(tmp_path), emit=emit,
    )
    await tracker.update({
        "index": 0, "call_id": "call_a", "name": "write_file",
        "arguments_delta": '{"path": "a.txt", "content": "x"}',
    })
    await tracker.update({
        "index": 1, "call_id": "call_b", "name": "write_file",
        "arguments_delta": '{"path": "b.txt", "content": "x"}',
    })
    captured.clear()
    # Final response kept only call_a; call_b should fire an error event.
    kept = _FinalToolCall(id="call_a", name="write_file", arguments={"path": "a.txt"})
    await tracker.error_unmatched([kept], "Tool call did not complete.")
    assert len(captured) == 1
    ev = captured[0]
    assert ev["phase"] == "error"
    assert ev["status"] == "error"
    assert ev["call_id"] == "call_b"
    assert ev["error"] == "Tool call did not complete."
