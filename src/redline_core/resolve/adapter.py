"""Resolve adapter interface + the real (DaVinci Resolve Studio) implementation.

Every other module in redline_core talks to Resolve ONLY through this
interface â€” never through raw `DaVinciResolveScript` calls. That keeps the
messy, version-fragile scripting API quirks (1-based nodeIndex, headless
inconsistencies across releases, etc.) contained to this one file.

Phase 0 status: `connect()` genuinely attempts a real connection and raises a
clear `ResolveConnectionError` if one isn't available (e.g. in this sandbox,
in CI, or on a machine without Resolve Studio running).

Phase 1 status: `connect()` has been verified against a real, running
DaVinci Resolve Studio 21.0.3 instance (see docs/CHANGELOG.md). `duplicate_project()`
is now implemented for real too, via an export/import round-trip, also verified
against that instance. The remaining methods (`import_media`, `build_timeline`,
`add_markers`, `queue_render`, `get_render_status`, `cancel_render`) are still
`NotImplementedError` stubs, to be filled in the same way â€” implemented and
verified against a real, running instance rather than guessed at from
documentation alone. Until then, all higher-level code for those operations
should be developed and tested against `MockResolveAdapter`."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from redline_core.resolve.exceptions import (
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    ResolveConnectionError,
)
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ProjectHandle:
    """Reference to a DaVinci Resolve project that Redline OS created/opened."""

    name: str
    path: str | None = None


class ResolveAdapter(ABC):
    """Interface every Resolve adapter (real or mock) must implement."""

    @abstractmethod
    def connect(self) -> None:
        """Establish a connection to a running DaVinci Resolve Studio instance."""

    @abstractmethod
    def duplicate_project(self, project_name: str, template_name: str) -> ProjectHandle:
        """Duplicate `template_name` as a new project called `project_name`."""
    @abstractmethod
    def import_media(self, project_name: str, media_paths: list[str], bin_name: str) -> list[str]:
        """Import media files into a named bin in the project's media pool. Returns clip IDs."""

    @abstractmethod
    def build_timeline(self, project_name: str, timeline_name: str) -> str:
        """Build a timeline in the project from the configured template. Returns timeline ID."""

    @abstractmethod
    def add_markers(self, project_name: str, timeline_name: str, markers: list[dict]) -> None:
        """Apply markers (each dict: frame, color, name, note) to a timeline."""

    @abstractmethod
    def queue_render(self, project_name: str, preset_name: str, output_path: str) -> str:
        """Queue a render job using a named Resolve render preset. Returns the Resolve job ID."""

    @abstractmethod
    def get_render_status(self, resolve_job_id: str) -> str:
        """Return the current status string for a queued render job."""

    @abstractmethod
    def cancel_render(self, resolve_job_id: str) -> None:
        """Cancel a queued or in-progress render job."""


class ResolveScriptAdapter(ResolveAdapter):
    """Real adapter, backed by DaVinci Resolve Studio's Python scripting API.

    Requires RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB to be set (see
    .env.example and docs/CONFIG.md) and a running Resolve Studio instance.
    """

    def __init__(self) -> None:
        self._resolve = None
        self._project_manager = None

    def connect(self) -> None:
        try:
            import DaVinciResolveScript as dvr_script  # type: ignore
        except ImportError as exc:
            raise ResolveConnectionError(
                "Could not import DaVinciResolveScript. This requires DaVinci Resolve "
                "STUDIO (not the free edition) to be installed and running, and "
                "RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB / PYTHONPATH to be set correctly. "
                "See docs/CONFIG.md."
            ) from exc

        resolve = dvr_script.scriptapp("Resolve")
        if resolve is None:
            raise ResolveConnectionError(
                "DaVinciResolveScript.scriptapp('Resolve') returned None. Is Resolve "
                "Studio running, and is scripting access enabled in Preferences > "
                "General > External scripting using?"
            )

        self._resolve = resolve
        self._project_manager = resolve.GetProjectManager()
        logger.info("Connected to DaVinci Resolve Studio.")

    def duplicate_project(self, project_name: str, template_name: str) -> ProjectHandle:
        """Duplicate `template_name` as a new project called `project_name`.

        Real Resolve has no single "duplicate project" call. This does it via
        a temporary DRP export/import round-trip: export `template_name` to a
        scratch file, then import that file back in under `project_name`.
        Verified against a live Resolve Studio 21.0.3 instance.

        Raises:
            ResolveConnectionError: not connected yet.
            ProjectNotFoundError: `template_name` doesn't exist.
            ProjectAlreadyExistsError: `project_name` already exists.
            RuntimeError: Resolve reported success but the expected state
                (exported file, or the new project) wasn't actually there.
        """
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        project_names = self._project_manager.GetProjectListInCurrentFolder() or []
        if template_name not in project_names:
            raise ProjectNotFoundError(f"Template project does not exist: {template_name}")
        if project_name in project_names:
            raise ProjectAlreadyExistsError(f"Project already exists: {project_name}")

        temporary_path = Path(tempfile.gettempdir()) / f"redline-project-copy-{uuid.uuid4().hex}.drp"
        try:
            logger.info("Exporting Resolve project '%s' to '%s'.", template_name, temporary_path)
            exported = self._project_manager.ExportProject(template_name, str(temporary_path), True)
            if not exported:
                raise RuntimeError(f"Resolve failed to export template project: {template_name}")
            if not temporary_path.exists():
                raise RuntimeError(
                    f"Resolve reported a successful export, but the DRP file was not created: {temporary_path}"
                )

            logger.info("Importing Resolve project as '%s'.", project_name)
            imported = self._project_manager.ImportProject(str(temporary_path), project_name)
            if not imported:
                raise RuntimeError(f"Resolve failed to import duplicated project as '{project_name}'.")

            updated_project_names = self._project_manager.GetProjectListInCurrentFolder() or []
            if project_name not in updated_project_names:
                raise RuntimeError(
                    f"Resolve reported a successful import, but the new project was not found: {project_name}"
                )

            logger.info("Duplicated Resolve project '%s' as '%s'.", template_name, project_name)
            return ProjectHandle(name=project_name)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Unable to delete temporary Resolve export: %s", temporary_path, exc_info=True)
    def import_media(self, project_name: str, media_paths: list[str], bin_name: str) -> list[str]:
        # Media Manager (Phase 3) business logic is built and tested against
        # MockResolveAdapter. This real implementation is blocked pending a
        # Resolve Studio license on the workstation (see docs/CHANGELOG.md).
        raise NotImplementedError("import_media requires DaVinci Resolve Studio â€” not yet implemented for real.")

    def build_timeline(self, project_name: str, timeline_name: str) -> str:
        # Timeline Builder (Phase 4) business logic is built and tested against
        # MockResolveAdapter. This real implementation is blocked pending a
        # Resolve Studio license on the workstation (see docs/CHANGELOG.md).
        raise NotImplementedError("build_timeline requires DaVinci Resolve Studio â€” not yet implemented for real.")

    def add_markers(self, project_name: str, timeline_name: str, markers: list[dict]) -> None:
        # Same as build_timeline above â€” blocked on a real Studio license.
        raise NotImplementedError("add_markers requires DaVinci Resolve Studio â€” not yet implemented for real.")

    def queue_render(self, project_name: str, preset_name: str, output_path: str) -> str:
        # Render Manager (Phase 6) business logic is built and tested against
        # MockResolveAdapter. This real implementation is blocked pending a
        # Resolve Studio license on the workstation (see docs/CHANGELOG.md).
        raise NotImplementedError("queue_render requires DaVinci Resolve Studio â€” not yet implemented for real.")

    def get_render_status(self, resolve_job_id: str) -> str:
        # Render Manager (Phase 6) business logic is built and tested against
        # MockResolveAdapter. This real implementation is blocked pending a
        # Resolve Studio license on the workstation (see docs/CHANGELOG.md).
        raise NotImplementedError("get_render_status requires DaVinci Resolve Studio â€” not yet implemented for real.")

    def cancel_render(self, resolve_job_id: str) -> None:
        # Same as get_render_status above â€” blocked on a real Studio license.
        raise NotImplementedError("cancel_render requires DaVinci Resolve Studio â€” not yet implemented for real.")

