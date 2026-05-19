"""Smoke tests for the generate_image tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pythinker.agent.tools.image_generation import ImageGenerationTool
from pythinker.config.schema import ImageGenerationConfig, ProviderConfig


@pytest.fixture
def cfg() -> ImageGenerationConfig:
    return ImageGenerationConfig(enabled=True, provider="openrouter", model="m")


async def test_missing_provider_class(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr(
        "pythinker.agent.tools.image_generation.get_image_gen_provider",
        lambda _: None,
    )
    tool = ImageGenerationTool(workspace=tmp_path, config=cfg, provider_configs={})
    result = await tool.execute(prompt="a cat")
    assert result.startswith("Error: unsupported image generation provider")


async def test_missing_api_key(tmp_path, cfg, monkeypatch):
    fake_cls = MagicMock()
    fake_cls.missing_key_message = "OpenRouter API key is not configured."
    monkeypatch.setattr(
        "pythinker.agent.tools.image_generation.get_image_gen_provider",
        lambda _: fake_cls,
    )
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=cfg,
        provider_configs={"openrouter": ProviderConfig(api_key="")},
    )
    result = await tool.execute(prompt="a cat")
    assert "API key is not configured" in result


async def test_generate_persists_artifacts(tmp_path, cfg, monkeypatch):
    """generate returns artifact metadata via generated_image_tool_result."""
    fake_response = MagicMock(
        images=[
            # 1x1 transparent png
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
        ],
        content="",
        raw={},
    )

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def generate(self, **kwargs):
            return fake_response

    monkeypatch.setattr(
        "pythinker.agent.tools.image_generation.get_image_gen_provider",
        lambda _: FakeClient,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(
        "pythinker.utils.artifacts.get_media_dir", lambda: media,
    )

    tool = ImageGenerationTool(
        workspace=workspace,
        config=cfg,
        provider_configs={"openrouter": ProviderConfig(api_key="sk-test")},
    )
    result = await tool.execute(prompt="a cat", count=1)
    assert '"artifacts"' in result
    assert '"path"' in result
    assert "Call the message tool" in result
