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


@dataclass
class ArchiveRecord:
    episode_id: str
    archive_path: str
    id: int | None = None
    archived_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "ArchiveRecord":
        return cls(
            id=row["id"],
            episode_id=row["episode_id"],
            archive_path=row["archive_path"],
            archived_at=row["archived_at"],
        )
