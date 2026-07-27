"""Render Manager — builds/queues render jobs and tracks their status.

Rendering is long-running (real episodes can take hours), so this is
async by design per docs/ARCHITECTURE.md §5/§9: `queue_render()` returns
immediately with a job ID, and `get_render_status()` is a separate,
cheap, poll-able call. Nothing in here blocks waiting for a render to finish.

SQLite (`render_jobs` table) is the source of truth for which jobs Redline OS
knows about; Resolve's own render queue is the source of truth for whether a
given job is actually done. `get_render_status()` reconciles the two on
every call by asking Resolve and syncing the DB row if it's changed.
"""
from __future__ import annotations

import logging
from pathlib import Path

from redline_core.config.schema import RedlineConfig
from redline_core.db.database import Database
from redline_core.db.models import EpisodeStatus, RenderJob, RenderJobStatus
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.render.exceptions import RenderJobNotFoundError, RenderPresetNotFoundError
from redline_core.resolve.adapter import ResolveAdapter

logger = logging.getLogger(__name__)

# Resolve's adapter-level status strings that map cleanly onto RenderJobStatus.
# Anything else (e.g. "unknown") is left as-is rather than guessed at.
_KNOWN_STATUSES = {s.value for s in RenderJobStatus}


class RenderManager:
    def __init__(self, config: RedlineConfig, db: Database, resolve: ResolveAdapter):
        self.config = config
        self.db = db
        self.resolve = resolve

    def queue_render(self, episode_id: str, preset_name: str) -> RenderJob:
        """Queue a render for an episode using a named preset from config/render_presets.yaml.

        Raises EpisodeNotFoundError / RenderPresetNotFoundError up front,
        before ever touching Resolve, so a bad request fails fast and cheap.
        """
        episode = self.db.get_episode_by_episode_id(episode_id)
        if episode is None:
            raise EpisodeNotFoundError(f"No episode with episode_id={episode_id}.")

        preset = self.config.render_presets.get(preset_name)
        if preset is None:
            raise RenderPresetNotFoundError(f"No render preset named '{preset_name}'.")

        output_path = str(Path(episode.folder_path or ".") / preset.output_subfolder)

        job = self.db.create_render_job(episode_id, preset_name)
        resolve_job_id = self.resolve.queue_render(episode.project_name, preset.resolve_preset_name, output_path)
        self.db.update_render_job(
            job.id, resolve_job_id=resolve_job_id, output_path=output_path, status=RenderJobStatus.QUEUED
        )
        self.db.update_episode_status(episode_id, EpisodeStatus.RENDER_QUEUED)

        logger.info("Queued render for %s (preset=%s, resolve_job_id=%s)", episode_id, preset_name, resolve_job_id)
        return self.db.get_render_job_by_id(job.id)

    def get_render_status(self, job_id: int) -> RenderJob:
        """Poll Resolve for a job's live status and sync the DB row if it changed.

        If the render just completed, also bumps the episode's status to
        RENDERED — the one place render completion feeds back into the
        episode lifecycle.
        """
        job = self.db.get_render_job_by_id(job_id)
        if job is None:
            raise RenderJobNotFoundError(f"No render job with id={job_id}.")

        if job.resolve_job_id is not None:
            live_status = self.resolve.get_render_status(job.resolve_job_id)
            if live_status in _KNOWN_STATUSES and live_status != job.status.value:
                new_status = RenderJobStatus(live_status)
                self.db.update_render_job(job.id, status=new_status)
                job = self.db.get_render_job_by_id(job.id)
                if new_status == RenderJobStatus.COMPLETE:
                    self.db.update_episode_status(job.episode_id, EpisodeStatus.RENDERED)

        return job

    def cancel_render(self, job_id: int) -> RenderJob:
        job = self.db.get_render_job_by_id(job_id)
        if job is None:
            raise RenderJobNotFoundError(f"No render job with id={job_id}.")
        if job.resolve_job_id is not None:
            self.resolve.cancel_render(job.resolve_job_id)
        self.db.update_render_job(job.id, status=RenderJobStatus.CANCELLED)
        logger.info("Cancelled render job %s for %s", job_id, job.episode_id)
        return self.db.get_render_job_by_id(job.id)

    def list_render_jobs_for_episode(self, episode_id: str) -> list[RenderJob]:
        return self.db.list_render_jobs_for_episode(episode_id)
