"""Tests for cli/recovery_planning_commands.py (Mission 1B-A2-1):
serialization, exit-code behavior, argparse registration, and the read-only,
no-destructive-action guarantee for `redline backup restore-recovery-plan`.
Mirrors tests/unit/test_cli_restore_commands.py's own established
convention.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from cli import backup_commands, recovery_planning_commands
from redline_core.runtime.composition import RestoreServices

from tests.unit._restore_test_helpers import make_environment, make_target_backup


def _services_from_env(env) -> RestoreServices:
    return RestoreServices(config=env.config, backup_manager=env.backup_manager, restore_manager=env.restore_manager)


# -- argparse registration --------------------------------------------------------


def test_restore_recovery_plan_action_registered_under_backup_resource():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)

    args = parser.parse_args(["backup", "restore-recovery-plan", "b1-x"])
    assert args.action == "restore-recovery-plan"
    assert args.backup_id == "b1-x"


def test_restore_recovery_plan_requires_backup_id_positional():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)
    with pytest.raises(SystemExit):
        parser.parse_args(["backup", "restore-recovery-plan"])


def test_no_destructive_restore_recovery_action_registered():
    """No `restore-recovery` (without `-plan`) or `restore-degraded` action
    exists anywhere -- Mission 1B-A2-1 adds read-only planning only."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)

    with pytest.raises(SystemExit):
        parser.parse_args(["backup", "restore-recovery", "b1-x"])
    with pytest.raises(SystemExit):
        parser.parse_args(["backup", "restore-degraded", "b1-x"])


def test_existing_restore_plan_and_restore_actions_still_registered():
    """A1/A1's own actions must remain completely unaffected by this
    mission's registration additions."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)

    plan_args = parser.parse_args(["backup", "restore-plan", "b1-x"])
    assert plan_args.action == "restore-plan"

    restore_args = parser.parse_args(
        [
            "backup",
            "restore",
            "b1-x",
            "--confirm-backup-id",
            "b1-x",
            "--attest-mcp-stopped",
            "--attest-control-room-stopped",
            "--attest-no-other-cli-operation",
        ]
    )
    assert restore_args.action == "restore"


# -- run() dispatch -----------------------------------------------------------------


def test_run_returns_none_for_unrelated_action():
    args = argparse.Namespace(action="restore-plan", backup_id="b1-x")
    assert recovery_planning_commands.run(args, services=None) is None


def test_success_result_shape_and_exit_code(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    services = _services_from_env(env)

    result = recovery_planning_commands._run_backup_restore_recovery_plan(services, target_id)

    assert result["success"] is True
    plan = result["plan"]
    assert plan["backup_id"] == target_id
    assert plan["target_verified"] is True
    assert plan["schema_compatible"] is True
    assert plan["database"]["condition"] == "HEALTHY"
    assert plan["config"]["condition"] == "HEALTHY"
    assert plan["would_proceed"] is True

    args = argparse.Namespace(action="restore-recovery-plan", backup_id=target_id)
    exit_code = recovery_planning_commands.run(args, services)
    assert exit_code == 0


def test_blocked_result_exit_code(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.db_path.write_bytes(b"corrupted")

    services = _services_from_env(env)
    args = argparse.Namespace(action="restore-recovery-plan", backup_id=target_id)
    exit_code = recovery_planning_commands.run(args, services)
    assert exit_code == 0  # DEGRADED + RECOVERABLE is not itself a block

    from redline_core.restore import recovery_classification as rc

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(rc.fsutil, "is_unsafe_link", lambda st: True)
        exit_code = recovery_planning_commands.run(args, services)
    assert exit_code == 1  # RECOVERY_BLOCKED must fail the command


def test_invalid_backup_id_result(tmp_path: Path):
    env = make_environment(tmp_path)
    services = _services_from_env(env)

    result = recovery_planning_commands._run_backup_restore_recovery_plan(services, "not-a-valid-id")

    assert result["success"] is False
    assert result["error_type"] == "ValueError"


def test_missing_backup_result(tmp_path: Path):
    env = make_environment(tmp_path)
    make_target_backup(tmp_path, env)  # ensure backup_path exists at all
    services = _services_from_env(env)

    result = recovery_planning_commands._run_backup_restore_recovery_plan(
        services, "b1-20260817T000000Z-000000000000"
    )

    assert result["success"] is True
    assert result["plan"]["target_verified"] is False
    assert result["plan"]["would_proceed"] is False


def test_print_functions_do_not_raise(tmp_path: Path, capsys):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    services = _services_from_env(env)

    result = recovery_planning_commands._run_backup_restore_recovery_plan(services, target_id)
    recovery_planning_commands._print_backup_restore_recovery_plan_result(result)

    captured = capsys.readouterr()
    assert "Recovery Plan" in captured.out
    assert "not an indication that recovery execution exists".upper() in captured.out.upper()


# -- read-only guarantee, exercised through the full CLI dispatch path --------------


def test_cli_dispatch_never_mutates_live_fixture(tmp_path: Path):
    import hashlib

    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    services = _services_from_env(env)

    db_hash_before = hashlib.sha256(env.db_path.read_bytes()).hexdigest()
    config_before = {p.name: p.read_bytes() for p in env.config_dir.iterdir()}

    args = argparse.Namespace(action="restore-recovery-plan", backup_id=target_id)
    recovery_planning_commands.run(args, services)

    assert hashlib.sha256(env.db_path.read_bytes()).hexdigest() == db_hash_before
    assert {p.name: p.read_bytes() for p in env.config_dir.iterdir()} == config_before
