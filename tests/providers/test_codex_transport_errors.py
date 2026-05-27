"""Codex transport/API error classification (blank-error handling).

Verifies that Codex failures become typed, retryable, leak-free error responses instead
of the old bare ``Error calling Codex:`` content.
"""

from __future__ import annotations

import httpx
import pytest

from pythinker.providers.openai_codex_provider import (
    _codex_error_response,
    _CodexHTTPError,
    _friendly_error,
    _request_codex,
    _should_retry_status,
)


def test_friendly_error_omits_raw_body() -> None:
    raw = "raw upstream body with PRIVATE PROMPT MUST NOT APPEAR"
    message = _friendly_error(500, raw)
    assert message == "HTTP 500: Codex API request failed"
    assert "PRIVATE PROMPT" not in message


def test_blank_timeout_becomes_typed_retryable_response() -> None:
    # A blank-message ReadTimeout previously yielded bare "Error calling Codex: ".
    response = _codex_error_response(httpx.ReadTimeout(""))
    assert response.finish_reason == "error"
    assert response.content == "Error calling Codex (ReadTimeout): timed out waiting for response"
    assert response.error_kind == "timeout"
    assert response.error_should_retry is True


def test_connection_error_is_typed_retryable() -> None:
    response = _codex_error_response(httpx.ConnectError("boom"))
    assert response.error_kind == "connection"
    assert response.error_should_retry is True
    assert "boom" in response.content


def test_http_error_preserves_status_and_retry_metadata() -> None:
    exc = _CodexHTTPError(
        "HTTP 503: backend unavailable",
        status_code=503,
        retry_after=2.5,
        error_type="server_error",
        error_code="overloaded",
        should_retry=True,
    )
    response = _codex_error_response(exc)
    assert response.content == "Error calling Codex (CodexHTTPError): HTTP 503: backend unavailable"
    assert response.error_status_code == 503
    assert response.error_kind == "http"
    assert response.error_type == "server_error"
    assert response.error_code == "overloaded"
    assert response.retry_after == 2.5
    assert response.error_should_retry is True


def test_should_retry_status_semantics() -> None:
    assert _should_retry_status(503, None, None, None) is True
    assert _should_retry_status(500, None, None, None) is True
    assert _should_retry_status(400, None, None, None) is False
    # 429 with a non-retryable quota signal is not retried.
    assert _should_retry_status(429, "insufficient_quota", "insufficient_quota", None) is False


async def test_request_codex_non_200_populates_http_metadata(monkeypatch) -> None:
    original_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "2"},
            json={"error": {"type": "rate_limit_exceeded", "code": "rate_limit_exceeded"}},
            request=request,
        )

    def fake_client(*, timeout: float, verify: bool) -> httpx.AsyncClient:
        return original_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(
        "pythinker.providers.openai_codex_provider.httpx.AsyncClient", fake_client
    )

    with pytest.raises(_CodexHTTPError) as caught:
        await _request_codex("https://codex.example/responses", {}, {"input": []}, verify=True)

    error = caught.value
    assert error.status_code == 429
    assert error.retry_after == 2.0
    assert error.error_type == "rate_limit_exceeded"
    assert error.error_code == "rate_limit_exceeded"
    assert error.should_retry is True


async def test_request_codex_honors_stream_idle_timeout_env(monkeypatch) -> None:
    """PYTHINKER_AI_STREAM_IDLE_TIMEOUT_S overrides the default Codex stream timeout,
    matching anthropic/openai_compat instead of a hardcoded value."""
    monkeypatch.setenv("PYTHINKER_AI_STREAM_IDLE_TIMEOUT_S", "5")
    original_client = httpx.AsyncClient
    seen: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    def fake_client(*, timeout: int, verify: bool) -> httpx.AsyncClient:
        seen["timeout"] = timeout
        return original_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(
        "pythinker.providers.openai_codex_provider.httpx.AsyncClient", fake_client
    )

    await _request_codex("https://codex.example/responses", {}, {"input": []}, verify=True)

    assert seen["timeout"] == 5
