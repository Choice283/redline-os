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
against that instance. `import_media()`, `build_timeline()`, and
`add_markers()` are implemented, tested, and verified live. `place_clips()` is
implemented, unit-tested, and live-verified for sequential audio-only WAV and
still-image PNG placement: returned TimelineItem order matched requested
MediaPoolItem order, placement was contiguous, the WAV landed on an audio track,
the PNG landed on a video track, and each tested MediaPoolItem returned one
TimelineItem. Still pending for placement: embedded/linked video-audio
cardinality, explicit track targeting, explicit record-frame placement, and
rollback. The remaining render methods are still `NotImplementedError` stubs,
to be filled in the same way â€” implemented and verified against a real, running
instance rather than guessed at from documentation alone."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from redline_core.resolve.exceptions import (
    MediaImportError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    ResolveConnectionError,
    TimelineOperationError,
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
    def place_clips(self, project_name: str, timeline_name: str, clip_ids: list[str]) -> list[str]:
        """Place imported clips sequentially on an existing timeline."""

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
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        requested_count = len(media_paths)
        logger.info(
            "Importing media into Resolve project '%s', bin '%s': requested_count=%d",
            project_name,
            bin_name,
            requested_count,
        )

        if not media_paths:
            return []

        normalized_paths: list[str] = []
        invalid_paths: list[str] = []
        for media_path in media_paths:
            path = Path(media_path)
            if not path.exists() or not path.is_file():
                invalid_paths.append(str(path))
                continue
            normalized_paths.append(str(path.resolve()))

        if invalid_paths:
            raise MediaImportError(
                "Cannot import media because the following path(s) do not exist or are not files: "
                + ", ".join(invalid_paths)
            )

        project = self._project_manager.LoadProject(project_name)
        if not project:
            raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")

        media_pool = project.GetMediaPool()
        if not media_pool:
            raise MediaImportError(f"Resolve project has no media pool: {project_name}")

        root_folder = media_pool.GetRootFolder()
        if not root_folder:
            raise MediaImportError(f"Resolve media pool has no root folder: {project_name}")

        target_bin = None
        for folder in root_folder.GetSubFolderList() or []:
            get_name = getattr(folder, "GetName", None)
            if callable(get_name) and get_name() == bin_name:
                target_bin = folder
                break

        if target_bin is None:
            target_bin = media_pool.AddSubFolder(root_folder, bin_name)

        if not target_bin:
            raise MediaImportError(f"Could not find or create Resolve media pool bin '{bin_name}' in project '{project_name}'.")

        if not media_pool.SetCurrentFolder(target_bin):
            raise MediaImportError(f"Could not set Resolve media pool current folder to bin '{bin_name}'.")

        media_storage = self._resolve.GetMediaStorage()
        if not media_storage:
            raise MediaImportError("Resolve MediaStorage is unavailable.")

        imported_items = media_storage.AddItemListToMediaPool(normalized_paths)
        if not imported_items:
            raise MediaImportError(
                f"Resolve failed to import media into project '{project_name}' bin '{bin_name}'."
            )

        imported_items = list(imported_items)
        imported_count = len(imported_items)
        if imported_count != requested_count:
            raise MediaImportError(
                f"Resolve imported {imported_count} item(s), but {requested_count} path(s) were requested."
            )

        clip_ids = [self._media_pool_item_id(item) for item in imported_items]
        logger.info(
            "Imported media into Resolve project '%s', bin '%s': imported_count=%d",
            project_name,
            bin_name,
            imported_count,
        )
        return clip_ids

    def _media_pool_item_id(self, item) -> str:
        for method_name in ("GetMediaId", "GetUniqueId"):
            method = getattr(item, method_name, None)
            if not callable(method):
                continue
            try:
                value = method()
            except Exception:
                continue
            if value:
                return str(value)
        raise MediaImportError("Resolve imported a media item without a usable media ID.")

    def build_timeline(self, project_name: str, timeline_name: str) -> str:
        """Create a new empty timeline named `timeline_name` in `project_name`.

        Raises:
            ResolveConnectionError: not connected yet.
            ProjectNotFoundError: project_name doesn't exist or can't be loaded.
            TimelineOperationError: timeline_name is invalid, Resolve reported
                failure, or Resolve returned an unexpected timeline name.

        Failure boundary:
            If CreateEmptyTimeline succeeds but later verification fails because
            GetName() is empty or Resolve auto-renamed the timeline, the created
            timeline may remain in the Resolve project. Automatic timeline
            rollback is intentionally deferred until deletion behavior is
            validated against live Resolve.
        """
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        if not isinstance(timeline_name, str) or not timeline_name.strip():
            raise TimelineOperationError("Timeline name must be a non-empty string.")

        project = self._project_manager.LoadProject(project_name)
        if not project:
            raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")

        existing_timeline = self._find_timeline(project, timeline_name)
        if existing_timeline is not None:
            existing_name = existing_timeline.GetName()
            if not existing_name:
                raise TimelineOperationError(f"Existing timeline '{timeline_name}' has no usable name.")
            logger.info("Reusing Resolve timeline '%s' in project '%s'.", existing_name, project_name)
            return existing_name

        media_pool = project.GetMediaPool()
        if not media_pool:
            raise TimelineOperationError(f"Resolve project has no media pool: {project_name}")

        logger.info("Creating Resolve timeline '%s' in project '%s'.", timeline_name, project_name)
        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if not timeline:
            raise TimelineOperationError(
                f"Resolve failed to create timeline '{timeline_name}' in project '{project_name}'."
            )

        actual_name = timeline.GetName()
        if not actual_name:
            raise TimelineOperationError(
                f"Resolve created timeline '{timeline_name}' without a usable name."
            )
        if actual_name != timeline_name:
            raise TimelineOperationError(
                f"Resolve created timeline under a different name: requested '{timeline_name}', got '{actual_name}'."
            )

        logger.info("Created Resolve timeline '%s' in project '%s'.", actual_name, project_name)
        return actual_name

    def _find_timeline(self, project, timeline_name: str):
        """Look up a Timeline object in `project` by name. Returns None if not found."""
        try:
            timeline_count = project.GetTimelineCount()
        except Exception as exc:
            raise TimelineOperationError("Resolve failed to report timeline count.") from exc
        if timeline_count is None:
            timeline_count = 0
        if isinstance(timeline_count, bool) or not isinstance(timeline_count, int) or timeline_count < 0:
            raise TimelineOperationError(f"Resolve returned an invalid timeline count: {timeline_count!r}")

        for index in range(1, timeline_count + 1):
            try:
                timeline = project.GetTimelineByIndex(index)
            except Exception as exc:
                raise TimelineOperationError(f"Resolve failed to get timeline at index {index}.") from exc
            if not timeline:
                continue
            get_name = getattr(timeline, "GetName", None)
            if not callable(get_name):
                continue
            try:
                name = get_name()
            except Exception as exc:
                raise TimelineOperationError(
                    f"Resolve failed to get timeline name at index {index}."
                ) from exc
            if name == timeline_name:
                return timeline
        return None

    def add_markers(self, project_name: str, timeline_name: str, markers: list[dict]) -> None:
        """Apply markers to timeline `timeline_name` in `project_name`.

        Each marker dict must supply: frame (int), color (str), name (str),
        note (str). `duration` (int, frames) is optional and defaults to 1;
        `customData` (str) is optional per Resolve's own AddMarker signature.

        Raises:
            ResolveConnectionError: not connected yet.
            ProjectNotFoundError: project_name doesn't exist or can't be loaded.
            TimelineOperationError: marker input is invalid, the named timeline
                doesn't exist, or Resolve rejects a marker.
        """
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        if not markers:
            return

        normalized_markers = self._validate_markers(markers)

        project = self._project_manager.LoadProject(project_name)
        if not project:
            raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")

        timeline = self._find_timeline(project, timeline_name)
        if timeline is None:
            raise TimelineOperationError(f"Timeline '{timeline_name}' not found in project '{project_name}'.")

        logger.info(
            "Applying %d marker(s) to Resolve timeline '%s' in project '%s'.",
            len(normalized_markers),
            timeline_name,
            project_name,
        )
        added_count = 0
        for index, marker in enumerate(normalized_markers):
            try:
                added = timeline.AddMarker(
                    marker["frame"],
                    marker["color"],
                    marker["name"],
                    marker["note"],
                    marker["duration"],
                    marker["custom_data"],
                )
            except Exception as exc:
                logger.error(
                    "Failed to add Resolve marker: project='%s', timeline='%s', requested_count=%d, "
                    "added_count=%d, failed_index=%d",
                    project_name,
                    timeline_name,
                    len(normalized_markers),
                    added_count,
                    index,
                )
                raise TimelineOperationError(
                    f"Resolve raised while adding marker index {index} to timeline '{timeline_name}'."
                ) from exc
            if not added:
                logger.error(
                    "Failed to add Resolve marker: project='%s', timeline='%s', requested_count=%d, "
                    "added_count=%d, failed_index=%d",
                    project_name,
                    timeline_name,
                    len(normalized_markers),
                    added_count,
                    index,
                )
                raise TimelineOperationError(
                    f"Resolve rejected marker index {index} on timeline '{timeline_name}'."
                )
            added_count += 1

        logger.info("Applied %d marker(s) to Resolve timeline '%s'.", added_count, timeline_name)

    def place_clips(self, project_name: str, timeline_name: str, clip_ids: list[str]) -> list[str]:
        """Place imported clips sequentially on an existing Resolve timeline.

        V1 appends whole MediaPoolItem objects in the requested order. It does
        not set explicit record frames, tracks, source in/out, or durations.

        Failure boundary:
            If Resolve appends some timeline items and then returns an invalid
            or partial result, Redline OS raises `TimelineOperationError`, but
            those timeline items may remain. Automatic rollback is intentionally
            deferred until live Resolve deletion behavior is validated.
        """
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        self._validate_clip_ids_container(clip_ids)
        requested_count = len(clip_ids)
        logger.info(
            "Placing clips on Resolve timeline: project='%s', timeline='%s', requested_count=%d",
            project_name,
            timeline_name,
            requested_count,
        )

        if not clip_ids:
            return []

        self._validate_clip_ids(clip_ids)

        project = self._project_manager.LoadProject(project_name)
        if not project:
            raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")

        timeline = self._find_timeline(project, timeline_name)
        if timeline is None:
            raise TimelineOperationError(f"Timeline '{timeline_name}' not found in project '{project_name}'.")

        try:
            current_set = project.SetCurrentTimeline(timeline)
        except Exception as exc:
            raise TimelineOperationError(
                f"Resolve failed to set timeline '{timeline_name}' current in project '{project_name}'."
            ) from exc
        if not current_set:
            raise TimelineOperationError(
                f"Resolve could not set timeline '{timeline_name}' current in project '{project_name}'."
            )

        media_pool = project.GetMediaPool()
        if not media_pool:
            raise TimelineOperationError(f"Resolve project has no media pool: {project_name}")

        root_folder = media_pool.GetRootFolder()
        if not root_folder:
            raise TimelineOperationError(f"Resolve media pool has no root folder: {project_name}")

        media_pool_items = self._find_media_pool_items_by_id(root_folder, clip_ids)
        resolved_count = len(media_pool_items)
        logger.info(
            "Resolved clips for Resolve placement: project='%s', timeline='%s', resolved_count=%d",
            project_name,
            timeline_name,
            resolved_count,
        )

        try:
            appended_items = media_pool.AppendToTimeline(media_pool_items)
        except Exception as exc:
            self._log_clip_placement_failure(project_name, timeline_name, requested_count, None, 0)
            raise TimelineOperationError(
                f"Resolve raised while placing clips on timeline '{timeline_name}' in project '{project_name}'."
            ) from exc
        if appended_items is None or appended_items is False:
            self._log_clip_placement_failure(project_name, timeline_name, requested_count, appended_items, 0)
            raise TimelineOperationError(
                f"Resolve failed to place clips on timeline '{timeline_name}' in project '{project_name}'."
            )
        if not isinstance(appended_items, (list, tuple)):
            self._log_clip_placement_failure(project_name, timeline_name, requested_count, appended_items, 0)
            raise TimelineOperationError(
                f"Resolve returned an invalid placement result: {type(appended_items).__name__}."
            )

        appended_items = list(appended_items)
        if not appended_items:
            self._log_clip_placement_failure(project_name, timeline_name, requested_count, appended_items, 0)
            raise TimelineOperationError(
                f"Resolve placed no clips on timeline '{timeline_name}' in project '{project_name}'."
            )
        if len(appended_items) != requested_count:
            self._log_clip_placement_failure(project_name, timeline_name, requested_count, appended_items, 0)
            raise TimelineOperationError(
                f"Resolve placed {len(appended_items)} item(s), but {requested_count} clip(s) were requested."
            )

        timeline_item_ids = self._get_timeline_item_ids(
            appended_items, project_name, timeline_name, requested_count
        )

        logger.info(
            "Placed clips on Resolve timeline: project='%s', timeline='%s', requested_count=%d, "
            "resolved_count=%d, placed_count=%d",
            project_name,
            timeline_name,
            requested_count,
            resolved_count,
            len(timeline_item_ids),
        )
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

    def _find_media_pool_items_by_id(self, root_folder, clip_ids: list[str]) -> list:
        requested = set(clip_ids)
        matches: dict[str, list] = {clip_id: [] for clip_id in clip_ids}

        for folder in self._walk_media_pool_folders(root_folder, set()):
            try:
                clips = folder.GetClipList() or []
            except Exception as exc:
                raise TimelineOperationError("Resolve failed while listing media pool clips.") from exc
            for clip in clips:
                if not clip:
                    continue
                clip_id = self._get_media_pool_item_id(clip)
                if clip_id in requested:
                    matches[clip_id].append(clip)

        missing = [clip_id for clip_id, found in matches.items() if not found]
        duplicates = [clip_id for clip_id, found in matches.items() if len(found) > 1]
        if missing:
            raise TimelineOperationError("Media Pool clip ID(s) not found: " + ", ".join(missing))
        if duplicates:
            raise TimelineOperationError("Multiple Media Pool items matched clip ID(s): " + ", ".join(duplicates))

        return [matches[clip_id][0] for clip_id in clip_ids]

    def _walk_media_pool_folders(self, root_folder, visited: set[int]):
        folder_id = id(root_folder)
        if folder_id in visited:
            return
        visited.add(folder_id)
        yield root_folder
        try:
            subfolders = root_folder.GetSubFolderList() or []
        except Exception as exc:
            raise TimelineOperationError("Resolve failed while traversing media pool folders.") from exc
        for subfolder in subfolders:
            if not subfolder:
                continue
            yield from self._walk_media_pool_folders(subfolder, visited)

    def _get_media_pool_item_id(self, media_pool_item) -> str | None:
        for method_name in ("GetMediaId", "GetUniqueId"):
            method = getattr(media_pool_item, method_name, None)
            if not callable(method):
                continue
            try:
                value = method()
            except Exception as exc:
                if method_name == "GetMediaId":
                    continue
                raise TimelineOperationError(
                    "Resolve failed while reading MediaPoolItem identifier via GetUniqueId()."
                ) from exc
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _get_timeline_item_ids(
        self, appended_items: list, project_name: str, timeline_name: str, requested_count: int
    ) -> list[str]:
        timeline_item_ids: list[str] = []
        seen: set[str] = set()
        for index, timeline_item in enumerate(appended_items):
            try:
                timeline_item_id = self._get_timeline_item_id(timeline_item)
            except TimelineOperationError:
                self._log_clip_placement_failure(
                    project_name, timeline_name, requested_count, appended_items, len(timeline_item_ids), index
                )
                raise
            if timeline_item_id in seen:
                self._log_clip_placement_failure(
                    project_name, timeline_name, requested_count, appended_items, len(timeline_item_ids), index
                )
                raise TimelineOperationError(f"Resolve returned duplicate TimelineItem ID: {timeline_item_id}")
            seen.add(timeline_item_id)
            timeline_item_ids.append(timeline_item_id)
        return timeline_item_ids

    def _get_timeline_item_id(self, timeline_item) -> str:
        if not timeline_item:
            raise TimelineOperationError("Resolve returned a falsey TimelineItem handle.")
        method = getattr(timeline_item, "GetUniqueId", None)
        if not callable(method):
            raise TimelineOperationError("Resolve returned a TimelineItem without GetUniqueId().")
        try:
            value = method()
        except Exception as exc:
            raise TimelineOperationError("Resolve failed while reading TimelineItem ID.") from exc
        if not isinstance(value, str) or not value.strip():
            raise TimelineOperationError("Resolve returned a TimelineItem without a usable ID.")
        return value

    def _log_clip_placement_failure(
        self,
        project_name: str,
        timeline_name: str,
        requested_count: int,
        appended_items,
        extracted_count: int,
        failed_index: int | None = None,
    ) -> None:
        returned_count = len(appended_items) if isinstance(appended_items, (list, tuple)) else None
        logger.error(
            "Resolve clip placement failed after AppendToTimeline: project='%s', timeline='%s', "
            "requested_count=%d, returned_count=%s, extracted_count=%d, failed_index=%s. "
            "Partial Resolve state may remain.",
            project_name,
            timeline_name,
            requested_count,
            returned_count,
            extracted_count,
            failed_index,
        )

    def _validate_markers(self, markers: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        failures: list[str] = []

        for index, marker in enumerate(markers):
            marker_failures: list[str] = []
            if not isinstance(marker, dict):
                failures.append(f"marker index {index}: marker must be a dictionary")
                continue

            if "frame" not in marker:
                marker_failures.append("missing frame")
            else:
                frame = marker["frame"]
                if isinstance(frame, bool) or not isinstance(frame, int):
                    marker_failures.append("frame must be an integer")
                elif frame < 0:
                    marker_failures.append("frame must be >= 0")

            if "color" not in marker:
                marker_failures.append("missing color")
            else:
                color = marker["color"]
                if not isinstance(color, str) or not color.strip():
                    marker_failures.append("color must be a non-empty string")

            name = marker.get("name", "")
            if not isinstance(name, str):
                marker_failures.append("name must be a string")

            note = marker.get("note", "")
            if not isinstance(note, str):
                marker_failures.append("note must be a string")

            duration = marker.get("duration", 1)
            if isinstance(duration, bool) or not isinstance(duration, int):
                marker_failures.append("duration must be an integer")
            elif duration < 1:
                marker_failures.append("duration must be >= 1")

            has_custom_data = "custom_data" in marker
            has_custom_data_legacy = "customData" in marker
            custom_data = marker.get("custom_data", marker.get("customData", ""))
            if has_custom_data and has_custom_data_legacy:
                marker_failures.append("provide only one of custom_data or customData")
            if not isinstance(custom_data, str):
                marker_failures.append("custom_data must be a string")

            if marker_failures:
                failures.append(f"marker index {index}: {', '.join(marker_failures)}")
                continue

            normalized.append(
                {
                    "frame": marker["frame"],
                    "color": marker["color"],
                    "name": name,
                    "note": note,
                    "duration": duration,
                    "custom_data": custom_data,
                }
            )

        if failures:
            raise TimelineOperationError("Invalid marker input: " + "; ".join(failures))

        return normalized

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
