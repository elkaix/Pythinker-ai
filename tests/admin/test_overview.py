"""Tests for ``AdminService.overview()`` augmentations."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pythinker.admin.service import AdminService
from pythinker.config.schema import Config, ModelPresetConfig
from pythinker.providers.base import LLMProvider, LLMResponse
from pythinker.providers.fallback_provider import FallbackProvider


class _StubProvider(LLMProvider):
    def __init__(self, name: str = "stub") -> None:
        super().__init__()
        self.name = name

    def get_default_model(self) -> str:
        return f"{self.name}/model"

    async def chat(self, *_args, **_kwargs) -> LLMResponse:
        return LLMResponse(content="ok", finish_reason="stop")

    async def chat_stream(self, *_args, **_kwargs) -> LLMResponse:
        return LLMResponse(content="ok", finish_reason="stop")


def _preset(model: str) -> ModelPresetConfig:
    return ModelPresetConfig(
        model=model,
        provider="custom",
        max_tokens=4096,
        context_window_tokens=32_768,
        temperature=0.1,
    )


@pytest.fixture
def _admin_with_loop(tmp_path: Path) -> tuple[AdminService, SimpleNamespace]:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")
    loop = SimpleNamespace(provider=None, model="primary-model")
    admin = AdminService(
        config=Config(),
        config_path=config_path,
        agent_loop=loop,
    )
    return admin, loop


def test_overview_fallback_chain_empty_when_provider_has_no_fallbacks(
    _admin_with_loop: tuple[AdminService, SimpleNamespace],
) -> None:
    admin, loop = _admin_with_loop
    loop.provider = _StubProvider()
    overview = admin.overview()
    assert overview["agent"]["fallback_chain"] == []


def test_overview_fallback_chain_lists_resolved_fallback_models(
    _admin_with_loop: tuple[AdminService, SimpleNamespace],
) -> None:
    admin, loop = _admin_with_loop
    primary = _StubProvider("primary")
    fb = FallbackProvider(
        primary=primary,
        fallback_presets=[_preset("anthropic/claude"), _preset("openai/gpt-mini")],
        provider_factory=MagicMock(),
    )
    loop.provider = fb
    overview = admin.overview()
    assert overview["agent"]["fallback_chain"] == [
        "anthropic/claude",
        "openai/gpt-mini",
    ]


def test_overview_fallback_chain_empty_when_loop_missing_provider(
    _admin_with_loop: tuple[AdminService, SimpleNamespace],
) -> None:
    admin, loop = _admin_with_loop
    loop.provider = None
    assert admin.overview()["agent"]["fallback_chain"] == []
