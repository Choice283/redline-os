"""In-memory mock of ResolveAdapter, used by every unit test.

This lets all of redline_core's business logic (Episode Manager, Timeline
Builder, Render Manager, etc.) be built and tested WITHOUT a real DaVinci
Resolve Studio license or a running instance. Real behavior is verified
separately, manually, in tests/integration against ResolveScriptAdapter.
"""
from __future__ import annotations

import itertools
import logging
from pathlib import Path

from redline_core.resolve.adapter import ProjectHandle, ResolveAdapter
from redline_core.resolve.exceptions import (
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    RenderJobError,
    TimelineOperationError,
)

logger = logging.getLogger(__name__)


class MockResolveAdapter(ResolveAdapter):
    """Fake Resolve backend: dicts standing in for projects/timelines/render jobs."""

    def __init__(self) -> None:
        self.connected = False
        self.projects: dict[str, ProjectHandle] = {}
        self.media: dict[str, list[str]] = {}       # project_name -> clip ids
        self.timelines: dict[str, list[str]] = {}    # project_name -> timeline names
        self.markers: dict[str, list[dict]] = {}     # f"{project}:{timeline}" -> markers
        self.timeline_items: dict[str, list[dict]] = {}  # f"{project}:{timeline}" -> placement records
        self.render_jobs: dict[str, str] = {}        # job_id -> status
        self.render_job_metadata: dict[str, dict] = {}
        self.video_timeline_item_counts: dict[str, int] = {}  # f"{project}:{timeline}" -> count
        self._job_ids = itertools.count(1)
        self._timeline_item_ids = itertools.count(1)

    def connect(self) -> None:
        self.connected = True
        logger.info("MockResolveAdapter connected (no real Resolve involved).")

    def _require_connected(self) -> None:
        if not self.connected:
            raise RuntimeError("MockResolveAdapter.connect() must be called first.")

    def duplicate_project(self, project_name: str, template_name: str) -> ProjectHandle:
        self._require_connected()
        if project_name in self.projects:
            raise ProjectAlreadyExistsError(f"Project '{project_name}' already exists.")
        handle = ProjectHandle(name=project_name, path=f"/mock/projects/{project_name}.drp")
        self.projects[project_name] = handle
        self.media[project_name] = []
        self.timelines[project_name] = []
        logger.info("Duplicated template '%s' as '%s' (mock).", template_name, project_name)
        return handle

    def import_media(self, project_name: str, media_paths: list[str], bin_name: str) -> list[str]:
        self._require_connected()
        if project_name not in self.projects:
            raise ProjectNotFoundError(f"Project '{project_name}' does not exist.")
        clip_ids = [f"{project_name}:{bin_name}:{i}" for i, _ in enumerate(media_paths)]
        self.media[project_name].extend(clip_ids)
        return clip_ids

    def build_timeline(self, project_name: str, timeline_name: str) -> str:
        self._require_connected()
        if project_name not in self.projects:
            raise ProjectNotFoundError(f"Project '{project_name}' does not exist.")
        timelines = self.timelines.setdefault(project_name, [])
        if timeline_name not in timelines:
            timelines.append(timeline_name)
        return timeline_name

    def add_markers(self, project_name: str, timeline_name: str, markers: list[dict]) -> None:
        self._require_connected()
        if self.timelines.get(project_name) is None or timeline_name not in self.timelines[project_name]:
            raise TimelineOperationError(f"Timeline '{timeline_name}' does not exist.")
        key = f"{project_name}:{timeline_name}"
        self.markers.setdefault(key, []).extend(markers)

    def place_clips(self, project_name: str, timeline_name: str, clip_ids: list[str]) -> list[str]:
        self._require_connected()
        self._validate_clip_ids_container(clip_ids)
        if not clip_ids:
            return []

        self._validate_clip_ids(clip_ids)
        if project_name not in self.projects:
            raise ProjectNotFoundError(f"Project '{project_name}' does not exist.")
        if self.timelines.get(project_name) is None or timeline_name not in self.timelines[project_name]:
            raise TimelineOperationError(f"Timeline '{timeline_name}' does not exist.")

        imported_clip_ids = set(self.media.get(project_name, []))
        missing = [clip_id for clip_id in clip_ids if clip_id not in imported_clip_ids]
        if missing:
            raise TimelineOperationError("Media Pool clip ID(s) not found: " + ", ".join(missing))

        key = f"{project_name}:{timeline_name}"
        records = self.timeline_items.setdefault(key, [])
        timeline_item_ids: list[str] = []
        for order, clip_id in enumerate(clip_ids):
            timeline_item_id = f"{project_name}:{timeline_name}:timeline-item-{next(self._timeline_item_ids)}"
            records.append({"timeline_item_id": timeline_item_id, "clip_id": clip_id, "order": order})
            timeline_item_ids.append(timeline_item_id)
        return timeline_item_ids

    def _validate_clip_ids_container(self, clip_ids: list[str]) -> None:
        if not isinstance(clip_ids, list):
            raise TimelineOperationError("clip_ids must be a list of strings.")

    def _validate_clip_ids(self, clip_ids: list[str]) -> None:
        failures: list[str] = []
        seen: dict[str, int] = {}
        duplicates: list[str] = []
        for index, clip_id in enumerate(clip_ids):
            if not isinstance(clip_id, str) or not clip_id.strip():
                failures.append(f"clip ID index {index}: must be a non-empty string")
                continue
            if clip_id in seen:
                duplicates.append(f"{clip_id!r} at indexes {seen[clip_id]} and {index}")
            else:
                seen[clip_id] = index
        if failures:
            raise TimelineOperationError("Invalid clip ID input: " + "; ".join(failures))
        if duplicates:
            raise TimelineOperationError("Duplicate clip ID input: " + "; ".join(duplicates))

    def queue_render_job(
        self,
        *,
        project_name: str,
        timeline_name: str,
        resolve_preset_name: str,
        target_directory: str,
        custom_name: str,
    ) -> str:
        self._require_connected()
        if project_name not in self.projects:
            raise ProjectNotFoundError(f"Project '{project_name}' does not exist.")
        if timeline_name not in self.timelines.get(project_name, []):
            raise RenderJobError(f"Timeline '{timeline_name}' does not exist.")
        job_id = f"mock-job-{next(self._job_ids)}"
        self.render_jobs[job_id] = "queued"
        self.render_job_metadata[job_id] = {
            "JobId": job_id,
            "ProjectName": project_name,
            "TimelineName": timeline_name,
            "TargetDir": target_directory,
            "CustomName": custom_name,
            "RenderPreset": resolve_preset_name,
        }
        return job_id

    def list_render_jobs(self, project_name: str) -> list[dict]:
        self._require_connected()
        if project_name not in self.projects:
            raise ProjectNotFoundError(f"Project '{project_name}' does not exist.")
        return [
            dict(metadata)
            for job_id, metadata in self.render_job_metadata.items()
            if metadata.get("ProjectName") == project_name and self.render_jobs.get(job_id) in {"queued", "rendering"}
        ]

    def delete_render_job(self, project_name: str, resolve_job_id: str) -> None:
        self._require_connected()
        metadata = self.render_job_metadata.get(resolve_job_id)
        if metadata is None or metadata.get("ProjectName") != project_name:
            raise RenderJobError(f"No render job '{resolve_job_id}' to delete.")
        self.render_jobs.pop(resolve_job_id, None)
        self.render_job_metadata.pop(resolve_job_id, None)

    def get_render_status(self, resolve_job_id: str) -> str:
        self._require_connected()
        return self.render_jobs.get(resolve_job_id, "unknown")

    def cancel_render(self, resolve_job_id: str) -> None:
        self._require_connected()
        current = self.render_jobs.get(resolve_job_id)
        if current is None:
            raise RenderJobError(f"No render job '{resolve_job_id}' to cancel.")
        if current in ("complete", "failed", "cancelled"):
            raise RenderJobError(f"Render job '{resolve_job_id}' is already '{current}' and cannot be cancelled.")
        self.render_jobs[resolve_job_id] = "cancelled"

    def start_render(
        self, *, project_name: str, timeline_name: str, resolve_job_id: str, output_path: str
    ) -> None:
        """Mirrors `ResolveScriptAdapter.start_render()`'s identity-binding
        contract: the requested job must actually belong to `project_name`
        and `timeline_name`, and its own stored queue destination must
        resolve to `output_path`, not merely exist somewhere.

        Uses the same metadata `queue_render_job()` already records per
        job: `TargetDir` (a real directory-path comparison, directly
        analogous to the real adapter's `TargetDir` check) and `CustomName`
        (compared here against `Path(output_path).stem`).

        `CustomName` is NOT a faithful stand-in for Resolve's real
        `OutputFilename` representation -- Rev4 correction: live
        getter-only evidence from a real, running Resolve Studio 21.0.3.7
        instance (`RLC-E9901_render_queue_snapshot_rev3_20260810T233837Z.json`,
        SHA-256 `f2afab5c4e2fb04821c928511341801e3ae6c232ed9fbbe70151c369710c8975`)
        shows `GetRenderJobList()` reports `OutputFilename` as the
        *complete* filename, extension included (e.g.
        `RLC-E9901_MASTER.mov`) -- which is exactly what
        `ResolveScriptAdapter._require_exact_queued_output_destination()`
        now compares against. `CustomName` here models the *queue-input*
        identity `RenderManager.queue_render()` actually writes via
        `SetRenderSettings({"CustomName": ...})` (always the extensionless
        stem, by Redline's own established convention -- see
        `RenderOutputPlan.output_stem`), not the *queue-readback* shape
        Resolve reports back through `GetRenderJobList()`. This stem-based
        check is retained as-is because `MockResolveAdapter.queue_render_job()`
        only ever receives `custom_name` (the stem) from its caller, with
        no extension to reconstruct a complete filename from without
        inventing preset/format-driven extension logic the mock has no
        principled basis for. The adapter-level tests in
        `tests/unit/test_resolve_script_adapter_render_start.py` are the
        authoritative coverage for the real `OutputFilename` (complete
        filename) representation; this mock-level check only proves that
        `RenderManager` threads `project_name`/`timeline_name`/`output_path`
        through to the adapter call and that a mismatch is rejected."""
        self._require_connected()
        current = self.render_jobs.get(resolve_job_id)
        metadata = self.render_job_metadata.get(resolve_job_id)
        if current is None or metadata is None:
            raise RenderJobError(f"No render job '{resolve_job_id}' to start.")
        if metadata.get("ProjectName") != project_name:
            raise RenderJobError(
                f"Render job '{resolve_job_id}' belongs to project {metadata.get('ProjectName')!r}, "
                f"not the requested project {project_name!r}."
            )
        if metadata.get("TimelineName") != timeline_name:
            raise RenderJobError(
                f"Render job '{resolve_job_id}' belongs to timeline {metadata.get('TimelineName')!r}, "
                f"not the requested timeline {timeline_name!r}."
            )
        expected_path = Path(output_path)
        expected_target_dir = expected_path.parent.expanduser().resolve(strict=False)
        expected_stem = expected_path.stem
        actual_target_dir_value = metadata.get("TargetDir")
        actual_stem = metadata.get("CustomName")
        actual_target_dir = (
            Path(str(actual_target_dir_value)).expanduser().resolve(strict=False)
            if actual_target_dir_value is not None
            else None
        )
        if actual_target_dir != expected_target_dir or actual_stem != expected_stem:
            raise RenderJobError(
                f"Render job '{resolve_job_id}' targets output {actual_target_dir_value!r}/{actual_stem!r}, "
                f"not the requested output destination {str(expected_target_dir)!r}/{expected_stem!r}."
            )
        if current == "rendering":
            raise RenderJobError(f"Render job '{resolve_job_id}' is already rendering.")
        if current in ("complete", "failed", "cancelled"):
            raise RenderJobError(f"Render job '{resolve_job_id}' cannot be started from terminal status '{current}'.")
        if current != "queued":
            raise RenderJobError(f"Render job '{resolve_job_id}' has unsupported status '{current}'.")
        if any(status == "rendering" for status in self.render_jobs.values()):
            raise RenderJobError(
                "A render is already in progress; refusing to start "
                f"render job '{resolve_job_id}' while another render may be affected."
            )
        self.render_jobs[resolve_job_id] = "rendering"

    def simulate_render_complete(self, resolve_job_id: str) -> None:
        """Test helper only — not part of the ResolveAdapter interface."""
        self.render_jobs[resolve_job_id] = "complete"

    def get_video_timeline_item_count(self, project_name: str, timeline_name: str) -> int:
        self._require_connected()
        if project_name not in self.projects:
            raise ProjectNotFoundError(f"Project '{project_name}' does not exist.")
        if self.timelines.get(project_name) is None or timeline_name not in self.timelines[project_name]:
            raise TimelineOperationError(f"Timeline '{timeline_name}' does not exist.")
        return self.video_timeline_item_counts.get(f"{project_name}:{timeline_name}", 0)

    def set_video_timeline_item_count(self, project_name: str, timeline_name: str, count: int) -> None:
        """Test helper only — not part of the ResolveAdapter interface.

        Lets unit tests deterministically make a mock timeline renderable
        (count > 0) or non-renderable (count == 0, the default).
        """
        self.video_timeline_item_counts[f"{project_name}:{timeline_name}"] = count
