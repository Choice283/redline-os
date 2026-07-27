"""In-memory mock of ResolveAdapter, used by every unit test.

This lets all of redline_core's business logic (Episode Manager, Timeline
Builder, Render Manager, etc.) be built and tested WITHOUT a real DaVinci
Resolve Studio license or a running instance. Real behavior is verified
separately, manually, in tests/integration against ResolveScriptAdapter.
"""
from __future__ import annotations

import itertools
import logging

from redline_core.resolve.adapter import ProjectHandle, ResolveAdapter
from redline_core.resolve.exceptions import ProjectAlreadyExistsError, ProjectNotFoundError, RenderJobError

logger = logging.getLogger(__name__)


class MockResolveAdapter(ResolveAdapter):
    """Fake Resolve backend: dicts standing in for projects/timelines/render jobs."""

    def __init__(self) -> None:
        self.connected = False
        self.projects: dict[str, ProjectHandle] = {}
        self.media: dict[str, list[str]] = {}       # project_name -> clip ids
        self.timelines: dict[str, str] = {}          # project_name -> timeline_name
        self.markers: dict[str, list[dict]] = {}     # f"{project}:{timeline}" -> markers
        self.render_jobs: dict[str, str] = {}        # job_id -> status
        self._job_ids = itertools.count(1)

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
        self.timelines[project_name] = timeline_name
        return timeline_name

    def add_markers(self, project_name: str, timeline_name: str, markers: list[dict]) -> None:
        self._require_connected()
        key = f"{project_name}:{timeline_name}"
        self.markers.setdefault(key, []).extend(markers)

    def queue_render(self, project_name: str, preset_name: str, output_path: str) -> str:
        self._require_connected()
        if project_name not in self.projects:
            raise ProjectNotFoundError(f"Project '{project_name}' does not exist.")
        job_id = f"mock-job-{next(self._job_ids)}"
        self.render_jobs[job_id] = "queued"
        return job_id

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

    def simulate_render_complete(self, resolve_job_id: str) -> None:
        """Test helper only — not part of the ResolveAdapter interface."""
        self.render_jobs[resolve_job_id] = "complete"
