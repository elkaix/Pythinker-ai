from __future__ import annotations

import httpx
import pytest

from pythinker.providers import transcription
from pythinker.providers.transcription import GroqTranscriptionProvider, OpenAITranscriptionProvider


class _FakeResponse:
    def __init__(self, status_code: int, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"text": "ok"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.test/transcribe")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> object:
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


@pytest.mark.asyncio
async def test_openai_transcription_retries_transient_status(monkeypatch, tmp_path) -> None:
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"audio")
    calls: list[dict] = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, files, timeout):
            calls.append(files)
            if len(calls) == 1:
                return _FakeResponse(503)
            return _FakeResponse(200, {"text": "hello"})

    monkeypatch.setattr(transcription.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(transcription.asyncio, "sleep", lambda _delay: _instant_sleep())

    provider = OpenAITranscriptionProvider(api_key="key", api_base="https://example.test/transcribe")

    assert await provider.transcribe(audio) == "hello"
    assert len(calls) == 2
    assert calls[0]["model"] == (None, "whisper-1")


@pytest.mark.asyncio
async def test_groq_transcription_retries_transient_exception(monkeypatch, tmp_path) -> None:
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"audio")
    calls = 0

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, files, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ReadError("temporary")
            return _FakeResponse(200, {"text": "transcribed"})

    monkeypatch.setattr(transcription.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(transcription.asyncio, "sleep", lambda _delay: _instant_sleep())

    provider = GroqTranscriptionProvider(api_key="key", api_base="https://example.test/transcribe")

    assert await provider.transcribe(audio) == "transcribed"
    assert calls == 2


@pytest.mark.asyncio
async def test_transcription_malformed_response_returns_empty(monkeypatch, tmp_path) -> None:
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"audio")

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, files, timeout):
            return _FakeResponse(200, ValueError("bad json"))

    monkeypatch.setattr(transcription.httpx, "AsyncClient", FakeClient)

    provider = OpenAITranscriptionProvider(api_key="key", api_base="https://example.test/transcribe")

    assert await provider.transcribe(audio) == ""


async def _instant_sleep() -> None:
    return None


# ---------------------------------------------------------------------------
# apiBase normalization: a chat-style base must not be POSTed verbatim
# ---------------------------------------------------------------------------


def test_resolve_transcription_url_falls_back_to_default() -> None:
    default = "https://api.openai.com/v1/audio/transcriptions"
    assert transcription._resolve_transcription_url(None, default) == default
    assert transcription._resolve_transcription_url("", default) == default


def test_resolve_transcription_url_appends_path_to_chat_style_base() -> None:
    assert (
        transcription._resolve_transcription_url(
            "https://api.groq.com/openai/v1", "https://x/audio/transcriptions"
        )
        == "https://api.groq.com/openai/v1/audio/transcriptions"
    )
    # Trailing slash must not produce a doubled separator.
    assert (
        transcription._resolve_transcription_url(
            "https://api.groq.com/openai/v1/", "https://x/audio/transcriptions"
        )
        == "https://api.groq.com/openai/v1/audio/transcriptions"
    )


def test_resolve_transcription_url_keeps_full_endpoint() -> None:
    full = "https://api.groq.com/openai/v1/audio/transcriptions"
    assert transcription._resolve_transcription_url(full, "https://x/audio/transcriptions") == full


def test_groq_provider_normalizes_chat_style_api_base() -> None:
    """apiBase set to the v1 base resolves to the audio endpoint."""
    provider = GroqTranscriptionProvider(
        api_key="gsk-test", api_base="https://api.groq.com/openai/v1"
    )
    assert provider.api_url == "https://api.groq.com/openai/v1/audio/transcriptions"
