"""Tests for the file-edit activity helpers."""

from __future__ import annotations

from pathlib import Path

from pythinker.utils.file_edit_events import (
    FileSnapshot,
    build_file_edit_end_event,
    build_file_edit_error_event,
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
