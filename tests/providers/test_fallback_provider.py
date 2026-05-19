"""Tests for FallbackProvider model failover."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pythinker.config.schema import (
    AgentDefaults,
    Config,
    InlineFallbackConfig,
    ModelPresetConfig,
)
from pythinker.providers.base import LLMProvider, LLMResponse
from pythinker.providers.factory import (
    _inline_fallback_preset,
    _resolve_fallback_presets,
    build_provider_snapshot,
    provider_signature,
)
from pythinker.providers.fallback_provider import FallbackProvider


def _make_response(
    content: str = "ok",
    finish_reason: str = "stop",
    *,
    error_kind: str | None = None,
    error_status_code: int | None = None,
    error_type: str | None = None,
    error_code: str | None = None,
    error_should_retry: bool | None = None,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        finish_reason=finish_reason,
        error_kind=error_kind,
        error_status_code=error_status_code,
        error_type=error_type,
        error_code=error_code,
        error_should_retry=error_should_retry,
    )


def _error_response(content: str = "api error") -> LLMResponse:
    return _make_response(content, finish_reason="error", error_kind="server_error")


def _fallback(
    model: str,
    provider: str = "custom",
    *,
    max_tokens: int = 8192,
    context_window_tokens: int = 65_536,
    temperature: float = 0.1,
    reasoning_effort: str | None = None,
) -> ModelPresetConfig:
    return ModelPresetConfig(
        model=model,
        provider=provider,
        max_tokens=max_tokens,
        context_window_tokens=context_window_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )


class _FakeProvider(LLMProvider):
    """Fake provider for testing failover; records kwargs on each call."""

    def __init__(self, name: str = "fake", response: LLMResponse | None = None):
        super().__init__()
        self.name = name
        self._response = response or _make_response()
        self.chat_calls: list[dict[str, Any]] = []
        self.chat_stream_calls: list[dict[str, Any]] = []

    def get_default_model(self) -> str:
        return f"{self.name}/model"

    async def chat(self, *_args: Any, **kwargs: Any) -> LLMResponse:
        self.chat_calls.append(dict(kwargs))
        return self._response

    async def chat_stream(self, *_args: Any, **kwargs: Any) -> LLMResponse:
        self.chat_stream_calls.append(dict(kwargs))
        on_delta = kwargs.get("on_content_delta")
        if on_delta and self._response.content:
            await on_delta(self._response.content)
        return self._response


# ---------------------------------------------------------------------------
# Config-level: schema + factory plumbing
# ---------------------------------------------------------------------------


def test_fallback_models_default_empty() -> None:
    defaults = AgentDefaults()
    assert defaults.fallback_models == []


def test_fallback_models_accept_preset_refs_and_inline_configs() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "fallbackModels": [
                    "deep",
                    {
                        "provider": "openai",
                        "model": "gpt-4.1",
                        "maxTokens": 4096,
                    },
                ]
            }
        },
        "modelPresets": {
            "deep": {"provider": "anthropic", "model": "claude-opus-4-7"}
        },
    })

    assert config.agents.defaults.fallback_models[0] == "deep"
    assert config.agents.defaults.fallback_models[1] == InlineFallbackConfig(
        provider="openai",
        model="gpt-4.1",
        max_tokens=4096,
    )


def test_fallback_model_preset_ref_must_exist() -> None:
    with pytest.raises(ValueError, match="fallback_models.*not found"):
        Config.model_validate({
            "agents": {"defaults": {"fallbackModels": ["missing"]}},
            "modelPresets": {},
        })


def test_resolve_fallback_presets_mixes_refs_and_inline() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "modelPreset": "fast",
                "fallbackModels": [
                    "deep",
                    {"provider": "openai", "model": "gpt-4.1"},
                ],
            }
        },
        "modelPresets": {
            "fast": {"model": "anthropic/claude-opus-4-5", "provider": "anthropic"},
            "deep": {"model": "anthropic/claude-sonnet-4-6", "provider": "anthropic"},
        },
    })

    primary = config.resolve_preset()
    presets = _resolve_fallback_presets(config, primary)

    assert len(presets) == 2
    assert presets[0].model == "anthropic/claude-sonnet-4-6"
    assert presets[1].model == "gpt-4.1"
    assert presets[1].provider == "openai"


def test_inline_fallback_inherits_max_tokens_from_primary_when_unset() -> None:
    primary = ModelPresetConfig(model="m", provider="p", max_tokens=4096)
    fb = InlineFallbackConfig(model="fb", provider="other")  # no max_tokens
    resolved = _inline_fallback_preset(primary, fb)
    assert resolved.max_tokens == 4096


def test_inline_fallback_reasoning_effort_does_not_inherit_primary() -> None:
    primary = ModelPresetConfig(model="m", provider="p", reasoning_effort="high")
    fb = InlineFallbackConfig(model="fb", provider="other")  # no reasoning_effort
    resolved = _inline_fallback_preset(primary, fb)
    assert resolved.reasoning_effort is None


def test_provider_signature_changes_when_fallback_chain_changes() -> None:
    base = {
        "agents": {
            "defaults": {
                "modelPreset": "fast",
                "fallbackModels": ["deep"],
            }
        },
        "modelPresets": {
            "fast": {"model": "openai/gpt-4.1", "provider": "openai"},
            "deep": {"model": "anthropic/claude-sonnet-4-6", "provider": "anthropic"},
        },
        "providers": {
            "openai": {"apiKey": "primary-key"},
            "anthropic": {"apiKey": "fallback-key"},
        },
    }
    changed_fallback = {
        **base,
        "agents": {"defaults": {"modelPreset": "fast", "fallbackModels": ["backup"]}},
        "modelPresets": {
            **base["modelPresets"],
            "backup": {"model": "deepseek/deepseek-chat", "provider": "deepseek"},
        },
        "providers": {
            **base["providers"],
            "deepseek": {"apiKey": "deepseek-key"},
        },
    }
    changed_key = {
        **base,
        "providers": {
            "openai": {"apiKey": "primary-key"},
            "anthropic": {"apiKey": "new-fallback-key"},
        },
    }

    signature = provider_signature(Config.model_validate(base))
    assert signature != provider_signature(Config.model_validate(changed_fallback))
    assert signature != provider_signature(Config.model_validate(changed_key))


def test_provider_snapshot_uses_smallest_fallback_context_window() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "modelPreset": "fast",
                "fallbackModels": ["deep"],
            }
        },
        "modelPresets": {
            "fast": {
                "model": "openai/gpt-4.1",
                "provider": "openai",
                "contextWindowTokens": 128000,
            },
            "deep": {
                "model": "deepseek/deepseek-chat",
                "provider": "deepseek",
                "contextWindowTokens": 64000,
            },
        },
        "providers": {
            "openai": {"apiKey": "primary-key"},
            "deepseek": {"apiKey": "fallback-key"},
        },
    })

    with patch("pythinker.providers.openai_compat_provider.AsyncOpenAI"):
        snapshot = build_provider_snapshot(config)

    assert snapshot.context_window_tokens == 64000


def test_make_provider_wraps_with_fallback_when_chain_configured() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "modelPreset": "fast",
                "fallbackModels": ["deep"],
            }
        },
        "modelPresets": {
            "fast": {"model": "openai/gpt-4.1", "provider": "openai"},
            "deep": {"model": "anthropic/claude-sonnet-4-6", "provider": "anthropic"},
        },
        "providers": {
            "openai": {"apiKey": "primary-key"},
            "anthropic": {"apiKey": "fallback-key"},
        },
    })

    from pythinker.providers.factory import make_provider

    with patch("pythinker.providers.openai_compat_provider.AsyncOpenAI"):
        provider = make_provider(config)

    assert isinstance(provider, FallbackProvider)


def test_make_provider_returns_plain_when_chain_empty() -> None:
    config = Config.model_validate({
        "agents": {"defaults": {"model": "openai/gpt-4.1"}},
        "providers": {"openai": {"apiKey": "primary-key"}},
    })

    from pythinker.providers.factory import make_provider

    with patch("pythinker.providers.openai_compat_provider.AsyncOpenAI"):
        provider = make_provider(config)

    assert not isinstance(provider, FallbackProvider)


# ---------------------------------------------------------------------------
# FallbackProvider behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_fallback_when_primary_succeeds() -> None:
    primary = _FakeProvider("primary", _make_response("primary ok"))
    factory = MagicMock()
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "primary ok"
    assert result.finish_reason == "stop"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_on_primary_error() -> None:
    primary = _FakeProvider("primary", _error_response())
    fallback = _FakeProvider("fallback", _make_response("fallback ok"))
    factory = MagicMock(return_value=fallback)

    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}], model="primary-model")
    assert result.content == "fallback ok"
    assert result.finish_reason == "stop"
    assert primary.chat_calls[0]["model"] == "primary-model"
    assert fallback.chat_calls[0]["model"] == "fallback-a"


@pytest.mark.asyncio
async def test_no_fallback_when_content_already_streamed() -> None:
    primary = _FakeProvider("primary", _error_response())
    factory = MagicMock()
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    async def _delta(_text: str) -> None:
        pass

    result = await fb.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=_delta,
    )
    assert result.finish_reason == "error"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_failover_on_rate_limit_text() -> None:
    primary = _FakeProvider("primary", _error_response("rate limit exceeded"))
    fallback = _FakeProvider("fallback", _make_response("fallback ok"))
    factory = MagicMock(return_value=fallback)
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "fallback ok"
    factory.assert_called_once()


@pytest.mark.asyncio
async def test_no_fallback_on_bad_request() -> None:
    primary = _FakeProvider(
        "primary",
        _make_response(
            "invalid request",
            finish_reason="error",
            error_status_code=400,
            error_kind="invalid_request",
        ),
    )
    factory = MagicMock()
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.finish_reason == "error"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_no_fallback_on_auth_error() -> None:
    primary = _FakeProvider(
        "primary",
        _make_response(
            "unauthorized",
            finish_reason="error",
            error_status_code=401,
            error_kind="authentication",
        ),
    )
    factory = MagicMock()
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.finish_reason == "error"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_failover_on_timeout_kind() -> None:
    primary = _FakeProvider(
        "primary",
        _make_response("timed out", finish_reason="error", error_kind="timeout"),
    )
    fallback = _FakeProvider("fallback", _make_response("fallback ok"))
    factory = MagicMock(return_value=fallback)
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "fallback ok"


@pytest.mark.asyncio
async def test_fallback_tries_models_in_order() -> None:
    primary = _FakeProvider("primary", _error_response("primary fail"))
    fallback_a = _FakeProvider("a", _error_response("a fail"))
    fallback_b = _FakeProvider("b", _make_response("b ok"))
    factory = MagicMock(side_effect=[fallback_a, fallback_b])

    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a"), _fallback("fallback-b")],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "b ok"
    assert factory.call_count == 2


@pytest.mark.asyncio
async def test_all_fallbacks_fail_returns_last_error() -> None:
    primary = _FakeProvider("primary", _error_response("primary fail"))
    fallback = _FakeProvider("fallback", _error_response("all fail"))
    factory = MagicMock(return_value=fallback)

    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.finish_reason == "error"
    assert "all fail" in result.content


@pytest.mark.asyncio
async def test_factory_exception_skips_that_model() -> None:
    primary = _FakeProvider("primary", _error_response())
    fallback_b = _FakeProvider("b", _make_response("b ok"))
    factory = MagicMock(side_effect=[ValueError("no key"), fallback_b])

    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a"), _fallback("fallback-b")],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "b ok"
    assert factory.call_count == 2


@pytest.mark.asyncio
async def test_fallback_uses_fallback_generation_fields() -> None:
    primary = _FakeProvider("primary", _error_response())
    fallback = _FakeProvider("fallback", _make_response("ok"))
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[
            _fallback(
                "fallback-model",
                max_tokens=1234,
                temperature=0.4,
                reasoning_effort=None,
            )
        ],
        provider_factory=MagicMock(return_value=fallback),
    )

    await fb.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="primary-model",
        max_tokens=8192,
        temperature=0.1,
        reasoning_effort="high",
    )

    assert fallback.chat_calls[0]["model"] == "fallback-model"
    assert fallback.chat_calls[0]["max_tokens"] == 1234
    assert fallback.chat_calls[0]["temperature"] == 0.4
    assert "reasoning_effort" not in fallback.chat_calls[0]


@pytest.mark.asyncio
async def test_empty_fallback_list_passes_error_through() -> None:
    primary = _FakeProvider("primary", _error_response())
    factory = MagicMock()
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[],
        provider_factory=factory,
    )

    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.finish_reason == "error"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_chat_stream_failover_when_no_content_streamed() -> None:
    primary = _FakeProvider("primary", _error_response(""))
    fallback = _FakeProvider("fallback", _make_response("stream ok"))
    factory = MagicMock(return_value=fallback)

    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    result = await fb.chat_stream(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "stream ok"
    assert result.finish_reason == "stop"


def test_get_default_model_returns_primary() -> None:
    primary = _FakeProvider("primary")
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("a")],
        provider_factory=MagicMock(),
    )
    assert fb.get_default_model() == "primary/model"


def test_generation_is_forwarded_to_primary() -> None:
    from pythinker.providers.base import GenerationSettings

    primary = _FakeProvider("primary")
    primary.generation = GenerationSettings(temperature=0.5, max_tokens=1024)
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("a")],
        provider_factory=MagicMock(),
    )
    assert fb.generation.temperature == 0.5
    assert fb.generation.max_tokens == 1024


@pytest.mark.asyncio
async def test_circuit_breaker_skips_primary_after_threshold() -> None:
    primary = _FakeProvider("primary", _error_response())
    fallback = _FakeProvider("fallback", _make_response("fallback ok"))
    factory = MagicMock(return_value=fallback)
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    for _ in range(3):
        await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert len(primary.chat_calls) == 3

    primary.chat_calls.clear()
    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "fallback ok"
    assert primary.chat_calls == []


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_primary_success() -> None:
    primary = _FakeProvider("primary", _error_response())
    fallback = _FakeProvider("fallback", _make_response("fallback ok"))
    factory = MagicMock(return_value=fallback)
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_fallback("fallback-a")],
        provider_factory=factory,
    )

    for _ in range(2):
        await fb.chat(messages=[{"role": "user", "content": "hi"}])

    # Primary recovers; failure counter resets.
    primary._response = _make_response("primary ok")
    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "primary ok"

    # Primary fails again — still inside the budget after reset.
    primary._response = _error_response()
    primary.chat_calls.clear()
    result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "fallback ok"
    assert len(primary.chat_calls) == 1
