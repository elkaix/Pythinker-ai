"""End-to-end test: runner emits file-edit events to file_activity_callback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

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
