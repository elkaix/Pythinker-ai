"""Tests for the /goal slash command (rewrites the turn to nudge long_task)."""

from __future__ import annotations

from pythinker.bus.events import InboundMessage
from pythinker.command.builtin import cmd_goal
from pythinker.command.router import CommandContext


def _ctx(content: str, args: str) -> CommandContext:
    msg = InboundMessage(
        channel="websocket", sender_id="u", chat_id="c", content=content, metadata={}
    )
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=content, args=args)


async def test_goal_without_args_returns_usage() -> None:
    ctx = _ctx("/goal", "")
    result = await cmd_goal(ctx)
    assert result is not None
    assert "Usage:" in result.content


async def test_goal_rewrites_content_and_continues() -> None:
    ctx = _ctx("/goal ship the release", "ship the release")
    result = await cmd_goal(ctx)
    # None → loop continues the rewritten message as a normal agent turn.
    assert result is None
    assert "long_task" in ctx.msg.content
    assert "ship the release" in ctx.msg.content
    assert ctx.msg.metadata["original_command"] == "/goal"
    assert "goal_started_at" in ctx.msg.metadata


def test_goal_is_registered_with_metadata() -> None:
    from pythinker.command import CommandRouter, register_builtin_commands
    from pythinker.command.metadata import BUILTIN_COMMAND_METADATA

    router = CommandRouter()
    register_builtin_commands(router)
    assert "/goal" in router._exact
    assert any(m.name == "/goal" for m in BUILTIN_COMMAND_METADATA)
