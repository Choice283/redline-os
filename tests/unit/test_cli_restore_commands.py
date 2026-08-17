"""Tests for cli/restore_commands.py (Mission 1B-A1): serialization,
exit-code behavior, argparse registration, and composition-tier boundaries
for `redline backup restore-plan|restore` -- mirrors
test_cli_backup_commands.py's own established convention.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from cli import backup_commands, restore_commands
from redline_core.db.database import Database
from redline_core.runtime.composition import RestoreServices, build_restore_services

from tests.unit._restore_test_helpers import make_environment, make_target_backup


def _services_from_env(env) -> RestoreServices:
    return RestoreServices(config=env.config, backup_manager=env.backup_manager, restore_manager=env.restore_manager)


def _append_backup_path_to_config_dir_on_disk(config_dir: Path, backup_root: Path) -> None:
    """`make_environment()`'s in-memory `env.config` already carries
    `backup_path`, but real `cli.main.main()` dispatch reloads config fresh
    from `REDLINE_CONFIG_DIR` on disk -- so end-to-end tests need it there
    too. Single-quoted YAML scalar, matching Mission 1A's own precedent for
    a raw Windows path (no backslash-escape processing)."""
    paths_file = config_dir / "paths.yaml"
    paths_file.write_text(paths_file.read_text(encoding="utf-8") + f"backup_path: '{backup_root}'\n", encoding="utf-8")


# -- argparse registration --------------------------------------------------------


def test_restore_actions_registered_under_backup_resource():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)

    plan_args = parser.parse_args(["backup", "restore-plan", "b1-x"])
    assert plan_args.action == "restore-plan"
    assert plan_args.backup_id == "b1-x"

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
    assert restore_args.backup_id == "b1-x"
    assert restore_args.confirm_backup_id == "b1-x"
    assert restore_args.attest_mcp_stopped is True


def test_restore_plan_requires_backup_id_positional():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)
    with pytest.raises(SystemExit):
        parser.parse_args(["backup", "restore-plan"])


def test_restore_requires_confirm_backup_id():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)
    with pytest.raises(SystemExit):
        parser.parse_args(["backup", "restore", "b1-x"])  # missing --confirm-backup-id


def test_restore_attestation_flags_default_false():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)
    args = parser.parse_args(["backup", "restore", "b1-x", "--confirm-backup-id", "b1-x"])
    assert args.attest_mcp_stopped is False
    assert args.attest_control_room_stopped is False
    assert args.attest_no_other_cli_operation is False


def test_no_latest_shortcut_option_exists():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)
    with pytest.raises(SystemExit):
        parser.parse_args(["backup", "restore", "--latest", "--confirm-backup-id", "x"])


# -- run(): restore-plan --------------------------------------------------------------


def test_run_restore_plan_success_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    services = _services_from_env(env)

    exit_code = restore_commands.run(argparse.Namespace(action="restore-plan", backup_id=target_id), services)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Would proceed:        yes" in out


def test_run_restore_plan_blocking_issue_exit_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    env = make_environment(tmp_path)
    services = _services_from_env(env)

    exit_code = restore_commands.run(
        argparse.Namespace(action="restore-plan", backup_id="b1-20260817T000000Z-000000000000"), services
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Would proceed:        NO" in out
    assert "Blocking issue(s):" in out


# -- run(): restore --------------------------------------------------------------------


def test_run_restore_success_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    services = _services_from_env(env)

    exit_code = restore_commands.run(
        argparse.Namespace(
            action="restore",
            backup_id=target_id,
            confirm_backup_id=target_id,
            attest_mcp_stopped=True,
            attest_control_room_stopped=True,
            attest_no_other_cli_operation=True,
            reason=None,
        ),
        services,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "VERIFIED_SUCCESS." in out


def test_run_restore_confirmation_mismatch_exit_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    services = _services_from_env(env)

    exit_code = restore_commands.run(
        argparse.Namespace(
            action="restore",
            backup_id=target_id,
            confirm_backup_id="something-else",
            attest_mcp_stopped=True,
            attest_control_room_stopped=True,
            attest_no_other_cli_operation=True,
            reason=None,
        ),
        services,
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "RestoreConfirmationError" in out


def test_run_restore_missing_attestation_exit_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    services = _services_from_env(env)

    exit_code = restore_commands.run(
        argparse.Namespace(
            action="restore",
            backup_id=target_id,
            confirm_backup_id=target_id,
            attest_mcp_stopped=True,
            attest_control_room_stopped=False,
            attest_no_other_cli_operation=True,
            reason=None,
        ),
        services,
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "RestoreAttestationMissingError" in out


# -- composition boundary: RestoreServices never touches live Database/Resolve ------


def test_build_restore_services_never_touches_database_class(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    seed_db = Database(db_path).connect()  # test setup only, before the patch below is installed
    seed_db.init_schema()
    seed_db.close()

    config_dir = tmp_path / "config"
    from tests.unit._restore_test_helpers import write_minimal_config_dir

    write_minimal_config_dir(config_dir)

    def _fail_connect(self):
        raise AssertionError("build_restore_services() must never call Database.connect()")

    def _fail_init_schema(self):
        raise AssertionError("build_restore_services() must never call Database.init_schema()")

    monkeypatch.setattr(Database, "connect", _fail_connect)
    monkeypatch.setattr(Database, "init_schema", _fail_init_schema)

    services = build_restore_services(config_dir=str(config_dir), db_path=str(db_path))
    assert services.restore_manager is not None


def test_build_restore_services_never_constructs_resolve_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from redline_core.resolve.adapter import ResolveScriptAdapter

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    seed_db = Database(db_path).connect()
    seed_db.init_schema()
    seed_db.close()

    config_dir = tmp_path / "config"
    from tests.unit._restore_test_helpers import write_minimal_config_dir

    write_minimal_config_dir(config_dir)

    def _fail_init(self, *args, **kwargs):
        raise AssertionError("restore composition must never construct a ResolveAdapter")

    monkeypatch.setattr(ResolveScriptAdapter, "__init__", _fail_init)

    services = build_restore_services(config_dir=str(config_dir), db_path=str(db_path))
    plan = services.restore_manager.restore_plan("b1-20260817T000000Z-000000000000")
    assert plan.target_verified is False


# -- real cli.main.main() dispatch: restore-plan/restore use RestoreServices --------


def test_main_backup_restore_plan_end_to_end_routes_through_restore_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Real argparse parsing, real env-var resolution, real dispatch through
    `cli.main.main()` -- proves `backup restore-plan` is routed through
    `build_restore_services()`, not `build_backup_services()`, by patching
    the latter to explode if it's ever called for this action."""
    from cli import main as cli_main
    from redline_core.runtime import composition as composition_module

    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    _append_backup_path_to_config_dir_on_disk(env.config_dir, env.backup_root)

    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(env.config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(env.db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    def _fail_build_backup_services(*args, **kwargs):
        raise AssertionError("`backup restore-plan` must never route through build_backup_services()")

    monkeypatch.setattr(composition_module, "build_backup_services", _fail_build_backup_services)
    monkeypatch.setattr(cli_main, "build_backup_services", _fail_build_backup_services)

    exit_code = cli_main.main(["backup", "restore-plan", target_id])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Restore Plan" in out


def test_main_backup_restore_end_to_end_never_touches_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from redline_core.resolve.adapter import ResolveScriptAdapter

    from cli import main as cli_main

    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E888")
    _append_backup_path_to_config_dir_on_disk(env.config_dir, env.backup_root)

    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(env.config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(env.db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    def _fail_resolve_init(self, *args, **kwargs):
        raise AssertionError("real `backup restore` CLI dispatch must never construct a ResolveAdapter")

    monkeypatch.setattr(ResolveScriptAdapter, "__init__", _fail_resolve_init)

    exit_code = cli_main.main(
        [
            "backup",
            "restore",
            target_id,
            "--confirm-backup-id",
            target_id,
            "--attest-mcp-stopped",
            "--attest-control-room-stopped",
            "--attest-no-other-cli-operation",
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "VERIFIED_SUCCESS." in out
