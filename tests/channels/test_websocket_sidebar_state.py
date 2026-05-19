"""Tests for the ``webui_sidebar_state.{get,set}`` WebSocket envelopes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pythinker.channels.websocket import WebSocketChannel


_PORT = 18891


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


@pytest.mark.asyncio
async def test_get_returns_default_state_for_non_admin(bus: MagicMock) -> None:
    channel = _ch(bus)
    conn = _FakeConnection()
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={"type": "webui_sidebar_state.get", "request_id": "r1"},
    )

    assert len(conn.sent) == 1
    event = conn.sent[0]
    assert event["event"] == "webui_sidebar_state"
    assert event["request_id"] == "r1"
    state = event["state"]
    assert state["schema_version"] == 1
    assert state["pinned_keys"] == []


@pytest.mark.asyncio
async def test_set_refused_for_non_admin(bus: MagicMock) -> None:
    channel = _ch(bus)
    conn = _FakeConnection()
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={
            "type": "webui_sidebar_state.set",
            "request_id": "r2",
            "state": {"pinned_keys": ["websocket:abc"]},
        },
    )

    assert len(conn.sent) == 1
    event = conn.sent[0]
    assert event["event"] == "webui_sidebar_state_error"
    assert event["detail"] == "admin token required"


@pytest.mark.asyncio
async def test_set_persists_when_admin_connection(bus: MagicMock) -> None:
    channel = _ch(bus)
    conn = _FakeConnection()
    channel._admin_connections.add(conn)

    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={
            "type": "webui_sidebar_state.set",
            "request_id": "r3",
            "state": {
                "pinned_keys": ["websocket:abc"],
                "view": {"density": "compact"},
            },
        },
    )

    assert len(conn.sent) == 1
    event = conn.sent[0]
    assert event["event"] == "webui_sidebar_state"
    state = event["state"]
    assert state["pinned_keys"] == ["websocket:abc"]
    assert state["view"]["density"] == "compact"
    assert state["updated_at"] is not None

    # Roundtrip: a subsequent get returns the persisted state.
    conn.sent.clear()
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={"type": "webui_sidebar_state.get", "request_id": "r4"},
    )
    follow_up = conn.sent[0]["state"]
    assert follow_up["pinned_keys"] == ["websocket:abc"]
    assert follow_up["view"]["density"] == "compact"
