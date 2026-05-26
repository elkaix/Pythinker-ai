"""Runner keeps looping while a sustained goal is active.

When the model returns a final text response (no tool calls) but a goal is still
active, the runner injects a continuation prompt instead of stopping.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from pythinker.agent.runner import AgentRunner, AgentRunSpec
from pythinker.providers.base import LLMResponse

_MAX = 4096


def _provider(calls: dict[str, int]) -> MagicMock:
    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        calls["n"] += 1
        return LLMResponse(content="step done", tool_calls=[], usage={})

    # No streaming hook in these tests → the runner uses the non-streaming path.
    provider.chat_with_retry = chat_with_retry
    return provider


def _tools() -> MagicMock:
    tools = MagicMock()
    tools.get_definitions.return_value = []
    return tools


async def test_runner_continues_once_while_goal_active():
    calls = {"n": 0}
    runner = AgentRunner(_provider(calls))

    # Active for the first completion, then satisfied so the loop stops.
    def predicate() -> bool:
        return calls["n"] < 2

    result = await runner.run(AgentRunSpec(
        initial_messages=[], tools=_tools(), model="m",
        max_iterations=5, max_tool_result_chars=_MAX,
        goal_active_predicate=predicate,
    ))

    assert calls["n"] == 2  # continued once via goal-continue, then stopped
    assert result.final_content == "step done"


async def test_runner_stops_when_no_goal_active():
    calls = {"n": 0}
    runner = AgentRunner(_provider(calls))

    result = await runner.run(AgentRunSpec(
        initial_messages=[], tools=_tools(), model="m",
        max_iterations=5, max_tool_result_chars=_MAX,
        goal_active_predicate=lambda: False,
    ))

    assert calls["n"] == 1  # no continuation; stops after the first final response
    assert result.final_content == "step done"


async def test_runner_stops_without_predicate():
    calls = {"n": 0}
    runner = AgentRunner(_provider(calls))

    result = await runner.run(AgentRunSpec(
        initial_messages=[], tools=_tools(), model="m",
        max_iterations=5, max_tool_result_chars=_MAX,
    ))

    assert calls["n"] == 1
    assert result.final_content == "step done"
