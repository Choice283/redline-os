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

Mission 5's `asset list` is the first real, demonstrated exception: it
needs nothing but `RedlineConfig` — no SQLite, no Resolve connection. Rather
than bolt a `require_resolve=False`/`require_database=False` flag onto
`build_application_services()` (which would keep growing as more
config-only capabilities show up), `CoreServices`/`build_core_services()`
below is a second, narrower composition path scoped strictly to that one
dependency boundary — configuration-backed services requiring neither
SQLite nor Resolve. It is not a general "core" layer future commands
default into; a manager earns a place on `CoreServices` only by needing
nothing but config, the same way `AssetManager` does. Anything needing a
DB connection or Resolve stays on `ApplicationServices`, which itself is
unchanged — still the full composition root for the MCP server and every
Resolve/DB-dependent CLI command. This is not a general dependency-
injection redesign: add a further narrower builder (e.g. for DB-only,
no-Resolve capabilities) only when a real command demonstrates that
boundary too, the same discipline as everything else in this file.

This module owns construction only — it does not configure logging (each
transport's own entrypoint calls redline_core.logging.setup.configure_logging()
at startup, the same way mcp_server/server.py and cli/main.py both do), parse
arguments, register tools, print output, or contain business workflows.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from redline_core.archive.manager import ArchiveManager
from redline_core.asset.manager import AssetManager
from redline_core.config.loader import load_config
from redline_core.config.schema import RedlineConfig
from redline_core.db.database import Database
from redline_core.episode.manager import EpisodeManager
from redline_core.media.manager import MediaManager
from redline_core.render.manager import RenderManager
from redline_core.resolve.adapter import ResolveAdapter, ResolveScriptAdapter
from redline_core.timeline.builder import TimelineBuilder


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


def build_application_services(
    config_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    resolve_adapter: ResolveAdapter | None = None,
) -> ApplicationServices:
    """Build the shared ApplicationServices: loads config, connects the DB, connects Resolve.

    `resolve_adapter` defaults to `ResolveScriptAdapter` (the real one) unless
    explicitly overridden — e.g. with `MockResolveAdapter` for trying a
    transport out before you have a Resolve Studio license, or in tests.
    """
    config_dir = Path(config_dir or os.environ.get("REDLINE_CONFIG_DIR", "./config"))
    db_path = Path(db_path or os.environ.get("REDLINE_DB_PATH", "./redline.db"))

    config = load_config(config_dir)

    db = Database(db_path).connect()
    db.init_schema()

    resolve = resolve_adapter or ResolveScriptAdapter()
    resolve.connect()
    media_manager = MediaManager(config, resolve)
    timeline_builder = TimelineBuilder(config, resolve)

    return ApplicationServices(
        config=config,
        db=db,
        resolve=resolve,
        episode_manager=EpisodeManager(config, db, resolve, media_manager, timeline_builder),
        asset_manager=AssetManager(config),
        media_manager=media_manager,
        timeline_builder=timeline_builder,
        render_manager=RenderManager(config, db, resolve),
        archive_manager=ArchiveManager(config, db),
    )


def build_core_services(config_dir: str | Path | None = None) -> CoreServices:
    """Build CoreServices: loads config only. Never opens a Database
    connection, never constructs or connects a ResolveAdapter — a command
    routed through this builder genuinely cannot touch either, by
    construction, not by convention."""
    config_dir = Path(config_dir or os.environ.get("REDLINE_CONFIG_DIR", "./config"))
    config = load_config(config_dir)

    return CoreServices(
        config=config,
        asset_manager=AssetManager(config),
    )
