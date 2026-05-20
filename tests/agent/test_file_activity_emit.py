"""End-to-end test: runner emits file-edit events to file_activity_callback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pythinker.agent.hook import AgentHook
from pythinker.agent.runner import AgentRunner, AgentRunSpec
from pythinker.agent.tools.filesystem import WriteFileTool
from pythinker.agent.tools.registry import ToolRegistry
from pythinker.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class _StubProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__()
        self._responses = list(responses)

    def get_default_model(self) -> str:
        return "stub/model"

    async def chat(self, *_a: Any, **_kw: Any) -> LLMResponse:
        return self._responses.pop(0)

    async def chat_stream(self, *_a: Any, **_kw: Any) -> LLMResponse:
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_runner_emits_file_activity_start_and_end_on_write_file(tmp_path: Path) -> None:
    """A successful ``write_file`` call should produce one start and one end event."""

    tools = ToolRegistry()
    tools.register(WriteFileTool(workspace=tmp_path))

    provider = _StubProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="call-1",
                    name="write_file",
                    arguments={"path": "out.txt", "content": "alpha\nbeta\n"},
                ),
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ])

    captured: list[dict[str, Any]] = []

    async def _capture(payload: dict[str, Any]) -> None:
        captured.append(payload)

    runner = AgentRunner(provider)
    await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "write it"}],
        tools=tools,
        model="stub/model",
        workspace=tmp_path,
        file_activity_callback=_capture,
        max_iterations=4,
        max_tool_result_chars=4096,
    ))

    phases = [event["phase"] for event in captured]
    assert phases == ["start", "end"], captured

    end_event = captured[-1]
    assert end_event["tool"] == "write_file"
    assert end_event["path"] == "out.txt"
    assert end_event["status"] == "done"
    assert end_event["added"] == 2
    assert end_event["deleted"] == 0
    assert end_event["call_id"] == "call-1"


@pytest.mark.asyncio
async def test_runner_emits_error_event_when_tool_fails(tmp_path: Path) -> None:
    """A ``write_file`` returning an Error string should produce start + error."""

    tools = ToolRegistry()

    class _FailingWrite(WriteFileTool):
        async def execute(self, **_kw: Any) -> str:
            return "Error: disk on fire"

    tools.register(_FailingWrite(workspace=tmp_path))

    provider = _StubProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="call-2",
                    name="write_file",
                    arguments={"path": "out.txt", "content": "x"},
                ),
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ])

    captured: list[dict[str, Any]] = []

    async def _capture(payload: dict[str, Any]) -> None:
        captured.append(payload)

    runner = AgentRunner(provider)
    await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "write it"}],
        tools=tools,
        model="stub/model",
        workspace=tmp_path,
        file_activity_callback=_capture,
        max_iterations=4,
        max_tool_result_chars=4096,
    ))

    phases = [event["phase"] for event in captured]
    assert phases == ["start", "error"], captured
    assert "disk on fire" in (captured[-1].get("error") or "")


# ---------------------------------------------------------------------------
# Streaming path (Phase 2): live events from StreamingFileEditTracker
# ---------------------------------------------------------------------------


class _StreamingHook(AgentHook):
    """AgentHook subclass that opts into the streaming code path."""

    def wants_streaming(self) -> bool:
        return True


class _StreamingStubProvider(LLMProvider):
    """Calls ``on_tool_call_delta`` with synthetic frames before returning."""

    def __init__(
        self,
        deltas: list[dict[str, Any]],
        responses: list[LLMResponse],
    ) -> None:
        super().__init__()
        self._deltas = list(deltas)
        self._responses = list(responses)
        self.tool_call_frames_seen: list[dict[str, Any]] = []

    def get_default_model(self) -> str:
        return "stub/model"

    async def chat(self, *_a: Any, **_kw: Any) -> LLMResponse:
        return self._responses.pop(0)

    async def chat_stream(  # type: ignore[override]
        self,
        *_a: Any,
        on_content_delta: Any = None,
        on_tool_call_delta: Any = None,
        **_kw: Any,
    ) -> LLMResponse:
        if on_tool_call_delta is not None:
            for frame in self._deltas:
                self.tool_call_frames_seen.append(frame)
                await on_tool_call_delta(frame)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_streaming_path_emits_live_then_end_with_exact_diff(
    tmp_path: Path,
) -> None:
    """Live events fire mid-stream; sync ``end`` arrives with the exact diff."""

    tools = ToolRegistry()
    tools.register(WriteFileTool(workspace=tmp_path))

    # Three streamed frames build up the JSON for one ``write_file`` call.
    deltas = [
        {
            "index": 0,
            "call_id": "call-stream-1",
            "name": "write_file",
            "arguments_delta": '{"path": "out.txt", "content": "alpha\\n',
        },
        {"index": 0, "arguments_delta": "beta\\n"},
        {"index": 0, "arguments_delta": 'gamma"}'},
    ]
    responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="call-stream-1",
                    name="write_file",
                    arguments={
                        "path": "out.txt",
                        "content": "alpha\nbeta\ngamma",
                    },
                ),
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ]
    provider = _StreamingStubProvider(deltas, responses)

    captured: list[dict[str, Any]] = []

    async def _capture(payload: dict[str, Any]) -> None:
        captured.append(payload)

    runner = AgentRunner(provider)
    await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "write it"}],
        tools=tools,
        model="stub/model",
        workspace=tmp_path,
        file_activity_callback=_capture,
        hook=_StreamingHook(),
        max_iterations=4,
        max_tool_result_chars=4096,
    ))

    # We expect at least one live "start" event (approximate=True) and then a
    # final "end" event with exact counts. The synchronous start MUST be
    # suppressed so it does not overwrite the live counts.
    live_events = [
        ev for ev in captured
        if ev["phase"] == "start" and ev.get("approximate") is True
        and ev["call_id"] == "call-stream-1"
    ]
    end_events = [ev for ev in captured if ev["phase"] == "end"]
    assert live_events, captured
    # No non-approximate start should appear for this call.
    for ev in captured:
        if ev["phase"] == "start" and ev["call_id"] == "call-stream-1":
            assert ev.get("approximate") is True, ev
    assert len(end_events) == 1
    assert end_events[0]["call_id"] == "call-stream-1"
    assert end_events[0]["added"] == 3
    assert end_events[0]["deleted"] == 0
    assert end_events[0]["approximate"] is False


@pytest.mark.asyncio
async def test_streaming_tracker_error_unmatched_for_dropped_calls(
    tmp_path: Path,
) -> None:
    """Streamed call that the final response dropped → standalone error event."""

    tools = ToolRegistry()
    tools.register(WriteFileTool(workspace=tmp_path))

    deltas = [
        {
            "index": 0,
            "call_id": "call-stream-A",
            "name": "write_file",
            "arguments_delta": '{"path": "a.txt", "content": "x"}',
        },
        {
            "index": 1,
            "call_id": "call-stream-B",
            "name": "write_file",
            "arguments_delta": '{"path": "b.txt", "content": "y"}',
        },
    ]
    # Final response keeps only call-A.
    responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="call-stream-A",
                    name="write_file",
                    arguments={"path": "a.txt", "content": "x"},
                ),
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ]
    provider = _StreamingStubProvider(deltas, responses)

    captured: list[dict[str, Any]] = []

    async def _capture(payload: dict[str, Any]) -> None:
        captured.append(payload)

    runner = AgentRunner(provider)
    await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "write both"}],
        tools=tools,
        model="stub/model",
        workspace=tmp_path,
        file_activity_callback=_capture,
        hook=_StreamingHook(),
        max_iterations=4,
        max_tool_result_chars=4096,
    ))

    error_events = [ev for ev in captured if ev["phase"] == "error"]
    assert any(ev["call_id"] == "call-stream-B" for ev in error_events), captured


@pytest.mark.asyncio
async def test_streamed_call_ids_skip_sync_start_under_concurrent_tools(
    tmp_path: Path,
) -> None:
    """When ``concurrent_tools=True`` the sequential-batch optimization is
    bypassed in favor of ``asyncio.gather``. ``streamed_call_ids`` must still
    reach every parallel ``_run_tool`` so the synchronous ``start`` event is
    suppressed for both calls — otherwise the WebUI would see live counts
    flicker back to 0 mid-burst.
    """

    tools = ToolRegistry()
    tools.register(WriteFileTool(workspace=tmp_path))

    deltas = [
        {
            "index": 0,
            "call_id": "par-A",
            "name": "write_file",
            "arguments_delta": '{"path": "a.txt", "content": "alpha\\n"}',
        },
        {
            "index": 1,
            "call_id": "par-B",
            "name": "write_file",
            "arguments_delta": '{"path": "b.txt", "content": "beta\\ngamma\\n"}',
        },
    ]
    responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="par-A", name="write_file",
                    arguments={"path": "a.txt", "content": "alpha\n"},
                ),
                ToolCallRequest(
                    id="par-B", name="write_file",
                    arguments={"path": "b.txt", "content": "beta\ngamma\n"},
                ),
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ]
    provider = _StreamingStubProvider(deltas, responses)

    captured: list[dict[str, Any]] = []

    async def _capture(payload: dict[str, Any]) -> None:
        captured.append(payload)

    runner = AgentRunner(provider)
    await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "write both"}],
        tools=tools,
        model="stub/model",
        workspace=tmp_path,
        file_activity_callback=_capture,
        hook=_StreamingHook(),
        concurrent_tools=True,
        max_iterations=4,
        max_tool_result_chars=4096,
    ))

    # Both call_ids must have at least one live (approximate=True) start and
    # exactly one non-approximate end. The synchronous start must be skipped
    # for both — i.e., no ``start`` event with approximate=False under those
    # call_ids.
    for cid in ("par-A", "par-B"):
        events = [ev for ev in captured if ev["call_id"] == cid]
        starts = [ev for ev in events if ev["phase"] == "start"]
        ends = [ev for ev in events if ev["phase"] == "end"]
        assert starts, f"{cid}: no start event captured"
        assert all(ev.get("approximate") is True for ev in starts), (
            f"{cid}: synchronous start leaked through — would zero live counts"
        )
        assert len(ends) == 1, f"{cid}: expected exactly one end, got {len(ends)}"
        assert ends[0]["approximate"] is False
