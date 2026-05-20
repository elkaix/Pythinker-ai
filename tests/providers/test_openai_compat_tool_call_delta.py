"""Tests for the ``on_tool_call_delta`` demux added to ``chat_stream``.

The streaming branch enumerates SDK chunks and emits one frame per chunk that
carries either a ``tool_calls[*]`` partial or a legacy ``function_call``
partial.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pythinker.providers.openai_compat_provider import OpenAICompatProvider


def _sdk_chunk(
    *,
    tool_calls: list[Any] | None = None,
    function_call: Any | None = None,
    content: str | None = None,
    finish: str | None = None,
) -> Any:
    delta = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        function_call=function_call,
        reasoning_content=None,
        reasoning=None,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish)],
        usage=None,
    )


def _tool_delta(*, index: int, call_id: str = "", name: str = "", args: str = "") -> Any:
    fn = SimpleNamespace(name=name, arguments=args)
    return SimpleNamespace(index=index, id=call_id, function=fn)


class _FakeChatStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for ch in self._chunks:
            yield ch


class _FakeCompletions:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks
        self.received_kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.received_kwargs = kwargs
        return _FakeChatStream(self._chunks)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, chunks: list[Any]) -> None:
        self._completions = _FakeCompletions(chunks)
        self.chat = _FakeChat(self._completions)


@pytest.fixture
def provider() -> OpenAICompatProvider:
    # Construct via __new__ to avoid touching the network/SDK init path.
    p = OpenAICompatProvider.__new__(OpenAICompatProvider)
    # Stub the few attributes chat_stream relies on.
    p._spec = None  # type: ignore[attr-defined]
    p.api_base = "https://example.test"  # type: ignore[attr-defined]
    p.default_model = "gpt-fake"  # type: ignore[attr-defined]
    return p


async def test_on_tool_call_delta_fires_per_chunk(
    provider: OpenAICompatProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three streamed chunks for one tool call → three frames in order."""

    chunks = [
        # First chunk: id + name + opening JSON brace.
        _sdk_chunk(tool_calls=[
            _tool_delta(index=0, call_id="call_42", name="write_file", args='{"pa'),
        ]),
        # Second chunk: arguments-only delta (no id/name).
        _sdk_chunk(tool_calls=[
            _tool_delta(index=0, call_id="", name="", args='th":"out.txt","content":"x'),
        ]),
        # Third chunk: closing args + finish_reason.
        _sdk_chunk(
            tool_calls=[_tool_delta(index=0, args='"}')],
            finish="tool_calls",
        ),
    ]
    client = _FakeClient(chunks)
    provider._client = client  # type: ignore[attr-defined]

    monkeypatch.setattr(
        provider, "_build_kwargs", lambda *a, **kw: {"model": "gpt-fake"},
    )
    monkeypatch.setattr(
        provider, "_should_use_responses_api", lambda *a, **kw: False,
    )

    captured: list[dict[str, Any]] = []

    async def on_delta(payload: dict[str, Any]) -> None:
        captured.append(payload)

    await provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_tool_call_delta=on_delta,
    )

    assert len(captured) == 3
    assert captured[0]["index"] == 0
    assert captured[0]["call_id"] == "call_42"
    assert captured[0]["name"] == "write_file"
    assert captured[0]["arguments_delta"] == '{"pa'
    # Subsequent frames must NOT lose the index even though id/name are blank.
    assert captured[1]["index"] == 0
    assert captured[1]["call_id"] == ""
    assert captured[1]["name"] == ""
    assert captured[1]["arguments_delta"] == 'th":"out.txt","content":"x'
    assert captured[2]["arguments_delta"] == '"}'


async def test_legacy_function_call_routes_through_callback(
    provider: OpenAICompatProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deprecated single ``function_call`` shape must also fire frames."""

    chunks = [
        _sdk_chunk(function_call=SimpleNamespace(
            name="legacy_tool", arguments='{"x": 1}',
        )),
        _sdk_chunk(finish="stop"),
    ]
    client = _FakeClient(chunks)
    provider._client = client  # type: ignore[attr-defined]

    monkeypatch.setattr(
        provider, "_build_kwargs", lambda *a, **kw: {"model": "gpt-fake"},
    )
    monkeypatch.setattr(
        provider, "_should_use_responses_api", lambda *a, **kw: False,
    )

    captured: list[dict[str, Any]] = []

    async def on_delta(payload: dict[str, Any]) -> None:
        captured.append(payload)

    await provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_tool_call_delta=on_delta,
    )

    assert len(captured) == 1
    assert captured[0]["index"] == 0
    assert captured[0]["call_id"] == ""
    assert captured[0]["name"] == "legacy_tool"
    assert captured[0]["arguments_delta"] == '{"x": 1}'


async def test_content_only_chunks_do_not_fire_tool_call_delta(
    provider: OpenAICompatProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plain text deltas must not trigger ``on_tool_call_delta``."""

    chunks = [
        _sdk_chunk(content="hello"),
        _sdk_chunk(content=" world", finish="stop"),
    ]
    client = _FakeClient(chunks)
    provider._client = client  # type: ignore[attr-defined]

    monkeypatch.setattr(
        provider, "_build_kwargs", lambda *a, **kw: {"model": "gpt-fake"},
    )
    monkeypatch.setattr(
        provider, "_should_use_responses_api", lambda *a, **kw: False,
    )

    content_calls: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    async def on_content(t: str) -> None:
        content_calls.append(t)

    async def on_tool(p: dict[str, Any]) -> None:
        tool_calls.append(p)

    await provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=on_content,
        on_tool_call_delta=on_tool,
    )

    assert content_calls == ["hello", " world"]
    assert tool_calls == []
