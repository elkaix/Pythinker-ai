"""ContextBuilder mirrors an active sustained goal into the Runtime Context block."""

from __future__ import annotations

from pathlib import Path

from pythinker.agent.context import ContextBuilder
from pythinker.session.goal_state import GOAL_STATE_KEY


def _runtime_text(messages: list[dict]) -> str:
    """Extract the runtime-context text from the built user message."""
    content = messages[-1]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))


def test_active_goal_mirrored_into_runtime_context(tmp_path: Path) -> None:
    builder = ContextBuilder(workspace=tmp_path, timezone="UTC")
    messages = builder.build_messages(
        history=[],
        current_message="hi",
        channel="cli",
        chat_id="c",
        session_metadata={GOAL_STATE_KEY: {"status": "active", "objective": "Ship X"}},
    )
    text = _runtime_text(messages)
    assert "Goal (active):" in text
    assert "Ship X" in text


def test_no_goal_means_no_goal_lines(tmp_path: Path) -> None:
    builder = ContextBuilder(workspace=tmp_path, timezone="UTC")
    messages = builder.build_messages(
        history=[], current_message="hi", channel="cli", chat_id="c",
        session_metadata={},
    )
    assert "Goal (active):" not in _runtime_text(messages)


def test_completed_goal_not_mirrored(tmp_path: Path) -> None:
    builder = ContextBuilder(workspace=tmp_path, timezone="UTC")
    messages = builder.build_messages(
        history=[], current_message="hi", channel="cli", chat_id="c",
        session_metadata={GOAL_STATE_KEY: {"status": "completed", "objective": "Ship X"}},
    )
    assert "Goal (active):" not in _runtime_text(messages)
