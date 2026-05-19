import asyncio

import pytest

from pythinker.heartbeat.service import HeartbeatService
from pythinker.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    provider = DummyProvider([])

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_decide_returns_skip_when_no_tool_call(tmp_path) -> None:
    provider = DummyProvider([LLMResponse(content="no tool call", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    action, tasks = await service._decide("heartbeat content")
    assert action == "skip"
    assert tasks == ""


@pytest.mark.asyncio
async def test_trigger_now_executes_when_decision_is_run(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        )
    ])

    called_with: list[str] = []

    async def _on_execute(tasks: str) -> str:
        called_with.append(tasks)
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    result = await service.trigger_now()
    assert result == "done"
    assert called_with == ["check open tasks"]


@pytest.mark.asyncio
async def test_trigger_now_returns_none_when_decision_is_skip(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "skip"},
                )
            ],
        )
    ])

    async def _on_execute(tasks: str) -> str:
        return tasks

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    assert await service.trigger_now() is None


@pytest.mark.asyncio
async def test_tick_notifies_when_evaluator_says_yes(tmp_path, monkeypatch) -> None:
    """Phase 1 run -> Phase 2 execute -> Phase 3 evaluate=notify -> on_notify called."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] check deployments", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check deployments"},
                )
            ],
        ),
    ])

    executed: list[str] = []
    notified: list[str] = []

    async def _on_execute(tasks: str) -> str:
        executed.append(tasks)
        return "deployment failed on staging"

    async def _on_notify(response: str) -> None:
        notified.append(response)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        on_notify=_on_notify,
    )

    async def _eval_notify(*a, **kw):
        return True

    monkeypatch.setattr("pythinker.utils.evaluator.evaluate_response", _eval_notify)

    await service._tick()
    assert executed == ["check deployments"]
    assert notified == ["deployment failed on staging"]


@pytest.mark.asyncio
async def test_tick_suppresses_when_evaluator_says_no(tmp_path, monkeypatch) -> None:
    """Phase 1 run -> Phase 2 execute -> Phase 3 evaluate=silent -> on_notify NOT called."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] check status", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check status"},
                )
            ],
        ),
    ])

    executed: list[str] = []
    notified: list[str] = []

    async def _on_execute(tasks: str) -> str:
        executed.append(tasks)
        return "everything is fine, no issues"

    async def _on_notify(response: str) -> None:
        notified.append(response)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        on_notify=_on_notify,
    )

    async def _eval_silent(*a, **kw):
        return False

    monkeypatch.setattr("pythinker.utils.evaluator.evaluate_response", _eval_silent)

    await service._tick()
    assert executed == ["check status"]
    assert notified == []


def test_is_deliverable_unit_filters_finalization_fallback_and_leaks() -> None:
    """``_is_deliverable`` drops canned finalization messages and leaked reasoning."""
    deliverable = HeartbeatService._is_deliverable

    assert deliverable("deployment failed on staging") is True
    assert deliverable("everything looks fine") is True

    # Runner finalization fallback (case-insensitive).
    assert deliverable("I couldn't produce a final answer after retries.") is False

    # Leaked-reasoning patterns.
    for leak in (
        "Looked at HEARTBEAT.md and decided",
        "Judgment call: this is borderline",
        "My instructions say to skip",
        "Strict heartbeat interpretation suggests no",
        "I am supposed to summarize.",
        "Valid options are run or skip.",
    ):
        assert deliverable(leak) is False, leak


@pytest.mark.asyncio
async def test_tick_suppresses_non_deliverable_response(tmp_path, monkeypatch) -> None:
    """Pre-evaluator filter drops leaked-reasoning output without calling evaluator/notify."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] check deployments", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check deployments"},
                )
            ],
        ),
    ])

    notified: list[str] = []
    evaluator_called: list[bool] = []

    async def _on_execute(tasks: str) -> str:
        return "I looked at HEARTBEAT.md and decided to skip this turn."

    async def _on_notify(response: str) -> None:
        notified.append(response)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        on_notify=_on_notify,
    )

    async def _evaluator(*a, **kw):
        evaluator_called.append(True)
        return True

    monkeypatch.setattr("pythinker.utils.evaluator.evaluate_response", _evaluator)

    await service._tick()
    assert notified == []
    assert evaluator_called == [], "deliverability guard must run before the evaluator"


@pytest.mark.asyncio
async def test_decide_retries_transient_error_then_succeeds(tmp_path, monkeypatch) -> None:
    provider = DummyProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        ),
    ])

    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    action, tasks = await service._decide("heartbeat content")

    assert action == "run"
    assert tasks == "check open tasks"
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_decide_prompt_includes_current_time(tmp_path) -> None:
    """Phase 1 user prompt must contain current time so the LLM can judge task urgency."""

    captured_messages: list[dict] = []

    class CapturingProvider(LLMProvider):
        async def chat(self, *, messages=None, **kwargs) -> LLMResponse:
            if messages:
                captured_messages.extend(messages)
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="hb_1", name="heartbeat",
                        arguments={"action": "skip"},
                    )
                ],
            )

        def get_default_model(self) -> str:
            return "test-model"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=CapturingProvider(),
        model="test-model",
    )

    await service._decide("- [ ] check servers at 10:00 UTC")

    user_msg = captured_messages[1]
    assert user_msg["role"] == "user"
    assert "Current Time:" in user_msg["content"]



async def test_heartbeat_resolves_runtime_per_call(tmp_path):
    """llm_runtime resolver is called on each decide so swapped providers take effect."""
    from pythinker.utils.llm_runtime import LLMRuntime

    call_count = 0
    providers_seen: list[str] = []

    class PA(LLMProvider):
        async def chat(self, *, messages=None, **kwargs) -> LLMResponse:
            providers_seen.append("A")
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="x", name="heartbeat", arguments={"action": "skip"})
                ],
            )

        def get_default_model(self) -> str:
            return "model-a"

    class PB(LLMProvider):
        async def chat(self, *, messages=None, **kwargs) -> LLMResponse:
            providers_seen.append("B")
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="x", name="heartbeat", arguments={"action": "skip"})
                ],
            )

        def get_default_model(self) -> str:
            return "model-b"

    runtimes = [
        LLMRuntime(provider=PA(), model="model-a"),
        LLMRuntime(provider=PB(), model="model-b"),
    ]

    def resolver():
        nonlocal call_count
        rt = runtimes[min(call_count, len(runtimes) - 1)]
        call_count += 1
        return rt

    service = HeartbeatService(
        workspace=tmp_path,
        llm_runtime=resolver,
    )

    await service._decide("first")
    await service._decide("second")

    assert providers_seen == ["A", "B"]


async def test_heartbeat_requires_provider_or_runtime(tmp_path):
    """Constructor must reject the case where neither resolver nor provider+model is given."""
    import pytest

    with pytest.raises(ValueError):
        HeartbeatService(workspace=tmp_path)
