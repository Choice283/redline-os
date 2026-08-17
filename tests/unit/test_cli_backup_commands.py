"""Tests for cli/backup_commands.py (Mission 1A): serialization and exit-code
behavior for `redline backup create|list|verify`, against a real temporary
database/config/backup-root -- no Resolve, no argparse/main() plumbing
(mirrors the existing test_cli_archive_*.py convention of exercising
`<resource>_commands.run()` directly against a manually constructed
services object).

Mission 1A correction pass: `backup_commands` is now routed through
`BackupServices`/`build_backup_services()`, not `PersistenceServices` --
see `redline_core.runtime.composition.BackupServices`. The database file
used below is created directly with `redline_core.db.database.Database`
purely as *test setup* (a real pipeline DB must exist on disk for
`BackupManager` to read), never as part of the composition object under
test -- `BackupServices` itself carries no `Database` instance at all.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cli import backup_commands
from redline_core.backup.manager import BackupManager
from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.db.database import Database
from redline_core.runtime.composition import BackupServices, build_backup_services

_FIXED_MOMENT = datetime(2026, 8, 16, 19, 30, 0, tzinfo=timezone.utc)
_REQUIRED_CONFIG_FILES = {
    "naming.yaml": (
        'episode_id_pattern: "RLC-E{episode_number:03d}"\nproject_name_pattern: "{episode_id}_MASTER"\n'
    ),
    "folder_structure.yaml": 'root_path: "./_episodes"\n',
    "render_presets.yaml": "presets: []\n",
    "paths.yaml": (
        'ingest_path: "./_ingest"\narchive_path: "./_archive"\nassets_path: "./_assets"\n'
        'master_project_template: "RLC_MASTER_TEMPLATE"\n'
    ),
    "assets.yaml": "assets: []\nrequired_for_episode: []\n",
    "timeline_template.yaml": 'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n',
}


def _write_config_dir(config_dir: Path, *, backup_path: str | None = None) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in _REQUIRED_CONFIG_FILES.items():
        if filename == "paths.yaml" and backup_path is not None:
            # single-quoted YAML scalar: no backslash-escape processing, safe
            # for a raw Windows path.
            text = text + f"backup_path: '{backup_path}'\n"
        (config_dir / filename).write_text(text, encoding="utf-8")


def _make_redline_config(*, backup_path: str | None) -> RedlineConfig:
    return RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path="./_episodes"),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path="./_ingest",
            archive_path="./_archive",
            assets_path="./_assets",
            master_project_template="RLC_MASTER_TEMPLATE",
            backup_path=backup_path,
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )


def _make_services(tmp_path: Path, *, configure_backup_path: bool = True) -> BackupServices:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    _seed_db = Database(db_path).connect()  # test setup only: a real pipeline DB must exist on disk
    _seed_db.init_schema()
    _seed_db.close()

    config_dir = tmp_path / "config"
    _write_config_dir(config_dir)

    backup_root = tmp_path / "backups"
    config = _make_redline_config(backup_path=str(backup_root) if configure_backup_path else None)
    backup_manager = BackupManager(config, config_dir, db_path, clock=lambda: _FIXED_MOMENT)
    return BackupServices(config=config, backup_manager=backup_manager)


def test_backup_create_exit_zero_and_serializes_result(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    services = _make_services(tmp_path)
    args = argparse.Namespace(action="create", reason="cli test")

    exit_code = backup_commands.run(args, services)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Backup created" not in out  # banner text is the header, not this exact phrase
    assert "Backup ID:" in out
    assert "Database SHA-256:" in out


def test_backup_create_exit_one_when_backup_path_not_configured(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    services = _make_services(tmp_path, configure_backup_path=False)
    args = argparse.Namespace(action="create", reason=None)

    exit_code = backup_commands.run(args, services)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Backup create failed" in out


def test_backup_list_exit_zero_empty_and_populated(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    services = _make_services(tmp_path)

    empty_exit_code = backup_commands.run(argparse.Namespace(action="list"), services)
    assert empty_exit_code == 0
    assert "No backups found." in capsys.readouterr().out

    create_exit_code = backup_commands.run(argparse.Namespace(action="create", reason=None), services)
    assert create_exit_code == 0
    capsys.readouterr()

    list_exit_code = backup_commands.run(argparse.Namespace(action="list"), services)
    assert list_exit_code == 0
    out = capsys.readouterr().out
    assert "1 backup(s)." in out


def test_backup_verify_exit_zero_for_real_backup(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    services = _make_services(tmp_path)
    backup_commands.run(argparse.Namespace(action="create", reason=None), services)
    backup_id = services.backup_manager.list_backups()[0].backup_id
    capsys.readouterr()

    exit_code = backup_commands.run(argparse.Namespace(action="verify", backup_id=backup_id), services)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Verified:           yes" in out


def test_backup_verify_exit_one_for_unknown_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    services = _make_services(tmp_path)
    backup_commands.run(argparse.Namespace(action="create", reason=None), services)
    capsys.readouterr()

    exit_code = backup_commands.run(
        argparse.Namespace(action="verify", backup_id="b1-20260816T193000Z-000000000000"), services
    )

    assert exit_code == 1
    assert "Backup verify failed" in capsys.readouterr().out


def test_run_returns_none_for_unhandled_action(tmp_path: Path):
    services = _make_services(tmp_path)
    assert backup_commands.run(argparse.Namespace(action="restore"), services) is None


# -- Correction 4: non-mutating backup composition (behavioral proof) -----------
#
# Mission 1A correction pass: independent review found `build_persistence_
# services()` (the pre-Mission-1A `archive`-tier builder backup commands
# were routed through) opens a live `Database` connection and calls
# `Database.init_schema()` even for read-only `backup list`/`backup
# verify`. `BackupServices`/`build_backup_services()` (see
# `redline_core.runtime.composition`) is the corrected, narrower
# composition tier. A *static* check (e.g. "backup_commands.py doesn't
# import Database") would prove intent but not actual behavior; these
# tests monkeypatch `Database.connect`/`Database.init_schema` themselves to
# raise, then genuinely exercise the composition builder and the full
# create/list/verify CLI dispatch, proving neither is ever reached.


def test_build_backup_services_never_touches_database_class(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    seed_db = Database(db_path).connect()  # test setup only, before the patch below is installed
    seed_db.init_schema()
    seed_db.close()

    config_dir = tmp_path / "config"
    _write_config_dir(config_dir)

    def _fail_connect(self):
        raise AssertionError("build_backup_services() must never call Database.connect()")

    def _fail_init_schema(self):
        raise AssertionError("build_backup_services() must never call Database.init_schema()")

    monkeypatch.setattr(Database, "connect", _fail_connect)
    monkeypatch.setattr(Database, "init_schema", _fail_init_schema)

    services = build_backup_services(config_dir=str(config_dir), db_path=str(db_path))

    assert services.backup_manager is not None
    assert services.config is not None


def test_backup_create_list_verify_never_touch_database_class(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    seed_db = Database(db_path).connect()  # test setup only, before the patch below is installed
    seed_db.init_schema()
    seed_db.close()

    backup_root = tmp_path / "backups"
    config_dir = tmp_path / "config"
    _write_config_dir(config_dir, backup_path=str(backup_root))

    services = build_backup_services(config_dir=str(config_dir), db_path=str(db_path))

    def _fail_connect(self):
        raise AssertionError("`backup` CLI dispatch must never call Database.connect()")

    def _fail_init_schema(self):
        raise AssertionError("`backup` CLI dispatch must never call Database.init_schema()")

    monkeypatch.setattr(Database, "connect", _fail_connect)
    monkeypatch.setattr(Database, "init_schema", _fail_init_schema)

    create_exit = backup_commands.run(argparse.Namespace(action="create", reason=None), services)
    assert create_exit == 0

    list_exit = backup_commands.run(argparse.Namespace(action="list"), services)
    assert list_exit == 0

    backup_id = services.backup_manager.list_backups()[0].backup_id
    verify_exit = backup_commands.run(argparse.Namespace(action="verify", backup_id=backup_id), services)
    assert verify_exit == 0


def test_build_backup_services_never_constructs_resolve_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from redline_core.resolve.adapter import ResolveScriptAdapter

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    seed_db = Database(db_path).connect()
    seed_db.init_schema()
    seed_db.close()

    backup_root = tmp_path / "backups"
    config_dir = tmp_path / "config"
    _write_config_dir(config_dir, backup_path=str(backup_root))

    def _fail_init(self, *args, **kwargs):
        raise AssertionError("backup composition must never construct a ResolveAdapter")

    monkeypatch.setattr(ResolveScriptAdapter, "__init__", _fail_init)

    services = build_backup_services(config_dir=str(config_dir), db_path=str(db_path))
    create_exit = backup_commands.run(argparse.Namespace(action="create", reason=None), services)
    assert create_exit == 0
    list_exit = backup_commands.run(argparse.Namespace(action="list"), services)
    assert list_exit == 0


def test_register_parser_has_no_restore_action():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)

    with pytest.raises(SystemExit):
        parser.parse_args(["backup", "restore", "some-id"])


# -- Correction A (second correction pass): real cli.main dispatch proof --------
#
# The tests above exercise build_backup_services() and backup_commands.run()
# directly -- neither goes through cli.main.main()'s actual argparse/dispatch
# path, so neither would fail if main.py's `args.resource == "backup"` branch
# were reverted to call build_persistence_services() instead. These tests
# close that gap: they invoke the real `redline backup ...` CLI entrypoint
# end-to-end (real parser, real dispatch, real REDLINE_CONFIG_DIR/REDLINE_
# DB_PATH environment resolution -- the same mechanism build_backup_services()
# itself uses), with Database.connect/Database.init_schema/ResolveScriptAdapter
# construction all monkeypatched to raise. If a future edit changed main.py's
# backup branch back to build_persistence_services() (which does call
# Database.connect()+init_schema()), these tests would fail.


def _write_isolated_config_dir_for_main(config_dir: Path, *, backup_path: str) -> None:
    """Same shape as `_write_config_dir()` but mirrors the archive suite's
    `write_isolated_config_dir()` naming for an end-to-end `cli.main.main()`
    invocation. Single-quoted YAML scalar for `backup_path` -- unlike the
    archive suite's own double-quoted interpolation (which breaks on Windows
    paths containing backslashes; a pre-existing, unrelated baseline issue,
    not repeated here)."""
    _write_config_dir(config_dir, backup_path=backup_path)


def test_main_backup_list_end_to_end_never_touches_database_or_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from redline_core.resolve.adapter import ResolveScriptAdapter

    from cli import main as cli_main

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    seed_db = Database(db_path).connect()  # test setup only, before the patch below is installed
    seed_db.init_schema()
    seed_db.close()

    backup_root = tmp_path / "backups"
    config_dir = tmp_path / "config"
    _write_isolated_config_dir_for_main(config_dir, backup_path=str(backup_root))

    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    def _fail_connect(self):
        raise AssertionError("real `backup list` CLI dispatch must never call Database.connect()")

    def _fail_init_schema(self):
        raise AssertionError("real `backup list` CLI dispatch must never call Database.init_schema()")

    def _fail_resolve_init(self, *args, **kwargs):
        raise AssertionError("real `backup list` CLI dispatch must never construct a ResolveAdapter")

    monkeypatch.setattr(Database, "connect", _fail_connect)
    monkeypatch.setattr(Database, "init_schema", _fail_init_schema)
    monkeypatch.setattr(ResolveScriptAdapter, "__init__", _fail_resolve_init)

    exit_code = cli_main.main(["backup", "list"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No backups found." in out


def test_main_backup_create_list_verify_end_to_end_never_touch_database_or_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The fuller proof: `backup create`, `backup list`, and `backup verify`
    all invoked through the real cli.main.main() entrypoint in sequence,
    with Database.connect/init_schema/ResolveScriptAdapter construction all
    monkeypatched to raise for the entire sequence -- not just `list`."""
    from redline_core.resolve.adapter import ResolveScriptAdapter

    from cli import main as cli_main

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    seed_db = Database(db_path).connect()  # test setup only, before the patch below is installed
    seed_db.init_schema()
    seed_db.close()

    backup_root = tmp_path / "backups"
    config_dir = tmp_path / "config"
    _write_isolated_config_dir_for_main(config_dir, backup_path=str(backup_root))

    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    def _fail_connect(self):
        raise AssertionError("real `backup` CLI dispatch must never call Database.connect()")

    def _fail_init_schema(self):
        raise AssertionError("real `backup` CLI dispatch must never call Database.init_schema()")

    def _fail_resolve_init(self, *args, **kwargs):
        raise AssertionError("real `backup` CLI dispatch must never construct a ResolveAdapter")

    monkeypatch.setattr(Database, "connect", _fail_connect)
    monkeypatch.setattr(Database, "init_schema", _fail_init_schema)
    monkeypatch.setattr(ResolveScriptAdapter, "__init__", _fail_resolve_init)

    create_exit_code = cli_main.main(["backup", "create", "--reason", "end-to-end dispatch proof"])
    create_out = capsys.readouterr().out
    assert create_exit_code == 0, create_out
    assert "Backup ID:" in create_out

    backup_id = next(
        line.split(":", 1)[1].strip() for line in create_out.splitlines() if line.startswith("Backup ID:")
    )

    list_exit_code = cli_main.main(["backup", "list"])
    list_out = capsys.readouterr().out
    assert list_exit_code == 0, list_out
    assert backup_id in list_out
    assert "1 backup(s)." in list_out

    verify_exit_code = cli_main.main(["backup", "verify", backup_id])
    verify_out = capsys.readouterr().out
    assert verify_exit_code == 0, verify_out
    assert "Verified:           yes" in verify_out
