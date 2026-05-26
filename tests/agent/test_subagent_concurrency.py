"""Subagent concurrency cap (``agents.defaults.maxConcurrentSubagents``).

Default is 0 (unlimited), preserving prior behavior. A positive value caps how
many subagents run their LLM/tool loop at once; queued spawns wait on a
semaphore before doing any work.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from pythinker.agent.subagent import SubagentManager
from pythinker.bus.queue import MessageBus
from pythinker.runtime.context import RequestContext


def _manager(tmp_path, *, cap: int) -> SubagentManager:
    provider = MagicMock()
    provider.get_default_model.return_value = "m"
    return SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=4096,
        model="m",
        max_concurrent_subagents=cap,
    )


def test_unlimited_by_default(tmp_path):
    assert _manager(tmp_path, cap=0)._subagent_semaphore is None


def test_positive_cap_builds_semaphore(tmp_path):
    sm = _manager(tmp_path, cap=2)
    assert isinstance(sm._subagent_semaphore, asyncio.Semaphore)


async def test_cap_limits_concurrent_execution(tmp_path):
    parent_ctx = RequestContext.for_inbound(
        channel="cli", sender_id="u", chat_id="c", session_key="cli:c",
    )
    state = {"active": 0, "peak": 0}

    async def _run(_spec):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.02)
        state["active"] -= 1
        result = MagicMock()
        result.stop_reason = "completed"
        result.error = None
        result.final_content = "done"
        result.usage = {}
        result.tool_events = []
        return result

    with patch("pythinker.agent.subagent.AgentRunner") as mock_runner:
        mock_runner.return_value.run = AsyncMock(side_effect=_run)
        sm = _manager(tmp_path, cap=2)
        for i in range(5):
            await sm.spawn(
                task="do thing",
                label=f"t{i}",
                origin_channel="cli",
                origin_chat_id="c",
                session_key="cli:c",
                parent_context=parent_ctx,
                parent_egress=object(),
            )
        await asyncio.gather(*list(sm._running_tasks.values()), return_exceptions=True)

    assert state["peak"] <= 2
    assert state["peak"] >= 1
