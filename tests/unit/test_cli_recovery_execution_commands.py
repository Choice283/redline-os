"""Tests for cli/recovery_execution_commands.py (Mission 1B-A2-3):
argparse registration, no --capture-id anywhere, serialization, exit-code
behavior, and dispatch. Mirrors tests/unit/test_cli_recovery_planning_
commands.py's own established convention.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from cli import backup_commands, recovery_execution_commands
from redline_core.runtime.composition import RestoreServices

from tests.unit._restore_test_helpers import make_environment, make_target_backup

_REQUIRED_FLAGS = [
    "--attest-mcp-stopped",
    "--attest-control-room-stopped",
    "--attest-no-other-cli-operation",
    "--attest-disposition-understood",
    "--attest-no-automatic-rollback",
]


def _services_from_env(env) -> RestoreServices:
    return RestoreServices(config=env.config, backup_manager=env.backup_manager, restore_manager=env.restore_manager)


def _append_backup_path_to_config_dir_on_disk(config_dir: Path, backup_root: Path) -> None:
    """`make_environment()`'s in-memory `env.config` already carries
    `backup_path`, but real `cli.main.main()` dispatch reloads config fresh
    from `REDLINE_CONFIG_DIR` on disk -- mirrors test_cli_restore_commands
    .py's own identical helper."""
    paths_file = config_dir / "paths.yaml"
    paths_file.write_text(paths_file.read_text(encoding="utf-8") + f"backup_path: '{backup_root}'\n", encoding="utf-8")


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)
    return parser.parse_args(argv)


# -- argparse registration -----------------------------------------------------------


def test_restore_recovery_action_registered_under_backup_resource():
    args = _parse(["backup", "restore-recovery", "b1-x", "--confirm-backup-id", "b1-x", *_REQUIRED_FLAGS])
    assert args.action == "restore-recovery"
    assert args.backup_id == "b1-x"
    assert args.attest_disposition_understood is True
    assert args.attest_no_automatic_rollback is True


def test_restore_recovery_requires_confirm_backup_id():
    with pytest.raises(SystemExit):
        _parse(["backup", "restore-recovery", "b1-x", *_REQUIRED_FLAGS])


def test_restore_recovery_attestation_flags_default_false():
    args = _parse(["backup", "restore-recovery", "b1-x", "--confirm-backup-id", "b1-x"])
    assert args.attest_mcp_stopped is False
    assert args.attest_control_room_stopped is False
    assert args.attest_no_other_cli_operation is False
    assert args.attest_disposition_understood is False
    assert args.attest_no_automatic_rollback is False


def test_restore_recovery_has_no_capture_id_flag():
    """No --capture-id or --confirm-capture-id exists anywhere -- every
    attempt builds its own fresh, brand-new capture."""
    with pytest.raises(SystemExit):
        _parse(["backup", "restore-recovery", "b1-x", "--confirm-backup-id", "b1-x", "--capture-id", "dsc1-x", *_REQUIRED_FLAGS])
    with pytest.raises(SystemExit):
        _parse(["backup", "restore-recovery", "b1-x", "--confirm-backup-id", "b1-x", "--confirm-capture-id", "dsc1-x", *_REQUIRED_FLAGS])


def test_execute_recovery_signature_and_cli_parser_agree_on_no_capture_id():
    import inspect

    from redline_core.restore.recovery_execution import execute_recovery

    params = inspect.signature(execute_recovery).parameters
    assert "capture_id" not in params
    assert "confirm_capture_id" not in params


def test_existing_restore_plan_restore_and_recovery_plan_actions_still_registered():
    """A1/A2-1's own actions remain completely unaffected by this
    mission's registration additions."""
    plan_args = _parse(["backup", "restore-plan", "b1-x"])
    assert plan_args.action == "restore-plan"

    recovery_plan_args = _parse(["backup", "restore-recovery-plan", "b1-x"])
    assert recovery_plan_args.action == "restore-recovery-plan"

    restore_args = _parse(
        [
            "backup", "restore", "b1-x", "--confirm-backup-id", "b1-x",
            "--attest-mcp-stopped", "--attest-control-room-stopped", "--attest-no-other-cli-operation",
        ]
    )
    assert restore_args.action == "restore"


# -- run() dispatch -------------------------------------------------------------------


def test_run_returns_none_for_unrelated_action():
    args = argparse.Namespace(action="restore-plan")
    assert recovery_execution_commands.run(args, services=None) is None


def test_success_result_shape_and_exit_code(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E600")
    env.db_path.unlink()
    services = _services_from_env(env)

    result = recovery_execution_commands._run_backup_restore_recovery(
        services, target_id, confirm_backup_id=target_id,
        attest_mcp_stopped=True, attest_control_room_stopped=True, attest_no_other_cli_operation=True,
        attest_disposition_understood=True, attest_no_automatic_rollback=True, reason="cli test",
    )

    assert result["success"] is True
    recovery = result["recovery"]
    assert recovery["backup_id"] == target_id
    assert recovery["capture_id"].startswith("dsc1-")
    assert recovery["disposed_targets"] == []

    args = argparse.Namespace(
        action="restore-recovery", backup_id=target_id, confirm_backup_id=target_id,
        attest_mcp_stopped=True, attest_control_room_stopped=True, attest_no_other_cli_operation=True,
        attest_disposition_understood=True, attest_no_automatic_rollback=True, reason=None,
    )
    # a second, fresh attempt (the db is now present, healthy -- nothing
    # left to recover, but the command still runs a full fresh attempt)
    env.db_path.unlink()
    exit_code = recovery_execution_commands.run(args, services)
    assert exit_code == 0


def test_missing_attestation_result_is_a_failure(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E601")
    services = _services_from_env(env)

    result = recovery_execution_commands._run_backup_restore_recovery(
        services, target_id, confirm_backup_id=target_id,
        attest_mcp_stopped=True, attest_control_room_stopped=True, attest_no_other_cli_operation=True,
        attest_disposition_understood=False, attest_no_automatic_rollback=True, reason=None,
    )

    assert result["success"] is False
    assert result["error_type"] == "RecoveryAttestationMissingError"


def test_confirm_mismatch_result_is_a_failure(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E602")
    services = _services_from_env(env)

    result = recovery_execution_commands._run_backup_restore_recovery(
        services, target_id, confirm_backup_id="b1-20260817T000000Z-000000000000",
        attest_mcp_stopped=True, attest_control_room_stopped=True, attest_no_other_cli_operation=True,
        attest_disposition_understood=True, attest_no_automatic_rollback=True, reason=None,
    )

    assert result["success"] is False
    assert result["error_type"] == "RecoveryConfirmationError"

    args = argparse.Namespace(
        action="restore-recovery", backup_id=target_id, confirm_backup_id="b1-20260817T000000Z-000000000000",
        attest_mcp_stopped=True, attest_control_room_stopped=True, attest_no_other_cli_operation=True,
        attest_disposition_understood=True, attest_no_automatic_rollback=True, reason=None,
    )
    exit_code = recovery_execution_commands.run(args, services)
    assert exit_code == 1


def test_print_functions_do_not_raise_on_success(tmp_path: Path, capsys):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E603")
    env.db_path.unlink()
    services = _services_from_env(env)

    result = recovery_execution_commands._run_backup_restore_recovery(
        services, target_id, confirm_backup_id=target_id,
        attest_mcp_stopped=True, attest_control_room_stopped=True, attest_no_other_cli_operation=True,
        attest_disposition_understood=True, attest_no_automatic_rollback=True, reason=None,
    )
    recovery_execution_commands._print_backup_restore_recovery_result(result)

    captured = capsys.readouterr()
    assert "Recovery Execution" in captured.out
    assert "VERIFIED_SUCCESS" in captured.out


# -- real cli.main.main() dispatch: restore-recovery uses RestoreServices -----------


def test_main_backup_restore_recovery_end_to_end_routes_through_restore_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Real argparse parsing, real env-var resolution, real dispatch
    through `cli.main.main()` -- proves `backup restore-recovery` is
    routed through `build_restore_services()`, not
    `build_backup_services()`, by patching the latter to explode if it's
    ever called for this action."""
    from cli import main as cli_main
    from redline_core.runtime import composition as composition_module

    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E605")
    _append_backup_path_to_config_dir_on_disk(env.config_dir, env.backup_root)
    env.db_path.unlink()

    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(env.config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(env.db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    def _fail_build_backup_services(*args, **kwargs):
        raise AssertionError("`backup restore-recovery` must never route through build_backup_services()")

    monkeypatch.setattr(composition_module, "build_backup_services", _fail_build_backup_services)
    monkeypatch.setattr(cli_main, "build_backup_services", _fail_build_backup_services)

    exit_code = cli_main.main(
        [
            "backup", "restore-recovery", target_id, "--confirm-backup-id", target_id,
            *_REQUIRED_FLAGS,
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Recovery Execution" in out
    assert "VERIFIED_SUCCESS" in out


def test_print_functions_do_not_raise_on_failure(tmp_path: Path, capsys):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E604")
    services = _services_from_env(env)

    result = recovery_execution_commands._run_backup_restore_recovery(
        services, target_id, confirm_backup_id="b1-mismatch-000000000000000000",
        attest_mcp_stopped=True, attest_control_room_stopped=True, attest_no_other_cli_operation=True,
        attest_disposition_understood=True, attest_no_automatic_rollback=True, reason=None,
    )
    recovery_execution_commands._print_backup_restore_recovery_result(result)

    captured = capsys.readouterr()
    assert "failed" in captured.out.lower()
