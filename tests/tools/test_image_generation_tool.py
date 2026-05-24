"""Tests for the generate_image tool's provider auth gating.

Providers that handle their own auth (local Ollama, OAuth Codex) are allowed
to run without a configured API key; key-based providers are not.
"""

from __future__ import annotations

import json

from pythinker.agent.tools.image_generation import ImageGenerationTool
from pythinker.config.schema import ImageGenerationConfig, ProviderConfig

# 1x1 transparent png
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


class FakeImageClient:
    """Captures construction kwargs and generate() calls."""

    instances: list["FakeImageClient"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[dict] = []
        FakeImageClient.instances.append(self)

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        from unittest.mock import MagicMock

        return MagicMock(images=[PNG_DATA_URL], content="", raw={})


async def test_generate_image_tool_allows_ollama_without_api_key(tmp_path, monkeypatch):
    FakeImageClient.instances = []
    monkeypatch.setattr(
        "pythinker.agent.tools.image_generation.get_image_gen_provider",
        lambda name: FakeImageClient if name == "ollama" else None,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr("pythinker.utils.artifacts.get_media_dir", lambda: media)

    tool = ImageGenerationTool(
        workspace=workspace,
        config=ImageGenerationConfig(
            enabled=True,
            provider="ollama",
            model="x/z-image-turbo",
        ),
        provider_configs={"ollama": ProviderConfig(api_base="http://localhost:11434/v1")},
    )

    result = await tool.execute(prompt="draw a cat")

    payload = json.loads(result)
    assert len(payload["artifacts"]) == 1

    fake = FakeImageClient.instances[0]
    assert fake.kwargs["api_key"] is None
    assert fake.kwargs["api_base"] == "http://localhost:11434/v1"
    assert fake.calls[0]["aspect_ratio"] == "1:1"
    assert fake.calls[0]["image_size"] == "1K"


async def test_generate_image_tool_still_requires_key_for_key_based_provider(tmp_path, monkeypatch):
    FakeImageClient.instances = []
    fake_cls = FakeImageClient
    fake_cls.missing_key_message = "OpenAI API key is not configured."
    monkeypatch.setattr(
        "pythinker.agent.tools.image_generation.get_image_gen_provider",
        lambda name: fake_cls if name == "openai" else None,
    )

    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationConfig(enabled=True, provider="openai", model="dall-e-3"),
        provider_configs={"openai": ProviderConfig(api_key="")},
    )

    result = await tool.execute(prompt="draw a cat")

    assert result.startswith("Error:")
    assert "API key is not configured" in result
