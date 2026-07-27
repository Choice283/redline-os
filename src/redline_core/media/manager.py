"""Media Manager — matches ingested media to an episode and organizes it
into the Resolve media pool.

Matching is done purely by filename convention (the episode_id, e.g.
"RLC-E025", appearing in the filename) — Redline OS doesn't inspect media
metadata at this stage. Import into Resolve's media pool goes through
ResolveAdapter.import_media(), same interface whether that's the real
adapter or MockResolveAdapter in tests.
"""
from __future__ import annotations

import logging
from pathlib import Path

from redline_core.config.schema import RedlineConfig
from redline_core.resolve.adapter import ResolveAdapter

logger = logging.getLogger(__name__)


class MediaManager:
    def __init__(self, config: RedlineConfig, resolve: ResolveAdapter):
        self.config = config
        self.resolve = resolve

    def scan_ingest_for_episode(self, episode_id: str) -> list[Path]:
        """Return every file directly under ingest_path whose name contains episode_id.

        Returns an empty list (rather than raising) if the ingest folder
        doesn't exist yet — an empty ingest folder is a normal state, not
        an error condition.
        """
        ingest_path = Path(self.config.paths.ingest_path)
        if not ingest_path.is_dir():
            logger.warning("Ingest path %s does not exist; no media to scan.", ingest_path)
            return []
        matches = sorted(p for p in ingest_path.iterdir() if p.is_file() and episode_id in p.name)
        logger.info("Found %d ingest file(s) matching %s", len(matches), episode_id)
        return matches

    def organize_bins(self, project_name: str, episode_id: str, bin_name: str = "footage") -> list[str]:
        """Scan ingest for this episode's media and import it into the project's media pool.

        Returns the clip IDs Resolve assigned (empty list if nothing matched).
        """
        media_paths = self.scan_ingest_for_episode(episode_id)
        if not media_paths:
            return []
        clip_ids = self.resolve.import_media(project_name, [str(p) for p in media_paths], bin_name)
        logger.info("Imported %d clip(s) into project %s bin '%s'", len(clip_ids), project_name, bin_name)
        return clip_ids
