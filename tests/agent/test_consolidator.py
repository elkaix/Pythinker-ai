"""Tests for the lightweight Consolidator — append-only to HISTORY.md."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pythinker.agent.memory import Consolidator, MemoryStore
from pythinker.utils.prompt_templates import render_template


class TestConsolidatorPromptShape:
    """Phase 3 (coding-prompt uplift): the rendered prompt advertises the
    six structured section tags that downstream MEMORY.md ingestion
    relies on for scan-friendliness."""

    def test_consolidator_prompt_advertises_structured_tags(self):
        rendered = render_template("agent/consolidator_archive.md", strip=True)
        for tag in (
            "<current_focus>",
            "<active_issues>",
            "<code_state>",
            "<completed_tasks>",
            "<environment>",
            "<important_context>",
        ):
            assert tag in rendered, f"missing section tag: {tag}"

    def test_consolidator_prompt_keeps_core_compression_directives(self):
        """Compression rules must survive: secrets-mask, 5-line snippet cap,
        flat (no nested) tags. Drift here = tokens leaking."""
        rendered = render_template("agent/consolidator_archive.md", strip=True)
        assert "Mask secrets" in rendered
        assert "5 lines" in rendered
        assert "flat" in rendered.lower()


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


@pytest.fixture
def mock_provider():
    p = MagicMock()
    p.chat_with_retry = AsyncMock()
    return p


@pytest.fixture
def consolidator(store, mock_provider):
    sessions = MagicMock()
    sessions.save = MagicMock()
    return Consolidator(
        store=store,
        provider=mock_provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=5100,
        build_messages=MagicMock(return_value=[]),
        get_tool_definitions=MagicMock(return_value=[]),
        max_completion_tokens=100,
    )


class TestConsolidatorSummarize:
    async def test_summarize_appends_to_history(self, consolidator, mock_provider, store):
        """Consolidator should call LLM to summarize, then append to HISTORY.md."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module."
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done, fixed the race condition."},
        ]
        result = await consolidator.archive(messages)
        assert result == "User fixed a bug in the auth module."
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1

    async def test_summarize_raw_dumps_on_llm_failure(self, consolidator, mock_provider, store):
        """On LLM failure, raw-dump messages to HISTORY.md."""
        mock_provider.chat_with_retry.side_effect = Exception("API error")
        messages = [{"role": "user", "content": "hello"}]
        result = await consolidator.archive(messages)
        assert result is None  # no summary on raw dump fallback
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" in entries[0]["content"]

    async def test_summarize_skips_empty_messages(self, consolidator):
        result = await consolidator.archive([])
        assert result is None


class TestConsolidatorArchiveErrorHandling:
    """archive() must fall back to raw_archive when the LLM returns an error
    response (finish_reason == 'error'), e.g. overloaded / quota exceeded.
    """

    async def test_archive_falls_back_on_error_finish_reason(self, consolidator, mock_provider, store):
        """LLM returning finish_reason='error' should trigger raw_archive, not write error text."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Error: {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'overloaded_error (529)'}}",
            finish_reason="error",
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done, fixed the race condition."},
        ]
        result = await consolidator.archive(messages)
        assert result is None
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" in entries[0]["content"]
        assert "Error:" not in entries[0]["content"]

    async def test_archive_preserves_summary_on_success(self, consolidator, mock_provider, store):
        """Normal LLM response should still produce a proper summary entry."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module.",
            finish_reason="stop",
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done."},
        ]
        result = await consolidator.archive(messages)
        assert result == "User fixed a bug in the auth module."
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" not in entries[0]["content"]


class TestConsolidatorTokenBudget:
    async def test_prompt_below_threshold_does_not_consolidate(self, consolidator):
        """No consolidation when tokens are within budget."""
        session = MagicMock()
        session.last_consolidated = 0
        session.messages = [{"role": "user", "content": "hi"}]
        session.key = "test:key"
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value=True)
        await consolidator.maybe_consolidate_by_tokens(session)
        consolidator.archive.assert_not_called()

    async def test_chunk_cap_preserves_user_turn_boundary(self, consolidator):
        """Chunk cap should rewind to the last user boundary within the cap."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {
                "role": "user" if i in {0, 50, 61} else "assistant",
                "content": f"m{i}",
            }
            for i in range(70)
        ]
        # New session-refresh guard re-reads via get_or_create; return the same
        # session so the test continues to operate on the in-test MagicMock.
        consolidator.sessions.get_or_create = MagicMock(return_value=session)
        consolidator.estimate_session_prompt_tokens = MagicMock(
            side_effect=[(1200, "tiktoken"), (400, "tiktoken")]
        )
        consolidator.pick_consolidation_boundary = MagicMock(return_value=(61, 999))
        consolidator.archive = AsyncMock(return_value=True)

        await consolidator.maybe_consolidate_by_tokens(session)

        archived_chunk = consolidator.archive.await_args.args[0]
        assert len(archived_chunk) == 50
        assert archived_chunk[0]["content"] == "m0"
        assert archived_chunk[-1]["content"] == "m49"
        assert session.last_consolidated == 50

    async def test_chunk_cap_skips_when_no_user_boundary_within_cap(self, consolidator):
        """If the cap would cut mid-turn, consolidation should skip that round."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {
                "role": "user" if i in {0, 61} else "assistant",
                "content": f"m{i}",
            }
            for i in range(70)
        ]
        consolidator.sessions.get_or_create = MagicMock(return_value=session)
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(1200, "tiktoken"))
        consolidator.pick_consolidation_boundary = MagicMock(return_value=(61, 999))
        consolidator.archive = AsyncMock(return_value=True)

        await consolidator.maybe_consolidate_by_tokens(session)

        consolidator.archive.assert_not_awaited()
        assert session.last_consolidated == 0


def test_consolidator_uses_budget_policy_target(tmp_path, monkeypatch):
    """Consolidation target should be policy.target, not hand-rolled offsets."""
    from pythinker.agent.budget import BudgetPolicy
    from pythinker.agent.memory.consolidator import Consolidator

    consolidator = Consolidator(
        store=MagicMock(),
        provider=MagicMock(generation=MagicMock(max_tokens=24_000)),
        model="gpt-5.5",
        sessions=MagicMock(),
        context_window_tokens=272_000,
        build_messages=lambda **_: [],
        get_tool_definitions=lambda: [],
        max_completion_tokens=24_000,
    )
    expected = BudgetPolicy.for_model(window=272_000, output_reserve=24_000)
    assert consolidator.policy.target == expected.target
    assert consolidator.policy.soft == expected.soft


def test_probe_includes_current_message():
    """A real user message should be projected into the token probe."""
    from pythinker.agent.memory.consolidator import Consolidator
    from pythinker.session.manager import Session

    provider = MagicMock()
    provider.generation = MagicMock(max_tokens=4096)
    provider.estimate_prompt_tokens = None

    big = "word " * 2000
    calls: list[str] = []

    def build_messages(**kwargs):
        calls.append(kwargs.get("current_message") or "")
        return [{"role": "user", "content": kwargs.get("current_message", "")}]

    c = Consolidator(
        store=MagicMock(),
        provider=provider,
        model="gpt-5.5",
        sessions=MagicMock(),
        context_window_tokens=65_536,
        build_messages=build_messages,
        get_tool_definitions=lambda: [],
    )
    session = Session(key="cli:t")
    session.messages = [{"role": "user", "content": "old"}]

    c.estimate_session_prompt_tokens(session)
    c.estimate_session_prompt_tokens(session, current_message=big)

    assert calls[0] == "[token-probe]"
    assert calls[1] == big


# ---------------------------------------------------------------------------
# compact_idle_session — lock-protected idle truncation path used by AutoCompact
# ---------------------------------------------------------------------------


class TestCompactIdleSession:
    @pytest.fixture
    def real_session_consolidator(self, tmp_path, mock_provider):
        """Consolidator backed by a real SessionManager so compact_idle_session
        round-trips through invalidate/get_or_create/save."""
        from pythinker.agent.memory.consolidator import Consolidator
        from pythinker.agent.memory.store import MemoryStore
        from pythinker.session.manager import SessionManager

        sessions = SessionManager(tmp_path / "sessions")
        return Consolidator(
            store=MemoryStore(tmp_path / "memory"),
            provider=mock_provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=5100,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
            max_completion_tokens=100,
        ), sessions

    async def test_compact_archives_prefix_keeps_suffix(self, real_session_consolidator, mock_provider):
        """compact_idle_session archives old messages and retains a recent suffix."""
        c, sessions = real_session_consolidator
        session = sessions.get_or_create("test:idle")
        session.messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
            for i in range(20)
        ]
        sessions.save(session)
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="summary text", finish_reason="stop",
        )

        summary = await c.compact_idle_session("test:idle", max_suffix=4)

        assert summary == "summary text"
        refreshed = sessions.get_or_create("test:idle")
        assert len(refreshed.messages) <= 20
        assert refreshed.last_consolidated == 0
        # Summary persisted in metadata for prepare_session() pickup
        assert refreshed.metadata.get("_last_summary", {}).get("text") == "summary text"

    async def test_compact_empty_session_just_touches_timestamp(self, real_session_consolidator):
        """No tail to archive: bump updated_at and return ''."""
        c, sessions = real_session_consolidator
        session = sessions.get_or_create("test:empty")
        sessions.save(session)

        summary = await c.compact_idle_session("test:empty")
        assert summary == ""

    async def test_compact_skips_nothing_summary(self, real_session_consolidator, mock_provider):
        """Archive returning '(nothing)' should not persist a summary marker."""
        c, sessions = real_session_consolidator
        session = sessions.get_or_create("test:nothing")
        session.messages = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
            {"role": "user", "content": "e"},
            {"role": "assistant", "content": "f"},
        ]
        sessions.save(session)
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="(nothing)", finish_reason="stop",
        )

        summary = await c.compact_idle_session("test:nothing", max_suffix=2)
        assert summary == "(nothing)"
        refreshed = sessions.get_or_create("test:nothing")
        assert "_last_summary" not in refreshed.metadata

    async def test_compact_llm_failure_returns_none(self, real_session_consolidator, mock_provider):
        """LLM error path: archive() returns None, compact returns None too."""
        c, sessions = real_session_consolidator
        session = sessions.get_or_create("test:fail")
        session.messages = [
            {"role": "user", "content": f"m{i}"} for i in range(6)
        ]
        sessions.save(session)
        mock_provider.chat_with_retry.side_effect = Exception("LLM down")

        summary = await c.compact_idle_session("test:fail", max_suffix=2)
        assert summary is None  # archive falls back to raw_archive

    async def test_compact_uses_session_lock(self, real_session_consolidator):
        """compact_idle_session must acquire Consolidator.get_lock(key)."""
        c, sessions = real_session_consolidator
        session = sessions.get_or_create("test:lock")
        sessions.save(session)

        lock = c.get_lock("test:lock")
        await lock.acquire()
        try:
            done = asyncio.Event()

            async def compact_call():
                await c.compact_idle_session("test:lock")
                done.set()

            task = asyncio.create_task(compact_call())
            await asyncio.sleep(0.01)
            assert not done.is_set(), "compact should block on the per-session lock"
        finally:
            lock.release()
        await asyncio.wait_for(task, timeout=1.0)


class TestMaybeConsolidateRefreshGuard:
    async def test_refresh_swaps_session_when_replaced(self, consolidator):
        """If sessions.get_or_create returns a different session, swap in the fresh one."""
        stale = MagicMock()
        stale.key = "test:race"
        stale.last_consolidated = 0
        stale.messages = [{"role": "user", "content": "old"}]

        fresh = MagicMock()
        fresh.key = "test:race"
        fresh.last_consolidated = 0
        fresh.messages = [{"role": "user", "content": "new"}]

        consolidator.sessions.get_or_create = MagicMock(return_value=fresh)
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value="ok")

        await consolidator.maybe_consolidate_by_tokens(stale)

        # Refresh swap returned early on the fresh session (under budget),
        # so archive must not have been called against either reference.
        consolidator.archive.assert_not_awaited()
        consolidator.sessions.get_or_create.assert_called_once_with("test:race")

    async def test_empty_guard_skips_after_refresh(self, consolidator):
        """If the refreshed session has no messages, return without archiving."""
        stale = MagicMock()
        stale.key = "test:empty"
        stale.last_consolidated = 0
        stale.messages = [{"role": "user", "content": "stale"}]

        fresh = MagicMock()
        fresh.key = "test:empty"
        fresh.messages = []  # truthiness check should short-circuit

        consolidator.sessions.get_or_create = MagicMock(return_value=fresh)
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(999_999, "tiktoken"))
        consolidator.archive = AsyncMock(return_value="ok")

        await consolidator.maybe_consolidate_by_tokens(stale)

        consolidator.archive.assert_not_awaited()
