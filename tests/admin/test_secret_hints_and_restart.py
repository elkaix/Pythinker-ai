"""Tests for the secret-mask hint helper and AdminService restart-tracking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pythinker.admin.service import AdminService
from pythinker.config.editing import (
    collect_secret_hints,
    mask_secret_hint,
    redacted_config,
)
from pythinker.config.schema import Config


# ---------------------------------------------------------------------------
# mask_secret_hint
# ---------------------------------------------------------------------------


def test_mask_secret_hint_long_secret_reveals_head_and_tail() -> None:
    assert mask_secret_hint("sk-1234567890abcdef") == "sk-1••••cdef"


def test_mask_secret_hint_short_secret_collapses_to_bullets() -> None:
    assert mask_secret_hint("short") == "••••"
    assert mask_secret_hint("12345678") == "••••"  # exactly 8 chars


def test_mask_secret_hint_empty_or_none() -> None:
    assert mask_secret_hint("") is None
    assert mask_secret_hint(None) is None


def test_mask_secret_hint_env_reference_returns_none() -> None:
    assert mask_secret_hint("${OPENAI_API_KEY}") is None


# ---------------------------------------------------------------------------
# collect_secret_hints
# ---------------------------------------------------------------------------


def test_collect_secret_hints_emits_hints_only_for_set_secrets() -> None:
    cfg = Config()
    cfg.providers.openai.api_key = "sk-1234567890abcdef"
    cfg.providers.anthropic.api_key = ""  # explicitly empty
    secret_paths = set(redacted_config(cfg)["secret_paths"])
    hints = collect_secret_hints(cfg, secret_paths)

    assert hints.get("providers.openai.api_key") == "sk-1••••cdef"
    assert "providers.anthropic.api_key" not in hints


# ---------------------------------------------------------------------------
# AdminService restart tracking
# ---------------------------------------------------------------------------


@pytest.fixture
def _admin(tmp_path: Path) -> AdminService:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"providers": {"openai": {"apiKey": "sk-init-abcdefghij"}}}),
        encoding="utf-8",
    )
    return AdminService(config=Config(), config_path=config_path)


def test_config_payload_includes_secret_hint_and_no_pending_restart_initially(
    _admin: AdminService,
) -> None:
    payload = _admin.config_payload()
    assert payload["requires_restart"] is False
    assert payload["pending_restart_sections"] == []
    assert payload["secret_hints"].get("providers.openai.api_key") == "sk-i••••ghij"


def test_set_config_marks_top_level_section_as_pending(_admin: AdminService) -> None:
    _admin.set_config("agents.defaults.model", "openai/gpt-4o")
    payload = _admin.config_payload()
    assert payload["requires_restart"] is True
    assert "agents" in payload["pending_restart_sections"]


def test_replace_secret_marks_providers_section(_admin: AdminService) -> None:
    _admin.replace_secret("providers.openai.api_key", "sk-new-abcdefghij")
    payload = _admin.config_payload()
    assert "providers" in payload["pending_restart_sections"]
    # Hint reflects the new value after the edit.
    assert payload["secret_hints"]["providers.openai.api_key"] == "sk-n••••ghij"


def test_unset_config_marks_section(_admin: AdminService) -> None:
    _admin.set_config("agents.defaults.model", "openai/gpt-4o")
    _admin.unset_config("agents.defaults.model")
    payload = _admin.config_payload()
    assert "agents" in payload["pending_restart_sections"]


def test_restore_config_backup_marks_wildcard(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")
    admin = AdminService(config=Config(), config_path=config_path)
    # First edit creates a backup.
    admin.set_config("agents.defaults.model", "openai/gpt-4o")
    backups = admin.config_backups()
    assert backups, "expected backup after set_config"
    admin.restore_config_backup(backups[0]["id"])
    payload = admin.config_payload()
    assert "*" in payload["pending_restart_sections"]
