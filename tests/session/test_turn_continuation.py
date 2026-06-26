"""Tests for pythinker.session.turn_continuation."""

from typing import Any

import pytest

from pythinker.session.turn_continuation import (
    INTERNAL_CONTINUATION_META,
    INTERNAL_CONTINUATION_PENDING_META,
    _MAX_GOAL_CONTINUATION_ROUNDS,
    build_continuation_metadata,
    clear_internal_continuation_state,
    continuation_available,
    goal_continuation_prompt,
    increment_goal_continuation_round,
    internal_continuation_inbound,
    internal_continuation_pending,
    internal_continuation_run_started_at,
    save_skip_for_turn,
    should_persist_user_message,
    should_stream_budget_response,
    strip_terminal_assistant,
)

_ACTIVE_GOAL: dict[str, Any] = {
    "goal_state": {"status": "active", "objective": "do stuff"}
}


def _active_session_meta() -> dict[str, Any]:
    return dict(_ACTIVE_GOAL)


class TestInternalContinuationFlags:
    def test_inbound_false_for_empty(self):
        assert not internal_continuation_inbound(None)
        assert not internal_continuation_inbound({})

    def test_inbound_true_when_set(self):
        assert internal_continuation_inbound({INTERNAL_CONTINUATION_META: True})

    def test_pending_false_for_empty(self):
        assert not internal_continuation_pending(None)

    def test_pending_true_when_set(self):
        assert internal_continuation_pending({INTERNAL_CONTINUATION_PENDING_META: True})

    def test_run_started_at_none_when_missing(self):
        assert internal_continuation_run_started_at(None) is None
        assert internal_continuation_run_started_at({}) is None

    def test_run_started_at_returns_float(self):
        meta = {"_internal_continuation_run_started_at": 1234567890.5}
        assert internal_continuation_run_started_at(meta) == pytest.approx(1234567890.5)


class TestShouldPersist:
    def test_persist_normal_message(self):
        assert should_persist_user_message({}) is True
        assert should_persist_user_message(None) is True

    def test_no_persist_continuation(self):
        assert should_persist_user_message({INTERNAL_CONTINUATION_META: True}) is False


class TestShouldStreamBudgetResponse:
    def test_stream_when_no_pending_queue(self):
        assert should_stream_budget_response(
            stop_reason="max_iterations",
            pending_queue_available=False,
            session_metadata=_active_session_meta(),
        )

    def test_stream_when_not_max_iterations(self):
        assert should_stream_budget_response(
            stop_reason="stop",
            pending_queue_available=True,
            session_metadata=_active_session_meta(),
        )

    def test_no_stream_when_continuation_available(self):
        assert not should_stream_budget_response(
            stop_reason="max_iterations",
            pending_queue_available=True,
            session_metadata=_active_session_meta(),
        )

    def test_stream_when_goal_inactive(self):
        assert should_stream_budget_response(
            stop_reason="max_iterations",
            pending_queue_available=True,
            session_metadata={"goal_state": {"status": "done"}},
        )


class TestContinuationAvailable:
    def test_available_with_active_goal(self):
        q = object()  # non-None pending_queue
        assert continuation_available(
            stop_reason="max_iterations",
            session_metadata=_active_session_meta(),
            pending_queue=q,
        )

    def test_not_available_without_queue(self):
        assert not continuation_available(
            stop_reason="max_iterations",
            session_metadata=_active_session_meta(),
            pending_queue=None,
        )

    def test_not_available_when_rounds_exhausted(self):
        meta = _active_session_meta()
        meta["_sustained_goal_continuation_rounds"] = _MAX_GOAL_CONTINUATION_ROUNDS
        q = object()
        assert not continuation_available(
            stop_reason="max_iterations",
            session_metadata=meta,
            pending_queue=q,
        )


class TestRoundCounter:
    def test_increment_from_zero(self):
        meta: dict[str, Any] = {}
        increment_goal_continuation_round(meta)
        assert meta["_sustained_goal_continuation_rounds"] == 1

    def test_increment_accumulates(self):
        meta: dict[str, Any] = {"_sustained_goal_continuation_rounds": 3}
        increment_goal_continuation_round(meta)
        assert meta["_sustained_goal_continuation_rounds"] == 4


class TestClearContinuationState:
    def test_clears_rounds_when_goal_inactive(self):
        meta: dict[str, Any] = {"_sustained_goal_continuation_rounds": 5}
        clear_internal_continuation_state(meta)
        assert "_sustained_goal_continuation_rounds" not in meta

    def test_preserves_rounds_when_goal_active(self):
        meta = _active_session_meta()
        meta["_sustained_goal_continuation_rounds"] = 5
        clear_internal_continuation_state(meta)
        assert meta["_sustained_goal_continuation_rounds"] == 5


class TestSaveSkipForTurn:
    def test_normal_turn_skip(self):
        skip = save_skip_for_turn(
            message_metadata={},
            initial_message_count=10,
            history_count=3,
            user_persisted_early=True,
        )
        assert skip == 1 + 3 + 1  # 5

    def test_continuation_turn_uses_initial_count(self):
        skip = save_skip_for_turn(
            message_metadata={INTERNAL_CONTINUATION_META: True},
            initial_message_count=10,
            history_count=3,
            user_persisted_early=False,
        )
        assert skip == 10


class TestStripTerminalAssistant:
    def test_strips_empty_terminal_assistant(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "thinking..."},
        ]
        result = strip_terminal_assistant(messages, "thinking...")
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_preserves_message_with_tool_calls(self):
        messages = [
            {"role": "assistant", "content": "x", "tool_calls": [{"id": "1"}]},
        ]
        result = strip_terminal_assistant(messages, "x")
        assert len(result) == 1

    def test_preserves_message_when_content_differs(self):
        messages = [{"role": "assistant", "content": "something else"}]
        result = strip_terminal_assistant(messages, "different")
        assert len(result) == 1


class TestBuildContinuationMetadata:
    def test_marks_as_internal(self):
        meta = build_continuation_metadata({"original_command": "/goal"})
        assert meta[INTERNAL_CONTINUATION_META] is True

    def test_strips_stream_keys(self):
        src = {"_stream_id": "abc", "_stream_end": True, "keep": "this"}
        meta = build_continuation_metadata(src)
        assert "_stream_id" not in meta
        assert "_stream_end" not in meta
        assert meta["keep"] == "this"

    def test_embeds_run_started_at(self):
        meta = build_continuation_metadata({}, run_started_at=999.5)
        assert meta["_internal_continuation_run_started_at"] == pytest.approx(999.5)


class TestGoalContinuationPrompt:
    def test_includes_goal_objective(self):
        meta = _active_session_meta()
        prompt = goal_continuation_prompt(meta)
        assert "sustained goal" in prompt.lower()

    def test_fallback_without_goal(self):
        prompt = goal_continuation_prompt(None)
        assert "tool-call budget" in prompt
