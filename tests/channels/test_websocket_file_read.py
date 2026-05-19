"""Tests for the ``webui_file_read.get`` WebSocket envelope."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pythinker.channels.websocket import WebSocketChannel

_PORT = 18895


def _ch(bus: Any, admin_service: Any | None = None) -> WebSocketChannel:
    cfg: dict[str, Any] = {
        "enabled": True,
        "allowFrom": ["*"],
        "host": "127.0.0.1",
        "port": _PORT,
        "path": "/ws",
        "websocketRequiresToken": False,
    }
    return WebSocketChannel(cfg, bus, admin_service=admin_service)


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "secrets.bin").write_bytes(b"\x00\x01\x02ABC")
    return tmp_path


@pytest.fixture()
def admin_service(workspace: Path) -> MagicMock:
    svc = MagicMock()
    svc.config = MagicMock()
    svc.config.workspace_path = workspace
    return svc


class _FakeConnection:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.remote_address = ("127.0.0.1", 0)

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


@pytest.mark.asyncio
async def test_file_read_refused_for_non_admin(
    bus: MagicMock, admin_service: MagicMock
) -> None:
    channel = _ch(bus, admin_service=admin_service)
    conn = _FakeConnection()
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={"type": "webui_file_read.get", "request_id": "r1", "path": "pkg/mod.py"},
    )
    assert conn.sent[0]["event"] == "webui_file_read_error"
    assert conn.sent[0]["detail"] == "admin token required"


@pytest.mark.asyncio
async def test_file_read_returns_text_for_workspace_relative_path(
    bus: MagicMock, admin_service: MagicMock
) -> None:
    channel = _ch(bus, admin_service=admin_service)
    conn = _FakeConnection()
    channel._admin_connections.add(conn)

    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={"type": "webui_file_read.get", "request_id": "r2", "path": "pkg/mod.py"},
    )
    event = conn.sent[0]
    assert event["event"] == "webui_file_read"
    assert event["request_id"] == "r2"
    assert event["binary"] is False
    assert event["truncated"] is False
    assert event["content"] == "print('hello')\n"
    assert event["path"] == "pkg/mod.py"


@pytest.mark.asyncio
async def test_file_read_blocks_path_traversal(
    bus: MagicMock, admin_service: MagicMock, tmp_path: Path
) -> None:
    # Create a file outside the workspace; the resolved path will escape.
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    try:
        channel = _ch(bus, admin_service=admin_service)
        conn = _FakeConnection()
        channel._admin_connections.add(conn)
        await channel._dispatch_envelope(
            conn,
            client_id="c1",
            envelope={
                "type": "webui_file_read.get",
                "request_id": "r3",
                "path": "../outside.txt",
            },
        )
        assert conn.sent[0]["event"] == "webui_file_read_error"
        assert conn.sent[0]["detail"] == "path escapes workspace"
    finally:
        outside.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_file_read_flags_binary_content(
    bus: MagicMock, admin_service: MagicMock
) -> None:
    channel = _ch(bus, admin_service=admin_service)
    conn = _FakeConnection()
    channel._admin_connections.add(conn)
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={"type": "webui_file_read.get", "request_id": "r4", "path": "secrets.bin"},
    )
    event = conn.sent[0]
    assert event["event"] == "webui_file_read"
    assert event["binary"] is True
    assert event["content"] == ""


@pytest.mark.asyncio
async def test_file_read_truncates_oversize_files(
    bus: MagicMock, admin_service: MagicMock, workspace: Path
) -> None:
    big = workspace / "big.txt"
    big.write_text("a" * (1_100_000), encoding="utf-8")
    channel = _ch(bus, admin_service=admin_service)
    conn = _FakeConnection()
    channel._admin_connections.add(conn)
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={"type": "webui_file_read.get", "request_id": "r5", "path": "big.txt"},
    )
    event = conn.sent[0]
    assert event["event"] == "webui_file_read"
    assert event["truncated"] is True
    assert len(event["content"]) == 1_048_576


@pytest.mark.asyncio
async def test_file_read_rejects_directory_path(
    bus: MagicMock, admin_service: MagicMock
) -> None:
    channel = _ch(bus, admin_service=admin_service)
    conn = _FakeConnection()
    channel._admin_connections.add(conn)
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={"type": "webui_file_read.get", "request_id": "r6", "path": "pkg"},
    )
    assert conn.sent[0]["event"] == "webui_file_read_error"
    assert conn.sent[0]["detail"] == "not a regular file"


@pytest.mark.asyncio
async def test_file_read_rejects_empty_path(
    bus: MagicMock, admin_service: MagicMock
) -> None:
    channel = _ch(bus, admin_service=admin_service)
    conn = _FakeConnection()
    channel._admin_connections.add(conn)
    await channel._dispatch_envelope(
        conn,
        client_id="c1",
        envelope={"type": "webui_file_read.get", "request_id": "r7", "path": ""},
    )
    assert conn.sent[0]["event"] == "webui_file_read_error"
    assert conn.sent[0]["detail"] == "path is required"
