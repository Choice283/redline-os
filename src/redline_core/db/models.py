"""Data models for Redline OS pipeline state.

These are plain dataclasses mirroring the SQLite schema (schema.sql) — not an
ORM. Keeping this thin is intentional: SQLite is the source of truth for
*pipeline state* only, so we don't need a heavy ORM layer for what is
fundamentally a handful of narrow tables.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EpisodeStatus(str, Enum):
    CREATED = "created"
    ASSETS_VERIFIED = "assets_verified"
    MEDIA_ORGANIZED = "media_organized"
    TIMELINE_BUILT = "timeline_built"
    ASSEMBLED = "assembled"
    RENDER_QUEUED = "render_queued"
    RENDERED = "rendered"
    ARCHIVED = "archived"
    FAILED = "failed"


class RenderJobStatus(str, Enum):
    CLAIMING = "claiming"
    QUEUED = "queued"
    RENDERING = "rendering"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Episode:
    episode_number: int
    episode_id: str
    project_name: str
    id: int | None = None
    project_path: str | None = None
    folder_path: str | None = None
    status: EpisodeStatus = EpisodeStatus.CREATED
    assembly_claim_token: str | None = None
    assembly_claimed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "Episode":
        return cls(
            id=row["id"],
            episode_number=row["episode_number"],
            episode_id=row["episode_id"],
            project_name=row["project_name"],
            project_path=row["project_path"],
            folder_path=row["folder_path"],
            status=EpisodeStatus(row["status"]),
            assembly_claim_token=row["assembly_claim_token"],
            assembly_claimed_at=row["assembly_claimed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class RenderJob:
    episode_id: str
    preset_name: str
    id: int | None = None
    resolve_job_id: str | None = None
    status: RenderJobStatus = RenderJobStatus.QUEUED
    output_path: str | None = None
    project_name: str | None = None
    timeline_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "RenderJob":
        return cls(
            id=row["id"],
            episode_id=row["episode_id"],
            preset_name=row["preset_name"],
            resolve_job_id=row["resolve_job_id"],
            status=RenderJobStatus(row["status"]),
            output_path=row["output_path"],
            project_name=row["project_name"],
            timeline_name=row["timeline_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class ArchiveState(str, Enum):
    """Committed-archive state. Phase 15 Rev1 recognizes exactly two values
    -- see docs/ARCHITECTURE.md's Archive Rev1 section for why this is
    deliberately not a broader lifecycle enum. In particular, there is no
    "verifying"/"failed"/"VERIFIED_UNREGISTERED" member: `VERIFIED_UNREGISTERED`
    (the state `ArchiveVerifiedUnregisteredError` reports) means a fully
    verified filesystem archive package was published to disk but the
    database commit that would have inserted its `archives` row failed
    afterward -- since no row was ever inserted, there is no `archive_state`
    value to hold that condition. It is an attempt/reconciliation concept
    the caller (`ArchiveManager.create_archive()`) surfaces via a typed
    exception, not a value this column ever stores; recovery for it is a
    later-mission (15H) concern, not modeled here.

    LEGACY: a pre-Rev1 archive row (archive_schema_version == 0). Written
    by `Database.create_archive_record()`, the legacy unguarded insert
    retained for compatibility/history -- no current production code path
    calls it (Phase 15 Mission 15F retired `ArchiveManager.archive_episode()`,
    its last caller); it remains as the writer synthetic-legacy-row tests
    use, and as a record of the pre-Rev1 archive-insert shape. Never
    written by `commit_verified_archive()`.

    COMPLETE: a Rev1 archive row (archive_schema_version == 1), written only
    by `Database.commit_verified_archive()` once a verified archive package
    already exists on disk. This is the only row shape
    `ArchiveManager.verify_archive()` (Phase 15 Mission 15F) will verify --
    a LEGACY row is classified and rejected (`ArchiveLegacyRecordError`)
    rather than pretended to have Rev1 manifest/hash data it does not have.
    """

    LEGACY = "legacy"
    COMPLETE = "complete"


@dataclass
class ArchiveRecord:
    episode_id: str
    archive_path: str
    id: int | None = None
    archive_id: str | None = None
    archive_schema_version: int = 0
    archive_state: ArchiveState = ArchiveState.LEGACY
    manifest_path: str | None = None
    manifest_sha256: str | None = None
    render_job_id: int | None = None
    verified_at: str | None = None
    archived_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "ArchiveRecord":
        return cls(
            id=row["id"],
            episode_id=row["episode_id"],
            archive_path=row["archive_path"],
            archive_id=row["archive_id"],
            archive_schema_version=row["archive_schema_version"],
            archive_state=ArchiveState(row["archive_state"]),
            manifest_path=row["manifest_path"],
            manifest_sha256=row["manifest_sha256"],
            render_job_id=row["render_job_id"],
            verified_at=row["verified_at"],
            archived_at=row["archived_at"],
        )
