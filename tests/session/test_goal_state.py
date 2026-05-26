"""Tests for sustained-goal session metadata helpers."""

from __future__ import annotations

import json

from pythinker.session.goal_state import (
    GOAL_STATE_KEY,
    goal_state_runtime_lines,
    goal_state_ws_blob,
    parse_goal_state,
    runner_wall_llm_timeout_s,
    sustained_goal_active,
)
from pythinker.session.manager import SessionManager


def test_parse_goal_state_accepts_dict_and_json_string():
    assert parse_goal_state({"status": "active"}) == {"status": "active"}
    assert parse_goal_state(json.dumps({"status": "active"})) == {"status": "active"}
    assert parse_goal_state("not json") is None
    assert parse_goal_state(None) is None


def test_sustained_goal_active_only_when_status_active():
    assert sustained_goal_active({GOAL_STATE_KEY: {"status": "active"}}) is True
    assert sustained_goal_active({GOAL_STATE_KEY: {"status": "completed"}}) is False
    assert sustained_goal_active({}) is False
    assert sustained_goal_active(None) is False


def test_legacy_key_is_read():
    assert sustained_goal_active({"thread_goal": {"status": "active"}}) is True


def test_runtime_lines_render_active_objective():
    meta = {GOAL_STATE_KEY: {"status": "active", "objective": "Ship X", "ui_summary": "ship"}}
    lines = goal_state_runtime_lines(meta)
    assert lines[0] == "Goal (active):"
    assert "Ship X" in lines
    assert "Summary: ship" in lines
    assert goal_state_runtime_lines({GOAL_STATE_KEY: {"status": "completed"}}) == []


def test_ws_blob_shape():
    active = goal_state_ws_blob({GOAL_STATE_KEY: {"status": "active", "objective": "Ship X"}})
    assert active == {"active": True, "objective": "Ship X"}
    assert goal_state_ws_blob({}) == {"active": False}


def test_runner_wall_timeout_disabled_only_when_goal_active(tmp_path):
    sessions = SessionManager(tmp_path)
    assert runner_wall_llm_timeout_s(sessions, "cli:c") is None
    assert (
        runner_wall_llm_timeout_s(
            sessions, "cli:c", metadata={GOAL_STATE_KEY: {"status": "active"}}
        )
        == 0.0
    )
