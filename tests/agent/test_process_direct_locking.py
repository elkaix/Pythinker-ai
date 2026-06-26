"""Session lock coverage for process_direct."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pythinker.agent.loop import AgentLoop
from pythinker.bus.events import OutboundMessage
from pythinker.bus.queue import MessageBus
from pythinker.providers.base import GenerationSettings, LLMResponse


def _make_loop(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (0, "test-counter")
    response = LLMResponse(content="done", tool_calls=[])
    provider.chat_with_retry = AsyncMock(return_value=response)
    provider.chat_stream_with_retry = AsyncMock(return_value=response)

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


@pytest.mark.asyncio
async def test_process_direct_reuses_existing_session_lock(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    loop._connect_mcp = AsyncMock()
    session_key = "api:fixed"
    lock = loop._session_locks.setdefault(session_key, asyncio.Lock())
    await lock.acquire()
    entered = asyncio.Event()

    async def _process_message(msg, **_kwargs):
        entered.set()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=msg.content)

    loop._process_message = _process_message
    task = asyncio.create_task(loop.process_direct("direct", session_key=session_key))
    try:
        await asyncio.sleep(0)
        assert not entered.is_set()

        lock.release()
        response = await asyncio.wait_for(task, timeout=1.0)

        assert entered.is_set()
        assert response is not None
        assert response.content == "direct"
    finally:
        if lock.locked():
            lock.release()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
