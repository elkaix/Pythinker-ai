"""Internal turn-continuation helpers.

Keeps budget-boundary continuation policy out of AgentLoop. The loop calls
a small set of helpers; those helpers decide whether an internal continuation
is allowed and queue the next turn when it is.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from pythinker.session.goal_state import (
    goal_state_runtime_lines,
    sustained_goal_active,
    sustained_goal_turn,
)

INTERNAL_CONTINUATION_META = "_internal_continuation"
INTERNAL_CONTINUATION_KIND_META = "_internal_continuation_kind"
INTERNAL_CONTINUATION_PENDING_META = "_internal_continuation_pending"
INTERNAL_CONTINUATION_RUN_STARTED_AT_META = "_internal_continuation_run_started_at"

_GOAL_CONTINUATION_KIND = "sustained_goal"
_GOAL_CONTINUATION_SENDER = "system:continuation"
_GOAL_CONTINUATION_ROUNDS_KEY = "_sustained_goal_continuation_rounds"
_MAX_GOAL_CONTINUATION_ROUNDS = 12
_STRIPPED_INBOUND_META_KEYS = {
    "_stream_id",
    "_stream_delta",
    "_stream_end",
    "_resuming",
    INTERNAL_CONTINUATION_PENDING_META,
}


def internal_continuation_inbound(metadata: Mapping[str, Any] | None) -> bool:
    """True for an inbound message created by an internal continuation policy."""
    return bool(metadata and metadata.get(INTERNAL_CONTINUATION_META) is True)


def internal_continuation_pending(metadata: Mapping[str, Any] | None) -> bool:
    """True when the current turn scheduled an invisible continuation slice."""
    return bool(metadata and metadata.get(INTERNAL_CONTINUATION_PENDING_META) is True)


def internal_continuation_run_started_at(metadata: Mapping[str, Any] | None) -> float | None:
    """Return the user-visible run start propagated across continuation slices."""
    if not metadata:
        return None
    value = metadata.get(INTERNAL_CONTINUATION_RUN_STARTED_AT_META)
    if not isinstance(value, int | float):
        return None
    started_at = float(value)
    return started_at if started_at > 0 else None


def should_persist_user_message(metadata: Mapping[str, Any] | None) -> bool:
    """Return whether this inbound message should be persisted as user input."""
    return not internal_continuation_inbound(metadata)


def should_stream_budget_response(
    *,
    stop_reason: str,
    pending_queue_available: bool,
    session_metadata: Mapping[str, Any] | None,
    message_metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether the budget-boundary response should be sent to the user."""
    return not _continuation_available(
        stop_reason=stop_reason,
        pending_queue_available=pending_queue_available,
        session_metadata=session_metadata,
        message_metadata=message_metadata,
    )


def continuation_available(
    *,
    stop_reason: str,
    session_metadata: Mapping[str, Any] | None,
    message_metadata: Mapping[str, Any] | None = None,
    pending_queue: Any,
) -> bool:
    """True when an internal continuation should be queued for this turn."""
    return _continuation_available(
        stop_reason=stop_reason,
        pending_queue_available=pending_queue is not None,
        session_metadata=session_metadata,
        message_metadata=message_metadata,
    )


def clear_internal_continuation_state(metadata: MutableMapping[str, Any]) -> None:
    """Reset policy bookkeeping once its owning runtime mode is inactive."""
    if not sustained_goal_active(metadata):
        metadata.pop(_GOAL_CONTINUATION_ROUNDS_KEY, None)


def build_continuation_metadata(
    message_metadata: Mapping[str, Any] | None,
    *,
    run_started_at: float | None = None,
) -> dict[str, Any]:
    """Build metadata for an internal continuation inbound message."""
    metadata = dict(message_metadata or {})
    metadata[INTERNAL_CONTINUATION_META] = True
    metadata[INTERNAL_CONTINUATION_KIND_META] = _GOAL_CONTINUATION_KIND
    if run_started_at is not None:
        metadata[INTERNAL_CONTINUATION_RUN_STARTED_AT_META] = float(run_started_at)
    for key in _STRIPPED_INBOUND_META_KEYS:
        metadata.pop(key, None)
    return metadata


def increment_goal_continuation_round(session_metadata: MutableMapping[str, Any]) -> None:
    """Increment the per-session continuation-round counter."""
    try:
        rounds = int(session_metadata.get(_GOAL_CONTINUATION_ROUNDS_KEY) or 0)
    except (TypeError, ValueError):
        rounds = 0
    session_metadata[_GOAL_CONTINUATION_ROUNDS_KEY] = rounds + 1


def goal_continuation_prompt(metadata: Mapping[str, Any] | None) -> str:
    """Build the content for an internal continuation turn."""
    lines = goal_state_runtime_lines(metadata)
    if lines:
        goal = "\n".join(lines)
        return (
            "Continue the active sustained goal after the previous turn reached "
            "its tool-call budget.\n\n"
            f"{goal}\n\n"
            "Continue from the saved context. Do not mention the continuation "
            "boundary to the user. Use tools as needed, and call complete_goal "
            "when the objective is truly finished."
        )
    return (
        "Continue the active sustained goal after the previous turn reached "
        "its tool-call budget. Continue from the saved context. Do not mention "
        "the continuation boundary to the user. Use tools as needed, and call "
        "complete_goal when the objective is truly finished."
    )


def save_skip_for_turn(
    *,
    message_metadata: Mapping[str, Any] | None,
    initial_message_count: int,
    history_count: int,
    user_persisted_early: bool,
) -> int:
    """Return the persisted-message append boundary for this turn."""
    if internal_continuation_inbound(message_metadata):
        return initial_message_count
    return 1 + history_count + (1 if user_persisted_early else 0)


def strip_terminal_assistant(
    messages: list[dict[str, Any]],
    final_content: str | None,
) -> list[dict[str, Any]]:
    """Drop the synthetic max-iteration assistant message before saving history."""
    if not messages:
        return messages
    last = messages[-1]
    if last.get("role") != "assistant":
        return messages
    if final_content is None or last.get("content") != final_content:
        return messages
    if last.get("tool_calls"):
        return messages
    return messages[:-1]


def _continuation_available(
    *,
    stop_reason: str,
    pending_queue_available: bool,
    session_metadata: Mapping[str, Any] | None,
    message_metadata: Mapping[str, Any] | None = None,
) -> bool:
    if stop_reason != "max_iterations" or not pending_queue_available:
        return False
    return _goal_continuation_available(
        session_metadata,
        message_metadata=message_metadata,
    )


def _goal_continuation_available(
    session_metadata: Mapping[str, Any] | None,
    *,
    message_metadata: Mapping[str, Any] | None = None,
    max_rounds: int = _MAX_GOAL_CONTINUATION_ROUNDS,
) -> bool:
    if not sustained_goal_turn(session_metadata, message_metadata=message_metadata):
        return False
    if not sustained_goal_active(session_metadata):
        return False
    try:
        rounds = int((session_metadata or {}).get(_GOAL_CONTINUATION_ROUNDS_KEY) or 0)
    except (TypeError, ValueError):
        rounds = 0
    return rounds < max(0, max_rounds)
