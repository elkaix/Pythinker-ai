"""Session lock coverage for prepare -> consolidate -> build and auto-compact."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pythinker.agent.loop import AgentLoop
from pythinker.bus.queue import MessageBus
from pythinker.providers.base import GenerationSettings, LLMResponse


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "gpt-5.5"
    provider.generation = GenerationSettings(max_tokens=4_096)
    provider.estimate_prompt_tokens = lambda *_a, **_kw: (10, "test")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    return provider


@pytest.mark.asyncio
async def test_inbound_path_does_not_deadlock(tmp_path):
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_provider(),
        workspace=tmp_path,
        model="gpt-5.5",
    )
    await asyncio.wait_for(loop.process_direct("hi", session_key="cli:t"), timeout=5.0)


@pytest.mark.asyncio
async def test_check_expired_skips_active_session_keys(tmp_path):
    """After the AutoCompact race-fix refactor, the 'don't compact during a
    live turn' guarantee is enforced by ``check_expired``'s active-keys
    filter rather than by sharing the AgentLoop's per-session turn lock.

    Verify the new contract: when a session key is reported as active,
    ``_archive`` is not scheduled for it; the Consolidator's own per-session
    lock is the only thing serializing concurrent compactions."""
    from datetime import datetime, timedelta

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_provider(),
        workspace=tmp_path,
        model="gpt-5.5",
        context_window_tokens=10_000,
        session_ttl_minutes=1,
    )

    key = "cli:t"
    session = loop.sessions.get_or_create(key)
    session.add_message("user", "u")
    session.add_message("assistant", "a")
    session.updated_at = datetime.now() - timedelta(minutes=10)  # well past TTL
    loop.sessions.save(session)

    scheduled: list[asyncio.Task] = []
    loop.auto_compact.check_expired(
        schedule_background=lambda coro: scheduled.append(asyncio.create_task(coro)),
        active_session_keys={key},
    )
    assert scheduled == [], "active session must not be scheduled for archival"

    loop.auto_compact.check_expired(
        schedule_background=lambda coro: scheduled.append(asyncio.create_task(coro)),
        active_session_keys=set(),
    )
    assert len(scheduled) == 1, "idle session should be scheduled when not active"
    for t in scheduled:
        t.cancel()
