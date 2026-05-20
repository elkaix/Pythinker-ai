"""Per-chat WebUI activity transcript for refresh-survival.

``file_activity`` and ``provider_failover`` events live only in the live
WebSocket stream — refreshing the page mid-turn loses the chip cluster and
any failover notice. This module appends a tiny JSONL per chat so the
WebUI can replay the recent slice on ``attach``.

Strictly best-effort: persistence failures are logged but never raise; the
live event delivery remains the source of truth. Per-file cap is 256 KiB;
when an append would exceed it the file is trimmed to the most recent
~128 KiB on the next line boundary.

JSONL line shape (schema v1):

```json
{"v": 1, "ts": "2026-05-19T12:00:00Z", "kind": "file_activity",
 "activity": {...payload...}}
{"v": 1, "ts": "...", "kind": "provider_failover", "info": {...}}
{"v": 1, "ts": "...", "kind": "turn_boundary"}
```

``turn_boundary`` markers let the WebUI rebuild per-turn cluster groupings
on replay (one cluster per turn, frozen). Without them N turns of activity
would collapse into a single replayed cluster.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

from pythinker.config.paths import get_webui_dir

WEBUI_ACTIVITY_TRANSCRIPT_SCHEMA_VERSION = 1

# Hard cap per chat transcript. Exceeded → trim to last ~half on next write.
_MAX_FILE_BYTES = 256 * 1024
_TRIM_TARGET_BYTES = 128 * 1024

# Replay default: enough to cover several turns of mixed activity without
# flooding the WebUI on attach. Callers can lower for tight payloads.
DEFAULT_REPLAY_EVENTS = 50
_MAX_REPLAY_EVENTS = 500

# Mirrors ``pythinker.channels.websocket.multiplex._CHAT_ID_RE`` so we
# refuse anything that couldn't have come from a real WS envelope. Keeps
# the on-disk filename surface tight.
_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")

# Kinds we will accept on append. Anything else is rejected (and logged)
# so a future caller can't smuggle unrelated payloads through this surface.
_ALLOWED_KINDS = frozenset({"file_activity", "provider_failover", "turn_boundary"})


def _safe_filename(chat_id: str) -> str:
    """Map a chat_id to a filename-safe key.

    chat_ids match ``[A-Za-z0-9_:-]{1,64}``. ``:`` is filename-safe on
    POSIX but reserved on Windows; map to ``__`` so the same on-disk
    layout works everywhere.
    """
    return chat_id.replace(":", "__")


def webui_activity_dir() -> Path:
    return get_webui_dir() / "activity"


def webui_activity_transcript_path(chat_id: str) -> Path | None:
    if not isinstance(chat_id, str) or not _CHAT_ID_RE.match(chat_id):
        return None
    return webui_activity_dir() / f"{_safe_filename(chat_id)}.jsonl"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _encode_line(kind: str, payload: dict[str, Any] | None) -> bytes | None:
    """Serialize one event to a JSONL line; return ``None`` if payload
    can't be encoded (e.g. contains non-serializable values)."""
    if kind not in _ALLOWED_KINDS:
        logger.debug("activity_transcript: rejecting kind={}", kind)
        return None
    record: dict[str, Any] = {
        "v": WEBUI_ACTIVITY_TRANSCRIPT_SCHEMA_VERSION,
        "ts": _iso_now(),
        "kind": kind,
    }
    if kind == "file_activity":
        if not isinstance(payload, dict):
            return None
        record["activity"] = payload
    elif kind == "provider_failover":
        if not isinstance(payload, dict):
            return None
        record["info"] = payload
    # ``turn_boundary`` carries no payload.
    try:
        return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        logger.debug("activity_transcript: encode failed: {}", exc)
        return None


def _trim_in_place(path: Path) -> None:
    """Rewrite *path* keeping only the trailing ``_TRIM_TARGET_BYTES``
    on a line boundary. Best-effort — silently no-ops on any I/O error.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= _MAX_FILE_BYTES:
        return
    try:
        with open(path, "rb") as f:
            f.seek(-_TRIM_TARGET_BYTES, os.SEEK_END)
            tail = f.read()
    except OSError as exc:
        logger.warning("activity_transcript: trim read failed for {}: {}", path, exc)
        return
    # Drop the first (possibly partial) line so the file starts on a
    # clean JSON boundary.
    nl = tail.find(b"\n")
    if nl >= 0:
        tail = tail[nl + 1 :]
    tmp = path.with_suffix(".jsonl.trim")
    try:
        with open(tmp, "wb") as out:
            out.write(tail)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("activity_transcript: trim write failed for {}: {}", path, exc)
        # Clean up the tmp file if rename failed.
        try:
            tmp.unlink()
        except OSError:
            pass


def append_webui_activity(
    chat_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Append one event to the chat's transcript.

    Returns ``True`` on success, ``False`` on any rejection or I/O error.
    Never raises — callers can fire-and-forget without try/except.
    """
    path = webui_activity_transcript_path(chat_id)
    if path is None:
        return False
    line = _encode_line(kind, payload)
    if line is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as f:
            f.write(line)
    except OSError as exc:
        logger.warning("activity_transcript: append failed for {}: {}", path, exc)
        return False
    # Trim opportunistically. The check is cheap (one stat) and avoids
    # an ever-growing file across long-lived sessions.
    _trim_in_place(path)
    return True


def read_webui_activity_transcript(
    chat_id: str,
    *,
    max_events: int = DEFAULT_REPLAY_EVENTS,
) -> list[dict[str, Any]]:
    """Return the last *max_events* events from the transcript.

    Skips malformed lines silently — a single bad line shouldn't break
    replay. Returns ``[]`` for an unknown chat_id, missing file, or any
    read error.
    """
    path = webui_activity_transcript_path(chat_id)
    if path is None or not path.is_file():
        return []
    limit = max(1, min(int(max_events), _MAX_REPLAY_EVENTS))
    try:
        with open(path, "rb") as f:
            try:
                size = os.fstat(f.fileno()).st_size
            except OSError:
                size = 0
            # Read at most the cap so a corrupted oversized file doesn't
            # explode the process. ``append`` keeps us under cap normally.
            if size > _MAX_FILE_BYTES:
                f.seek(-_MAX_FILE_BYTES, os.SEEK_END)
                raw = f.read()
                nl = raw.find(b"\n")
                if nl >= 0:
                    raw = raw[nl + 1 :]
            else:
                raw = f.read()
    except OSError as exc:
        logger.warning("activity_transcript: read failed for {}: {}", path, exc)
        return []
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(record, dict) and record.get("kind") in _ALLOWED_KINDS:
            events.append(record)
    if len(events) > limit:
        return events[-limit:]
    return events


def clear_webui_activity_transcript(chat_id: str) -> bool:
    """Delete the transcript for *chat_id*. Returns ``True`` if a file was
    removed. Used by tests; runtime callers shouldn't need this."""
    path = webui_activity_transcript_path(chat_id)
    if path is None or not path.is_file():
        return False
    try:
        path.unlink()
    except OSError as exc:
        logger.warning("activity_transcript: clear failed for {}: {}", path, exc)
        return False
    return True
