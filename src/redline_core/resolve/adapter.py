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
rollback. `queue_render()` is now implemented and live-verified against a real,
running instance. `get_render_status()` is implemented against
`Project.GetRenderJobStatus(...)`, verified against Resolve Studio 21.0.3.7.
`cancel_render()` is implemented for queued jobs through `DeleteRenderJob(...)`
and active jobs through verified, project-scoped `StopRendering()`, preserving
cancelled active queue entries rather than deleting them. `start_render()` is
implemented through the job-ID-targeted `StartRendering([resolve_job_id],
isInteractiveMode=False)` form (verified against the local Resolve Scripting
README, not guessed), gated on an exact current-project identity match, a
strict (alias-conflict-and-malformation-aware, see `_strict_alias_value()`)
queued-job/timeline identity match and queued-output-destination match
against `GetRenderJobList()`, the target job's own status being `Ready`,
and `IsRenderingInProgress()` being exactly `False`. Once `StartRendering()`
has actually been called, every outcome (`True`, `False`, an exception, or
any non-boolean return) is resolved identically through a bounded
getter-only postcondition poll for `JobStatus == "Rendering"` — no return
value, including an exact `False`, is treated as sufficient proof by
itself that no mutation occurred — with an explicit reconciliation-required
outcome (see `RenderStartReconciliationRequiredError`) whenever that
postcondition cannot be established. Construction-only as of this
addition; not yet verified against a live Resolve instance."""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from redline_core.resolve.exceptions import (
    MediaImportError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    RenderJobError,
    RenderQueueAcceptanceNotObservedError,
    RenderQueueIdentityUnresolvedError,
    RenderStartReconciliationRequiredError,
    ResolveConnectionError,
    TimelineOperationError,
)
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Dedicated logger for the queue-identity-unresolved diagnostic only, under
# the application's configured "redline_os" namespace (see
# redline_core.logging.setup.configure_logging) so it reaches the console
# and rotating-file handlers configure_logging() owns. The routine `logger`
# above stays under "redline_core.resolve.adapter" and is unaffected.
_render_queue_identity_logger = logging.getLogger("redline_os.resolve.adapter")

_RENDER_CANCEL_POSTCONDITION_ATTEMPTS = 5
_RENDER_CANCEL_POSTCONDITION_DELAY_SECONDS = 0.1

# Bounded getter-only postcondition check after StartRendering(), mirroring
# _RENDER_CANCEL_POSTCONDITION_ATTEMPTS/_DELAY's existing precedent for the
# same class of problem (a Resolve state transition that is not guaranteed
# to be immediately visible through GetRenderJobStatus() the instant the
# mutating call returns). Named separately from the cancel constants so the
# two call sites' retry budgets can be tuned independently if live behavior
# ever shows they should differ; both currently use the same values (5
# attempts, 0.1s apart, ~0.5s worst case) because no live evidence yet
# suggests a different bound is needed for starting versus stopping.
_RENDER_START_POSTCONDITION_ATTEMPTS = 5
_RENDER_START_POSTCONDITION_DELAY_SECONDS = 0.1

# Alias key sets used only by the strict, start-pathway-owned identity
# checks (ResolveScriptAdapter._strict_alias_value() and its callers). Kept
# separate from the legacy, precedence-based helpers below
# (_render_job_id_from_job(), used by queue_render_job()'s reconciliation
# and cancel_render()) rather than reusing or weakening them.
_JOB_ID_ALIASES = ("JobId", "JobID", "jobId", "job_id", "Id", "ID", "id")
_TIMELINE_NAME_ALIASES = ("TimelineName", "Timeline", "timeline_name", "timelineName")
_TARGET_DIR_ALIASES = ("TargetDir", "targetDir", "target_dir")
_OUTPUT_FILENAME_ALIASES = ("OutputFilename", "outputFilename", "output_filename")


def _safe_repr(value: object) -> str:
    """repr() a diagnostic value without letting a broken __repr__ raise."""
    try:
        return repr(value)
    except Exception:
        return f"<unrepresentable {type(value).__name__}>"


_RESOLVE_RENDER_STATUS_MAP: dict[str, str] = {
    "ready": "queued",
    "rendering": "rendering",
    "complete": "complete",
    "failed": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


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
    def queue_render_job(
        self,
        *,
        project_name: str,
        timeline_name: str,
        resolve_preset_name: str,
        target_directory: str,
        custom_name: str,
    ) -> str:
        """Queue a render job using an explicit prepared render plan. Returns the Resolve job ID."""

    @abstractmethod
    def list_render_jobs(self, project_name: str) -> list[dict]:
        """Return Resolve render queue metadata for a project."""

    @abstractmethod
    def delete_render_job(self, project_name: str, resolve_job_id: str) -> None:
        """Delete a newly queued Resolve render job."""

    @abstractmethod
    def get_render_status(self, resolve_job_id: str) -> str:
        """Return the current status string for a queued render job."""

    @abstractmethod
    def cancel_render(self, resolve_job_id: str) -> None:
        """Cancel a queued or in-progress render job."""

    @abstractmethod
    def start_render(
        self, *, project_name: str, timeline_name: str, resolve_job_id: str, output_path: str
    ) -> None:
        """Start rendering exactly the queued job identified by `resolve_job_id`.

        Unlike `get_render_status()`/`cancel_render()`, this mutation
        independently verifies the caller-supplied identity before ever
        invoking the underlying start-rendering mutation call: the
        currently loaded Resolve project must be exactly `project_name`,
        `resolve_job_id`'s own queue entry must target exactly
        `timeline_name`, and that same queue entry's own output
        destination must resolve to exactly `output_path` — all checked
        getter-only, before the mutation call, so a mismatched or stale
        caller fails closed rather than starting the wrong job or trusting
        an unverified destination. Implementations must call the
        underlying Resolve start-rendering API at most once per
        invocation, must not affect any render job other than the one
        requested, must never mutate render settings to reconcile a
        mismatch, and must never call the start-rendering API again to
        "retry" after an ambiguous or uncertain outcome — see
        `RenderStartReconciliationRequiredError`.
        """

    @abstractmethod
    def get_video_timeline_item_count(self, project_name: str, timeline_name: str) -> int:
        """Return the number of video TimelineItems currently on the named timeline.

        Used by the renderability preflight to fail closed before Resolve
        queue mutation when a preset requires a video payload. Raises the
        same connection/lookup exceptions as other timeline inspection calls
        rather than assuming renderability on unavailable or invalid data.
        """


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

    def queue_render_job(
        self,
        *,
        project_name: str,
        timeline_name: str,
        resolve_preset_name: str,
        target_directory: str,
        custom_name: str,
    ) -> str:
        """Add one render job to Resolve's queue and return its Resolve job ID.

        This method only queues the job. It does not start rendering, poll
        status, or attempt rollback if a queued job cannot be reconciled.
        """
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        if not isinstance(project_name, str) or not project_name.strip():
            raise RenderJobError("Project name must be a non-empty string.")
        if not isinstance(timeline_name, str) or not timeline_name.strip():
            raise RenderJobError("Timeline name must be a non-empty string.")
        if not isinstance(resolve_preset_name, str) or not resolve_preset_name.strip():
            raise RenderJobError("Render preset name must be a non-empty string.")
        if not isinstance(target_directory, str) or not target_directory.strip():
            raise RenderJobError("Render target directory must be a non-empty string.")
        if not isinstance(custom_name, str) or not custom_name.strip():
            raise RenderJobError("Render custom name must be a non-empty string.")

        try:
            logger.info(
                "Queueing Resolve render job: project='%s', preset='%s'",
                project_name,
                resolve_preset_name,
            )
            project = self._project_manager.LoadProject(project_name)
            if not project:
                raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")

            timeline = self._find_timeline(project, timeline_name)
            if timeline is None:
                raise RenderJobError(f"Timeline '{timeline_name}' not found in project '{project_name}'.")
            set_current_timeline = getattr(project, "SetCurrentTimeline", None)
            if not callable(set_current_timeline):
                raise RenderJobError(
                    f"Resolve cannot select timeline '{timeline_name}' in project '{project_name}'."
                )
            current_set = set_current_timeline(timeline)
            if current_set is not True:
                raise RenderJobError(
                    f"Resolve could not set timeline '{timeline_name}' current in project '{project_name}'."
                )
            current_timeline = self._get_current_timeline(project, project_name)
            current_timeline_name = self._timeline_name(current_timeline, timeline_name)
            if current_timeline_name != timeline_name:
                raise RenderJobError(
                    f"Resolve selected timeline '{current_timeline_name}' instead of '{timeline_name}' "
                    f"in project '{project_name}'."
                )

            before_jobs = self._get_render_jobs(project, project_name, "before")
            before_job_ids = self._extract_required_render_job_ids(before_jobs)
            before_queue_inventory = self._capture_render_queue_inventory(before_jobs)

            preset_loaded = project.LoadRenderPreset(resolve_preset_name)
            if not preset_loaded:
                raise RenderJobError(
                    f"Resolve could not load render preset '{resolve_preset_name}' for project '{project_name}'."
                )

            render_settings = {
                "TargetDir": str(Path(target_directory).expanduser()),
                "CustomName": custom_name,
            }
            settings_applied = project.SetRenderSettings(render_settings)
            if not settings_applied:
                raise RenderJobError(
                    f"Resolve rejected render output settings for project '{project_name}'."
                )

            pre_add_context = self._capture_pre_add_render_context(
                project=project,
                project_name=project_name,
                requested_timeline_name=timeline_name,
                current_timeline_name=current_timeline_name,
                resolve_preset_name=resolve_preset_name,
                target_directory=render_settings["TargetDir"],
                custom_name=render_settings["CustomName"],
            )

            add_result = project.AddRenderJob()
            if add_result is False:
                raise RenderJobError(f"Resolve failed to add a render job for project '{project_name}'.")

            direct_job_id = self._coerce_render_job_id(add_result)
            if direct_job_id is not None:
                logger.info(
                    "Queued Resolve render job: project='%s', preset='%s', job_id='%s'",
                    project_name,
                    resolve_preset_name,
                    direct_job_id,
                )
                return direct_job_id

            resolved_job_id = self._reconcile_after_add(
                project,
                project_name,
                resolve_preset_name,
                before_job_ids,
                before_queue_inventory,
                add_result,
                pre_add_context,
            )
            logger.info(
                "Queued Resolve render job: project='%s', preset='%s', job_id='%s'",
                project_name,
                resolve_preset_name,
                resolved_job_id,
            )
            return resolved_job_id
        except (ResolveConnectionError, ProjectNotFoundError, RenderJobError):
            raise
        except Exception as exc:
            raise RenderJobError(f"Failed to queue render for project {project_name!r}.") from exc

    def list_render_jobs(self, project_name: str) -> list[dict]:
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")
        try:
            project = self._project_manager.LoadProject(project_name)
            if not project:
                raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")
            return self._get_render_jobs(project, project_name, "for inspection")
        except (ResolveConnectionError, ProjectNotFoundError, RenderJobError):
            raise
        except Exception as exc:
            raise RenderJobError(f"Failed to list Resolve render jobs for project {project_name!r}.") from exc

    def delete_render_job(self, project_name: str, resolve_job_id: str) -> None:
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")
        try:
            project = self._project_manager.LoadProject(project_name)
            if not project:
                raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")
            deleted = project.DeleteRenderJob(resolve_job_id)
            if deleted is not True:
                raise RenderJobError(f"Resolve failed to delete queued render job {resolve_job_id!r}.")
        except (ResolveConnectionError, ProjectNotFoundError, RenderJobError):
            raise
        except Exception as exc:
            raise RenderJobError(f"Failed to delete Resolve render job {resolve_job_id!r}.") from exc

    def _get_render_job_ids(self, project, project_name: str, phase: str) -> list[str]:
        return self._extract_required_render_job_ids(self._get_render_jobs(project, project_name, phase))

    def _extract_required_render_job_ids(self, jobs: list[dict]) -> list[str]:
        job_ids: list[str] = []
        for job in jobs:
            job_id = self._render_job_id_from_job(job)
            if job_id is not None:
                job_ids.append(job_id)
        return job_ids

    def _get_render_jobs(self, project, project_name: str, phase: str) -> list[dict]:
        get_render_job_list = getattr(project, "GetRenderJobList", None)
        if not callable(get_render_job_list):
            raise RenderJobError(f"Resolve project '{project_name}' cannot list render jobs.")
        try:
            jobs = get_render_job_list()
        except Exception as exc:
            raise RenderJobError(
                f"Resolve failed to list render jobs for project '{project_name}' {phase} queueing."
            ) from exc
        if jobs is None or jobs is False:
            return []
        if not isinstance(jobs, list):
            raise RenderJobError(
                f"Resolve returned an invalid render job list for project '{project_name}': "
                f"{type(jobs).__name__}."
            )

        for index, job in enumerate(jobs):
            job_id = self._render_job_id_from_job(job)
            if job_id is None:
                raise RenderJobError(
                    f"Resolve render job list item {index} has no usable job ID for project '{project_name}'."
                )
        return jobs

    def _get_render_jobs_snapshot(self, project, project_name: str, phase: str) -> list:
        """Fetch GetRenderJobList() exactly once, validating only the outer
        return shape. Unlike _get_render_jobs, does not require every item to
        have a usable ID — an unidentifiable item here is diagnostic evidence
        for post-AddRenderJob() reconciliation, not an immediate hard failure
        to raise before the caller can capture and log it.
        """
        get_render_job_list = getattr(project, "GetRenderJobList", None)
        if not callable(get_render_job_list):
            raise RenderJobError(f"Resolve project '{project_name}' cannot list render jobs.")
        try:
            jobs = get_render_job_list()
        except Exception as exc:
            raise RenderJobError(
                f"Resolve failed to list render jobs for project '{project_name}' {phase} queueing."
            ) from exc
        if jobs is None or jobs is False:
            return []
        if not isinstance(jobs, list):
            raise RenderJobError(
                f"Resolve returned an invalid render job list for project '{project_name}': "
                f"{type(jobs).__name__}."
            )
        return jobs

    def _get_current_timeline(self, project, project_name: str):
        get_current_timeline = getattr(project, "GetCurrentTimeline", None)
        if not callable(get_current_timeline):
            raise RenderJobError(f"Resolve project '{project_name}' cannot report the current timeline.")
        current_timeline = get_current_timeline()
        if not current_timeline:
            raise RenderJobError(f"Resolve project '{project_name}' has no current timeline after selection.")
        return current_timeline

    def _timeline_name(self, timeline, requested_timeline_name: str) -> str:
        get_name = getattr(timeline, "GetName", None)
        if not callable(get_name):
            raise RenderJobError(f"Resolve timeline '{requested_timeline_name}' cannot report its name.")
        try:
            name = get_name()
        except Exception as exc:
            raise RenderJobError(f"Resolve failed to get timeline name for '{requested_timeline_name}'.") from exc
        if not isinstance(name, str) or not name.strip():
            raise RenderJobError(f"Resolve timeline '{requested_timeline_name}' has no usable name.")
        return name

    def _derive_new_render_job_id(self, before_job_ids: list[str], after_job_ids: list[str], project_name: str) -> str:
        candidates = self._compute_new_job_id_candidates(before_job_ids, after_job_ids)

        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise RenderJobError(
                f"Resolve added a render job for project '{project_name}' but returned no usable job ID. "
                "Manual render-queue reconciliation may be required."
            )
        raise RenderJobError(
            f"Resolve added {len(candidates)} possible render job IDs for project '{project_name}'. "
            "Manual render-queue reconciliation may be required."
        )

    def _compute_new_job_id_candidates(self, before_job_ids: list[str], after_job_ids: list[str]) -> list[str]:
        before_counts: dict[str, int] = {}
        for job_id in before_job_ids:
            before_counts[job_id] = before_counts.get(job_id, 0) + 1

        candidates: list[str] = []
        for job_id in after_job_ids:
            remaining_before = before_counts.get(job_id, 0)
            if remaining_before:
                before_counts[job_id] = remaining_before - 1
            else:
                candidates.append(job_id)
        return candidates

    def _extract_render_job_ids_lenient(self, jobs: list) -> tuple[list[str], list]:
        """Best-effort ID extraction that does not raise on an unidentifiable
        item — instead returns it so the caller can treat it as diagnostic
        evidence rather than silently dropping it from consideration."""
        job_ids: list[str] = []
        unidentified_items: list = []
        for job in jobs:
            job_id = self._render_job_id_from_job(job)
            if job_id is not None:
                job_ids.append(job_id)
            else:
                unidentified_items.append(job)
        return job_ids, unidentified_items

    def _capture_render_queue_inventory(self, jobs: list | None) -> dict[str, object]:
        """Summarize a queue snapshot without logging arbitrary job values."""
        if jobs is None:
            return {
                "available": False,
                "container_type": "unavailable",
                "count": "unavailable",
                "item_types": "unavailable",
                "dict_keys": "unavailable",
                "usable_job_ids": "unavailable",
                "items_missing_ids": "unavailable",
                "non_dict_items": "unavailable",
                "fingerprint": "unavailable",
            }

        item_types: list[str] = []
        dict_keys: list[object] = []
        usable_job_ids: list[str] = []
        fingerprint: list[dict[str, object]] = []
        items_missing_ids = 0
        non_dict_items = 0

        for job in jobs:
            item_type = type(job).__name__
            item_types.append(item_type)
            try:
                job_id = self._render_job_id_from_job(job)
                job_id_error_type = None
            except Exception as exc:
                job_id = None
                job_id_error_type = type(exc).__name__
            if job_id is not None:
                usable_job_ids.append(job_id)
            else:
                items_missing_ids += 1

            if isinstance(job, dict):
                try:
                    keys = sorted(str(key) for key in job.keys())
                except Exception:
                    keys = ["<unavailable>"]
                dict_keys.append(keys)
            else:
                keys = None
                dict_keys.append(None)
                non_dict_items += 1

            fingerprint.append(
                {
                    "type": item_type,
                    "keys": keys,
                    "has_usable_job_id": job_id is not None,
                    "job_id_error_type": job_id_error_type,
                }
            )

        return {
            "available": True,
            "container_type": type(jobs).__name__,
            "count": len(jobs),
            "item_types": item_types,
            "dict_keys": dict_keys,
            "usable_job_ids": usable_job_ids,
            "items_missing_ids": items_missing_ids,
            "non_dict_items": non_dict_items,
            "fingerprint": fingerprint,
        }

    def _compare_render_queue_inventories(
        self, before_inventory: dict[str, object], after_inventory: dict[str, object]
    ) -> dict[str, object]:
        """Diagnostic-only structural comparison; not used for acceptance."""
        before_count = before_inventory.get("count", "unavailable")
        after_count = after_inventory.get("count", "unavailable")
        before_fingerprint = before_inventory.get("fingerprint", "unavailable")
        after_fingerprint = after_inventory.get("fingerprint", "unavailable")
        count_delta: object = "unavailable"
        if isinstance(before_count, int) and isinstance(after_count, int):
            count_delta = after_count - before_count
        return {
            "before_count": before_count,
            "after_count": after_count,
            "count_delta": count_delta,
            "fingerprint_changed": before_fingerprint != after_fingerprint,
            "before_fingerprint": before_fingerprint,
            "after_fingerprint": after_fingerprint,
        }

    def _capture_target_directory_diagnostics(self, target_directory: str) -> dict[str, object]:
        try:
            normalized_path = Path(target_directory).expanduser().resolve(strict=False)
            exists = normalized_path.exists()
            is_dir = normalized_path.is_dir()
            try:
                accessible: object = os.access(normalized_path, os.R_OK)
                access_error_type: object = None
            except Exception as exc:
                accessible = "unavailable"
                access_error_type = type(exc).__name__
            return {
                "normalized_path": str(normalized_path),
                "exists": exists,
                "is_dir": is_dir,
                "read_accessible": accessible,
                "access_error_type": access_error_type,
            }
        except Exception as exc:
            return {
                "normalized_path": str(Path(target_directory).expanduser()),
                "exists": "unavailable",
                "is_dir": "unavailable",
                "read_accessible": "unavailable",
                "access_error_type": type(exc).__name__,
            }

    def _capture_render_settings_snapshot(self, project) -> dict[str, object]:
        try:
            get_render_settings = getattr(project, "GetRenderSettings", None)
            if not callable(get_render_settings):
                return {"available": False, "source": None, "keys": [], "value_types": {}, "error_type": None}
            raw_settings = get_render_settings()
            if not isinstance(raw_settings, dict):
                return {
                    "available": False,
                    "source": "GetRenderSettings",
                    "keys": [],
                    "value_types": {},
                    "error_type": type(raw_settings).__name__,
                }
            keys = sorted(str(key) for key in raw_settings.keys())
            value_types = {str(key): type(value).__name__ for key, value in raw_settings.items()}
            return {
                "available": True,
                "source": "GetRenderSettings",
                "keys": keys,
                "value_types": value_types,
                "error_type": None,
            }
        except Exception as exc:
            return {
                "available": False,
                "source": "GetRenderSettings",
                "keys": [],
                "value_types": {},
                "error_type": type(exc).__name__,
            }

    def _capture_pre_add_render_context(
        self,
        project,
        project_name: str,
        requested_timeline_name: str,
        current_timeline_name: str,
        resolve_preset_name: str,
        target_directory: str,
        custom_name: str,
    ) -> dict[str, object]:
        """Best-effort, read-only snapshot of render context immediately
        before AddRenderJob(). timeline_name/target_directory/custom_name are
        the already-validated, already-applied local values — callers must
        pass the exact values given to SetRenderSettings(), not recompute
        them here. Any further Resolve inspection (current format/codec) is
        fully defensive: attribute discovery, the call itself, and result
        parsing are wrapped in one try/except, since attribute lookup on a
        bridged Resolve object can itself raise — getattr(obj, name, default)
        only suppresses AttributeError, not an arbitrary exception a bridged
        __getattr__ might raise. Nothing in this method may block
        AddRenderJob().
        """
        context: dict[str, object] = {
            "project_name": project_name,
            "requested_timeline_name": requested_timeline_name,
            "current_timeline_name": current_timeline_name,
            "timeline_name": current_timeline_name,
            "resolve_preset_name": resolve_preset_name,
            "target_dir": target_directory,
            "target_dir_diagnostics": self._capture_target_directory_diagnostics(target_directory),
            "custom_name": custom_name,
            "render_format": "unavailable",
            "render_codec": "unavailable",
            "render_mode": "unavailable",
            "render_settings_snapshot": self._capture_render_settings_snapshot(project),
        }
        try:
            get_format_and_codec = getattr(project, "GetCurrentRenderFormatAndCodec", None)
            if callable(get_format_and_codec):
                raw = get_format_and_codec()
                if isinstance(raw, dict):
                    context["render_format"] = raw.get("format") or "unavailable"
                    context["render_codec"] = raw.get("codec") or "unavailable"
        except Exception:
            pass
        return context

    def _reconcile_after_add(
        self,
        project,
        project_name: str,
        resolve_preset_name: str,
        before_job_ids: list[str],
        before_queue_inventory: dict[str, object],
        add_result,
        pre_add_context: dict[str, object],
    ) -> str:
        """Determine the single new Resolve job ID after AddRenderJob() has
        returned something other than explicit False with no direct ID.

        Two outcomes are possible when reconciliation cannot return a job ID:

        - RenderQueueAcceptanceNotObservedError: AddRenderJob() returned an
          empty string, the after-phase snapshot itself succeeded, contained
          no unidentified item, and the before/after job-ID multisets are
          exactly equal (no new candidate). This is a positive claim that no
          accepted job was observed by job-ID comparison, not merely
          uncertainty — it does not inspect any other per-item queue
          metadata.
        - RenderQueueIdentityUnresolvedError: every other failure — the
          after-phase snapshot being unavailable, an unidentifiable queue
          item, multiple new candidates, or a non-empty-string add_result
          with zero candidates — where Redline genuinely cannot prove the
          identity of exactly one newly queued Resolve job. Note this only
          covers an existing job disappearing when that disappearance also
          leaves zero new candidates (multiset equality, not bare
          candidate-emptiness, is what's checked in that branch); a
          disappearance that coincides with exactly one new candidate is
          unaffected by the new classification branch and still resolves as a direct success
          through _derive_new_render_job_id()'s existing single-candidate
          path, unchanged from before this classification existed.

        Diagnostic logging is best-effort and can never replace either
        exception.
        """
        after_jobs: list | None = None
        after_job_ids: list[str] | None = None
        candidate_job_ids: list[str] | None = None
        unidentified_items: list | None = None
        after_queue_inventory = self._capture_render_queue_inventory(None)
        queue_structural_delta = self._compare_render_queue_inventories(
            before_queue_inventory, after_queue_inventory
        )
        try:
            after_jobs = self._get_render_jobs_snapshot(project, project_name, "after")
            after_queue_inventory = self._capture_render_queue_inventory(after_jobs)
            queue_structural_delta = self._compare_render_queue_inventories(
                before_queue_inventory, after_queue_inventory
            )
            after_job_ids, unidentified_items = self._extract_render_job_ids_lenient(after_jobs)
            candidate_job_ids = self._compute_new_job_id_candidates(before_job_ids, after_job_ids)
            if unidentified_items:
                raise RenderJobError(
                    f"Resolve render job list after queueing contains {len(unidentified_items)} "
                    f"item(s) with no usable job ID for project '{project_name}'."
                )
            return self._derive_new_render_job_id(before_job_ids, after_job_ids, project_name)
        except (RenderQueueIdentityUnresolvedError, RenderQueueAcceptanceNotObservedError):
            raise
        except Exception as exc:
            acceptance_not_observed = (
                isinstance(add_result, str)
                and add_result == ""
                and after_job_ids is not None
                and not unidentified_items
                and not candidate_job_ids
                and sorted(after_job_ids) == sorted(before_job_ids)
            )
            reconciliation_outcome = (
                "acceptance_not_observed" if acceptance_not_observed else "identity_unresolved"
            )
            try:
                self._log_render_queue_reconciliation_failure(
                    reconciliation_outcome,
                    project_name,
                    resolve_preset_name,
                    pre_add_context,
                    add_result,
                    before_job_ids,
                    after_jobs,
                    after_job_ids,
                    candidate_job_ids,
                    before_queue_inventory,
                    after_queue_inventory,
                    queue_structural_delta,
                    exc,
                )
            except Exception:
                pass
            if acceptance_not_observed:
                raise RenderQueueAcceptanceNotObservedError(
                    f"Resolve AddRenderJob() returned an empty string for project "
                    f"'{project_name}', and a successful after-call snapshot showed "
                    f"the same render-job ID multiset with no unidentified items. "
                    f"No accepted render job was observed."
                ) from exc
            raise RenderQueueIdentityUnresolvedError(str(exc)) from exc

    def _log_render_queue_reconciliation_failure(
        self,
        reconciliation_outcome: str,
        project_name: str,
        resolve_preset_name: str,
        pre_add_context: dict[str, object],
        add_result,
        before_job_ids: list[str],
        after_jobs: list | None,
        after_job_ids: list[str] | None,
        candidate_job_ids: list[str] | None,
        before_queue_inventory: dict[str, object],
        after_queue_inventory: dict[str, object],
        queue_structural_delta: dict[str, object],
        reconciliation_error: Exception,
    ) -> None:
        """Log diagnostics using only already-captured, known-safe values.

        Deliberately does not call _render_job_id_from_job() again on the raw
        after_jobs items — that lookup is exactly what can raise for a
        misbehaving item, and re-running it here would risk losing the whole
        diagnostic record for the one case (an unexpected error during
        extraction) where it matters most. Item types/keys are gathered
        directly from the raw snapshot, per-item defensively, so one broken
        item can't blank out the rest of the log. reconciliation_outcome is
        always exactly "acceptance_not_observed" or "identity_unresolved" —
        machine-searchable, not embedded in prose.
        """
        if after_jobs is None:
            after_job_count: object = "unavailable"
            after_job_item_types: object = "unavailable"
            after_job_item_keys: object = "unavailable"
        else:
            after_job_count = len(after_jobs)
            after_job_item_types = [type(job).__name__ for job in after_jobs]
            after_job_item_keys = []
            for job in after_jobs:
                if not isinstance(job, dict):
                    after_job_item_keys.append(None)
                    continue
                try:
                    after_job_item_keys.append(sorted(job.keys()))
                except Exception:
                    after_job_item_keys.append("<unavailable>")

        _render_queue_identity_logger.error(
            "Render queue reconciliation could not confirm a single accepted job after "
            "AddRenderJob(): project=%r preset=%r add_result_type=%s add_result_repr=%s "
            "before_job_ids=%r after_job_ids=%r after_job_count=%r after_job_item_types=%r "
            "after_job_item_keys=%r candidate_job_ids=%r reconciliation_error_type=%s "
            "reconciliation_error_repr=%s reconciliation_outcome=%s timeline_name=%r "
            "requested_project=%r requested_timeline=%r current_timeline=%r "
            "target_dir=%r custom_name=%r render_format=%r render_codec=%r render_mode=%r "
            "target_dir_diagnostics=%r render_settings_snapshot=%r before_queue_inventory=%r "
            "after_queue_inventory=%r queue_structural_delta=%r",
            project_name,
            resolve_preset_name,
            type(add_result).__name__,
            _safe_repr(add_result),
            before_job_ids,
            after_job_ids if after_job_ids is not None else "unavailable",
            after_job_count,
            after_job_item_types,
            after_job_item_keys,
            candidate_job_ids if candidate_job_ids is not None else "unavailable",
            type(reconciliation_error).__name__,
            _safe_repr(reconciliation_error),
            reconciliation_outcome,
            pre_add_context.get("timeline_name", "unavailable"),
            pre_add_context.get("project_name", "unavailable"),
            pre_add_context.get("requested_timeline_name", "unavailable"),
            pre_add_context.get("current_timeline_name", "unavailable"),
            pre_add_context.get("target_dir", "unavailable"),
            pre_add_context.get("custom_name", "unavailable"),
            pre_add_context.get("render_format", "unavailable"),
            pre_add_context.get("render_codec", "unavailable"),
            pre_add_context.get("render_mode", "unavailable"),
            pre_add_context.get("target_dir_diagnostics", "unavailable"),
            pre_add_context.get("render_settings_snapshot", "unavailable"),
            before_queue_inventory,
            after_queue_inventory,
            queue_structural_delta,
        )

    def _coerce_render_job_id(self, value) -> str | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (str, int)):
            job_id = str(value).strip()
            return job_id or None
        return self._render_job_id_from_job(value)

    def _render_job_id_from_job(self, job) -> str | None:
        if not isinstance(job, dict):
            return None
        for key in ("JobId", "JobID", "jobId", "job_id", "Id", "ID", "id"):
            if key not in job:
                continue
            job_id = self._coerce_render_job_id(job[key])
            if job_id is not None:
                return job_id
        return None

    def get_render_status(self, resolve_job_id: str) -> str:
        """Return the canonical Redline status for a Resolve render job.

        Resolve status lookup is scoped to the currently loaded project.
        Resolve Studio 21.0.3.7 returns None when the job is not found.
        """
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        if not isinstance(resolve_job_id, str) or not resolve_job_id.strip():
            raise RenderJobError("Resolve render job ID must be a non-empty string.")

        normalized_job_id = resolve_job_id.strip()

        try:
            project_manager = self._resolve.GetProjectManager()
            if project_manager is None:
                raise RenderJobError("Resolve project manager is unavailable.")

            project = project_manager.GetCurrentProject()
            if project is None:
                raise RenderJobError("Cannot query render status because no Resolve project is loaded.")

            result = project.GetRenderJobStatus(normalized_job_id)
            if result is None:
                return "unknown"
            if not isinstance(result, dict):
                raise RenderJobError("Resolve returned an invalid render-job status response.")

            raw_status = result.get("JobStatus")
            if not isinstance(raw_status, str) or not raw_status.strip():
                raise RenderJobError(
                    "Resolve render-job status response is missing a valid 'JobStatus' value."
                )

            return _RESOLVE_RENDER_STATUS_MAP.get(raw_status.strip().casefold(), "unknown")
        except RenderJobError:
            raise
        except Exception as exc:
            raise RenderJobError(f"Failed to query Resolve render job {normalized_job_id!r}.") from exc

    def cancel_render(self, resolve_job_id: str) -> None:
        """Cancel a queued or in-progress Resolve render job.

        Queued jobs are cancelled by deleting the queued Resolve job. Active
        renders are cancelled through Resolve's project-scoped StopRendering()
        API only after verifying that the requested job is the sole active
        render. Stopped active jobs are intentionally left in Resolve's render
        queue with status Cancelled.
        """
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        if not isinstance(resolve_job_id, str) or not resolve_job_id.strip():
            raise RenderJobError("Resolve render job ID must be a non-empty string.")

        normalized_job_id = resolve_job_id.strip()

        try:
            project_manager = self._resolve.GetProjectManager()
            if project_manager is None:
                raise RenderJobError("Resolve project manager is unavailable.")

            project = project_manager.GetCurrentProject()
            if project is None:
                raise RenderJobError("Cannot cancel render because no Resolve project is loaded.")

            result = project.GetRenderJobStatus(normalized_job_id)
            if result is None:
                raise RenderJobError(f"Resolve render job {normalized_job_id!r} was not found.")

            raw_status = self._render_job_status_from_response(result)
            status = raw_status.strip().casefold()

            if status == "ready":
                self._cancel_queued_render(project, normalized_job_id)
                return

            if status == "rendering":
                self._cancel_active_render(project, normalized_job_id)
                return

            if status in {"complete", "failed", "cancelled", "canceled"}:
                raise RenderJobError(
                    f"Resolve render job {normalized_job_id!r} cannot be cancelled "
                    f"from terminal status {raw_status!r}."
                )

            raise RenderJobError(
                f"Resolve render job {normalized_job_id!r} has unsupported status {raw_status!r}."
            )
        except RenderJobError:
            raise
        except Exception as exc:
            raise RenderJobError(f"Failed to cancel Resolve render job {normalized_job_id!r}.") from exc

    def _render_job_status_from_response(self, result) -> str:
        if not isinstance(result, dict):
            raise RenderJobError("Resolve returned an invalid render-job status response.")
        raw_status = result.get("JobStatus")
        if not isinstance(raw_status, str) or not raw_status.strip():
            raise RenderJobError(
                "Resolve render-job status response is missing a valid 'JobStatus' value."
            )
        return raw_status

    def _cancel_queued_render(self, project, resolve_job_id: str) -> None:
        deleted = project.DeleteRenderJob(resolve_job_id)
        if deleted is not True:
            raise RenderJobError(f"Resolve failed to delete queued render job {resolve_job_id!r}.")
        if project.GetRenderJobStatus(resolve_job_id) is not None:
            raise RenderJobError(f"Resolve render job {resolve_job_id!r} remained available after deletion.")

    def _cancel_active_render(self, project, resolve_job_id: str) -> None:
        if project.IsRenderingInProgress() is not True:
            raise RenderJobError(
                "Resolve reports the requested job as rendering, but no render is currently active."
            )

        self._verify_active_render_job(project, resolve_job_id)
        project.StopRendering()

        for _ in range(_RENDER_CANCEL_POSTCONDITION_ATTEMPTS):
            if project.IsRenderingInProgress() is False:
                break
            time.sleep(_RENDER_CANCEL_POSTCONDITION_DELAY_SECONDS)
        else:
            raise RenderJobError(f"Resolve did not stop active render job {resolve_job_id!r}.")

        for _ in range(_RENDER_CANCEL_POSTCONDITION_ATTEMPTS):
            stopped_status = project.GetRenderJobStatus(resolve_job_id)
            if isinstance(stopped_status, dict):
                stopped_raw_status = stopped_status.get("JobStatus")
                if isinstance(stopped_raw_status, str) and stopped_raw_status.strip().casefold() == "cancelled":
                    return
            time.sleep(_RENDER_CANCEL_POSTCONDITION_DELAY_SECONDS)

        raise RenderJobError(f"Resolve render job {resolve_job_id!r} did not transition to 'Cancelled'.")

    def _verify_active_render_job(self, project, resolve_job_id: str) -> None:
        try:
            jobs = project.GetRenderJobList()
        except Exception as exc:
            raise RenderJobError("Resolve failed to list render jobs while verifying the active render.") from exc

        if not isinstance(jobs, list):
            raise RenderJobError("Resolve returned an invalid render job list while verifying the active render.")

        rendering_ids: list[str] = []
        for job in jobs:
            job_id = self._render_job_id_from_job(job)
            if job_id is None:
                continue
            job_status = project.GetRenderJobStatus(job_id)
            if not isinstance(job_status, dict):
                continue
            raw_status = job_status.get("JobStatus")
            if isinstance(raw_status, str) and raw_status.strip().casefold() == "rendering":
                rendering_ids.append(job_id)

        if rendering_ids != [resolve_job_id]:
            raise RenderJobError(
                f"Resolve active render job could not be identified safely for {resolve_job_id!r}."
            )

    def start_render(
        self, *, project_name: str, timeline_name: str, resolve_job_id: str, output_path: str
    ) -> None:
        """Start rendering exactly the queued job identified by `resolve_job_id`.

        Unlike `get_render_status()`/`cancel_render()`'s existing
        current-project boundary (see docs/ARCHITECTURE.md §3.6/§3.7), this
        mutation does not trust that the currently loaded Resolve project
        and `resolve_job_id`'s own queue entry are the ones the caller
        actually intends. Three getter-only identity checks run before any
        mutation call, in this order:

        1. `GetCurrentProject().GetName()` must equal exactly
           `project_name`. Never calls `LoadProject()` and never switches
           projects — a wrong current project fails closed.
        2. Exactly one entry in `GetCurrentProject().GetRenderJobList()`
           must strictly resolve to `resolve_job_id` (see
           `_strict_alias_value()` — conflicting or malformed alias values
           anywhere in the queue fail closed rather than silently picking
           one), and that entry's own `TimelineName` must strictly resolve
           to exactly `timeline_name`. Never calls `SetCurrentTimeline()`.
        3. That same matched entry's own `TargetDir`/`OutputFilename` must
           strictly resolve to exactly the directory/complete filename
           (extension included — see `_require_exact_queued_output_destination()`)
           derived from `output_path`. Never calls `SetRenderSettings()` or
           `LoadRenderPreset()` to reconcile a mismatch — the already-queued
           job's identity is immutable for this operation; a mismatch means
           stop, not repair.

        Preconditions, in order (all before any mutation call): connected;
        `project_name`/`timeline_name`/`resolve_job_id`/`output_path` are
        each non-empty strings; current-project identity (1 above);
        queued-job/timeline identity (2 above); queued-output-destination
        identity (3 above); the job's own status is exactly `Ready`
        (`Rendering`, terminal, and unrecognized statuses each fail closed
        with a distinct message); and, independently of the target job's
        own status, `IsRenderingInProgress()` is exactly `False` — any
        other observed value (`True`, `None`, `0`, `1`, a string, a
        container, or any other object) fails closed rather than being
        read as "probably not rendering". None of these preconditions
        prove Resolve has not already been *connected to* elsewhere in the
        application (see `redline_core.runtime.composition`, which connects
        unconditionally before any CLI command runs) — they prove only that
        no start-specific mutation call has happened yet.

        Mutation: calls `StartRendering([resolve_job_id], isInteractiveMode=False)`
        — the job-ID-targeted form documented in the local Resolve Scripting
        README (`StartRendering([jobIds...], isInteractiveMode=False) -->
        Bool # Starts rendering jobs indicated by the input job ids.`), not
        the zero-argument form that starts every queued job. Called at most
        once per invocation, never inside a loop or retry.

        Outcome handling, evaluated only after that one call has actually
        happened (see `_invoke_start_rendering_and_reconcile()` for the
        full rationale): the documented contract is only `StartRendering(...)
        --> Bool`, with no stronger documented guarantee that an exact
        `False` proves no side effect or transient start occurred. Once the
        call has been made, `True`, `False`, an exception, and any
        non-boolean return value are all treated identically — every one of
        them is resolved via the same bounded, getter-only poll of
        `GetRenderJobStatus()` for `JobStatus == "Rendering"` (reusing
        `cancel_render()`'s established postcondition-wait pattern).
        Confirmed within budget: `start_render()` returns normally,
        regardless of which raw signal preceded it. Not confirmed within
        budget: raises `RenderStartReconciliationRequiredError` — never a
        plain `RenderJobError` implying a safe retry, because the mutation
        call did happen and no return value (including `False`) is treated
        as sufficient proof by itself that nothing happened.

        The postcondition poll itself never calls `StartRendering()` again,
        and tolerates (rather than propagates) a `GetRenderJobStatus()`
        exception or malformed response during any individual poll attempt
        — those simply count as "not yet confirmed" for that attempt, not
        as a reason to abandon the bounded wait early.
        """
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        if not isinstance(project_name, str) or not project_name.strip():
            raise RenderJobError("Project name must be a non-empty string.")
        if not isinstance(timeline_name, str) or not timeline_name.strip():
            raise RenderJobError("Timeline name must be a non-empty string.")
        if not isinstance(resolve_job_id, str) or not resolve_job_id.strip():
            raise RenderJobError("Resolve render job ID must be a non-empty string.")
        if not isinstance(output_path, str) or not output_path.strip():
            raise RenderJobError("Output path must be a non-empty string.")

        normalized_project_name = project_name.strip()
        normalized_timeline_name = timeline_name.strip()
        normalized_job_id = resolve_job_id.strip()
        normalized_output_path = output_path.strip()

        # ---- Category A: every one of these guards runs strictly before
        # StartRendering() is ever invoked. Any failure here proves zero
        # start-specific mutation calls occurred (it does NOT prove Resolve
        # was never connected to at all -- see the docstring above). ----
        try:
            project_manager = self._resolve.GetProjectManager()
            if project_manager is None:
                raise RenderJobError("Resolve project manager is unavailable.")

            project = project_manager.GetCurrentProject()
            if project is None:
                raise RenderJobError("Cannot start render because no Resolve project is loaded.")

            self._require_exact_current_project(project, normalized_project_name)
            matched_job = self._require_exact_queued_job_identity(
                project, normalized_job_id, normalized_timeline_name
            )
            self._require_exact_queued_output_destination(
                matched_job, normalized_job_id, normalized_output_path
            )

            result = project.GetRenderJobStatus(normalized_job_id)
            if result is None:
                raise RenderJobError(f"Resolve render job {normalized_job_id!r} was not found.")

            raw_status = self._render_job_status_from_response(result)
            status = raw_status.strip().casefold()

            if status == "ready":
                pass
            elif status == "rendering":
                raise RenderJobError(f"Resolve render job {normalized_job_id!r} is already rendering.")
            elif status in {"complete", "failed", "cancelled", "canceled"}:
                raise RenderJobError(
                    f"Resolve render job {normalized_job_id!r} cannot be started "
                    f"from terminal status {raw_status!r}."
                )
            else:
                raise RenderJobError(
                    f"Resolve render job {normalized_job_id!r} has unsupported status {raw_status!r}."
                )

            rendering_in_progress = project.IsRenderingInProgress()
            if rendering_in_progress is not False:
                raise RenderJobError(
                    "Resolve did not report an exact rendering-in-progress state of False "
                    f"(observed {rendering_in_progress!r}); refusing to start render job "
                    f"{normalized_job_id!r} while that cannot be ruled out."
                )
        except RenderJobError:
            raise
        except Exception as exc:
            raise RenderJobError(
                f"Failed to verify preconditions before starting Resolve render job {normalized_job_id!r}."
            ) from exc

        # ---- Category B begins here: StartRendering() is about to be
        # invoked. From this point on, an exception or ambiguous result
        # no longer proves no mutation occurred -- see
        # _invoke_start_rendering_and_reconcile(). ----
        self._invoke_start_rendering_and_reconcile(project, normalized_job_id)

    def _require_exact_current_project(self, project, expected_project_name: str) -> None:
        """Fail closed unless Resolve's currently loaded project's own
        reported name is exactly `expected_project_name`. Getter-only:
        never calls `LoadProject()` and never switches the current
        project."""
        get_name = getattr(project, "GetName", None)
        if not callable(get_name):
            raise RenderJobError("Resolve's current project cannot report its name.")
        try:
            actual_name = get_name()
        except Exception as exc:
            raise RenderJobError("Resolve failed while reading the current project's name.") from exc
        if not isinstance(actual_name, str) or not actual_name.strip():
            raise RenderJobError(
                f"Resolve's current project has no usable name (expected {expected_project_name!r})."
            )
        if actual_name != expected_project_name:
            raise RenderJobError(
                f"Resolve's current project is {actual_name!r}, but the render job requires project "
                f"{expected_project_name!r}. Refusing to start a render against the wrong project."
            )

    def _strict_alias_value(self, entry: dict, aliases: tuple[str, ...]) -> tuple[str | None, bool]:
        """Strict, start-pathway-owned alias resolution -- deliberately
        separate from the legacy, precedence-based `_render_job_id_from_job()`
        (which other, already-reviewed pathways such as `queue_render_job()`
        reconciliation and `cancel_render()` continue to use unchanged).

        Inspects every one of `aliases` present in `entry` -- not merely
        the first in precedence order -- and returns `(resolved_value,
        malformed)`:

        - No alias present: `(None, False)` -- absent, not malformed.
        - One or more aliases present, every present value a non-empty
          string, and all present values agreeing: `(value, False)`.
        - Any present alias holding a non-string value (including `bool`,
          since `bool` is a `str`-unsafe subtype of `int` in Python) or an
          all-whitespace string: `(None, True)` -- malformed. Never
          coerces `bool`/`int`/`dict`/any other type into a string.
        - Multiple present aliases holding validly-typed but disagreeing
          string values: `(None, True)` -- malformed (conflicting).

        A malformed result must never be silently treated as "no value" by
        a caller trying to match a specific requested identity -- it means
        the entry's true identity for this field cannot be safely
        determined at all.
        """
        present_values: list[str] = []
        for alias in aliases:
            if alias not in entry:
                continue
            value = entry[alias]
            if isinstance(value, bool) or not isinstance(value, str) or not value.strip():
                return None, True
            present_values.append(value)

        if not present_values:
            return None, False

        distinct_values = set(present_values)
        if len(distinct_values) > 1:
            return None, True

        return present_values[0], False

    def _require_exact_queued_job_identity(
        self, project, resolve_job_id: str, expected_timeline_name: str
    ) -> dict:
        """Fail closed unless exactly one entry in the current project's
        render queue strictly resolves to `resolve_job_id`, and that
        entry's own timeline identity strictly resolves to exactly
        `expected_timeline_name`. Getter-only: never calls
        `SetCurrentTimeline()`. Returns the matched queue entry so the
        caller can further verify its output destination.

        Every queue entry is inspected with `_strict_alias_value()`, not
        just entries that already look related to `resolve_job_id` -- an
        entry anywhere in the queue with conflicting or malformed job-ID
        aliases makes it impossible to prove "exactly one entry resolves
        to `resolve_job_id`" and fails the whole lookup closed, rather than
        being silently skipped.
        """
        try:
            jobs = project.GetRenderJobList()
        except Exception as exc:
            raise RenderJobError(
                "Resolve failed to list render jobs while verifying the job to start."
            ) from exc
        if not isinstance(jobs, list):
            raise RenderJobError(
                "Resolve returned an invalid render job list while verifying the job to start."
            )

        matches: list[dict] = []
        for job in jobs:
            if not isinstance(job, dict):
                raise RenderJobError(
                    f"Resolve's render queue contains a non-record entry while verifying job "
                    f"{resolve_job_id!r}; refusing to determine queue identity safely."
                )
            resolved_id, malformed = self._strict_alias_value(job, _JOB_ID_ALIASES)
            if malformed:
                raise RenderJobError(
                    f"Resolve's render queue contains an entry with conflicting or malformed job-ID "
                    f"alias values while verifying job {resolve_job_id!r}; refusing to determine queue "
                    "identity safely."
                )
            if resolved_id == resolve_job_id:
                matches.append(job)

        if not matches:
            raise RenderJobError(
                f"Resolve render job {resolve_job_id!r} was not found in the current project's render queue."
            )
        if len(matches) > 1:
            raise RenderJobError(
                f"Resolve's render queue contains {len(matches)} entries matching job ID "
                f"{resolve_job_id!r}; refusing to start an ambiguous job."
            )

        job = matches[0]

        timeline_name, timeline_malformed = self._strict_alias_value(job, _TIMELINE_NAME_ALIASES)
        if timeline_malformed:
            raise RenderJobError(
                f"Resolve's render queue entry for job {resolve_job_id!r} has conflicting or malformed "
                "timeline alias values."
            )
        if timeline_name is None:
            raise RenderJobError(
                f"Resolve's render queue entry for job {resolve_job_id!r} has no usable timeline name."
            )
        if timeline_name != expected_timeline_name:
            raise RenderJobError(
                f"Resolve's render queue entry for job {resolve_job_id!r} targets timeline "
                f"{timeline_name!r}, but the render job requires timeline {expected_timeline_name!r}."
            )

        return job

    def _require_exact_queued_output_destination(
        self, job: dict, resolve_job_id: str, expected_output_path: str
    ) -> None:
        """Fail closed unless the matched queue entry's own output
        destination (`TargetDir` + `OutputFilename`, strictly resolved)
        equals exactly the directory/complete filename derived from
        `expected_output_path`. Getter-only: never calls
        `SetRenderSettings()` or `LoadRenderPreset()` to reconcile a
        mismatch -- an already-queued job's destination is immutable for
        this operation; a mismatch means stop, not repair.

        Rev4 correction: `OutputFilename` is compared against
        `expected_path.name` (the complete filename, extension included),
        not `expected_path.stem`. Live getter-only evidence captured from a
        real, running Resolve Studio 21.0.3.7 instance's `GetRenderJobList()`
        (`RLC-E9901_render_queue_snapshot_rev3_20260810T233837Z.json`,
        SHA-256 `f2afab5c4e2fb04821c928511341801e3ae6c232ed9fbbe70151c369710c8975`)
        shows Resolve reports `OutputFilename` as the complete filename
        (e.g. `RLC-E9901_MASTER.mov`), not the extensionless stem Rev3
        assumed. The extension is never inferred from codec/format and
        never stripped -- it is read directly from the persisted
        `expected_output_path`, which already carries it.
        """
        target_dir_value, target_dir_malformed = self._strict_alias_value(job, _TARGET_DIR_ALIASES)
        if target_dir_malformed:
            raise RenderJobError(
                f"Resolve's render queue entry for job {resolve_job_id!r} has conflicting or malformed "
                "TargetDir alias values."
            )
        if target_dir_value is None:
            raise RenderJobError(
                f"Resolve's render queue entry for job {resolve_job_id!r} has no usable TargetDir."
            )

        output_filename_value, output_filename_malformed = self._strict_alias_value(
            job, _OUTPUT_FILENAME_ALIASES
        )
        if output_filename_malformed:
            raise RenderJobError(
                f"Resolve's render queue entry for job {resolve_job_id!r} has conflicting or malformed "
                "OutputFilename alias values."
            )
        if output_filename_value is None:
            raise RenderJobError(
                f"Resolve's render queue entry for job {resolve_job_id!r} has no usable OutputFilename."
            )

        expected_path = Path(expected_output_path)
        expected_output_filename = expected_path.name

        try:
            actual_target_dir = Path(target_dir_value).expanduser().resolve(strict=False)
            expected_target_dir = expected_path.parent.expanduser().resolve(strict=False)
        except Exception as exc:
            raise RenderJobError(
                f"Could not normalize TargetDir while verifying output destination for render job "
                f"{resolve_job_id!r}."
            ) from exc

        if actual_target_dir != expected_target_dir:
            raise RenderJobError(
                f"Resolve's render queue entry for job {resolve_job_id!r} targets output directory "
                f"{target_dir_value!r}, but the render job requires output directory "
                f"{str(expected_target_dir)!r}."
            )
        if output_filename_value != expected_output_filename:
            raise RenderJobError(
                f"Resolve's render queue entry for job {resolve_job_id!r} targets output filename "
                f"{output_filename_value!r}, but the render job requires output filename "
                f"{expected_output_filename!r}."
            )

    def _invoke_start_rendering_and_reconcile(self, project, resolve_job_id: str) -> None:
        """Call `StartRendering()` exactly once, then resolve its outcome.

        The documented contract is only `StartRendering(...) --> Bool`,
        with no stronger documented guarantee that an exact `False`
        return proves no side effect or transient start occurred. Once
        this call has actually been made, `True`, `False`, an exception,
        and any non-boolean return value are therefore all resolved
        identically: via the same bounded, getter-only reconciliation poll
        (`_poll_for_rendering()`). Confirmed `Rendering` within budget is
        success regardless of which raw signal preceded it; not confirmed
        always raises `RenderStartReconciliationRequiredError` -- including
        for an exact `False` return, since no safety guarantee is inferred
        from that value alone. Never calls `StartRendering()` a second
        time under any circumstance.
        """
        start_exception: Exception | None = None
        try:
            start_result = project.StartRendering([resolve_job_id], isInteractiveMode=False)
        except Exception as exc:
            start_exception = exc
            start_result = None

        if start_exception is None and start_result not in (True, False):
            logger.warning(
                "Resolve StartRendering() returned a non-boolean value %r for render job %r; "
                "reconciling via getters only.",
                start_result,
                resolve_job_id,
            )
        elif start_exception is None and start_result is False:
            logger.warning(
                "Resolve StartRendering() returned False for render job %r; reconciling via getters "
                "only rather than treating False alone as proof no mutation occurred.",
                resolve_job_id,
            )

        if self._poll_for_rendering(project, resolve_job_id):
            return

        if start_exception is not None:
            raise RenderStartReconciliationRequiredError(
                f"Resolve StartRendering() raised while starting render job {resolve_job_id!r}, and a "
                "getter-only reconciliation check could not confirm whether the job actually started. "
                "StartRendering was attempted; the final live Resolve state is not proven. Do not retry "
                "StartRendering for this job until manual reconciliation establishes state."
            ) from start_exception

        raise RenderStartReconciliationRequiredError(
            f"Resolve StartRendering() was invoked for render job {resolve_job_id!r} and returned "
            f"{start_result!r}, but a bounded getter-only postcondition check could not confirm the job "
            "transitioned to 'Rendering'. StartRendering was attempted; the final live Resolve state is "
            "not proven. Do not retry StartRendering for this job until manual reconciliation establishes "
            "state."
        )

    def _poll_for_rendering(self, project, resolve_job_id: str) -> bool:
        """Bounded, getter-only poll for `JobStatus == 'Rendering'`.

        Returns True if confirmed within the attempt budget, False
        otherwise. Never calls `StartRendering()`. A `GetRenderJobStatus()`
        exception or a malformed response during any individual attempt is
        tolerated as "not yet confirmed" for that attempt rather than
        aborting the wait early -- the caller decides what a final `False`
        means (always reconciliation-required, never a silent pass)."""
        for _ in range(_RENDER_START_POSTCONDITION_ATTEMPTS):
            try:
                status_response = project.GetRenderJobStatus(resolve_job_id)
            except Exception:
                status_response = None
            if isinstance(status_response, dict):
                raw_status = status_response.get("JobStatus")
                if isinstance(raw_status, str) and raw_status.strip().casefold() == "rendering":
                    return True
            time.sleep(_RENDER_START_POSTCONDITION_DELAY_SECONDS)
        return False

    def get_video_timeline_item_count(self, project_name: str, timeline_name: str) -> int:
        """Count video TimelineItems on `timeline_name` in `project_name`.

        Uses the same `Timeline.GetTrackCount("video")` /
        `Timeline.GetItemListInTrack("video", index)` calls verified during
        Phase 14 Test D evidence capture. Fails closed: a missing capability,
        invalid track count, or non-list item-list response raises
        `TimelineOperationError` rather than assuming renderability.
        """
        if self._resolve is None or self._project_manager is None:
            raise ResolveConnectionError("Not connected to Resolve. Call connect() first.")

        project = self._project_manager.LoadProject(project_name)
        if not project:
            raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")

        timeline = self._find_timeline(project, timeline_name)
        if timeline is None:
            raise TimelineOperationError(f"Timeline '{timeline_name}' not found in project '{project_name}'.")

        get_track_count = getattr(timeline, "GetTrackCount", None)
        get_item_list_in_track = getattr(timeline, "GetItemListInTrack", None)
        if not callable(get_track_count) or not callable(get_item_list_in_track):
            raise TimelineOperationError(
                f"Resolve timeline '{timeline_name}' cannot report video track/item counts."
            )

        try:
            track_count = get_track_count("video")
        except Exception as exc:
            raise TimelineOperationError(
                f"Resolve failed to report the video track count for timeline '{timeline_name}'."
            ) from exc
        if isinstance(track_count, bool) or not isinstance(track_count, int) or track_count < 0:
            raise TimelineOperationError(
                f"Resolve returned an invalid video track count for timeline '{timeline_name}': {track_count!r}."
            )

        total_items = 0
        for index in range(1, track_count + 1):
            try:
                raw_items = get_item_list_in_track("video", index)
            except Exception as exc:
                raise TimelineOperationError(
                    f"Resolve failed to list items on video track {index} of timeline '{timeline_name}'."
                ) from exc
            if raw_items is None or raw_items is False:
                raw_items = []
            if not isinstance(raw_items, list):
                raise TimelineOperationError(
                    f"Resolve returned an invalid item list for video track {index} of timeline "
                    f"'{timeline_name}': {type(raw_items).__name__}."
                )
            total_items += len(raw_items)

        return total_items
