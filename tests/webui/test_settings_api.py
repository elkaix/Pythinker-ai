from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from pythinker.config.loader import load_config, save_config
from pythinker.config.schema import Config, ModelPresetConfig
from pythinker.webui.settings_api import (
    WebUISettingsError,
    _model_catalog_kind,
    create_model_configuration,
    decorate_settings_payload,
    settings_payload,
    update_agent_settings,
    update_model_configuration,
    update_network_safety_settings,
    update_web_search_settings,
)
from pythinker.providers.registry import find_by_name


def _config(tmp_path: Path, *, api_key: str = "sk-test") -> Path:
    config_path = tmp_path / "config.json"
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.agents.defaults.model = "openai/gpt-4o"
    config.agents.defaults.provider = "openai"
    config.providers.openai.api_key = api_key
    save_config(config, config_path)
    return config_path


def test_decorate_settings_payload_adds_surface_and_capabilities() -> None:
    payload = decorate_settings_payload({"requires_restart": False}, surface="browser")
    assert payload["surface"] == "browser"
    assert payload["runtime_capabilities"]["can_restart_engine"] is False


def test_decorate_settings_payload_native_surface() -> None:
    payload = decorate_settings_payload({"requires_restart": False}, surface="native")
    assert payload["surface"] == "native"
    assert payload["runtime_capabilities"]["can_restart_engine"] is True


def test_model_catalog_kind_gateway() -> None:
    spec = find_by_name("openrouter")
    assert spec is not None
    assert _model_catalog_kind(spec) == "catalog"


def test_model_catalog_kind_official() -> None:
    spec = find_by_name("openai")
    assert spec is not None
    assert _model_catalog_kind(spec) == "official"


def test_model_catalog_kind_direct() -> None:
    spec = find_by_name("custom")
    assert spec is not None
    assert _model_catalog_kind(spec) == "custom"


def test_create_model_configuration_writes_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)

    payload = create_model_configuration(
        {
            "label": ["Fast writing"],
            "provider": ["openai"],
            "model": ["openai/gpt-4.1-mini"],
        }
    )

    assert payload["agent"]["model_preset"] == "fast-writing"
    rows = {row["name"]: row for row in payload["model_presets"]}
    assert rows["fast-writing"]["label"] == "Fast writing"

    saved = load_config(config_path)
    assert saved.agents.defaults.model_preset == "fast-writing"
    assert saved.model_presets["fast-writing"].model == "openai/gpt-4.1-mini"


def test_create_model_configuration_rejects_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)

    create_model_configuration(
        {"label": ["Fast"], "provider": ["openai"], "model": ["openai/gpt-4.1-mini"]}
    )
    with pytest.raises(WebUISettingsError) as exc_info:
        create_model_configuration(
            {"label": ["Fast"], "provider": ["openai"], "model": ["openai/gpt-4.1-mini"]}
        )
    assert exc_info.value.status == 409


def test_create_model_configuration_rejects_unconfigured_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="provider is not configured"):
        create_model_configuration(
            {"label": ["Deep"], "provider": ["openai"], "model": ["openai/gpt-4.1"]}
        )


def test_update_model_configuration_changes_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    config = load_config(config_path)
    config.model_presets["codex"] = ModelPresetConfig(
        label="Codex", provider="openai", model="openai/gpt-4.1"
    )
    save_config(config, config_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)

    update_model_configuration(
        {"name": ["codex"], "model": ["openai/gpt-4.1-mini"]}
    )

    saved = load_config(config_path)
    assert saved.model_presets["codex"].model == "openai/gpt-4.1-mini"


def test_update_model_configuration_unknown_preset_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="unknown model configuration"):
        update_model_configuration({"name": ["no-such-preset"]})


def test_update_agent_settings_changes_context_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)

    payload = update_agent_settings({"context_window_tokens": ["262144"]})
    assert payload["agent"]["context_window_tokens"] == 262_144

    saved = load_config(config_path)
    assert saved.agents.defaults.context_window_tokens == 262_144


def test_update_agent_settings_rejects_invalid_context_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="65536 or 262144"):
        update_agent_settings({"context_window_tokens": ["99999"]})


def test_update_web_search_rejects_unknown_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="unknown web search provider"):
        update_web_search_settings({"provider": ["unknown"]})


def test_settings_payload_returns_expected_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)

    payload = settings_payload()

    assert "agent" in payload
    assert "providers" in payload
    assert "web_search" in payload
    assert "runtime" in payload
    assert "advanced" in payload
    assert isinstance(payload["providers"], list)
    assert len(payload["providers"]) > 0


def test_update_network_safety_changes_default_access_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    monkeypatch.setattr("pythinker.config.loader._current_config_path", config_path)
    monkeypatch.setattr(
        "pythinker.webui.workspaces.webui_workspace_state_path",
        lambda: tmp_path / "workspace-state.json",
    )

    update_network_safety_settings({"webuiDefaultAccessMode": ["full"]})

    from pythinker.webui.workspaces import read_webui_default_access_mode
    assert read_webui_default_access_mode() == "full"
