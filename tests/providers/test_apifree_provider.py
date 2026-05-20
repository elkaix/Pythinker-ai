"""Tests for the APIFree provider registration."""

from unittest.mock import patch

from pythinker.config.schema import Config, ProvidersConfig
from pythinker.providers.openai_compat_provider import OpenAICompatProvider
from pythinker.providers.registry import PROVIDERS, find_by_name


def test_apifree_config_field_exists() -> None:
    config = ProvidersConfig()
    assert hasattr(config, "apifree")


def test_apifree_provider_in_registry() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}
    assert "apifree" in specs

    apifree = specs["apifree"]
    assert apifree.backend == "openai_compat"
    assert apifree.env_key == "APIFREE_API_KEY"
    assert apifree.display_name == "APIFree"
    assert apifree.default_api_base == "https://api.apifree.ai/agent/v1"
    assert apifree.detect_by_base_keyword == "apifree.ai"


def test_find_by_name_accepts_apifree() -> None:
    spec = find_by_name("apifree")
    assert spec is not None
    assert spec.name == "apifree"


def test_apifree_model_auto_matches_with_default_api_base() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "apifree": {
                    "apiKey": "apifree-key",
                },
            },
            "agents": {
                "defaults": {
                    "model": "apifree/some-model",
                },
            },
        }
    )

    assert config.get_provider_name("apifree/some-model") == "apifree"
    assert config.get_api_key("apifree/some-model") == "apifree-key"
    assert config.get_api_base("apifree/some-model") == "https://api.apifree.ai/agent/v1"


def test_apifree_preserves_official_model_name() -> None:
    spec = find_by_name("apifree")
    with patch("pythinker.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="apifree-key",
            default_model="apifree/some-model",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="apifree/some-model",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "apifree/some-model"
