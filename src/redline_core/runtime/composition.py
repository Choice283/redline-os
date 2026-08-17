"""Shared application composition root.

One Config, one DB connection, one Resolve adapter (and the managers built
on top of them), constructed once at process startup and handed to whichever
transport is running (MCP server, CLI, or any future transport). Resolve is
inherently single-instance and stateful (see docs/ARCHITECTURE.md §5) — the
whole point of this module is to guarantee exactly one of everything, not
one per command/tool-call.

`build_application_services()` builds the *same* full runtime every time —
full Config, full DB, a connected Resolve adapter, and all six managers.
That stayed deliberately unconditional through Missions 1-4: every command
up to `episode list` genuinely needed all of it, so adding a
capability-specific ("skip Resolve/DB for this command") construction path
would have been speculative abstraction with no real caller.

Mission 5's `asset list` was the first real, demonstrated exception: it
needs nothing but `RedlineConfig` — no SQLite, no Resolve connection. Rather
than bolt a `require_resolve=False`/`require_database=False` flag onto
`build_application_services()` (which would keep growing as more
config-only capabilities show up), `CoreServices`/`build_core_services()`
is a second, narrower composition path scoped strictly to that one
dependency boundary — configuration-backed services requiring neither
SQLite nor Resolve. It is not a general "core" layer future commands
default into; a manager earns a place on `CoreServices` only by needing
nothing but config, the same way `AssetManager` does.

Mission 7's `archive list` demonstrated a third, distinct boundary:
`ArchiveManager` needs `RedlineConfig` and a connected `Database`, but
never Resolve. `PersistenceServices`/`build_persistence_services()` below
is that third composition path — configuration-backed services requiring
SQLite persistence, but not Resolve. Also not a universal middle layer;
scoped exactly to that boundary, the same discipline as `CoreServices`.

Anything needing a Resolve adapter stays on `ApplicationServices`, which
itself is unchanged — still the full composition root for the MCP server
and every Resolve-dependent CLI command. This is not a general dependency-
injection redesign: the builders below share small private construction
helpers (`_resolve_config_dir`, `_resolve_db_path`, `_connect_database`)
purely to avoid duplicating the same few lines repeatedly — each public
builder still returns a complete, immutable service container matching its
own declared boundary, and none of the other builders' own behavior
changed as a result of that sharing. Add a further narrower builder only
when a real command demonstrates that boundary too, same as always.

Mission 1A's correction pass added a fourth such boundary,
`BackupServices`/`build_backup_services()`: Backup Manager needs config and
a database *path*, but — unlike `ArchiveManager` on `PersistenceServices`
— must never share a tier with a builder that opens a live `Database`
connection and calls `init_schema()` against the pipeline database. That
distinction (path vs. connection) is exactly why it is not simply added to
`PersistenceServices`.

This module owns construction only — it does not configure logging (each
transport entrypoints own redline_core.logging.setup.configure_logging()
timing), parse arguments, register tools, print output, or contain business
workflows.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from redline_core.archive.manager import ArchiveManager
from redline_core.asset.manager import AssetManager
from redline_core.backup.manager import BackupManager
from redline_core.build import BuildOrchestrator
from redline_core.config.loader import load_config
from redline_core.config.schema import RedlineConfig
from redline_core.db.database import Database
from redline_core.episode.manager import EpisodeManager
from redline_core.media.manager import MediaManager
from redline_core.render.manager import RenderManager
from redline_core.resolve.adapter import ResolveAdapter, ResolveScriptAdapter
from redline_core.restore.manager import RestoreManager
from redline_core.timeline.builder import TimelineBuilder
from redline_core.workflows import BuildRenderWorkflow


@dataclass
class ApplicationServices:
    config: RedlineConfig
    db: Database
    resolve: ResolveAdapter
    episode_manager: EpisodeManager
    asset_manager: AssetManager
    media_manager: MediaManager
    timeline_builder: TimelineBuilder
    render_manager: RenderManager
    build_orchestrator: BuildOrchestrator
    build_render_workflow: BuildRenderWorkflow
    archive_manager: ArchiveManager


@dataclass
class CoreServices:
    """Configuration-backed services requiring neither SQLite nor Resolve —
    not a general "core" layer every future command should route through.
    Its membership is defined strictly by that dependency boundary: a
    manager belongs here only if it, like AssetManager, needs nothing but
    RedlineConfig. Anything needing a DB connection or a Resolve adapter
    belongs on ApplicationServices, full stop, regardless of how simple
    that command otherwise looks. No `db` or `resolve` attribute exists on
    this dataclass at all — that's deliberate, not an oversight, so a
    caller can't accidentally reach for a connection this builder never
    made."""

    config: RedlineConfig
    asset_manager: AssetManager


@dataclass
class PersistenceServices:
    """Configuration-backed services requiring SQLite persistence, but not
    DaVinci Resolve — a third composition boundary alongside
    ApplicationServices (full runtime) and CoreServices (config-only), not
    a universal middle layer future commands default into. A manager
    belongs here only if it, like ArchiveManager, needs config and a DB
    connection but never touches Resolve. No `resolve` attribute exists on
    this dataclass at all, the same deliberate omission CoreServices makes
    for `db`/`resolve` together.

    `BackupManager` does **not** live here (Mission 1A correction pass):
    although it needs config and a database *path*, it must never share a
    tier with a builder that opens a live `Database` connection and calls
    `init_schema()` against the pipeline database — that is precisely the
    live-DB contact Backup Manager exists to be independent of. See
    `BackupServices`/`build_backup_services()` below, a fourth, narrower
    composition tier scoped exactly to that boundary."""

    config: RedlineConfig
    db: Database
    archive_manager: ArchiveManager


def _resolve_config_dir(config_dir: str | Path | None) -> Path:
    return Path(config_dir or os.environ.get("REDLINE_CONFIG_DIR", "./config"))


def _resolve_db_path(db_path: str | Path | None) -> Path:
    return Path(db_path or os.environ.get("REDLINE_DB_PATH", "./redline.db"))


def _connect_database(db_path: str | Path | None) -> Database:
    db = Database(_resolve_db_path(db_path)).connect()
    db.init_schema()
    return db


def build_application_services(
    config_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    resolve_adapter: ResolveAdapter | None = None,
    config: RedlineConfig | None = None,
) -> ApplicationServices:
    """Build the shared ApplicationServices: loads config, connects the DB, connects Resolve.

    `resolve_adapter` defaults to `ResolveScriptAdapter` (the real one) unless
    explicitly overridden — e.g. with `MockResolveAdapter` for trying a
    transport out before you have a Resolve Studio license, or in tests.
    """
    config = config or load_config(_resolve_config_dir(config_dir))
    db = _connect_database(db_path)

    resolve = resolve_adapter or ResolveScriptAdapter()
    resolve.connect()
    media_manager = MediaManager(config, resolve)
    timeline_builder = TimelineBuilder(config, resolve)
    episode_manager = EpisodeManager(config, db, resolve, media_manager, timeline_builder)
    render_manager = RenderManager(config, db, resolve)
    build_orchestrator = BuildOrchestrator(config=config, episode_manager=episode_manager)

    return ApplicationServices(
        config=config,
        db=db,
        resolve=resolve,
        episode_manager=episode_manager,
        asset_manager=AssetManager(config),
        media_manager=media_manager,
        timeline_builder=timeline_builder,
        render_manager=render_manager,
        build_orchestrator=build_orchestrator,
        build_render_workflow=BuildRenderWorkflow(
            build_orchestrator=build_orchestrator,
            render_manager=render_manager,
        ),
        archive_manager=ArchiveManager(config, db),
    )


def build_core_services(config_dir: str | Path | None = None) -> CoreServices:
    """Build CoreServices: loads config only. Never opens a Database
    connection, never constructs or connects a ResolveAdapter — a command
    routed through this builder genuinely cannot touch either, by
    construction, not by convention."""
    config = load_config(_resolve_config_dir(config_dir))

    return CoreServices(
        config=config,
        asset_manager=AssetManager(config),
    )


def build_persistence_services(
    config_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> PersistenceServices:
    """Build PersistenceServices: loads config, connects and initializes
    the DB. Never constructs or connects a ResolveAdapter — a command
    routed through this builder genuinely cannot touch Resolve, by
    construction, not by convention.
    """
    resolved_config_dir = _resolve_config_dir(config_dir)
    config = load_config(resolved_config_dir)
    db = _connect_database(db_path)

    return PersistenceServices(
        config=config,
        db=db,
        archive_manager=ArchiveManager(config, db),
    )


@dataclass
class BackupServices:
    """Configuration-backed services for Mission 1A Backup Manager only — a
    fourth, narrower composition boundary alongside ApplicationServices
    (full runtime), CoreServices (config-only), and PersistenceServices
    (config + a live DB connection, no Resolve).

    `BackupManager` needs `RedlineConfig`, the resolved configuration
    directory, and the database's *path* — never a live `Database`
    connection and never a Resolve adapter. It belongs on neither
    `CoreServices` (which has no path/database-adjacent notion at all) nor
    `PersistenceServices` (which exists specifically to open and initialize
    a `Database` connection — the live-DB contact Backup Manager exists to
    stay independent of). No `db` and no `resolve` attribute exists on this
    dataclass at all, the same deliberate omission `CoreServices` makes for
    `db`/`resolve` together: a caller routed through `BackupServices`
    genuinely cannot reach either, by construction, not by convention."""

    config: RedlineConfig
    backup_manager: BackupManager


def build_backup_services(
    config_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> BackupServices:
    """Build BackupServices: loads config and resolves the database path —
    never calls `Database.connect()`, never calls `Database.init_schema()`,
    and never constructs or connects a ResolveAdapter. A command routed
    through this builder genuinely cannot open a connection to the live
    pipeline database or touch Resolve, by construction, not by convention.

    `BackupManager` opens its own independent, short-lived, read-only SQLite
    connection only inside `create_backup()` (see
    `redline_core.backup.sqlite_snapshot`) — this builder never opens one on
    its behalf, for `create`, `list`, or `verify` alike.
    """
    resolved_config_dir = _resolve_config_dir(config_dir)
    config = load_config(resolved_config_dir)
    resolved_db_path = _resolve_db_path(db_path)

    return BackupServices(
        config=config,
        backup_manager=BackupManager(config, resolved_config_dir, resolved_db_path),
    )


@dataclass
class RestoreServices:
    """Configuration-backed services for Mission 1B-A1 Restore Manager only
    -- a fifth, narrower composition boundary alongside ApplicationServices,
    CoreServices, PersistenceServices, and BackupServices.

    `RestoreManager` wraps a `BackupManager` (for target verification and
    the mandatory pre-restore safety backup) and otherwise operates
    directly on `REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR` as plain filesystem
    paths -- never a live `Database` connection and never a Resolve
    adapter. `Database.init_schema()` is called exactly once inside
    `RestoreManager`'s own schema-compatibility check, and only against a
    disposable, temporary comparison database it creates and discards
    itself -- never through this composition tier, and never against the
    live or restored pipeline database. No `db` and no `resolve` attribute
    exists on this dataclass, the same deliberate omission `BackupServices`
    makes."""

    config: RedlineConfig
    backup_manager: BackupManager
    restore_manager: RestoreManager


def build_restore_services(
    config_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> RestoreServices:
    """Build RestoreServices: loads config and resolves the database path
    -- never calls `Database.connect()`, never calls `Database.init_schema()`
    against the live/pipeline database, and never constructs or connects a
    ResolveAdapter. Mirrors `build_backup_services()` exactly, plus the
    `RestoreManager` built on top of the same `BackupManager` instance.
    """
    resolved_config_dir = _resolve_config_dir(config_dir)
    config = load_config(resolved_config_dir)
    resolved_db_path = _resolve_db_path(db_path)

    backup_manager = BackupManager(config, resolved_config_dir, resolved_db_path)
    return RestoreServices(
        config=config,
        backup_manager=backup_manager,
        restore_manager=RestoreManager(backup_manager),
    )
