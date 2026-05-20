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
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TRACKED_FILE_EDIT_TOOLS = frozenset({"write_file", "edit_file", "notebook_edit"})
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
_LIVE_EMIT_INTERVAL_S = 0.18
_LIVE_EMIT_LINE_STEP = 24


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


def build_file_edit_live_event(
    tracker: FileEditTracker,
    *,
    added: int,
    deleted: int = 0,
) -> dict[str, Any]:
    """Build an approximate in-progress event while tool-call arguments stream."""
    return _event_payload(
        tracker,
        phase="start",
        status="editing",
        added=added,
        deleted=deleted,
        approximate=True,
    )


def build_file_edit_pending_event(
    *,
    call_id: str,
    tool_name: str,
    added: int = 0,
    deleted: int = 0,
) -> dict[str, Any]:
    """Build an early placeholder before the streamed JSON path is available."""
    return {
        "version": 1,
        "call_id": str(call_id or ""),
        "tool": tool_name,
        "path": "",
        "phase": "start",
        "status": "editing",
        "added": max(0, int(added)),
        "deleted": max(0, int(deleted)),
        "approximate": True,
        "binary": False,
        "pending": True,
    }


@dataclass
class _StreamingJsonStringField:
    """Incremental scanner for a single ``"<key>": "<value>"`` JSON field.

    Counts ``\\n``-equivalent boundaries as the value streams in, surviving
    partial ``\\uXXXX`` escapes split across chunks.
    """

    key: str
    scan_pos: int | None = None
    closed: bool = False
    escape: bool = False
    unicode_remaining: int = 0
    unicode_buffer: str = ""
    newline_count: int = 0
    has_chars: bool = False
    last_char_newline: bool = False
    last_char_cr: bool = False

    @property
    def line_count(self) -> int:
        if not self.has_chars:
            return 0
        return self.newline_count + (0 if self.last_char_newline else 1)

    def reset(self) -> None:
        self.scan_pos = None
        self.closed = False
        self.escape = False
        self.unicode_remaining = 0
        self.unicode_buffer = ""
        self.newline_count = 0
        self.has_chars = False
        self.last_char_newline = False
        self.last_char_cr = False

    def scan(self, source: str) -> None:
        if self.closed:
            return
        if self.scan_pos is None:
            match = re.search(rf'"{re.escape(self.key)}"\s*:\s*"', source)
            if match is None:
                return
            self.scan_pos = match.end()
        i = self.scan_pos
        while i < len(source):
            ch = source[i]
            if self.unicode_remaining > 0:
                self.unicode_buffer += ch
                self.unicode_remaining -= 1
                if self.unicode_remaining == 0:
                    try:
                        decoded = chr(int(self.unicode_buffer, 16))
                    except ValueError:
                        decoded = "x"
                    self.unicode_buffer = ""
                    self._mark_char(decoded)
                i += 1
                continue
            if self.escape:
                self.escape = False
                if ch == "u":
                    self.unicode_remaining = 4
                    self.unicode_buffer = ""
                elif ch == "n":
                    self._mark_char("\n")
                elif ch == "r":
                    self._mark_char("\r")
                else:
                    self._mark_char(ch)
                i += 1
                continue
            if ch == "\\":
                self.escape = True
                i += 1
                continue
            if ch == '"':
                self.closed = True
                i += 1
                break
            self._mark_char(ch)
            i += 1
        self.scan_pos = i

    def _mark_char(self, ch: str) -> None:
        self.has_chars = True
        if ch == "\r":
            self.newline_count += 1
            self.last_char_newline = True
            self.last_char_cr = True
        elif ch == "\n":
            if not self.last_char_cr:
                self.newline_count += 1
            self.last_char_newline = True
            self.last_char_cr = False
        else:
            self.last_char_newline = False
            self.last_char_cr = False


def _stream_key(payload: dict[str, Any]) -> str:
    """Derive a stable per-tool-call key from ``index`` or ``call_id``."""
    index = payload.get("index")
    if isinstance(index, int):
        return f"idx:{index}"
    if isinstance(index, str) and index:
        return f"idx:{index}"
    call_id = payload.get("call_id")
    if isinstance(call_id, str) and call_id:
        return f"id:{call_id}"
    return ""


def _extract_complete_json_string(source: str, key: str) -> str | None:
    """Return the decoded value of ``"<key>": "<value>"`` once fully closed."""
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"', source)
    if match is None:
        return None
    out: list[str] = []
    i = match.end()
    escape = False
    while i < len(source):
        ch = source[i]
        if escape:
            escape = False
            if ch == "n":
                out.append("\n")
            elif ch == "r":
                out.append("\r")
            elif ch == "t":
                out.append("\t")
            elif ch == "u":
                digits = source[i + 1:i + 5]
                if len(digits) < 4:
                    return None
                try:
                    out.append(chr(int(digits, 16)))
                except ValueError:
                    return None
                i += 4
            else:
                out.append(ch)
            i += 1
            continue
        if ch == "\\":
            escape = True
            i += 1
            continue
        if ch == '"':
            return "".join(out)
        out.append(ch)
        i += 1
    return None


@dataclass
class _StreamingFileEditState:
    """Per-tool-call accumulator: arguments, scanners, throttle bookkeeping."""

    key: str
    call_id: str = ""
    name: str = ""
    arguments: str = ""
    path: str | None = None
    tracker: FileEditTracker | None = None
    content: _StreamingJsonStringField = field(
        default_factory=lambda: _StreamingJsonStringField("content")
    )
    old_text: _StreamingJsonStringField = field(
        default_factory=lambda: _StreamingJsonStringField("old_text")
    )
    new_text: _StreamingJsonStringField = field(
        default_factory=lambda: _StreamingJsonStringField("new_text")
    )
    emitted_once: bool = False
    last_emitted_added: int = -1
    last_emitted_deleted: int = -1
    last_emit_at: float = 0.0
    pending_emitted: bool = False
    last_pending_added: int = -1
    last_pending_deleted: int = -1
    last_pending_at: float = 0.0

    def apply_delta(self, payload: dict[str, Any]) -> None:
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            self.call_id = call_id
        name = payload.get("name")
        if isinstance(name, str) and name:
            self.name = name
        args = payload.get("arguments")
        if isinstance(args, str):
            # Full arguments snapshot (some providers send cumulative state).
            self.arguments = args
            self.content.reset()
            self.old_text.reset()
            self.new_text.reset()
            return
        delta = payload.get("arguments_delta")
        if isinstance(delta, str) and delta:
            self.arguments += delta

    def live_diff_counts(self) -> tuple[int, int]:
        if self.name == "write_file":
            self.content.scan(self.arguments)
            return self.content.line_count, 0
        if self.name == "edit_file":
            self.old_text.scan(self.arguments)
            self.new_text.scan(self.arguments)
            return self.new_text.line_count, self.old_text.line_count
        return 0, 0

    def should_emit(self, added: int, deleted: int, now: float) -> bool:
        if not self.emitted_once:
            return True
        if added == self.last_emitted_added and deleted == self.last_emitted_deleted:
            return False
        if max(
            abs(added - self.last_emitted_added),
            abs(deleted - self.last_emitted_deleted),
        ) >= _LIVE_EMIT_LINE_STEP:
            return True
        return now - self.last_emit_at >= _LIVE_EMIT_INTERVAL_S

    def mark_emitted(self, added: int, deleted: int, now: float) -> None:
        self.emitted_once = True
        self.last_emitted_added = added
        self.last_emitted_deleted = deleted
        self.last_emit_at = now

    def should_emit_pending(self, added: int, deleted: int, now: float) -> bool:
        if not self.pending_emitted:
            return True
        if added == self.last_pending_added and deleted == self.last_pending_deleted:
            return False
        if max(
            abs(added - self.last_pending_added),
            abs(deleted - self.last_pending_deleted),
        ) >= _LIVE_EMIT_LINE_STEP:
            return True
        return now - self.last_pending_at >= _LIVE_EMIT_INTERVAL_S

    def mark_pending_emitted(self, added: int, deleted: int, now: float) -> None:
        self.pending_emitted = True
        self.last_pending_added = added
        self.last_pending_deleted = deleted
        self.last_pending_at = now

    def matches_final_tool_call(self, tool_call: Any) -> bool:
        call_id = getattr(tool_call, "id", None)
        canonical = self.call_id or (self.tracker.call_id if self.tracker else "")
        if isinstance(call_id, str) and call_id and canonical:
            # OpenAI Responses API encodes ``f"{call_id}|{item_id}"`` so a
            # streamed bare ``call_id`` matches the prefix of the composite id.
            head = call_id.split("|", 1)[0] if "|" in call_id else call_id
            if call_id == canonical or head == canonical:
                return True
        name = getattr(tool_call, "name", None)
        if name != self.name:
            return False
        arguments = getattr(tool_call, "arguments", None)
        if not isinstance(arguments, dict):
            return False
        path = arguments.get("path")
        if self.path is None and isinstance(path, str) and path:
            self.path = path
            return True
        return isinstance(path, str) and path == self.path


class StreamingFileEditTracker:
    """Track file-edit tool arguments while the model is still streaming them.

    Tool execution events only begin after the provider has completed the full
    function call. For large ``write_file`` calls, the long wait is usually the
    model producing the JSON ``content`` argument. Large ``edit_file`` calls
    have the same wait while ``old_text`` / ``new_text`` stream in. This
    tracker converts those argument deltas into approximate WebUI file-edit
    events before the final exact diff is available.
    """

    def __init__(
        self,
        *,
        workspace: Path | None,
        tools: Any,
        emit: Callable[[list[dict[str, Any]]], Awaitable[None]],
    ) -> None:
        self._workspace = workspace
        self._tools = tools
        self._emit = emit
        self._states: dict[str, _StreamingFileEditState] = {}

    async def update(self, payload: dict[str, Any]) -> None:
        key = _stream_key(payload)
        if not key:
            return
        state = self._states.get(key)
        if state is None:
            state = _StreamingFileEditState(key=key)
            self._states[key] = state

        state.apply_delta(payload)
        if state.name not in {"write_file", "edit_file"}:
            return
        if state.path is None:
            state.path = _extract_complete_json_string(state.arguments, "path")
        if state.path is None:
            added, deleted = state.live_diff_counts()
            now = time.monotonic()
            if state.should_emit_pending(added, deleted, now):
                state.mark_pending_emitted(added, deleted, now)
                await self._emit([build_file_edit_pending_event(
                    call_id=state.call_id or state.key,
                    tool_name=state.name,
                    added=added,
                    deleted=deleted,
                )])
            return
        if state.tracker is None:
            tool = self._tools.get(state.name) if hasattr(self._tools, "get") else None
            state.tracker = prepare_file_edit_tracker(
                call_id=state.call_id or state.key,
                tool_name=state.name,
                tool=tool,
                workspace=self._workspace,
                params={"path": state.path},
            )
            if state.tracker is None:
                return

        added, deleted = state.live_diff_counts()
        now = time.monotonic()
        if not state.should_emit(added, deleted, now):
            return
        state.mark_emitted(added, deleted, now)
        await self._emit([build_file_edit_live_event(
            state.tracker,
            added=added,
            deleted=deleted,
        )])

    async def flush(self) -> None:
        """Emit a final live event for any state whose counts changed since last emit."""
        events: list[dict[str, Any]] = []
        now = time.monotonic()
        for state in self._states.values():
            if state.tracker is None:
                continue
            added, deleted = state.live_diff_counts()
            if (
                state.emitted_once
                and state.last_emitted_added == added
                and state.last_emitted_deleted == deleted
            ):
                continue
            state.mark_emitted(added, deleted, now)
            events.append(build_file_edit_live_event(
                state.tracker,
                added=added,
                deleted=deleted,
            ))
        if events:
            await self._emit(events)

    def apply_final_call_ids(self, final_tool_calls: list[Any]) -> None:
        """Retrofit canonical call_ids onto final tool_calls so synchronous start/end
        events match call_ids the WebUI already received via live events.

        Preserves the OpenAI Responses-API composite ``"call_id|item_id"``
        form when present: the converter at
        ``openai_responses/converters.py:38`` splits that on ``|`` to round-trip
        the assistant message back into the next-turn ``function_call`` item.
        Overwriting the composite with a bare call_id silently loses the
        ``item_id`` half and breaks multi-turn flows.
        """
        for tool_call in final_tool_calls:
            canonical = self.canonical_call_id_for(tool_call)
            if not canonical:
                continue
            try:
                existing = str(getattr(tool_call, "id", "") or "")
                if "|" in existing:
                    _, item_id = existing.split("|", 1)
                    tool_call.id = f"{canonical}|{item_id}" if item_id else canonical
                else:
                    tool_call.id = canonical
            except Exception:
                pass

    def canonical_call_id_for(self, tool_call: Any) -> str | None:
        for state in self._states.values():
            if state.matches_final_tool_call(tool_call):
                return (
                    state.call_id
                    or (state.tracker.call_id if state.tracker else None)
                    or state.key
                )
        return None

    async def error_unmatched(
        self,
        final_tool_calls: list[Any],
        error: str,
    ) -> None:
        """Emit error events for streamed edits the final response dropped."""
        events: list[dict[str, Any]] = []
        for state in self._states.values():
            if state.tracker is None:
                continue
            if any(state.matches_final_tool_call(tc) for tc in final_tool_calls):
                continue
            events.append(build_file_edit_error_event(state.tracker, error))
        if events:
            await self._emit(events)

    def seen_canonical_call_ids(self) -> set[str]:
        """Return the set of canonical call_ids the tracker has emitted under.

        Runner uses this to skip the synchronous ``start`` event for calls
        already announced via live events — otherwise its ``added=0/deleted=0``
        would overwrite the live counts on the WebUI side.
        """
        out: set[str] = set()
        for state in self._states.values():
            if state.tracker is None:
                continue
            cid = state.tracker.call_id or state.call_id
            if cid:
                out.add(cid)
        return out
