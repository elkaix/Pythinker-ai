"""Tests for Pydantic config schema."""

from __future__ import annotations

import pytest

from pythinker.config.schema import Config


def test_provider_api_type_accepts_exact_values_only() -> None:
    config = Config.model_validate({
        "providers": {
            "openai": {
                "apiKey": "sk-test",
                "apiType": "responses",
            }
        }
    })
    assert config.providers.openai.api_type == "responses"

    with pytest.raises(ValueError):
        Config.model_validate({
            "providers": {
                "openai": {
                    "apiKey": "sk-test",
                    "apiType": "response",
                }
            }
        })


def test_provider_api_type_is_openai_only() -> None:
    with pytest.raises(ValueError, match="only supported for providers.openai"):
        Config.model_validate({
            "providers": {
                "custom": {
                    "apiType": "responses",
                }
            }
        })


def test_cli_tui_theme_default() -> None:
    cfg = Config()
    assert cfg.cli.tui.theme == "default"


def test_cli_tui_theme_round_trip_camel_case() -> None:
    cfg = Config()
    cfg.cli.tui.theme = "monochrome"
    dumped = cfg.model_dump(by_alias=True)
    assert dumped["cli"]["tui"]["theme"] == "monochrome"
    restored = Config.model_validate(dumped)
    assert restored.cli.tui.theme == "monochrome"
