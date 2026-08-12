"""Archive Rev1 restore-metadata snapshots (Phase 15 Mission 15G).

Four small, canonical JSON snapshots that help a future restore/audit
implementation answer: what episode was this, which render produced the
master, what Redline configuration shaped this package, and what
software/runtime produced it. Every snapshot is generated restore
metadata, not identity-bearing preservation content -- see
`redline_core.archive.supplement`'s module docstring for why these never
influence `content_set_digest`/`archive_id`.

Every builder here is a pure function of its already-resolved inputs: no
DB read, no config load, no filesystem access, no clock, no environment
inspection. `ArchiveManager` snapshots its own already-loaded `Episode`/
`RenderJob`/`RedlineConfig` once, at orchestration time, and calls these
functions -- so a second, concurrent authoritative read can never observe
a different value mid-package-construction (Mission 15G item 37).
`resolve_software_identity()` is the one exception (it reads
`sys`/`platform`/package metadata), kept as a separate, thin, non-pure
function so `build_software_snapshot()` itself stays a pure, directly
testable function of explicit arguments.

No generated snapshot ever includes a newly-captured wall-clock
timestamp -- the Archive Manifest's own `created_at_utc` already records
when a package was built (Mission 15G item 21). A source record's own
already-persisted timestamps (`Episode.created_at`, `RenderJob.updated_at`,
etc.) are preserved unchanged; they are genuine provenance, not a
freshly-captured one.
"""
from __future__ import annotations

import json
import platform
import sys
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from redline_core.config.schema import RedlineConfig
    from redline_core.db.models import Episode, RenderJob

_METADATA_SCHEMA_VERSION = 1
_DISTRIBUTION_NAME = "redline-os"

_SECRET_FIELD_KEYWORDS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "auth",
)


class ConfigSnapshotSecretFieldError(ValueError):
    """`RedlineConfig` (or a nested model) declared a field whose name
    matches a known secret-bearing keyword. `build_config_snapshot()`
    fails closed rather than archive it -- see the module docstring and
    Mission 15G item 17. This is a structural repository-schema defect,
    not a per-archive user-facing failure, so it does not subclass
    `ArchiveError`."""


def _canonical_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _assert_no_secret_bearing_fields(model_cls: type[BaseModel], *, _seen: frozenset[type] = frozenset()) -> None:
    """Recursively walk `model_cls`'s declared fields (and every nested
    `BaseModel` field type) and raise if any field name contains a known
    secret-bearing keyword. Runs against the *schema*, not a particular
    instance, so it also catches a field whose current value happens to
    be empty/default. `_seen` guards against infinite recursion through a
    self-referential model (none exist today; defensive)."""
    if model_cls in _seen:
        return
    _seen = _seen | {model_cls}

    for field_name, field_info in model_cls.model_fields.items():
        lowered = field_name.lower()
        if any(keyword in lowered for keyword in _SECRET_FIELD_KEYWORDS):
            raise ConfigSnapshotSecretFieldError(
                f"{model_cls.__name__}.{field_name} matches a secret-bearing field keyword; "
                "config_snapshot.json generation refuses to serialize it. Add it to an explicit "
                "restoration-relevant allowlist only after confirming it is not sensitive."
            )
        for candidate in _unwrap_annotation(field_info.annotation):
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                _assert_no_secret_bearing_fields(candidate, _seen=_seen)


def _unwrap_annotation(annotation: object) -> list[object]:
    """Return every type nested inside a (possibly `list[...]`/`| None`/
    generic) field annotation, shallowly -- enough to find a nested
    `BaseModel` inside `list[SomeModel]` or `SomeModel | None` without a
    full typing-introspection library."""
    args = getattr(annotation, "__args__", None)
    if args:
        found: list[object] = []
        for arg in args:
            found.extend(_unwrap_annotation(arg))
        return found
    return [annotation]


# -- episode ------------------------------------------------------------------


def build_episode_snapshot(episode: "Episode") -> dict:
    """Canonical `payload/metadata/episode.json` content.

    Deliberately omits `Episode.id` -- the internal SQLite surrogate row
    key, not restoration-relevant and not stable across a relocated/
    restored database; `episode_id` (the Universe-project-defined,
    human-meaningful identity) is the authoritative identifier preserved
    here. Every other persisted `Episode` field is included unchanged,
    including its own genuine timestamps.

    Snapshotted immediately before package construction (see
    `ArchiveManager`), so `status` is expected to read `"rendered"` --
    the DB transition to `"archived"` happens only after this package is
    already sealed (Mission 15G item 14).
    """
    return {
        "assembly_claim_token": episode.assembly_claim_token,
        "assembly_claimed_at": episode.assembly_claimed_at,
        "created_at": episode.created_at,
        "episode_id": episode.episode_id,
        "episode_number": episode.episode_number,
        "folder_path": episode.folder_path,
        "project_name": episode.project_name,
        "project_path": episode.project_path,
        "schema_version": _METADATA_SCHEMA_VERSION,
        "snapshot_kind": "episode",
        "status": episode.status.value,
        "updated_at": episode.updated_at,
    }


def build_episode_snapshot_bytes(episode: "Episode") -> bytes:
    return _canonical_json_bytes(build_episode_snapshot(episode))


# -- render job -----------------------------------------------------------------


def build_render_job_snapshot(render_job: "RenderJob") -> dict:
    """Canonical `payload/metadata/render_job.json` content for the
    selected render job. `RenderJob.id` is renamed to `render_job_id`
    (real data, clarified for a standalone restore-metadata document that
    has no surrounding SQLite context to imply what a bare `id` means)."""
    return {
        "created_at": render_job.created_at,
        "episode_id": render_job.episode_id,
        "output_path": render_job.output_path,
        "preset_name": render_job.preset_name,
        "project_name": render_job.project_name,
        "render_job_id": render_job.id,
        "resolve_job_id": render_job.resolve_job_id,
        "schema_version": _METADATA_SCHEMA_VERSION,
        "snapshot_kind": "render_job",
        "status": render_job.status.value,
        "timeline_name": render_job.timeline_name,
        "updated_at": render_job.updated_at,
    }


def build_render_job_snapshot_bytes(render_job: "RenderJob") -> bytes:
    return _canonical_json_bytes(build_render_job_snapshot(render_job))


# -- configuration ----------------------------------------------------------------


def build_config_snapshot(config: "RedlineConfig") -> dict:
    """Canonical `payload/metadata/config_snapshot.json` content: the
    complete effective `RedlineConfig`, via its own canonical
    `model_dump(mode="json")` serialization (Pydantic's stable public
    API) -- never a hand-maintained parallel schema, and never a broad
    `vars()`/`dataclasses.asdict()`-style dump.

    Fails closed (`ConfigSnapshotSecretFieldError`) before serializing
    anything if `RedlineConfig` (or any nested model) declares a field
    whose name matches a known secret-bearing keyword. `RedlineConfig` as
    it exists today (naming, folder_structure, render_presets, paths,
    assets, timeline) declares no such field -- this is a structural
    guard against a *future* config field being archived by accident, not
    evidence that one exists now. Absolute paths in `paths`/
    `folder_structure` are intentionally included: supplemental
    provenance metadata, not part of any package identity (Mission 15G
    item 18) -- restoring a relocated archive elsewhere does not change
    `content_set_digest`/`archive_id`.
    """
    _assert_no_secret_bearing_fields(type(config))
    return {
        "config": config.model_dump(mode="json"),
        "schema_version": _METADATA_SCHEMA_VERSION,
        "snapshot_kind": "config",
    }


def build_config_snapshot_bytes(config: "RedlineConfig") -> bytes:
    return _canonical_json_bytes(build_config_snapshot(config))


# -- software identity --------------------------------------------------------------


def resolve_software_identity() -> dict[str, object]:
    """Resolve the current process's software/runtime identity from
    stable, supported, network/subprocess-free sources only:
    `importlib.metadata` for the installed `redline-os` distribution
    version, `sys.version_info` for the Python runtime, and `platform`
    for OS identity. Never contacts Resolve, never shells out to `git`
    (no supported repository-revision discovery helper exists anywhere
    in this repository today -- see Mission 15G's report), and never
    requires network access. Kept separate from `build_software_snapshot()`
    so that function stays a pure, directly testable function of explicit
    arguments (Mission 15G item 41's dependency-injection seam)."""
    try:
        redline_os_version = importlib_metadata.version(_DISTRIBUTION_NAME)
    except importlib_metadata.PackageNotFoundError:
        redline_os_version = None

    version_info = sys.version_info
    return {
        "platform_machine": platform.machine(),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
        "python_version": f"{version_info.major}.{version_info.minor}.{version_info.micro}",
        "redline_os_version": redline_os_version,
        "repository_revision": None,
    }


def build_software_snapshot(
    *,
    redline_os_version: str | None,
    repository_revision: str | None,
    python_version: str | None,
    platform_system: str | None,
    platform_release: str | None,
    platform_machine: str | None,
) -> dict:
    """Canonical `payload/metadata/software.json` content from already-
    resolved values (see `resolve_software_identity()`). A value this
    process could not reliably obtain is passed as `None` here and
    serialized as JSON `null` -- never fabricated, never omitted from the
    schema (Mission 15G item 21: explicitly null, not silently absent)."""
    return {
        "platform": {
            "machine": platform_machine,
            "release": platform_release,
            "system": platform_system,
        },
        "python_version": python_version,
        "redline_os_version": redline_os_version,
        "repository_revision": repository_revision,
        "schema_version": _METADATA_SCHEMA_VERSION,
        "snapshot_kind": "software",
    }


def build_software_snapshot_bytes(**kwargs) -> bytes:
    return _canonical_json_bytes(build_software_snapshot(**kwargs))
