from __future__ import annotations

from pathlib import Path

import pytest

from pythinker.security.workspace_access import (
    WorkspaceScopeError,
    bind_workspace_scope,
    build_workspace_scope,
    current_scope_allows_loopback,
    current_tool_workspace,
    current_workspace_scope,
    default_access_mode,
    reset_workspace_scope,
    validate_workspace_scope_payload,
    workspace_sandbox_status,
)


def test_default_access_mode_restricted_when_restricted(tmp_path: Path) -> None:
    assert default_access_mode(True) == "restricted"


def test_default_access_mode_full_when_not_restricted(tmp_path: Path) -> None:
    assert default_access_mode(False) == "full"


def test_build_workspace_scope_restricted(tmp_path: Path) -> None:
    scope = build_workspace_scope(tmp_path, "restricted")
    assert scope.restrict_to_workspace is True
    assert scope.access_mode == "restricted"
    assert scope.project_path == tmp_path


def test_build_workspace_scope_full(tmp_path: Path) -> None:
    scope = build_workspace_scope(tmp_path, "full")
    assert scope.restrict_to_workspace is False
    assert scope.access_mode == "full"


def test_build_workspace_scope_rejects_invalid_mode(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceScopeError, match="access_mode must be restricted or full"):
        build_workspace_scope(tmp_path, "invalid")


def test_validate_workspace_scope_payload_none_returns_default(tmp_path: Path) -> None:
    scope = validate_workspace_scope_payload(
        None,
        default_workspace=tmp_path,
        default_restrict_to_workspace=True,
    )
    assert scope.restrict_to_workspace is True


def test_validate_workspace_scope_payload_path_must_exist(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-dir"
    with pytest.raises(WorkspaceScopeError, match="existing directory"):
        validate_workspace_scope_payload(
            {"project_path": str(missing)},
            default_workspace=tmp_path,
            default_restrict_to_workspace=False,
        )


def test_validate_workspace_scope_payload_null_byte_rejected(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceScopeError, match="invalid characters"):
        validate_workspace_scope_payload(
            {"project_path": str(tmp_path) + "\0"},
            default_workspace=tmp_path,
            default_restrict_to_workspace=False,
        )


def test_bind_reset_workspace_scope(tmp_path: Path) -> None:
    assert current_workspace_scope() is None
    scope = build_workspace_scope(tmp_path, "full", source_channel="websocket")
    token = bind_workspace_scope(scope)
    try:
        assert current_workspace_scope() is scope
    finally:
        reset_workspace_scope(token)
    assert current_workspace_scope() is None


def test_current_tool_workspace_uses_scope(tmp_path: Path) -> None:
    scope = build_workspace_scope(tmp_path, "restricted", source_channel="websocket")
    token = bind_workspace_scope(scope)
    try:
        tw = current_tool_workspace(None, restrict_to_workspace=False)
        assert tw.project_path == tmp_path
        assert tw.restrict_to_workspace is True
    finally:
        reset_workspace_scope(token)


def test_current_scope_allows_loopback_full_access(tmp_path: Path) -> None:
    scope = build_workspace_scope(tmp_path, "full", source_channel="websocket")
    token = bind_workspace_scope(scope)
    try:
        assert current_scope_allows_loopback(enabled=True) is True
        assert current_scope_allows_loopback(enabled=False) is False
    finally:
        reset_workspace_scope(token)


def test_current_scope_does_not_allow_loopback_restricted(tmp_path: Path) -> None:
    scope = build_workspace_scope(tmp_path, "restricted", source_channel="websocket")
    token = bind_workspace_scope(scope)
    try:
        assert current_scope_allows_loopback(enabled=True) is False
    finally:
        reset_workspace_scope(token)


def test_sandbox_status_off_when_not_restricted(tmp_path: Path) -> None:
    status = workspace_sandbox_status(restrict_to_workspace=False, workspace=tmp_path)
    assert status.level == "off"
    assert status.enforced is False


def test_sandbox_status_application_when_restricted_no_env(tmp_path: Path) -> None:
    status = workspace_sandbox_status(
        restrict_to_workspace=True, workspace=tmp_path, environ={}
    )
    assert status.level == "application"
    assert status.enforced is False


def test_sandbox_status_system_when_env_set(tmp_path: Path) -> None:
    environ = {"PYTHINKER_WORKSPACE_SANDBOX_ENFORCED": "bwrap"}
    status = workspace_sandbox_status(
        restrict_to_workspace=True, workspace=tmp_path, environ=environ
    )
    assert status.level == "system"
    assert status.enforced is True
    assert status.provider == "bwrap"
