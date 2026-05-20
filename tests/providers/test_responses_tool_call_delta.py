"""Tests for the ``on_tool_call_delta`` demux in the OpenAI Responses parser.

Both ``consume_sdk_stream`` (SDK objects) and ``consume_sse`` (raw SSE events)
must route ``response.output_item.added`` (function_call) and
``response.function_call_arguments.delta`` events to ``on_tool_call_delta``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, AsyncIterator

from pythinker.providers.openai_responses.parsing import (
    consume_sdk_stream,
)


async def _aiter(events: list[Any]) -> AsyncIterator[Any]:
    for ev in events:
        yield ev


async def test_consume_sdk_stream_emits_delta_frames() -> None:
    """Function-call init + two arguments-deltas → three frames in order."""

    events = [
        SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(
                type="function_call",
                call_id="resp_call_1",
                id="fc_77",
                name="write_file",
                arguments="",
            ),
        ),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            call_id="resp_call_1",
            delta='{"path": "out.txt", ',
        ),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            call_id="resp_call_1",
            delta='"content": "x"}',
        ),
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="function_call",
                call_id="resp_call_1",
                id="fc_77",
                name="write_file",
                arguments=json.dumps({"path": "out.txt", "content": "x"}),
            ),
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(status="completed", usage=None, output=[]),
        ),
    ]

    captured: list[dict[str, Any]] = []

    async def on_delta(payload: dict[str, Any]) -> None:
        captured.append(payload)

    content, tool_calls, finish_reason, usage, _ = await consume_sdk_stream(
        _aiter(events),
        on_content_delta=None,
        on_tool_call_delta=on_delta,
    )

    assert finish_reason == "stop"
    # Three delta frames: the seeding output_item.added plus two arguments deltas.
    assert len(captured) == 3
    assert captured[0]["index"] == 0
    assert captured[0]["call_id"] == "resp_call_1"
    assert captured[0]["name"] == "write_file"
    assert captured[0]["arguments_delta"] == ""
    assert captured[1]["arguments_delta"] == '{"path": "out.txt", '
    assert captured[2]["arguments_delta"] == '"content": "x"}'
    # Final tool_call list still produced exactly as before.
    assert len(tool_calls) == 1
    assert tool_calls[0].arguments == {"path": "out.txt", "content": "x"}


async def test_consume_sdk_stream_text_only_does_not_emit_tool_frames() -> None:
    """text deltas must not leak into on_tool_call_delta."""

    events = [
        SimpleNamespace(type="response.output_text.delta", delta="hello"),
        SimpleNamespace(type="response.output_text.delta", delta=" world"),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(status="completed", usage=None, output=[]),
        ),
    ]

    text_parts: list[str] = []
    tool_frames: list[dict[str, Any]] = []

    async def on_content(t: str) -> None:
        text_parts.append(t)

    async def on_tool(p: dict[str, Any]) -> None:
        tool_frames.append(p)

    await consume_sdk_stream(_aiter(events), on_content, on_tool_call_delta=on_tool)

    assert text_parts == ["hello", " world"]
    assert tool_frames == []


async def test_consume_sdk_stream_assigns_indices_per_call() -> None:
    """Two concurrent function_calls must get distinct ``index`` values."""

    events = [
        SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(
                type="function_call", call_id="A", id="fc_1", name="write_file",
                arguments="",
            ),
        ),
        SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(
                type="function_call", call_id="B", id="fc_2", name="edit_file",
                arguments="",
            ),
        ),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            call_id="B", delta='{"path": "b.txt"}',
        ),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            call_id="A", delta='{"path": "a.txt"}',
        ),
    ]

    captured: list[dict[str, Any]] = []

    async def on_delta(payload: dict[str, Any]) -> None:
        captured.append(payload)

    await consume_sdk_stream(_aiter(events), on_tool_call_delta=on_delta)

    indices_by_call = {p["call_id"]: p["index"] for p in captured}
    assert indices_by_call == {"A": 0, "B": 1}
    # B was seeded after A and so must own index 1 across all of its frames.
    b_frames = [p for p in captured if p["call_id"] == "B"]
    assert all(p["index"] == 1 for p in b_frames)
