"""Shared, non-collected fixtures for Mission 1B-A1 Restore tests.

Deliberately named with a leading underscore so pytest does not try to
collect this module itself as a test file -- mirrors how
`tests/unit/test_backup_manager.py` builds its own environment inline, but
factored out since every restore test file needs the same
config+db+BackupManager+RestoreManager scaffolding.

Every database created here goes through `redline_core.db.database.Database
.init_schema()` unless a test explicitly wants a schema-divergent database
(built with raw ``sqlite3`` instead, to prove Restore's schema-compatibility
check actually rejects it) -- Mission 1B-A1 requires exact application-schema
compatibility, so these helpers exist to make "exactly the real schema" vs.
"a deliberately different schema" trivially distinguishable in test code.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from redline_core.restore.manager import RestoreManager

FIXED_START = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)


class IncrementingClock:
    """A test clock that ticks forward by one second on every call --
    real production code uses wall-clock time, which naturally advances
    between "create the target backup" and "restore() later creates its
    own pre-restore safety backup"; a single frozen moment would make two
    otherwise-legitimate backups collide on the same backup_id. This keeps
    tests deterministic while still avoiding that false collision."""

    def __init__(self, start: datetime = FIXED_START):
        self._current = start

    def __call__(self) -> datetime:
        moment = self._current
        self._current += timedelta(seconds=1)
        return moment


def write_minimal_config_dir(config_dir: Path, *, omit: str | None = None) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    contents = {
        "naming.yaml": (
            'episode_id_pattern: "RLC-E{episode_number:03d}"\n'
            'project_name_pattern: "{episode_id}_MASTER"\n'
        ),
        "folder_structure.yaml": 'root_path: "./_episodes"\n',
        "render_presets.yaml": "presets: []\n",
        "paths.yaml": (
            'ingest_path: "./_ingest"\n'
            'archive_path: "./_archive"\n'
            'assets_path: "./_assets"\n'
            'master_project_template: "RLC_MASTER_TEMPLATE"\n'
        ),
        "assets.yaml": "assets: []\nrequired_for_episode: []\n",
        "timeline_template.yaml": ("timeline_name_pattern: \"{episode_id}_TIMELINE\"\nmarkers: []\n"),
    }
    for filename, text in contents.items():
        if filename == omit:
            continue
        (config_dir / filename).write_text(text, encoding="utf-8")


def make_redline_config(*, backup_path: str | None) -> RedlineConfig:
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


def make_real_schema_db(db_path: Path, *, with_episode: bool = True) -> None:
    """A database built through the real, current
    ``Database.init_schema()`` -- exactly what Restore's reference
    fingerprint is built from."""
    db = Database(db_path).connect()
    db.init_schema()
    if with_episode:
        db.create_episode(1, "RLC-E001", "RLC-E001_MASTER")
    db.close()


def make_raw_sqlite_db(db_path: Path, statements: list[str]) -> None:
    """A database built entirely outside ``Database``/``init_schema()`` --
    for constructing deliberately schema-divergent databases to back up
    and then attempt (and expect to fail) to restore."""
    conn = sqlite3.connect(str(db_path))
    try:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


class Environment:
    def __init__(self, tmp_path: Path, *, configure_backup_path: bool = True, clock: IncrementingClock | None = None):
        self.tmp_path = tmp_path
        self.runtime_dir = tmp_path / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.runtime_dir / "redline.db"
        make_real_schema_db(self.db_path)

        self.config_dir = tmp_path / "config"
        write_minimal_config_dir(self.config_dir)

        self.backup_root = tmp_path / "backups"
        self.config = make_redline_config(backup_path=str(self.backup_root) if configure_backup_path else None)

        self.clock = clock or IncrementingClock()
        self.backup_manager = BackupManager(self.config, self.config_dir, self.db_path, clock=self.clock)
        self.restore_manager = RestoreManager(self.backup_manager, clock=self.clock)


def make_environment(tmp_path: Path, **kwargs) -> Environment:
    return Environment(tmp_path, **kwargs)


def make_target_backup(
    tmp_path: Path,
    env: Environment,
    *,
    db_statements: list[str] | None = None,
    episode_id: str = "RLC-E999",
    reason: str = "target backup",
    unique_dir: str = "target_source",
) -> str:
    """Create a sealed backup under `env`'s own configured backup root,
    but sourced from an *independent* database/config directory -- not
    `env.db_path`/`env.config_dir` -- so restoring it onto `env`'s live
    system is a genuine, observable content change, not a no-op restore
    of identical bytes. Shares `env.clock` (an IncrementingClock) so
    backup_ids never collide with backups created later in the same test.
    """
    source_dir = tmp_path / unique_dir
    source_dir.mkdir(parents=True, exist_ok=True)
    source_db_path = source_dir / "redline.db"
    if db_statements is None:
        make_real_schema_db(source_db_path, with_episode=False)
        db = Database(source_db_path).connect()
        db.create_episode(1, episode_id, f"{episode_id}_MASTER")
        db.close()
    else:
        make_raw_sqlite_db(source_db_path, db_statements)

    source_config_dir = source_dir / "config"
    write_minimal_config_dir(source_config_dir)

    source_backup_manager = BackupManager(env.config, source_config_dir, source_db_path, clock=env.clock)
    result = source_backup_manager.create_backup(reason=reason)
    return result.backup_id
