"""Shared application context for the MCP server.

One Config, one DB connection, one Resolve adapter (and the managers built
on top of them), constructed once at server startup and handed to every
tool handler. Resolve is inherently single-instance and stateful (see
docs/ARCHITECTURE.md §5) — the whole point of this module is to guarantee
exactly one of everything, not one per tool call.
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
class AppContext:
    config: RedlineConfig
    db: Database
    resolve: ResolveAdapter
    episode_manager: EpisodeManager
    asset_manager: AssetManager
    media_manager: MediaManager
    timeline_builder: TimelineBuilder
    render_manager: RenderManager
    archive_manager: ArchiveManager


def build_context(
    config_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    resolve_adapter: ResolveAdapter | None = None,
) -> AppContext:
    """Build the shared AppContext: loads config, connects the DB, connects Resolve.

    `resolve_adapter` defaults to `ResolveScriptAdapter` (the real one) unless
    explicitly overridden — e.g. with `MockResolveAdapter` for trying the
    server out before you have a Resolve Studio license, or in tests.
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

    return AppContext(
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
