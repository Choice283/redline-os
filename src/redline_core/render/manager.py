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
from redline_core.render.exceptions import (
    RenderJobNotFoundError,
    RenderOutputCollisionError,
    RenderPersistenceError,
    RenderPresetNotFoundError,
    RenderReconciliationRequiredError,
    RenderTimelineNotRenderableError,
)
from redline_core.render.plan import RenderOutputPlan, build_render_output_plan
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

        timeline_name = self.config.timeline.timeline_name_pattern.format(episode_id=episode.episode_id)
        plan = build_render_output_plan(episode, preset, timeline_name)

        self._reject_collisions(plan)
        self._enforce_renderability(preset, plan)
        claim = self.db.claim_render_output(
            episode_id=episode_id,
            preset_name=preset_name,
            project_name=plan.project_name,
            timeline_name=plan.timeline_name,
            output_path=str(plan.output_path),
        )
        if claim is None:
            raise RenderOutputCollisionError(f"Active render job already targets output: {plan.output_path}")

        try:
            resolve_job_id = self.resolve.queue_render_job(
                project_name=plan.project_name,
                timeline_name=plan.timeline_name,
                resolve_preset_name=plan.resolve_preset_name,
                target_directory=str(plan.output_directory),
                custom_name=plan.output_stem,
            )
        except Exception as queue_exc:
            try:
                self.db.release_render_output_claim(claim.id)
            except Exception as release_exc:
                raise RenderPersistenceError(
                    f"Resolve queueing failed before acceptance, and Redline could not release database "
                    f"output claim {claim.id!r}."
                ) from release_exc
            raise queue_exc

        try:
            job = self.db.finalize_render_output_claim(claim.id, resolve_job_id)
        except Exception as exc:
            try:
                self.resolve.delete_render_job(plan.project_name, resolve_job_id)
            except Exception as delete_exc:
                logger.exception(
                    "Resolve render job %s was accepted but Redline could not persist it or delete it.",
                    resolve_job_id,
                )
                raise RenderReconciliationRequiredError(
                    f"Resolve accepted render job {resolve_job_id!r}, but database persistence failed and "
                    "best-effort Resolve deletion also failed. Manual reconciliation is required."
                ) from delete_exc
            try:
                self.db.release_render_output_claim(claim.id)
            except Exception as release_exc:
                raise RenderPersistenceError(
                    f"Resolve accepted render job {resolve_job_id!r} and the job was removed, but Redline "
                    f"could not release database output claim {claim.id!r}."
                ) from release_exc
            raise RenderPersistenceError(
                f"Resolve accepted render job {resolve_job_id!r}, but database persistence failed; "
                "the newly queued Resolve job was removed."
            ) from exc

        logger.info("Queued render for %s (preset=%s, resolve_job_id=%s)", episode_id, preset_name, resolve_job_id)
        return job

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

    def _reject_collisions(self, plan: RenderOutputPlan) -> None:
        if plan.output_path.exists():
            raise RenderOutputCollisionError(f"Render output already exists: {plan.output_path}")

        existing = self.db.get_active_render_job_by_output_path(str(plan.output_path))
        if existing is not None:
            raise RenderOutputCollisionError(
                f"Active render job {existing.id} already targets output: {plan.output_path}"
            )

        for job in self.resolve.list_render_jobs(plan.project_name):
            if self._resolve_job_targets_plan(job, plan):
                job_id = job.get("JobId") or job.get("JobID") or job.get("jobId") or job.get("job_id") or "unknown"
                raise RenderOutputCollisionError(
                    f"Resolve render job {job_id!r} already targets output: {plan.output_path}"
                )

    def _enforce_renderability(self, preset, plan: RenderOutputPlan) -> None:
        """Fail closed before any SQLite claim or Resolve queue mutation when
        `preset` requires a video payload the target timeline doesn't have.

        Preset-specific: only presets with `requires_video_payload: true`
        (currently `broadcast_master`, per the Phase 14 Test D finding) are
        checked. Other presets are unaffected.
        """
        if not preset.requires_video_payload:
            return

        video_item_count = self.resolve.get_video_timeline_item_count(plan.project_name, plan.timeline_name)
        if video_item_count <= 0:
            raise RenderTimelineNotRenderableError(
                f"Timeline {plan.timeline_name!r} in project {plan.project_name!r} is not renderable "
                f"with preset {preset.name!r}: no video TimelineItems were found. Resolve queue "
                "submission was not attempted."
            )

    def _resolve_job_targets_plan(self, job: dict, plan: RenderOutputPlan) -> bool:
        target_dir = self._job_value(job, "TargetDir", "targetDir", "target_dir")
        custom_name = self._job_value(job, "CustomName", "customName", "custom_name")
        if target_dir is None or custom_name is None:
            return False
        if Path(str(target_dir)).expanduser().resolve() != plan.output_directory:
            return False
        if str(custom_name) != plan.output_stem:
            return False

        project_name = self._job_value(job, "ProjectName", "Project", "project_name", "projectName")
        if project_name is not None and str(project_name) != plan.project_name:
            return False
        timeline_name = self._job_value(job, "TimelineName", "Timeline", "timeline_name", "timelineName")
        if timeline_name is not None and str(timeline_name) != plan.timeline_name:
            return False
        return True

    def _job_value(self, job: dict, *keys: str) -> object | None:
        for key in keys:
            value = job.get(key)
            if value is not None:
                return value
        return None
