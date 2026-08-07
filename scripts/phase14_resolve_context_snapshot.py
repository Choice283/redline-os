"""Phase 14 dual project/timeline read-only snapshot and offline comparison probe.

Construction status
-------------------
This source is Phase 14.1: a live-execution-*capable* construction and static
review revision. It remains fail-closed by default. Live snapshot execution
is gated by an explicit execution interlock (see ``enforce_execution_interlock``)
rather than an unconditional boolean disable. The interlock is a deliberate
execution control, not authentication and not a security secret: it exists so
an operator cannot reach Resolve by accident, not to keep out an adversary.

Reaching Resolve requires the CLI caller to pass
``--execution-authorization <revision-id>`` on the ``snapshot`` subcommand,
where ``<revision-id>`` must exactly equal ``EXECUTION_REVISION_ID`` below.
That value is immutable for this exact source text: any future source change
requires a new identifier and a new SHA-256, reviewed and bound together by a
separate founder authorization. Founder authorization for live use must still
bind: the exact repository commit, this exact source SHA-256, this exact
``EXECUTION_REVISION_ID``, the exact project/timeline contexts, and the exact
evidence paths. Minting matching source + identifier is a necessary
precondition, not the authorization itself.

The module may be imported and its pure comparison functions may be exercised
freely. The ``compare`` subcommand and ``--print-sha256`` never require the
interlock and never contact Resolve.

Safety design
-------------
* No Resolve module import occurs at module import time.
* The ``snapshot`` CLI path stops at the execution interlock, before output
  validation, before ``DaVinciResolveScript`` import, and before connection,
  unless the caller supplies the exact matching ``--execution-authorization``.
* Output paths (both ``snapshot`` and ``compare``) are validated for
  pre-existence before Resolve contact and are never overwritten: the final
  write is a same-directory temp file followed by a create-only atomic link,
  so a failure never leaves partial or replaced evidence.
* Snapshot collection accepts an injected Resolve handle for mocked tests.
* Every dynamically dispatched Resolve method is restricted to a closed,
  read-only allowlist.
* No project or timeline switch is attempted.
* No preset is loaded and no render setting is changed.
* No render job is created, deleted, started, stopped, or cancelled.
* Ambiguous, malformed, incomplete, repeated, or drifting state fails closed.
* Offline comparison never imports or contacts Resolve.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import copy
import datetime as dt
import hashlib
import importlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

MISSION = "Phase 14 — Dual Project/Timeline Read-Only Snapshot Probe"
SCHEMA_VERSION = "1.0"

# Immutable for this exact source revision. A future source change requires a
# new identifier minted together with a new SHA-256, both reviewed together
# and bound to founder authorization. This is a deliberate execution
# interlock, not a credential: its purpose is to require the operator to name
# the exact revision they intend to run, not to resist a determined attacker.
EXECUTION_REVISION_ID = "phase14.1-live-interlock-construction-rev7"
# Both endpoints must be alphanumeric (a trailing '.', '_', or '-' is
# rejected, not just a leading one); total length 2-80 characters.
EXECUTION_REVISION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,78}[A-Za-z0-9]$")

UNAVAILABLE_FOLDER_NAME = "<folder-name-unavailable>"
TRACK_TYPES_REQUIRED = ("video", "audio")
TRACK_TYPES_OPTIONAL = ("subtitle",)

# Closed dynamic-dispatch allowlist. These method names are inspection-only in
# the Resolve scripting interface. A future review must re-approve this exact
# set before enabling live execution.
READ_ONLY_RESOLVE_METHODS = frozenset(
    {
        # Resolve
        "GetProductName",
        "GetVersion",
        "GetVersionString",
        "GetProjectManager",
        # ProjectManager
        "GetCurrentProject",
        "GetProjectListInCurrentFolder",
        "GetProjectAttributesInCurrentFolder",
        # Project
        "GetName",
        "GetTimelineCount",
        "GetTimelineByIndex",
        "GetCurrentTimeline",
        "GetMediaPool",
        "GetSetting",
        "IsRenderingInProgress",
        "GetRenderJobList",
        "GetRenderPresetList",
        "GetRenderPresetNames",
        "GetCurrentRenderFormatAndCodec",
        "GetCurrentRenderMode",
        "GetRenderSettings",
        # MediaPool / Folder
        "GetRootFolder",
        "GetSubFolderList",
        "GetClipList",
        # Timeline
        "GetStartFrame",
        "GetEndFrame",
        "GetStartTimecode",
        "GetTrackCount",
        "GetItemListInTrack",
        "GetMarkers",
        # TimelineItem / MediaPoolItem optional accessors
        "GetStart",
        "GetEnd",
        "GetDuration",
        "GetLeftOffset",
        "GetRightOffset",
        "GetSourceStartFrame",
        "GetSourceEndFrame",
        "GetMediaPoolItem",
        "GetUniqueId",
        "GetClipEnabled",
        "GetMediaId",
        "GetClipProperty",
    }
)

# Explicitly forbidden for this probe. The list is also consumed by static
# tests. It is intentionally broader than the methods currently used by
# Redline OS.
PROHIBITED_RESOLVE_METHODS = frozenset(
    {
        "LoadProject",
        "CloseProject",
        "CreateProject",
        "DeleteProject",
        "SaveProject",
        "SetCurrentTimeline",
        "SetCurrentFolder",
        "SetSetting",
        "SetRenderSettings",
        "LoadRenderPreset",
        "AddRenderJob",
        "DeleteRenderJob",
        "DeleteAllRenderJobs",
        "StartRendering",
        "StopRendering",
        "CreateEmptyTimeline",
        "CreateTimelineFromClips",
        "ImportTimelineFromFile",
        "AppendToTimeline",
        "AddItemListToMediaPool",
        "ImportMedia",
        "AddSubFolder",
        "DeleteFolders",
        "MoveFolders",
        "DeleteClips",
        "MoveClips",
        "AddMarker",
        "DeleteMarkerAtFrame",
        "DeleteMarkersByColor",
        "SetName",
        "SetClipProperty",
        "SetClipEnabled",
    }
)

QUEUE_JOB_ID_KEYS = ("JobId", "JobID", "jobId", "job_id", "Id", "ID", "id")
CONTEXT_SENSITIVE_PREFIXES = (
    "/project/current_render_context",
    "/project/render_presets",
    "/project/render_queue",
)


class SnapshotError(RuntimeError):
    """Fail-closed snapshot error with a machine-readable classification."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": normalize_json_value(self.details),
        }


class UnsupportedEvidenceType(TypeError):
    """Raised when a bridged object cannot be represented safely in JSON."""


@dataclass(frozen=True)
class SnapshotContext:
    expected_project: str
    expected_timeline: str


@dataclass(frozen=True)
class ComparisonRecord:
    path: str
    classification: str
    control: Any
    production: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "classification": self.classification,
            "control": self.control,
            "production": self.production,
        }


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def script_sha256(path: Path | None = None) -> str:
    target = path or Path(__file__)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def normalize_json_value(value: Any, *, _path: str = "$", _seen: set[int] | None = None) -> Any:
    """Convert approved scalar/container values to deterministic JSON data.

    Arbitrary Resolve bridge handles are never stringified or repr()'d. Cyclic
    containers and non-string mapping keys are rejected explicitly.
    """

    if value is None or isinstance(value, (str, bool, int, float)):
        return value

    seen = _seen if _seen is not None else set()
    container_id = id(value)
    if isinstance(value, (list, tuple, dict)):
        if container_id in seen:
            raise UnsupportedEvidenceType(f"cyclic evidence container at {_path}")
        seen.add(container_id)

    try:
        if isinstance(value, (list, tuple)):
            return [
                normalize_json_value(item, _path=f"{_path}[{index}]", _seen=seen)
                for index, item in enumerate(value)
            ]
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key in sorted(value.keys(), key=lambda item: str(item)):
                if not isinstance(key, str):
                    raise UnsupportedEvidenceType(
                        f"non-string evidence key at {_path}: {type(key).__name__}"
                    )
                normalized[key] = normalize_json_value(
                    value[key], _path=f"{_path}.{key}", _seen=seen
                )
            return normalized
    finally:
        if isinstance(value, (list, tuple, dict)):
            seen.discard(container_id)

    raise UnsupportedEvidenceType(
        f"unsupported evidence type at {_path}: {type(value).__name__}"
    )


def _resolve_method(obj: Any, method_name: str) -> Callable[..., Any]:
    if method_name not in READ_ONLY_RESOLVE_METHODS:
        raise SnapshotError(
            "accessor_not_allowlisted",
            f"Resolve accessor is not in the approved read-only allowlist: {method_name}",
        )
    try:
        method = getattr(obj, method_name)
    except Exception as exc:
        raise SnapshotError(
            "accessor_lookup_failed",
            f"Resolve accessor lookup raised for {method_name}",
            details={"method": method_name, "error_type": type(exc).__name__},
        ) from exc
    if not callable(method):
        raise SnapshotError(
            "accessor_unavailable",
            f"Resolve accessor is not callable: {method_name}",
            details={"method": method_name},
        )
    return method


def call_required(obj: Any, method_name: str, *args: Any) -> Any:
    method = _resolve_method(obj, method_name)
    try:
        return method(*args)
    except SnapshotError:
        raise
    except Exception as exc:
        raise SnapshotError(
            "accessor_call_failed",
            f"Resolve accessor raised: {method_name}",
            details={"method": method_name, "error_type": type(exc).__name__},
        ) from exc


def observe_optional(obj: Any, method_name: str, *args: Any) -> dict[str, Any]:
    """Capture an optional read-only accessor without leaking bridge values."""

    if method_name not in READ_ONLY_RESOLVE_METHODS:
        return {
            "source_method": method_name,
            "status": "error",
            "value_type": None,
            "value": None,
            "error": {
                "type": "AccessorNotAllowlisted",
                "message": "method is not in the approved read-only allowlist",
            },
        }
    try:
        method = getattr(obj, method_name)
    except AttributeError:
        return {
            "source_method": method_name,
            "status": "unavailable",
            "value_type": None,
            "value": None,
            "error": {"type": "AccessorUnavailable", "message": "accessor is absent"},
        }
    except Exception as exc:
        return {
            "source_method": method_name,
            "status": "error",
            "value_type": None,
            "value": None,
            "error": {"type": type(exc).__name__, "message": "accessor lookup raised"},
        }
    if not callable(method):
        return {
            "source_method": method_name,
            "status": "unavailable",
            "value_type": None,
            "value": None,
            "error": {"type": "AccessorUnavailable", "message": "accessor is not callable"},
        }
    try:
        raw = method(*args)
    except Exception as exc:
        return {
            "source_method": method_name,
            "status": "error",
            "value_type": None,
            "value": None,
            "error": {"type": type(exc).__name__, "message": "accessor call raised"},
        }
    try:
        normalized = normalize_json_value(raw)
    except UnsupportedEvidenceType as exc:
        return {
            "source_method": method_name,
            "status": "error",
            "value_type": type(raw).__name__,
            "value": None,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    return {
        "source_method": method_name,
        "status": "observed",
        "value_type": type(raw).__name__,
        "value": normalized,
        "error": None,
    }


def require_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SnapshotError(
            "invalid_count",
            f"{label} must be a non-negative integer",
            details={"label": label, "value_type": type(value).__name__},
        )
    return value


def require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotError(
            "invalid_string",
            f"{label} must be a non-empty string",
            details={"label": label, "value_type": type(value).__name__},
        )
    return value


def require_collection(value: Any, label: str, *, false_means_empty: bool = False) -> list[Any]:
    if false_means_empty and (value is None or value is False):
        return []
    if not isinstance(value, (list, tuple)):
        raise SnapshotError(
            "invalid_collection",
            f"{label} must be a list or tuple",
            details={"label": label, "value_type": type(value).__name__},
        )
    return list(value)


def queue_job_id(job: Any) -> str | None:
    if not isinstance(job, dict):
        return None
    for key in QUEUE_JOB_ID_KEYS:
        value = job.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (str, int)):
            candidate = str(value).strip()
            if candidate:
                return candidate
    return None


def queue_inventory(raw_jobs: Any) -> dict[str, Any]:
    jobs = require_collection(raw_jobs, "render queue", false_means_empty=True)
    safe_items: list[dict[str, Any]] = []
    for item in jobs:
        if isinstance(item, dict):
            try:
                keys = sorted(str(key) for key in item.keys())
            except Exception as exc:
                raise SnapshotError(
                    "queue_item_keys_unavailable",
                    "render queue item keys could not be inspected",
                    details={"error_type": type(exc).__name__},
                ) from exc
            safe_items.append(
                {
                    "type": "dict",
                    "keys": keys,
                    "job_id": queue_job_id(item),
                }
            )
        else:
            safe_items.append(
                {
                    "type": type(item).__name__,
                    "keys": None,
                    "job_id": None,
                }
            )
    return {
        "raw_type": type(raw_jobs).__name__,
        "count": len(jobs),
        "items": safe_items,
    }


def capture_session(resolve: Any) -> dict[str, Any]:
    product = observe_optional(resolve, "GetProductName")
    version = observe_optional(resolve, "GetVersion")
    version_string = observe_optional(resolve, "GetVersionString")
    has_usable_version = False
    for observation in (version_string, version):
        if observation["status"] == "observed" and observation["value"] not in (None, "", []):
            has_usable_version = True
            break
    if not has_usable_version:
        raise SnapshotError(
            "resolve_version_unavailable",
            "Resolve did not expose a usable version through the approved accessors",
        )
    return {
        "product_name": product,
        "version": version,
        "version_string": version_string,
    }


def _timeline_name(timeline: Any, label: str) -> str:
    return require_nonempty_string(call_required(timeline, "GetName"), label)


def enumerate_timelines(project: Any) -> tuple[list[dict[str, Any]], Any]:
    count = require_nonnegative_int(call_required(project, "GetTimelineCount"), "timeline count")
    inventory: list[dict[str, Any]] = []
    handles: list[Any] = []
    for index in range(1, count + 1):
        timeline = call_required(project, "GetTimelineByIndex", index)
        if not timeline:
            raise SnapshotError(
                "timeline_handle_missing",
                "Resolve returned an unusable timeline handle",
                details={"index": index},
            )
        name = _timeline_name(timeline, f"timeline name at index {index}")
        inventory.append(
            {
                "index": index,
                "name": name,
                "unique_id": observe_optional(timeline, "GetUniqueId"),
            }
        )
        handles.append(timeline)
    return inventory, handles


def select_expected_timeline(
    project: Any,
    expected_timeline: str,
    inventory: Sequence[Mapping[str, Any]],
    handles: Sequence[Any],
) -> Any:
    matching_indexes = [
        index
        for index, entry in enumerate(inventory)
        if entry.get("name") == expected_timeline
    ]
    if not matching_indexes:
        raise SnapshotError(
            "expected_timeline_missing",
            f"Expected timeline was not found: {expected_timeline}",
        )
    if len(matching_indexes) != 1:
        raise SnapshotError(
            "duplicate_expected_timeline",
            f"Expected timeline matched more than once: {expected_timeline}",
            details={"matching_inventory_indexes": matching_indexes},
        )

    target = handles[matching_indexes[0]]
    current = call_required(project, "GetCurrentTimeline")
    if not current:
        raise SnapshotError("current_timeline_missing", "Resolve has no current timeline")
    current_name = _timeline_name(current, "current timeline name")
    if current_name != expected_timeline:
        raise SnapshotError(
            "current_timeline_mismatch",
            "The operator-prepositioned current timeline does not match the expected timeline",
            details={"expected": expected_timeline, "actual": current_name},
        )

    target_id = inventory[matching_indexes[0]].get("unique_id")
    current_id = observe_optional(current, "GetUniqueId")
    if (
        isinstance(target_id, dict)
        and target_id.get("status") == "observed"
        and current_id.get("status") == "observed"
        and target_id.get("value") != current_id.get("value")
    ):
        raise SnapshotError(
            "current_timeline_identity_mismatch",
            "Current timeline name matched, but the observed unique ID differed",
            details={"target_unique_id": target_id, "current_unique_id": current_id},
        )
    return target


def capture_project_manager(project_manager: Any) -> dict[str, Any]:
    return {
        "project_list_in_current_folder": observe_optional(
            project_manager, "GetProjectListInCurrentFolder"
        ),
        "project_attributes_in_current_folder": observe_optional(
            project_manager, "GetProjectAttributesInCurrentFolder"
        ),
    }


def capture_media_pool_item(item: Any) -> dict[str, Any]:
    return {
        "name": observe_optional(item, "GetName"),
        "media_id": observe_optional(item, "GetMediaId"),
        "unique_id": observe_optional(item, "GetUniqueId"),
        "clip_properties": observe_optional(item, "GetClipProperty"),
    }


def _folder_name(folder: Any) -> str:
    observation = observe_optional(folder, "GetName")
    if observation["status"] != "observed":
        return UNAVAILABLE_FOLDER_NAME
    value = observation["value"]
    if not isinstance(value, str) or not value:
        return UNAVAILABLE_FOLDER_NAME
    return value


def walk_media_pool_folder(
    folder: Any,
    *,
    path: tuple[str, ...],
    visited: dict[int, tuple[str, ...]],
) -> dict[str, Any]:
    name = _folder_name(folder)
    current_path = path + (name,)
    identity = id(folder)
    if identity in visited:
        raise SnapshotError(
            "repeated_media_pool_folder_handle",
            "A repeated or cyclic media-pool folder handle was encountered",
            details={
                "first_path": list(visited[identity]),
                "repeated_path": list(current_path),
            },
        )
    visited[identity] = current_path

    clips_raw = call_required(folder, "GetClipList")
    clips = require_collection(clips_raw, "media-pool clip list", false_means_empty=True)
    normalized_clips: list[dict[str, Any]] = []
    for index, clip in enumerate(clips):
        if not clip:
            raise SnapshotError(
                "media_pool_clip_handle_missing",
                "Media-pool clip list contained an unusable handle",
                details={"folder_path": list(current_path), "clip_index": index},
            )
        normalized_clips.append(capture_media_pool_item(clip))

    subfolders_raw = call_required(folder, "GetSubFolderList")
    subfolders = require_collection(
        subfolders_raw, "media-pool subfolder list", false_means_empty=True
    )
    normalized_subfolders: list[dict[str, Any]] = []
    for index, subfolder in enumerate(subfolders):
        if not subfolder:
            raise SnapshotError(
                "media_pool_subfolder_handle_missing",
                "Media-pool subfolder list contained an unusable handle",
                details={"folder_path": list(current_path), "subfolder_index": index},
            )
        normalized_subfolders.append(
            walk_media_pool_folder(subfolder, path=current_path, visited=visited)
        )

    return {
        "name": name,
        "path": list(current_path),
        "clips": normalized_clips,
        "subfolders": normalized_subfolders,
    }


def capture_media_pool(project: Any) -> dict[str, Any]:
    media_pool = call_required(project, "GetMediaPool")
    if not media_pool:
        raise SnapshotError("media_pool_missing", "Resolve project has no usable media pool")
    root = call_required(media_pool, "GetRootFolder")
    if not root:
        raise SnapshotError(
            "media_pool_root_missing", "Resolve media pool has no usable root folder"
        )
    return walk_media_pool_folder(root, path=(), visited={})


def capture_timeline_item(item: Any, *, track_type: str, track_index: int, item_index: int) -> dict[str, Any]:
    media_pool_item_observation: dict[str, Any]
    try:
        method = _resolve_method(item, "GetMediaPoolItem")
        source = method()
    except SnapshotError as exc:
        media_pool_item_observation = {
            "status": "error",
            "error": exc.to_dict(),
            "item": None,
        }
    except Exception as exc:
        media_pool_item_observation = {
            "status": "error",
            "error": {
                "code": "accessor_call_failed",
                "message": "GetMediaPoolItem raised",
                "details": {"error_type": type(exc).__name__},
            },
            "item": None,
        }
    else:
        if not source:
            media_pool_item_observation = {
                "status": "unavailable",
                "error": None,
                "item": None,
            }
        else:
            media_pool_item_observation = {
                "status": "observed",
                "error": None,
                "item": capture_media_pool_item(source),
            }

    return {
        "track_type": track_type,
        "track_index": track_index,
        "item_index": item_index,
        "name": observe_optional(item, "GetName"),
        "unique_id": observe_optional(item, "GetUniqueId"),
        "start": observe_optional(item, "GetStart"),
        "end": observe_optional(item, "GetEnd"),
        "duration": observe_optional(item, "GetDuration"),
        "left_offset": observe_optional(item, "GetLeftOffset"),
        "right_offset": observe_optional(item, "GetRightOffset"),
        "source_start_frame": observe_optional(item, "GetSourceStartFrame"),
        "source_end_frame": observe_optional(item, "GetSourceEndFrame"),
        "enabled": observe_optional(item, "GetClipEnabled"),
        "media_pool_item": media_pool_item_observation,
    }


def capture_track_group(timeline: Any, track_type: str, *, required: bool) -> dict[str, Any]:
    count_observation = observe_optional(timeline, "GetTrackCount", track_type)
    if count_observation["status"] != "observed":
        if required:
            raise SnapshotError(
                "track_count_unavailable",
                f"Required track count could not be observed: {track_type}",
                details={"observation": count_observation},
            )
        return {
            "status": "unavailable",
            "track_type": track_type,
            "count": count_observation,
            "tracks": [],
        }

    count = require_nonnegative_int(
        count_observation["value"], f"{track_type} track count"
    )
    tracks: list[dict[str, Any]] = []
    for track_index in range(1, count + 1):
        raw_items = call_required(timeline, "GetItemListInTrack", track_type, track_index)
        items = require_collection(
            raw_items,
            f"{track_type} track {track_index} item list",
            false_means_empty=True,
        )
        normalized_items: list[dict[str, Any]] = []
        for item_index, item in enumerate(items):
            if not item:
                raise SnapshotError(
                    "timeline_item_handle_missing",
                    "Timeline item collection contained an unusable handle",
                    details={
                        "track_type": track_type,
                        "track_index": track_index,
                        "item_index": item_index,
                    },
                )
            normalized_items.append(
                capture_timeline_item(
                    item,
                    track_type=track_type,
                    track_index=track_index,
                    item_index=item_index,
                )
            )
        tracks.append(
            {
                "track_index": track_index,
                "item_count": len(normalized_items),
                "items": normalized_items,
            }
        )
    return {
        "status": "observed",
        "track_type": track_type,
        "count": count_observation,
        "tracks": tracks,
    }


def capture_timeline(timeline: Any) -> dict[str, Any]:
    tracks: dict[str, Any] = {}
    for track_type in TRACK_TYPES_REQUIRED:
        tracks[track_type] = capture_track_group(timeline, track_type, required=True)
    for track_type in TRACK_TYPES_OPTIONAL:
        tracks[track_type] = capture_track_group(timeline, track_type, required=False)

    return {
        "name": _timeline_name(timeline, "target timeline name"),
        "unique_id": observe_optional(timeline, "GetUniqueId"),
        "start_frame": observe_optional(timeline, "GetStartFrame"),
        "end_frame": observe_optional(timeline, "GetEndFrame"),
        "start_timecode": observe_optional(timeline, "GetStartTimecode"),
        "settings": observe_optional(timeline, "GetSetting"),
        "markers": observe_optional(timeline, "GetMarkers"),
        "tracks": tracks,
    }


def capture_render_presets(project: Any) -> dict[str, Any]:
    primary = observe_optional(project, "GetRenderPresetList")
    if primary["status"] == "observed":
        return primary
    fallback = observe_optional(project, "GetRenderPresetNames")
    if fallback["status"] == "observed":
        return fallback
    return {
        "source_method": "GetRenderPresetList|GetRenderPresetNames",
        "status": "unavailable",
        "value_type": None,
        "value": None,
        "error": {
            "type": "RenderPresetInventoryUnavailable",
            "primary": primary,
            "fallback": fallback,
        },
    }


def capture_render_context(project: Any) -> dict[str, Any]:
    return {
        "format_and_codec": observe_optional(project, "GetCurrentRenderFormatAndCodec"),
        "render_mode": observe_optional(project, "GetCurrentRenderMode"),
        "render_settings": observe_optional(project, "GetRenderSettings"),
    }


def capture_guard_state(project: Any, target_timeline: Any) -> dict[str, Any]:
    project_name = require_nonempty_string(call_required(project, "GetName"), "project name")
    timeline_count = require_nonnegative_int(
        call_required(project, "GetTimelineCount"), "timeline count"
    )
    current_timeline = call_required(project, "GetCurrentTimeline")
    if not current_timeline:
        raise SnapshotError("current_timeline_missing", "Resolve has no current timeline")
    current_timeline_name = _timeline_name(current_timeline, "current timeline name")
    target_timeline_name = _timeline_name(target_timeline, "target timeline name")

    rendering = call_required(project, "IsRenderingInProgress")
    if not isinstance(rendering, bool):
        raise SnapshotError(
            "invalid_rendering_state",
            "IsRenderingInProgress() did not return a boolean",
            details={"value_type": type(rendering).__name__},
        )

    queue = queue_inventory(call_required(project, "GetRenderJobList"))
    return {
        "project_name": project_name,
        "timeline_count": timeline_count,
        "current_timeline_name": current_timeline_name,
        "target_timeline_name": target_timeline_name,
        "rendering_in_progress": rendering,
        "queue_count": queue["count"],
        "queue_fingerprint": queue["items"],
    }


def enforce_safe_guard_state(state: Mapping[str, Any], context: SnapshotContext) -> None:
    if state.get("project_name") != context.expected_project:
        raise SnapshotError(
            "project_identity_mismatch",
            "Current Resolve project does not match the expected project",
            details={
                "expected": context.expected_project,
                "actual": state.get("project_name"),
            },
        )
    if state.get("current_timeline_name") != context.expected_timeline:
        raise SnapshotError(
            "current_timeline_mismatch",
            "Current Resolve timeline does not match the expected timeline",
            details={
                "expected": context.expected_timeline,
                "actual": state.get("current_timeline_name"),
            },
        )
    if state.get("target_timeline_name") != context.expected_timeline:
        raise SnapshotError(
            "target_timeline_mismatch",
            "Selected target timeline no longer matches the expected timeline",
        )
    if state.get("rendering_in_progress") is not False:
        raise SnapshotError(
            "rendering_active",
            "Resolve reports rendering in progress; snapshot collection is prohibited",
        )
    if state.get("queue_count") != 0:
        raise SnapshotError(
            "render_queue_not_empty",
            "Resolve render queue must be empty for this comparison snapshot",
            details={"queue_count": state.get("queue_count")},
        )


def collect_snapshot(resolve: Any, context: SnapshotContext) -> dict[str, Any]:
    """Collect one fail-closed snapshot from an injected Resolve handle.

    This function does not import the Resolve module. Production use is not
    authorized by this construction mission; mocked unit tests may inject fake
    handles to exercise the logic.
    """

    if not context.expected_project.strip() or not context.expected_timeline.strip():
        raise SnapshotError(
            "invalid_expected_context",
            "Expected project and timeline names must be non-empty strings",
        )

    session = capture_session(resolve)
    project_manager = call_required(resolve, "GetProjectManager")
    if not project_manager:
        raise SnapshotError(
            "project_manager_missing", "Resolve returned no usable project manager"
        )
    project = call_required(project_manager, "GetCurrentProject")
    if not project:
        raise SnapshotError("current_project_missing", "Resolve has no current project")

    project_name = require_nonempty_string(call_required(project, "GetName"), "project name")
    if project_name != context.expected_project:
        raise SnapshotError(
            "project_identity_mismatch",
            "Current Resolve project does not match the expected project",
            details={"expected": context.expected_project, "actual": project_name},
        )

    timeline_inventory, timeline_handles = enumerate_timelines(project)
    target_timeline = select_expected_timeline(
        project,
        context.expected_timeline,
        timeline_inventory,
        timeline_handles,
    )

    pre_guard = capture_guard_state(project, target_timeline)
    enforce_safe_guard_state(pre_guard, context)

    project_payload = {
        "name": project_name,
        "settings": observe_optional(project, "GetSetting"),
        "timeline_count": pre_guard["timeline_count"],
        "timeline_inventory": timeline_inventory,
        "render_presets": capture_render_presets(project),
        "render_queue": {
            "count": pre_guard["queue_count"],
            "items": pre_guard["queue_fingerprint"],
        },
        "current_render_context": capture_render_context(project),
    }
    target_timeline_payload = capture_timeline(target_timeline)
    media_pool_payload = capture_media_pool(project)
    project_manager_payload = capture_project_manager(project_manager)
    post_session = capture_session(resolve)

    post_guard = capture_guard_state(project, target_timeline)
    enforce_safe_guard_state(post_guard, context)
    if post_guard != pre_guard:
        raise SnapshotError(
            "snapshot_identity_drift",
            "Project, timeline, rendering, or queue state changed during snapshot collection",
            details={"before": pre_guard, "after": post_guard},
        )
    if post_session != session:
        raise SnapshotError(
            "resolve_session_drift",
            "Resolve product or version identity changed during snapshot collection",
            details={"before": session, "after": post_session},
        )

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "mission": MISSION,
        "captured_at": utc_now(),
        "snapshot_complete": True,
        "expected_context": {
            "project": context.expected_project,
            "timeline": context.expected_timeline,
        },
        "session": session,
        "project_manager": project_manager_payload,
        "project": project_payload,
        "target_timeline": target_timeline_payload,
        "media_pool": media_pool_payload,
        "pre_guard": pre_guard,
        "post_guard": post_guard,
        "ambiguity_policy": {
            "difference_is_not_causation": True,
            "equality_does_not_rule_out_hidden_state": True,
            "current_render_context_is_context_sensitive": True,
            "partial_required_inventory_fails_closed": True,
        },
    }
    return normalize_json_value(snapshot)


def _observation_status(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("status") in {"observed", "unavailable", "error"}:
        return str(value["status"])
    return None


def _is_context_sensitive(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in CONTEXT_SENSITIVE_PREFIXES)


def classify_leaf(path: str, control: Any, production: Any) -> str:
    control_status = _observation_status(control)
    production_status = _observation_status(production)

    if control_status == "error" or production_status == "error":
        return "structurally_invalid"
    if control_status == "unavailable" and production_status == "unavailable":
        return "unavailable_on_both"
    if control_status == "unavailable":
        return "unavailable_on_control"
    if production_status == "unavailable":
        return "unavailable_on_production"

    if control == production:
        return "equal"
    if _is_context_sensitive(path):
        return "context_sensitive"
    return "different"


def _compare_recursive(path: str, control: Any, production: Any, records: list[ComparisonRecord]) -> None:
    if isinstance(control, dict) and isinstance(production, dict):
        control_observation = _observation_status(control)
        production_observation = _observation_status(production)
        if control_observation is not None or production_observation is not None:
            records.append(
                ComparisonRecord(
                    path=path,
                    classification=classify_leaf(path, control, production),
                    control=control,
                    production=production,
                )
            )
            return
        keys = sorted(set(control) | set(production))
        for key in keys:
            child_path = f"{path}/{key}"
            if key not in control:
                records.append(
                    ComparisonRecord(
                        path=child_path,
                        classification=(
                            "context_sensitive" if _is_context_sensitive(child_path) else "different"
                        ),
                        control={"missing": True},
                        production=production[key],
                    )
                )
            elif key not in production:
                records.append(
                    ComparisonRecord(
                        path=child_path,
                        classification=(
                            "context_sensitive" if _is_context_sensitive(child_path) else "different"
                        ),
                        control=control[key],
                        production={"missing": True},
                    )
                )
            else:
                _compare_recursive(child_path, control[key], production[key], records)
        return

    if isinstance(control, list) and isinstance(production, list):
        max_length = max(len(control), len(production))
        for index in range(max_length):
            child_path = f"{path}/{index}"
            if index >= len(control):
                records.append(
                    ComparisonRecord(
                        path=child_path,
                        classification=(
                            "context_sensitive" if _is_context_sensitive(child_path) else "different"
                        ),
                        control={"missing": True},
                        production=production[index],
                    )
                )
            elif index >= len(production):
                records.append(
                    ComparisonRecord(
                        path=child_path,
                        classification=(
                            "context_sensitive" if _is_context_sensitive(child_path) else "different"
                        ),
                        control=control[index],
                        production={"missing": True},
                    )
                )
            else:
                _compare_recursive(child_path, control[index], production[index], records)
        return

    records.append(
        ComparisonRecord(
            path=path,
            classification=classify_leaf(path, control, production),
            control=control,
            production=production,
        )
    )


def validate_snapshot_document(snapshot: Any, label: str) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise SnapshotError(
            "invalid_snapshot_document",
            f"{label} snapshot must be a JSON object",
        )
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError(
            "snapshot_schema_mismatch",
            f"{label} snapshot schema version does not match",
            details={"expected": SCHEMA_VERSION, "actual": snapshot.get("schema_version")},
        )
    if snapshot.get("snapshot_complete") is not True:
        raise SnapshotError(
            "incomplete_snapshot",
            f"{label} snapshot is not marked complete",
        )
    required = {
        "expected_context",
        "session",
        "project_manager",
        "project",
        "target_timeline",
        "media_pool",
        "pre_guard",
        "post_guard",
    }
    missing = sorted(required - set(snapshot))
    if missing:
        raise SnapshotError(
            "snapshot_missing_sections",
            f"{label} snapshot is missing required sections",
            details={"missing": missing},
        )
    return snapshot


def _version_identity(snapshot: Mapping[str, Any]) -> Any:
    session = snapshot.get("session")
    if not isinstance(session, dict):
        return None
    version_string = session.get("version_string")
    if isinstance(version_string, dict) and version_string.get("status") == "observed":
        return version_string.get("value")
    version = session.get("version")
    if isinstance(version, dict) and version.get("status") == "observed":
        return version.get("value")
    return None


def _comparison_projection(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize expected identity labels before property comparison."""

    projected = copy.deepcopy(dict(snapshot))
    expected = projected.get("expected_context")
    expected_project = expected.get("project") if isinstance(expected, dict) else None
    expected_timeline = expected.get("timeline") if isinstance(expected, dict) else None

    project = projected.get("project")
    if isinstance(project, dict):
        if project.get("name") == expected_project:
            project["name"] = "<expected-project>"
        inventory = project.get("timeline_inventory")
        if isinstance(inventory, list):
            for item in inventory:
                if isinstance(item, dict) and item.get("name") == expected_timeline:
                    item["name"] = "<expected-timeline>"

    target_timeline = projected.get("target_timeline")
    if isinstance(target_timeline, dict) and target_timeline.get("name") == expected_timeline:
        target_timeline["name"] = "<expected-timeline>"
    return projected


def compare_snapshots(control: Any, production: Any) -> dict[str, Any]:
    control_doc = validate_snapshot_document(control, "control")
    production_doc = validate_snapshot_document(production, "production")

    control_version = _version_identity(control_doc)
    production_version = _version_identity(production_doc)
    if control_version is None or production_version is None or control_version != production_version:
        return {
            "schema_version": SCHEMA_VERSION,
            "mission": MISSION,
            "compared_at": utc_now(),
            "comparison_complete": False,
            "overall_classification": "incomparable",
            "reason": "Resolve version identity is missing or differs between snapshots",
            "control_version": control_version,
            "production_version": production_version,
            "records": [],
        }

    control_projection = _comparison_projection(control_doc)
    production_projection = _comparison_projection(production_doc)
    excluded_root_fields = {"captured_at", "expected_context", "pre_guard", "post_guard"}
    records: list[ComparisonRecord] = []
    for key in sorted((set(control_projection) | set(production_projection)) - excluded_root_fields):
        if key not in control_projection or key not in production_projection:
            _compare_recursive(
                f"/{key}",
                control_projection.get(key, {"missing": True}),
                production_projection.get(key, {"missing": True}),
                records,
            )
        else:
            _compare_recursive(
                f"/{key}", control_projection[key], production_projection[key], records
            )

    counts: dict[str, int] = {}
    for record in records:
        counts[record.classification] = counts.get(record.classification, 0) + 1

    if counts.get("structurally_invalid", 0):
        overall_classification = "ambiguous_due_to_structural_errors"
    elif counts.get("different", 0):
        overall_classification = "differences_observed"
    elif any(
        counts.get(name, 0)
        for name in (
            "unavailable_on_control",
            "unavailable_on_production",
            "unavailable_on_both",
        )
    ):
        overall_classification = "no_exposed_intrinsic_difference_observed_with_gaps"
    else:
        overall_classification = "no_exposed_intrinsic_difference_observed"

    return {
        "schema_version": SCHEMA_VERSION,
        "mission": MISSION,
        "compared_at": utc_now(),
        "comparison_complete": True,
        "overall_classification": overall_classification,
        "control_context": control_doc["expected_context"],
        "production_context": production_doc["expected_context"],
        "resolve_version": control_version,
        "classification_counts": counts,
        "records": [record.to_dict() for record in records],
        "interpretation_limits": [
            "Differences are candidate discriminators, not proven causes.",
            "Equality does not rule out hidden Resolve state.",
            "Context-sensitive render observations are not intrinsic project identity.",
            "This comparison does not authorize repair or a mutating experiment.",
        ],
    }


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(
            "json_load_failed",
            f"Could not load JSON evidence file: {path}",
            details={"error_type": type(exc).__name__},
        ) from exc


def enforce_execution_interlock(supplied: str | None) -> None:
    """Deliberate execution interlock for live Resolve contact.

    Not authentication and not a secret: it exists so an operator cannot
    reach Resolve by omission or typo, not to resist an adversary. Must be
    called, and must pass, before output-path validation, before
    ``DaVinciResolveScript`` import, before Resolve connection, before output
    creation, and before any snapshot collection. The supplied value is never
    included in a raised error's message or details.
    """

    if supplied is None or supplied == "":
        raise SnapshotError(
            "live_execution_authorization_missing",
            "Live execution requires --execution-authorization naming this "
            "exact source revision",
        )
    # No .strip() or other normalization: the supplied value is checked
    # byte-for-byte. A value that is whitespace-only, or that carries
    # leading/trailing whitespace, fails EXECUTION_REVISION_ID_PATTERN (its
    # first and last characters must be alphanumeric) and is therefore
    # reported as malformed, never silently trimmed and accepted.
    if not EXECUTION_REVISION_ID_PATTERN.fullmatch(supplied):
        raise SnapshotError(
            "live_execution_authorization_invalid",
            "Execution authorization value is not a well-formed revision identifier",
        )
    if supplied != EXECUTION_REVISION_ID:
        raise SnapshotError(
            "live_execution_revision_mismatch",
            "Execution authorization does not match this source revision's identifier",
        )


def validate_output_path(path: Path) -> None:
    """Fail closed on any pre-existing output path, before Resolve contact.

    Policy: the parent directory must already exist. This function never
    creates a directory. Auto-creating filesystem paths before Resolve is
    even contacted is an avoidable mutation this probe chooses not to make;
    an operator preparing an evidence directory is expected to create it
    first (the proposed runbook does this as an explicit, logged step).
    """

    if path.exists():
        if path.is_dir():
            raise SnapshotError(
                "output_path_is_directory",
                f"Output path is an existing directory, not a file: {path}",
            )
        raise SnapshotError(
            "output_path_already_exists",
            f"Output path already exists and will not be overwritten: {path}",
        )
    if not path.parent.is_dir():
        raise SnapshotError(
            "output_parent_directory_missing",
            f"Output parent directory does not exist: {path.parent}",
        )


def write_json_no_overwrite(path: Path, value: Any) -> None:
    """Write ``value`` as JSON to ``path`` without ever overwriting it.

    The complete JSON text is serialized in memory first, so a serialization
    failure never touches disk. An OS-backed exclusive-create temporary file
    (``tempfile.mkstemp``, same directory as ``path`` so both paths are on
    the same filesystem) receives the text, which is flushed and fsynced
    before publication. Publication is a create-only atomic link (``os.link``
    raises ``FileExistsError`` if the destination exists on both Windows and
    POSIX, unlike a plain rename, which silently replaces on POSIX). Cleanup
    of the temporary file is attempted in every case, but a cleanup failure
    is never swallowed: it is raised as its own structured error, and if
    publication had already succeeded, that success is preserved (the
    completed final output is never deleted and success is never reported
    for a run whose temp file could not be removed).
    """

    normalized = normalize_json_value(value)
    text = json.dumps(normalized, indent=2, sort_keys=True) + "\n"
    json.loads(text)  # Validate completeness before any disk write.

    validate_output_path(path)

    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.tmp-", suffix="", dir=str(path.parent)
        )
    except OSError as exc:
        raise SnapshotError(
            "output_temp_create_failed",
            "Could not create an exclusive temporary output file",
            details={"error_type": type(exc).__name__},
        ) from exc

    tmp_path = Path(tmp_name)
    published = False
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise SnapshotError(
                "output_write_failed",
                "Could not write and fsync the temporary output file",
                details={"error_type": type(exc).__name__, "published": False},
            ) from exc

        try:
            os.link(tmp_path, path)
            published = True
        except FileExistsError as exc:
            raise SnapshotError(
                "output_path_already_exists",
                f"Output path already exists and will not be overwritten: {path}",
                details={"published": False},
            ) from exc
        except OSError as exc:
            raise SnapshotError(
                "output_publish_failed",
                "Could not publish the temporary output file to its final path",
                details={"error_type": type(exc).__name__, "published": False},
            ) from exc
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as exc:
            raise SnapshotError(
                "output_temp_cleanup_failed",
                (
                    "Output was published but its temporary file could not be "
                    "removed"
                    if published
                    else "Temporary output file could not be removed after a "
                    "failed write"
                ),
                details={"error_type": type(exc).__name__, "published": published},
            ) from exc


def connect_resolve_read_only(
    importer: Callable[[str], Any] = importlib.import_module,
) -> Any:
    """Import and connect to Resolve only after a future live contract enables it.

    Every exception this function can raise is a structured ``SnapshotError``
    with only a safe exception-type name in its details — never raw exception
    text, a local path, or an authorization value — so a controlled import or
    connection failure cannot escape ``main()`` as an uncaught traceback.
    """

    try:
        module = importer("DaVinciResolveScript")
    except Exception as exc:
        raise SnapshotError(
            "resolve_module_import_failed",
            "Importing DaVinciResolveScript raised",
            details={"error_type": type(exc).__name__},
        ) from exc

    scriptapp = getattr(module, "scriptapp", None)
    if not callable(scriptapp):
        raise SnapshotError(
            "resolve_scriptapp_unavailable",
            "DaVinciResolveScript.scriptapp is unavailable",
        )

    try:
        resolve = scriptapp("Resolve")
    except Exception as exc:
        raise SnapshotError(
            "resolve_scriptapp_call_failed",
            "DaVinciResolveScript.scriptapp('Resolve') raised",
            details={"error_type": type(exc).__name__},
        ) from exc

    if not resolve:
        raise SnapshotError(
            "resolve_connection_failed",
            "DaVinciResolveScript.scriptapp('Resolve') returned no usable handle",
        )
    return resolve


def run_snapshot_command(args: argparse.Namespace) -> int:
    # These two checks must remain, in this order, before connect_resolve_read_only().
    enforce_execution_interlock(args.execution_authorization)
    validate_output_path(args.output)
    resolve = connect_resolve_read_only()
    snapshot = collect_snapshot(
        resolve,
        SnapshotContext(
            expected_project=args.expected_project,
            expected_timeline=args.expected_timeline,
        ),
    )
    write_json_no_overwrite(args.output, snapshot)
    return 0


def run_compare_command(args: argparse.Namespace) -> int:
    control = load_json(args.control)
    production = load_json(args.production)
    comparison = compare_snapshots(control, production)
    write_json_no_overwrite(args.output, comparison)
    return 0 if comparison.get("comparison_complete") is True else 3


# ---------------------------------------------------------------------------
# Phase 14.1 rev4: authorization-manifest validation.
#
# Windows PowerShell 5.1's ConvertFrom-Json silently resolves duplicate JSON
# object keys to the last value, at any depth, with no warning. This module
# is the single implementation of duplicate-key-safe, exact-schema manifest
# validation: it is exercised directly by the test suite (import and call)
# and invoked as a subprocess by the proposed PowerShell runbook via the
# `validate-manifest` command below, reading raw bytes from stdin so both
# consumers share exactly one code path rather than two independently
# maintained ones. This never imports or contacts Resolve, and never
# accesses SQLite.
# ---------------------------------------------------------------------------

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_REQUIRED_TOP_FIELDS = frozenset(
    {
        "schema_version",
        "mission",
        "repository_root",
        "origin_url",
        "authorized_commit",
        "execution_revision_id",
        "probe_sha256",
        "test_sha256",
        "contract_sha256",
        "runbook_sha256",
        "resolve_product_version",
        "contexts",
    }
)
MANIFEST_STRING_FIELDS = (
    "mission",
    "repository_root",
    "origin_url",
    "authorized_commit",
    "execution_revision_id",
    "probe_sha256",
    "test_sha256",
    "contract_sha256",
    "runbook_sha256",
    "resolve_product_version",
)
MANIFEST_REQUIRED_CONTEXT_NAMES = frozenset({"Control", "Production"})
MANIFEST_REQUIRED_CONTEXT_FIELDS = frozenset({"project", "timeline"})


class ManifestValidationError(RuntimeError):
    """Duplicate-key-safe manifest validation failure with a stable code.

    The code never contains manifest field *values* -- only, at most, a
    known schema field *name* -- so it is always safe to print or log.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ManifestValidationError("manifest_duplicate_key")
        seen.add(key)
        result[key] = value
    return result


def validate_authorization_manifest_bytes(raw: bytes) -> dict[str, Any]:
    """Validate one exact byte sequence as a Phase 14.1 authorization manifest.

    Raises ``ManifestValidationError`` with a stable ``code`` on any
    violation: invalid UTF-8, invalid JSON, a duplicate object key at any
    depth, a non-object root, a top-level field set that is not exactly the
    required set, a ``schema_version`` that is not the literal integer ``1``
    (a JSON boolean is rejected even though Python's ``bool`` is an ``int``
    subclass), a non-string value for any field required to be a string, a
    ``contexts`` object whose keys are not exactly ``Control``/``Production``,
    or a context object whose keys are not exactly ``project``/``timeline``
    with string values. Never imports or contacts Resolve; never touches
    SQLite.
    """

    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ManifestValidationError("manifest_not_utf8") from exc

    try:
        document = json.loads(text, object_pairs_hook=_reject_duplicate_object_keys)
    except ManifestValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise ManifestValidationError("manifest_not_valid_json") from exc

    if not isinstance(document, dict):
        raise ManifestValidationError("manifest_root_not_object")

    if set(document.keys()) != MANIFEST_REQUIRED_TOP_FIELDS:
        raise ManifestValidationError("manifest_unexpected_top_level_fields")

    schema_version = document.get("schema_version")
    if type(schema_version) is not int or schema_version != MANIFEST_SCHEMA_VERSION:
        raise ManifestValidationError("manifest_schema_version_invalid")

    for field in MANIFEST_STRING_FIELDS:
        if type(document.get(field)) is not str:
            raise ManifestValidationError(f"manifest_field_not_string:{field}")

    contexts = document.get("contexts")
    if not isinstance(contexts, dict) or set(contexts.keys()) != MANIFEST_REQUIRED_CONTEXT_NAMES:
        raise ManifestValidationError("manifest_contexts_invalid")

    for context_name in MANIFEST_REQUIRED_CONTEXT_NAMES:
        context = contexts[context_name]
        if not isinstance(context, dict) or set(context.keys()) != MANIFEST_REQUIRED_CONTEXT_FIELDS:
            raise ManifestValidationError("manifest_context_fields_invalid")
        if (
            type(context.get("project")) is not str
            or type(context.get("timeline")) is not str
        ):
            raise ManifestValidationError("manifest_context_field_not_string")

    return document


def _emit_manifest_validation_result(raw: bytes) -> int:
    """Validate one exact byte sequence and emit the stable CLI result."""

    try:
        document = validate_authorization_manifest_bytes(raw)
    except ManifestValidationError as exc:
        print(json.dumps({"valid": False, "code": exc.code}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"valid": True, "manifest": document}, sort_keys=True))
    return 0


def run_validate_manifest_command() -> int:
    """Read manifest bytes from stdin exactly once and validate them.

    Retained for offline tooling and direct tests. The Windows PowerShell 5.1
    runbook uses ``validate-manifest-base64`` instead, because the target
    .NET Framework runtime lacks the modern byte-oriented stdin and
    per-argument APIs required for an unambiguous raw-byte subprocess pipe.
    Never imports or contacts Resolve; never accesses SQLite.
    """

    return _emit_manifest_validation_result(sys.stdin.buffer.read())


def run_validate_manifest_base64_command(encoded: str) -> int:
    """Decode canonical Base64 argv transport and validate the exact bytes.

    Base64 is ASCII-only and is passed through the Rev7 Windows CRT argv
    encoder. Strict decoding rejects whitespace, missing/extra characters,
    and non-Base64 input. The decoded byte sequence is passed unchanged to
    the same duplicate-key-safe validator used by the stdin command.
    Never imports or contacts Resolve; never accesses SQLite.
    """

    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        print(
            json.dumps({"valid": False, "code": "manifest_base64_invalid"}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    return _emit_manifest_validation_result(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=MISSION)
    parser.add_argument(
        "--print-sha256",
        action="store_true",
        help="Print the source SHA-256 and exit without Resolve contact.",
    )
    subparsers = parser.add_subparsers(dest="command")

    snapshot = subparsers.add_parser(
        "snapshot",
        help=(
            "Fail-closed by default. Requires --execution-authorization naming "
            "the exact source revision identifier to reach Resolve."
        ),
    )
    snapshot.add_argument("--expected-project", required=True)
    snapshot.add_argument("--expected-timeline", required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument(
        "--execution-authorization",
        required=False,
        default=None,
        help=(
            "Deliberate execution interlock, not a credential: must exactly equal "
            "this source revision's EXECUTION_REVISION_ID. Missing, malformed, or "
            "mismatched values stop before any Resolve import or connection."
        ),
    )

    compare = subparsers.add_parser(
        "compare", help="Compare two completed snapshot JSON files offline."
    )
    compare.add_argument("--control", type=Path, required=True)
    compare.add_argument("--production", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)

    subparsers.add_parser(
        "validate-manifest",
        help=(
            "Duplicate-key-safe, exact-schema validation of an authorization "
            "manifest's raw bytes, read from stdin. Never contacts Resolve."
        ),
    )

    validate_manifest_base64 = subparsers.add_parser(
        "validate-manifest-base64",
        help=(
            "Duplicate-key-safe, exact-schema validation of authorization "
            "manifest bytes transported as strict Base64 argv text. Never "
            "contacts Resolve."
        ),
    )
    validate_manifest_base64.add_argument("payload")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.print_sha256:
        print(script_sha256())
        return 0
    if args.command is None:
        parser.error("a command is required unless --print-sha256 is used")
    try:
        if args.command == "snapshot":
            return run_snapshot_command(args)
        if args.command == "compare":
            return run_compare_command(args)
        if args.command == "validate-manifest":
            return run_validate_manifest_command()
        if args.command == "validate-manifest-base64":
            return run_validate_manifest_base64_command(args.payload)
        raise SnapshotError("unsupported_command", f"Unsupported command: {args.command}")
    except SnapshotError as exc:
        print(json.dumps({"result": "stopped", "error": exc.to_dict()}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
