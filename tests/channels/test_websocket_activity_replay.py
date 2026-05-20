"""Tests for the ``webui_activity.replay`` WebSocket envelope."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pythinker.channels.websocket import WebSocketChannel
from pythinker.webui import activity_transcript as at

_PORT = 18895


def _ch(bus: Any, **kw: Any) -> WebSocketChannel:
    cfg: dict[str, Any] = {
        "enabled": True,
        "allowFrom": ["*"],
        "host": "127.0.0.1",
        "port": _PORT,
        "path": "/ws",
        "websocketRequiresToken": False,
    }
    cfg.update(kw)
    return WebSocketChannel(cfg, bus)


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("pythinker.config.paths.get_data_dir", lambda: tmp_path)
    return tmp_path


class _FakeConnection:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.remote_address = ("127.0.0.1", 0)

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def _file_activity_payload(call_id: str = "c1") -> dict[str, Any]:
    return {
        "version": 1,
        "call_id": call_id,
        "tool": "write_file",
        "path": "out.txt",
        "phase": "end",
        "status": "done",
        "added": 5,
        "deleted": 1,
        "approximate": False,
        "binary": False,
    }


async def test_replay_returns_empty_events_when_transcript_missing(bus: MagicMock) -> None:
    channel = _ch(bus)
    conn = _FakeConnection()
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={
            "type": "webui_activity.replay",
            "request_id": "r1",
            "chat_id": "websocket:never-seen",
        },
    )
    assert len(conn.sent) == 1
    event = conn.sent[0]
    assert event["event"] == "webui_activity_replay"
    assert event["request_id"] == "r1"
    assert event["chat_id"] == "websocket:never-seen"
    assert event["events"] == []


async def test_replay_returns_only_events_after_last_turn_boundary(bus: MagicMock) -> None:
    """Past turns' activity stays buried — only the in-flight slice replays."""
    cid = "websocket:abc"
    at.append_webui_activity(cid, "file_activity", _file_activity_payload("past-1"))
    at.append_webui_activity(cid, "turn_boundary")
    at.append_webui_activity(cid, "file_activity", _file_activity_payload("c2"))
    at.append_webui_activity(cid, "file_activity", _file_activity_payload("c3"))

    channel = _ch(bus)
    conn = _FakeConnection()
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={
            "type": "webui_activity.replay",
            "request_id": "r2",
            "chat_id": cid,
        },
    )
    assert len(conn.sent) == 1
    event = conn.sent[0]
    assert event["event"] == "webui_activity_replay"
    assert event["chat_id"] == cid
    kinds = [rec["kind"] for rec in event["events"]]
    assert kinds == ["file_activity", "file_activity"]
    assert [e["activity"]["call_id"] for e in event["events"]] == ["c2", "c3"]


async def test_replay_returns_empty_when_session_is_idle(bus: MagicMock) -> None:
    """A turn that ended cleanly leaves no in-flight slice to restore."""
    cid = "websocket:abc"
    at.append_webui_activity(cid, "file_activity", _file_activity_payload("c1"))
    at.append_webui_activity(cid, "turn_boundary")

    channel = _ch(bus)
    conn = _FakeConnection()
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={"type": "webui_activity.replay", "chat_id": cid},
    )
    event = conn.sent[0]
    assert event["event"] == "webui_activity_replay"
    assert event["events"] == []


async def test_replay_rejects_invalid_chat_id(bus: MagicMock) -> None:
    channel = _ch(bus)
    conn = _FakeConnection()
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={
            "type": "webui_activity.replay",
            "request_id": "r3",
            "chat_id": "../escape",
        },
    )
    assert len(conn.sent) == 1
    event = conn.sent[0]
    assert event["event"] == "webui_activity_replay_error"
    assert event["detail"] == "invalid chat_id"


async def test_replay_honors_max_events_cap(bus: MagicMock) -> None:
    cid = "websocket:abc"
    for i in range(20):
        at.append_webui_activity(cid, "file_activity", _file_activity_payload(f"c{i}"))

    channel = _ch(bus)
    conn = _FakeConnection()
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={
            "type": "webui_activity.replay",
            "chat_id": cid,
            "max_events": 5,
        },
    )
    event = conn.sent[0]
    assert event["event"] == "webui_activity_replay"
    assert len(event["events"]) == 5
    # Most-recent slice.
    assert [e["activity"]["call_id"] for e in event["events"]] == [
        f"c{i}" for i in range(15, 20)
    ]
