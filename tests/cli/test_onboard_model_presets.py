"""Logic tests for the model-preset onboard step."""

from __future__ import annotations

from typing import Any

import pytest

from pythinker.cli.onboard_steps.model_presets import (
    _add_preset,
    _edit_existing,
    _list_presets,
    _step_model_presets,
)
from pythinker.cli.onboard_types import _WizardContext
from pythinker.config.schema import Config, ModelPresetConfig


def _ctx(**overrides: Any) -> _WizardContext:
    cfg = Config()
    base = dict(
        draft=cfg,
        flow="manual",
        non_interactive=False,
        yes_security=False,
    )
    base.update(overrides)
    return _WizardContext(**base)


def test_step_skipped_non_interactive():
    ctx = _ctx(non_interactive=True)
    result = _step_model_presets(ctx)
    assert result.status == "skip"


def test_step_skipped_quickstart_flow():
    ctx = _ctx(flow="quickstart")
    result = _step_model_presets(ctx)
    assert result.status == "skip"


def test_step_skipped_when_user_declines(monkeypatch):
    """Top-level confirm: 'No' → continue without entering the CRUD loop."""
    ctx = _ctx()
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.confirm", lambda *_args, **_kwargs: False
    )
    select_calls: list[str] = []
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.select",
        lambda *args, **kwargs: select_calls.append(args[0]) or "should-not-be-called",
    )
    result = _step_model_presets(ctx)
    assert result.status == "continue"
    assert select_calls == []  # CRUD loop never entered


def test_step_done_exits_loop(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.confirm", lambda *_a, **_kw: True
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.select", lambda *_a, **_kw: "__done__"
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard._emit_docs_link", lambda _key: None
    )
    result = _step_model_presets(ctx)
    assert result.status == "continue"


def test_list_presets_includes_add_and_done():
    presets = {
        "fast": ModelPresetConfig(model="m1", provider="openai"),
        "deep": ModelPresetConfig(model="m2", provider="anthropic"),
    }
    options = _list_presets(presets)
    ids = [opt[0] for opt in options]
    assert ids[0] == "__add__"
    assert ids[-1] == "__done__"
    # Existing presets appear sorted by name
    assert ids[1:3] == ["deep", "fast"]


def test_add_preset_persists_to_draft(monkeypatch):
    cfg = Config()

    text_inputs = iter(
        [
            "fast",  # preset name
            "openai/gpt-4o-mini",  # model id
            "4096",  # max_tokens
            "65536",  # context_window_tokens
            "0.2",  # temperature
            "low",  # reasoning_effort
        ]
    )

    def fake_text(_label: str, *, default: str = "") -> str:
        return next(text_inputs)

    monkeypatch.setattr("pythinker.cli.onboard_views.clack.text", fake_text)
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.select", lambda *_a, **_kw: "openai"
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.note", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.print_status", lambda *_a, **_kw: None
    )

    _add_preset(cfg)
    assert "fast" in cfg.model_presets
    preset = cfg.model_presets["fast"]
    assert preset.model == "openai/gpt-4o-mini"
    assert preset.provider == "openai"
    assert preset.max_tokens == 4096
    assert preset.context_window_tokens == 65_536
    assert preset.temperature == pytest.approx(0.2)
    assert preset.reasoning_effort == "low"


def test_add_preset_rejects_reserved_default_name(monkeypatch):
    cfg = Config()
    statuses: list[str] = []
    text_inputs = iter(["default", ""])  # 'default' rejected, then blank cancels

    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.text",
        lambda *_a, **_kw: next(text_inputs),
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.print_status",
        lambda msg: statuses.append(msg),
    )

    _add_preset(cfg)
    assert cfg.model_presets == {}
    assert any("reserved" in s for s in statuses)


def test_delete_preset_clears_active_pointer(monkeypatch):
    cfg = Config()
    cfg.model_presets["fast"] = ModelPresetConfig(model="m", provider="openai")
    cfg.agents.defaults.model_preset = "fast"

    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.select",
        lambda *_a, **_kw: "delete",
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.confirm",
        lambda *_a, **_kw: True,
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.print_status", lambda *_a, **_kw: None
    )

    _edit_existing(cfg, "fast")
    assert "fast" not in cfg.model_presets
    assert cfg.agents.defaults.model_preset is None  # cleared so validation passes


def test_edit_preset_updates_fields(monkeypatch):
    cfg = Config()
    cfg.model_presets["fast"] = ModelPresetConfig(
        model="old-model", provider="openai", max_tokens=2048
    )

    text_inputs = iter(
        [
            "new-model",  # model
            "8192",  # max_tokens
            "131072",  # context_window_tokens
            "0.5",  # temperature
            "",  # reasoning_effort → cleared
        ]
    )

    select_inputs = iter(["edit", "anthropic"])
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.select",
        lambda *_a, **_kw: next(select_inputs),
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.text",
        lambda *_a, **_kw: next(text_inputs),
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.note", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(
        "pythinker.cli.onboard_views.clack.print_status", lambda *_a, **_kw: None
    )

    _edit_existing(cfg, "fast")
    preset = cfg.model_presets["fast"]
    assert preset.model == "new-model"
    assert preset.provider == "anthropic"
    assert preset.max_tokens == 8192
    assert preset.context_window_tokens == 131_072
    assert preset.temperature == pytest.approx(0.5)
    assert preset.reasoning_effort is None  # blank cleared it
