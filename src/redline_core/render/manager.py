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
    RenderJobMissingResolveIdError,
    RenderJobNotFoundError,
    RenderJobNotStartableError,
    RenderOutputCollisionError,
    RenderPersistenceError,
    RenderPresetNotFoundError,
    RenderReconciliationRequiredError,
    RenderStartPersistenceReconciliationRequiredError,
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

    def start_render(self, job_id: int) -> RenderJob:
        """Start rendering an already-queued Redline render job.

        Rejects, each before the start-specific `ResolveAdapter.start_render()`
        call: a missing DB job; a job with no persisted `resolve_job_id`
        (never accepted by Resolve); any job not currently `QUEUED`; a
        `QUEUED` job whose persisted `resolve_job_id`/`project_name`/
        `timeline_name`/`output_path` are not each a usable string (see
        `_require_usable_persisted_string()` — fails closed on a
        non-string value or one with leading/trailing/all whitespace
        rather than silently repairing corrupted persisted identity); and
        a `QUEUED` job whose expected output path already exists on disk
        (a start-time recheck of the same collision the queue-time path
        already enforces, since the filesystem can change between
        queueing and starting). None of these local checks prove Resolve
        has not already been *connected to* — `redline_core.runtime.composition`
        connects the adapter unconditionally before any CLI command
        dispatches — they prove only that no start-specific mutation call
        has happened yet for this job.

        Calls `ResolveAdapter.start_render()` exactly once, passing the
        job's own persisted `project_name`/`timeline_name`/`resolve_job_id`/
        `output_path`. Any exception from that call — including
        `RenderStartReconciliationRequiredError`, raised only once
        `StartRendering()` has actually been invoked live — propagates
        unchanged, and this method performs no database write in that
        case: the job's DB status stays exactly `QUEUED`. A caller may
        safely issue a fresh `start_render()` call for an ordinary
        pre-mutation rejection (e.g. a bad precondition); a
        `RenderStartReconciliationRequiredError`, by contrast, means the
        live Resolve state is unproven and must be reconciled manually
        before this job is touched again — this method never distinguishes
        the two automatically, it simply never retries anything itself.

        Once the adapter call returns normally, Resolve has already
        independently proven (via its own getter-only postcondition) that
        the target job is `Rendering`. Persistence uses a guarded
        `QUEUED -> RENDERING` database transition
        (`Database.transition_render_job_to_rendering()`) rather than an
        unconditional write, so a persistence failure at this point —
        Resolve confirmed rendering, but Redline's own database could not
        record it — raises the distinct
        `RenderStartPersistenceReconciliationRequiredError` instead of
        silently leaving (or claiming) an incorrect DB state. This method
        never compensates a persistence failure by calling
        `StopRendering()`, deleting the Resolve job, or invoking
        `ResolveAdapter.start_render()` again — any of those could affect a
        render that is already legitimately in progress.
        """
        job = self.db.get_render_job_by_id(job_id)
        if job is None:
            raise RenderJobNotFoundError(f"No render job with id={job_id}.")
        if job.resolve_job_id is None:
            raise RenderJobMissingResolveIdError(
                f"Render job {job_id} has no resolve_job_id; it was never accepted by Resolve."
            )
        if job.status != RenderJobStatus.QUEUED:
            raise RenderJobNotStartableError(
                f"Render job {job_id} cannot be started from status {job.status.value!r}; "
                "only a queued job can be started."
            )
        resolve_job_id = self._require_usable_persisted_string(
            job.resolve_job_id, job_id=job_id, field_name="resolve_job_id"
        )
        project_name = self._require_usable_persisted_string(
            job.project_name, job_id=job_id, field_name="project_name"
        )
        timeline_name = self._require_usable_persisted_string(
            job.timeline_name, job_id=job_id, field_name="timeline_name"
        )
        output_path = self._require_usable_persisted_string(
            job.output_path, job_id=job_id, field_name="output_path"
        )
        self._reject_start_time_output_collision(job.id, output_path)

        # Any exception here -- including RenderStartReconciliationRequiredError --
        # propagates unchanged. No database write happens below unless this
        # call returns normally, which only happens once the adapter's own
        # getter-only postcondition has independently confirmed 'Rendering'.
        self.resolve.start_render(
            project_name=project_name,
            timeline_name=timeline_name,
            resolve_job_id=resolve_job_id,
            output_path=output_path,
        )

        try:
            transitioned = self.db.transition_render_job_to_rendering(job.id)
        except Exception as exc:
            raise RenderStartPersistenceReconciliationRequiredError(
                f"Resolve render job {job.resolve_job_id!r} is confirmed Rendering, but Redline's database "
                f"transition to RENDERING failed for render job {job.id}. Resolve may already be rendering "
                "while Redline's own record remains QUEUED. Do not call start_render() again for this job "
                "until manual reconciliation confirms the database state."
            ) from exc
        if not transitioned:
            raise RenderStartPersistenceReconciliationRequiredError(
                f"Resolve render job {job.resolve_job_id!r} is confirmed Rendering, but Redline could not "
                f"guarantee exactly one QUEUED row transitioned to RENDERING for render job {job.id}. "
                "Resolve may already be rendering while Redline's own record is stale. Do not call "
                "start_render() again for this job until manual reconciliation confirms the database state."
            )

        try:
            reloaded = self.db.get_render_job_by_id(job.id)
        except Exception as exc:
            raise RenderStartPersistenceReconciliationRequiredError(
                f"Resolve render job {job.resolve_job_id!r} is confirmed Rendering and the RENDERING "
                f"transition succeeded, but Redline could not reload render job {job.id} afterward."
            ) from exc
        if reloaded is None:
            raise RenderStartPersistenceReconciliationRequiredError(
                f"Resolve render job {job.resolve_job_id!r} is confirmed Rendering and the RENDERING "
                f"transition succeeded, but render job {job.id} could not be found afterward."
            )

        logger.info("Started render job %s for %s", job_id, job.episode_id)
        return reloaded

    def _require_usable_persisted_string(self, value: object, *, job_id: int, field_name: str) -> str:
        """Fail closed on malformed persisted render-job identity rather
        than silently repairing it.

        A `bool`/`int`/`dict`/any other non-`str` value is rejected
        outright, never coerced into a string. A value that is empty,
        all-whitespace, or has leading/trailing whitespace is also
        rejected -- Redline's own writers (`Database.claim_render_output()`
        et al.) never produce such a value, so encountering one here means
        the persisted row is corrupted or was written by something else;
        silently `.strip()`-ing it and proceeding would paper over that
        rather than surface it.
        """
        if isinstance(value, bool) or not isinstance(value, str):
            raise RenderJobNotStartableError(
                f"Render job {job_id} has a non-string persisted {field_name} "
                f"({type(value).__name__}); refusing to start."
            )
        if value == "" or value != value.strip():
            raise RenderJobNotStartableError(
                f"Render job {job_id} has a blank or improperly-whitespaced persisted {field_name}; "
                "refusing to start."
            )
        return value

    def _reject_start_time_output_collision(self, job_id: int, output_path: str) -> None:
        """Start-time recheck of the queue-time output collision guard
        (`_reject_collisions()`), against the persisted `output_path`.
        Runs before the start-specific `ResolveAdapter.start_render()`
        call -- the filesystem can change between when a job was queued
        and when it is started."""
        resolved_output_path = Path(output_path)
        if resolved_output_path.exists():
            raise RenderOutputCollisionError(
                f"Render output already exists: {resolved_output_path}. Render start mutation was not attempted."
            )

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
