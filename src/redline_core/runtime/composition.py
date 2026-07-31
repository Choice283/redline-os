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
injection redesign: the three builders below share small private
construction helpers (`_resolve_config_dir`, `_connect_database`) purely to
avoid duplicating the same few lines three times — each public builder
still returns a complete, immutable service container matching its own
declared boundary, and none of the three public builders' own behavior
changed as a result of that sharing. Add a further narrower builder only
when a real command demonstrates that boundary too, same as always.

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
from redline_core.build import BuildOrchestrator
from redline_core.config.loader import load_config
from redline_core.config.schema import RedlineConfig
from redline_core.db.database import Database
from redline_core.episode.manager import EpisodeManager
from redline_core.media.manager import MediaManager
from redline_core.render.manager import RenderManager
from redline_core.resolve.adapter import ResolveAdapter, ResolveScriptAdapter
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
    for `db`/`resolve` together."""

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
    construction, not by convention."""
    config = load_config(_resolve_config_dir(config_dir))
    db = _connect_database(db_path)

    return PersistenceServices(
        config=config,
        db=db,
        archive_manager=ArchiveManager(config, db),
    )
