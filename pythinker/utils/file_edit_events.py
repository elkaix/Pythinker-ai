"""File-edit activity helpers for live progress events.

Filesystem tools (``write_file``, ``edit_file``, ``notebook_edit``) execute
inside the runner and produce a single string result. The WebUI needs more
than that: a stream of ``{phase, path, added, deleted}`` events so the user
can see which file the agent is touching and how much it grew/shrank.

The helpers here are pure: snapshot a file before/after, compute line-level
added/deleted via difflib, and produce dictionary payloads ready to be
emitted by the runner. The runner owns the integration point — these helpers
intentionally don't touch the bus, channel, or any I/O beyond reading the
target file.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TRACKED_FILE_EDIT_TOOLS = frozenset({"write_file", "edit_file", "notebook_edit"})
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class FileSnapshot:
    """Read-state of a file at a single point in time."""

    path: Path
    exists: bool
    text: str | None
    unreadable: bool = False
    binary: bool = False
    oversized: bool = False

    @property
    def countable(self) -> bool:
        return (
            self.text is not None
            and not self.binary
            and not self.oversized
            and not self.unreadable
        )


@dataclass(frozen=True)
class FileEditTracker:
    """Per-call state for one file-edit tool invocation."""

    call_id: str
    tool: str
    path: Path
    display_path: str
    before: FileSnapshot


def is_file_edit_tool(tool_name: str | None) -> bool:
    return bool(tool_name) and tool_name in TRACKED_FILE_EDIT_TOOLS


def resolve_file_edit_path(
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> Path | None:
    """Resolve the target file path from tool arguments.

    Prefers the tool's own ``_resolve(path)`` helper (filesystem tools use it
    to apply workspace-confinement). Falls back to ``workspace / path`` or to
    ``Path(path).expanduser().resolve()`` when no workspace is known.
    """
    if not isinstance(params, dict):
        return None
    raw_path = params.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    resolver = getattr(tool, "_resolve", None)
    if callable(resolver):
        try:
            resolved = resolver(raw_path)
        except Exception:
            return None
        if isinstance(resolved, Path):
            return resolved
        if resolved:
            return Path(resolved)
    if workspace is None:
        return Path(raw_path).expanduser().resolve()
    return (workspace / raw_path).expanduser().resolve()


def display_file_edit_path(path: Path, workspace: Path | None) -> str:
    """Return a workspace-relative POSIX-style path for display."""
    if workspace is not None:
        try:
            return path.resolve().relative_to(workspace.resolve()).as_posix()
        except Exception:
            pass
    return path.as_posix()


def read_file_snapshot(path: Path, *, max_bytes: int = _MAX_SNAPSHOT_BYTES) -> FileSnapshot:
    try:
        if not path.exists() or not path.is_file():
            return FileSnapshot(path=path, exists=False, text="")
        size = path.stat().st_size
        if size > max_bytes:
            return FileSnapshot(path=path, exists=True, text=None, oversized=True)
        raw = path.read_bytes()
    except OSError:
        return FileSnapshot(path=path, exists=path.exists(), text=None, unreadable=True)
    if b"\x00" in raw:
        return FileSnapshot(path=path, exists=True, text=None, binary=True)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return FileSnapshot(path=path, exists=True, text=None, binary=True)
    return FileSnapshot(path=path, exists=True, text=text.replace("\r\n", "\n"))


def line_diff_stats(before: str | None, after: str | None) -> tuple[int, int]:
    """Return ``(added, deleted)`` line counts between *before* and *after*."""
    if before is None or after is None:
        return 0, 0
    if before == "":
        return _text_line_count(after), 0
    if after == "":
        return 0, _text_line_count(before)
    before_lines = before.replace("\r\n", "\n").splitlines()
    after_lines = after.replace("\r\n", "\n").splitlines()
    added = 0
    deleted = 0
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            deleted += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, deleted


def _text_line_count(text: str) -> int:
    if not text:
        return 0
    line_count = 0
    last_was_newline = False
    last_was_cr = False
    for ch in text:
        if ch == "\r":
            line_count += 1
            last_was_newline = True
            last_was_cr = True
        elif ch == "\n":
            if not last_was_cr:
                line_count += 1
            last_was_newline = True
            last_was_cr = False
        else:
            last_was_newline = False
            last_was_cr = False
    return line_count if last_was_newline else line_count + 1


def prepare_file_edit_tracker(
    *,
    call_id: str,
    tool_name: str,
    tool: Any,
    workspace: Path | None,
    params: dict[str, Any] | None,
) -> FileEditTracker | None:
    """Build a tracker for a file-edit tool call, or return ``None`` to skip.

    Returns ``None`` when the tool isn't a tracked editor, when the path
    argument is missing/empty, or when the path can't be resolved through the
    tool's own workspace-confinement helper.
    """
    if not is_file_edit_tool(tool_name):
        return None
    path = resolve_file_edit_path(tool, workspace, params)
    if path is None:
        return None
    before = read_file_snapshot(path)
    return FileEditTracker(
        call_id=str(call_id or ""),
        tool=tool_name,
        path=path,
        display_path=display_file_edit_path(path, workspace),
        before=before,
    )


def _event_payload(
    tracker: FileEditTracker,
    *,
    phase: str,
    status: str,
    added: int,
    deleted: int,
    approximate: bool,
    binary: bool = False,
) -> dict[str, Any]:
    return {
        "version": 1,
        "call_id": tracker.call_id,
        "tool": tracker.tool,
        "path": tracker.display_path,
        "phase": phase,
        "status": status,
        "added": max(0, int(added)),
        "deleted": max(0, int(deleted)),
        "approximate": bool(approximate),
        "binary": bool(binary),
    }


def build_file_edit_start_event(tracker: FileEditTracker) -> dict[str, Any]:
    """Emit a start event with placeholder zero counts.

    The exact added/deleted line counts come from the end event; the start
    event exists so the WebUI can immediately render a "writing to <path>…"
    chip without waiting for tool completion.
    """
    return _event_payload(
        tracker,
        phase="start",
        status="editing",
        added=0,
        deleted=0,
        approximate=True,
    )


def build_file_edit_end_event(tracker: FileEditTracker) -> dict[str, Any]:
    """Emit an end event with exact line-level diff stats."""
    after = read_file_snapshot(tracker.path)
    if tracker.before.countable and after.countable:
        added, deleted = line_diff_stats(tracker.before.text, after.text)
        binary = False
    else:
        added, deleted = 0, 0
        binary = (after.binary or after.oversized or after.unreadable)
    return _event_payload(
        tracker,
        phase="end",
        status="done",
        added=added,
        deleted=deleted,
        approximate=False,
        binary=binary,
    )


def build_file_edit_error_event(
    tracker: FileEditTracker,
    error: str | None = None,
) -> dict[str, Any]:
    payload = _event_payload(
        tracker,
        phase="error",
        status="error",
        added=0,
        deleted=0,
        approximate=False,
    )
    if error:
        payload["error"] = error.strip()[:240]
    return payload
