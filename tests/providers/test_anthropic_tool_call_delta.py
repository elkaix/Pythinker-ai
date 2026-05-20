"""Tests for the ``on_tool_call_delta`` demux added to Anthropic ``chat_stream``.

The provider must dispatch ``content_block_start`` (tool_use) and
``content_block_delta`` (input_json_delta) chunks into ``on_tool_call_delta``,
while routing ``text_delta`` chunks into ``on_content_delta``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pythinker.providers.anthropic_provider import AnthropicProvider
from pythinker.providers.base import LLMResponse


class _FakeMessagesStream:
    """Mimics ``client.messages.stream(...).__aenter__()`` shape."""

    def __init__(self, chunks: list[Any], final: LLMResponse | Any) -> None:
        self._chunks = list(chunks)
        self._final = final

    async def __aenter__(self) -> "_FakeMessagesStream":
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None

    def __aiter__(self) -> "_FakeMessagesStream":
        return self

    async def __anext__(self) -> Any:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def get_final_message(self) -> Any:
        return self._final


class _FakeMessages:
    def __init__(self, stream_obj: _FakeMessagesStream) -> None:
        self._stream = stream_obj

    def stream(self, **_kwargs: Any) -> _FakeMessagesStream:
        return self._stream


class _FakeClient:
    def __init__(self, stream_obj: _FakeMessagesStream) -> None:
        self.messages = _FakeMessages(stream_obj)


def _block_start_tool_use(*, index: int, call_id: str, name: str) -> Any:
    return SimpleNamespace(
        type="content_block_start",
        index=index,
        content_block=SimpleNamespace(type="tool_use", id=call_id, name=name),
    )


def _text_delta(text: str) -> Any:
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )


def _input_json_delta(*, index: int, partial: str) -> Any:
    return SimpleNamespace(
        type="content_block_delta",
        index=index,
        delta=SimpleNamespace(type="input_json_delta", partial_json=partial),
    )


@pytest.fixture
def provider() -> AnthropicProvider:
    p = AnthropicProvider.__new__(AnthropicProvider)
    p.default_model = "claude-fake"  # type: ignore[attr-defined]
    return p


async def test_input_json_deltas_route_to_tool_call_delta(
    provider: AnthropicProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tool_use block_start + two input_json_delta chunks → three frames."""

    final = SimpleNamespace(content=[], stop_reason="end_turn", usage=None)
    chunks = [
        _block_start_tool_use(index=0, call_id="ant_call_1", name="write_file"),
        _input_json_delta(index=0, partial='{"path": "out.txt", '),
        _input_json_delta(index=0, partial='"content": "hello"}'),
    ]
    stream_obj = _FakeMessagesStream(chunks, final)
    provider._client = _FakeClient(stream_obj)  # type: ignore[attr-defined]

    monkeypatch.setattr(provider, "_build_kwargs", lambda *a, **kw: {"model": "claude-fake"})
    monkeypatch.setattr(
        provider, "_parse_response",
        lambda _r: LLMResponse(content=None, tool_calls=[], finish_reason="stop"),
    )

    captured: list[dict[str, Any]] = []

    async def on_delta(payload: dict[str, Any]) -> None:
        captured.append(payload)

    await provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_tool_call_delta=on_delta,
    )

    assert len(captured) == 3
    # First frame seeds id/name with empty arguments_delta.
    assert captured[0]["index"] == 0
    assert captured[0]["call_id"] == "ant_call_1"
    assert captured[0]["name"] == "write_file"
    assert captured[0]["arguments_delta"] == ""
    # Subsequent input_json_delta chunks carry partial JSON without re-stating id/name.
    assert captured[1]["arguments_delta"] == '{"path": "out.txt", '
    assert captured[1]["call_id"] == "ant_call_1"
    assert captured[1]["name"] == "write_file"
    assert captured[2]["arguments_delta"] == '"content": "hello"}'


async def test_text_deltas_route_to_content_delta_only(
    provider: AnthropicProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """text_delta chunks must not leak into on_tool_call_delta."""

    final = SimpleNamespace(content=[], stop_reason="end_turn", usage=None)
    chunks = [_text_delta("hello "), _text_delta("world")]
    stream_obj = _FakeMessagesStream(chunks, final)
    provider._client = _FakeClient(stream_obj)  # type: ignore[attr-defined]

    monkeypatch.setattr(provider, "_build_kwargs", lambda *a, **kw: {"model": "claude-fake"})
    monkeypatch.setattr(
        provider, "_parse_response",
        lambda _r: LLMResponse(content="hello world", finish_reason="stop"),
    )

    text_parts: list[str] = []
    tool_frames: list[dict[str, Any]] = []

    async def on_content(t: str) -> None:
        text_parts.append(t)

    async def on_tool(p: dict[str, Any]) -> None:
        tool_frames.append(p)

    await provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=on_content,
        on_tool_call_delta=on_tool,
    )

    assert text_parts == ["hello ", "world"]
    assert tool_frames == []
