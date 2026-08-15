"""Tests for control_room.app's deterministic path anchoring (Codex review
Finding 3): registry/repository/state_file resolution must never depend
on the launching process's current working directory."""
from __future__ import annotations

from pathlib import Path

import pytest

from control_room.app import _PACKAGE_ROOT, _preflight_registry_check, _resolve_base_dir, _resolve_registry_path, build_service


def test_default_base_dir_is_package_relative_not_cwd(tmp_path, monkeypatch):
    unrelated = tmp_path / "somewhere_else"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    monkeypatch.delenv("REDLINE_CONTROL_ROOM_ROOT", raising=False)

    assert _resolve_base_dir(None) == _PACKAGE_ROOT


def test_env_var_root_overrides_package_default_regardless_of_cwd(tmp_path, monkeypatch):
    unrelated = tmp_path / "somewhere_else"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    explicit_root = tmp_path / "explicit_root"
    explicit_root.mkdir()
    monkeypatch.setenv("REDLINE_CONTROL_ROOM_ROOT", str(explicit_root))

    assert _resolve_base_dir(None) == explicit_root


def test_explicit_base_dir_argument_wins_over_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("REDLINE_CONTROL_ROOM_ROOT", str(tmp_path / "env_root"))
    explicit = tmp_path / "explicit"

    assert _resolve_base_dir(explicit) == explicit


def test_registry_default_is_relative_to_base_dir_not_cwd(tmp_path, monkeypatch):
    unrelated_cwd = tmp_path / "cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    monkeypatch.delenv("REDLINE_CONTROL_ROOM_REGISTRY", raising=False)

    base_dir = tmp_path / "base"
    resolved = _resolve_registry_path(None, base_dir)

    assert resolved == base_dir / "config" / "control_room" / "projects.yaml"


def test_relative_registry_env_var_resolves_against_base_dir_not_cwd(tmp_path, monkeypatch):
    unrelated_cwd = tmp_path / "cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    monkeypatch.setenv("REDLINE_CONTROL_ROOM_REGISTRY", "custom/registry.yaml")

    base_dir = tmp_path / "base"
    resolved = _resolve_registry_path(None, base_dir)

    assert resolved == base_dir / "custom" / "registry.yaml"


def test_absolute_registry_env_var_is_used_as_is(tmp_path, monkeypatch):
    absolute_registry = tmp_path / "elsewhere" / "projects.yaml"
    monkeypatch.setenv("REDLINE_CONTROL_ROOM_REGISTRY", str(absolute_registry))

    resolved = _resolve_registry_path(None, tmp_path / "base")

    assert resolved == absolute_registry


def test_build_service_from_unrelated_cwd_ignores_decoy_registry_there(tmp_path, monkeypatch):
    """Launching from a directory that is not the Redline OS repo -- and
    that even has its own config/control_room/projects.yaml -- must not
    silently borrow that directory's registry. It must resolve against the
    real installed package location instead, which (for this editable dev
    install under test) is the real Redline OS repository."""
    unrelated = tmp_path / "not_the_redline_repo"
    decoy_registry_dir = unrelated / "config" / "control_room"
    decoy_registry_dir.mkdir(parents=True)
    (decoy_registry_dir / "projects.yaml").write_text(
        "projects:\n"
        "  - id: decoy\n"
        "    name: Decoy\n"
        "    repository: .\n"
        "    state_file: does_not_exist.yaml\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(unrelated)
    monkeypatch.delenv("REDLINE_CONTROL_ROOM_ROOT", raising=False)
    monkeypatch.delenv("REDLINE_CONTROL_ROOM_REGISTRY", raising=False)

    service = build_service()
    project_ids = [snapshot.project_id for snapshot in service.list_snapshots()]

    assert "decoy" not in project_ids
    assert "redline-os" in project_ids


def test_build_service_honors_explicit_root_override_from_unrelated_cwd(tmp_path, monkeypatch):
    unrelated_cwd = tmp_path / "cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    project_root = tmp_path / "project"
    registry_dir = project_root / "config" / "control_room"
    registry_dir.mkdir(parents=True)
    (registry_dir / "projects.yaml").write_text(
        "projects:\n"
        "  - id: example\n"
        "    name: Example\n"
        "    repository: .\n"
        "    state_file: state.yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REDLINE_CONTROL_ROOM_ROOT", str(project_root))

    service = build_service()
    project_ids = [snapshot.project_id for snapshot in service.list_snapshots()]

    assert project_ids == ["example"]


def test_preflight_registry_check_fails_fast_and_clearly_when_registry_missing(tmp_path, monkeypatch):
    """Codex review 'Prove the path design under an installed wheel': a
    missing registry (the installed-wheel-from-unrelated-CWD case) must
    raise SystemExit with an actionable message, not start a server that
    would only 503 on first request."""
    monkeypatch.setenv("REDLINE_CONTROL_ROOM_ROOT", str(tmp_path / "no_such_checkout"))
    service = build_service()

    with pytest.raises(SystemExit) as exc_info:
        _preflight_registry_check(service)

    message = str(exc_info.value)
    assert "REDLINE_CONTROL_ROOM_ROOT" in message
    assert "checkout" in message.lower()


def test_preflight_registry_check_passes_with_valid_root(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    registry_dir = project_root / "config" / "control_room"
    registry_dir.mkdir(parents=True)
    (registry_dir / "projects.yaml").write_text(
        "projects:\n"
        "  - id: example\n"
        "    name: Example\n"
        "    repository: .\n"
        "    state_file: state.yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REDLINE_CONTROL_ROOM_ROOT", str(project_root))
    service = build_service()

    _preflight_registry_check(service)  # must not raise
