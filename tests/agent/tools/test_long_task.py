"""Tests for the long_task / complete_goal sustained-goal tools."""

from __future__ import annotations

from pythinker.agent.tools.long_task import CompleteGoalTool, LongTaskTool
from pythinker.session.goal_state import GOAL_STATE_KEY, sustained_goal_active
from pythinker.session.manager import SessionManager


def _bound(cls, sessions):
    tool = cls(sessions, bus=None)
    tool.set_context("cli", "c", effective_key="cli:c")
    return tool


async def test_long_task_records_active_goal(tmp_path):
    sessions = SessionManager(tmp_path)
    tool = _bound(LongTaskTool, sessions)

    result = await tool.execute(goal="Ship the feature", ui_summary="ship")

    assert "Goal recorded" in result
    meta = sessions.get_or_create("cli:c").metadata
    assert sustained_goal_active(meta) is True
    assert meta[GOAL_STATE_KEY]["objective"] == "Ship the feature"
    assert meta[GOAL_STATE_KEY]["ui_summary"] == "ship"


async def test_long_task_rejects_second_active_goal(tmp_path):
    sessions = SessionManager(tmp_path)
    tool = _bound(LongTaskTool, sessions)
    await tool.execute(goal="first")

    result = await tool.execute(goal="second")
    assert "already active" in result
    assert sessions.get_or_create("cli:c").metadata[GOAL_STATE_KEY]["objective"] == "first"


async def test_complete_goal_marks_completed(tmp_path):
    sessions = SessionManager(tmp_path)
    await _bound(LongTaskTool, sessions).execute(goal="do it")

    result = await _bound(CompleteGoalTool, sessions).execute(recap="done")
    assert "complete" in result.lower()
    meta = sessions.get_or_create("cli:c").metadata
    assert sustained_goal_active(meta) is False
    assert meta[GOAL_STATE_KEY]["status"] == "completed"
    assert meta[GOAL_STATE_KEY]["recap"] == "done"


async def test_complete_goal_noop_without_active_goal(tmp_path):
    sessions = SessionManager(tmp_path)
    result = await _bound(CompleteGoalTool, sessions).execute()
    assert "No active goal" in result


async def test_long_task_rejects_blank_goal(tmp_path):
    sessions = SessionManager(tmp_path)
    tool = _bound(LongTaskTool, sessions)
    result = await tool.execute(goal="   ")
    assert "non-empty" in result
    assert GOAL_STATE_KEY not in sessions.get_or_create("cli:c").metadata


async def test_long_task_requires_session_context(tmp_path):
    sessions = SessionManager(tmp_path)
    tool = LongTaskTool(sessions, bus=None)  # no set_context → no session key
    result = await tool.execute(goal="x")
    assert "requires an active chat session" in result
