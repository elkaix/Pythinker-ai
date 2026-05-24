"""Tests for web_fetch SSRF protection and untrusted content marking."""

from __future__ import annotations

import json
import socket
from unittest.mock import patch

import httpx
import pytest

from pythinker.agent.tools.web import WebFetchTool


def _fake_resolve_private(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_resolve_public(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


_REAL_GETADDRINFO = socket.getaddrinfo


@pytest.mark.asyncio
async def test_web_fetch_strips_markdown_url_wrappers(monkeypatch):
    tool = WebFetchTool()
    captured = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None):
            raise RuntimeError("skip image preflight")

    async def _fake_fetch_jina(url: str, max_chars: int) -> str:
        captured["url"] = url
        return json.dumps({"url": url, "text": "ok"})

    monkeypatch.setattr("pythinker.agent.tools.web.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(tool, "_fetch_jina", _fake_fetch_jina)
    with patch("pythinker.security.network.socket.getaddrinfo", _fake_resolve_public):
        result = await tool.execute(url=" `\"https://example.com/page\"` ")

    assert captured["url"] == "https://example.com/page"
    assert json.loads(result)["url"] == "https://example.com/page"


@pytest.mark.asyncio
async def test_web_fetch_blocks_private_ip():
    tool = WebFetchTool()
    with patch("pythinker.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await tool.execute(url="http://169.254.169.254/computeMetadata/v1/")
    data = json.loads(result)
    assert "error" in data
    assert "private" in data["error"].lower() or "blocked" in data["error"].lower()


@pytest.mark.asyncio
async def test_web_fetch_blocks_localhost():
    tool = WebFetchTool()
    def _resolve_localhost(hostname, port, family=0, type_=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]
    with patch("pythinker.security.network.socket.getaddrinfo", _resolve_localhost):
        result = await tool.execute(url="http://localhost/admin")
    data = json.loads(result)
    assert "error" in data


@pytest.mark.asyncio
async def test_web_fetch_result_contains_untrusted_flag():
    """When fetch succeeds, result JSON must include untrusted=True and the banner."""
    tool = WebFetchTool()

    fake_html = "<html><head><title>Test</title></head><body><p>Hello world</p></body></html>"


    class FakeResponse:
        status_code = 200
        url = "https://example.com/page"
        text = fake_html
        headers = {"content-type": "text/html"}
        def raise_for_status(self): pass
        def json(self): return {}

    async def _fake_get(self, url, **kwargs):
        return FakeResponse()

    with patch("pythinker.security.network.socket.getaddrinfo", _fake_resolve_public), \
         patch("httpx.AsyncClient.get", _fake_get):
        result = await tool.execute(url="https://example.com/page")

    data = json.loads(result)
    assert data.get("untrusted") is True
    assert "[External content" in data.get("text", "")


@pytest.mark.asyncio
async def test_web_fetch_returns_site_block_metadata_for_expected_http_blocks(monkeypatch):
    tool = WebFetchTool()
    warnings = []
    errors = []

    class FakeResponse:
        status_code = 403
        url = "https://example.com/blocked"

        def raise_for_status(self):
            request = httpx.Request("GET", str(self.url))
            response = httpx.Response(
                self.status_code,
                request=request,
                headers={"content-type": "text/html"},
                text="blocked",
            )
            raise httpx.HTTPStatusError("blocked", request=request, response=response)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("pythinker.agent.tools.web.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("pythinker.agent.tools.web.logger.warning", lambda *args: warnings.append(args))
    monkeypatch.setattr("pythinker.agent.tools.web.logger.error", lambda *args: errors.append(args))

    result = await tool._fetch_readability("https://example.com/blocked", "markdown", 1000)

    data = json.loads(result)
    assert data == {
        "error": "Blocked by site (403 Forbidden)",
        "url": "https://example.com/blocked",
        "finalUrl": "https://example.com/blocked",
        "status": 403,
        "blockedBySite": True,
    }
    assert warnings
    assert not errors


@pytest.mark.asyncio
async def test_web_fetch_blocks_private_redirect_before_returning_image(monkeypatch):
    tool = WebFetchTool()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/image.png":
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/secret.png"},
                request=request,
            )
        if str(request.url) == "http://127.0.0.1/secret.png":
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=b"\x89PNG\r\n\x1a\n",
                request=request,
            )
        return httpx.Response(404, request=request)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    class TransportAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("proxy", None)
            super().__init__(*args, transport=transport, **kwargs)

    monkeypatch.setattr("pythinker.agent.tools.web.httpx.AsyncClient", TransportAsyncClient)

    def resolve_public_start_only(hostname, port, family=0, type_=0):
        if hostname == "example.com":
            return _fake_resolve_public(hostname, port, family, type_)
        return _REAL_GETADDRINFO(hostname, port, family, type_)

    with patch("pythinker.security.network.socket.getaddrinfo", resolve_public_start_only):
        result = await tool.execute(url="https://example.com/image.png")

    data = json.loads(result)
    assert "error" in data
    assert "redirect blocked" in data["error"].lower()


@pytest.mark.asyncio
async def test_web_fetch_does_not_request_private_redirect_target(monkeypatch):
    tool = WebFetchTool()
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == "https://attacker.example/start":
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1:8765/metadata"},
                request=request,
            )
        if str(request.url) == "http://127.0.0.1:8765/metadata":
            return httpx.Response(200, content=b"internal secret", request=request)
        return httpx.Response(404, request=request)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    class TransportAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("proxy", None)
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("pythinker.agent.tools.web.httpx.AsyncClient", TransportAsyncClient)

    def resolve_public_start_only(hostname, port, family=0, type_=0):
        if hostname == "attacker.example":
            return _fake_resolve_public(hostname, port, family, type_)
        return _REAL_GETADDRINFO(hostname, port, family, type_)

    with patch("pythinker.security.network.socket.getaddrinfo", resolve_public_start_only):
        result = await tool.execute(url="https://attacker.example/start")

    data = json.loads(result)
    assert "error" in data
    assert "redirect blocked" in data["error"].lower()
    assert requested == ["https://attacker.example/start"]
