"""Pydantic schema for Redline OS configuration.

Redline OS does NOT define naming, folder, or asset-ID conventions itself —
those belong to the Redline Universe project (Showrunner Bible, Broadcast
Package V1.0). These models only describe the *shape* Redline OS expects
that data to arrive in via YAML config files under /config. If the Universe
conventions change, only the YAML files change — not this code.
"""
from __future__ import annotations

from pathlib import Path
import re

from pydantic import BaseModel, Field, field_validator

from redline_core.render.plan import SUPPORTED_FILENAME_PLACEHOLDERS, filename_template_placeholders

_RENDER_EXTENSION_RE = re.compile(r"^\.[A-Za-z0-9]+$")


class NamingConfig(BaseModel):
    """Episode ID / filename naming convention, sourced from the Universe project."""

    episode_id_pattern: str = Field(
        ...,
        description="Python str.format pattern for episode IDs, e.g. 'RLC-E{episode_number:03d}'.",
    )
    project_name_pattern: str = Field(
        ...,
        description="Pattern for the DaVinci Resolve project name, e.g. '{episode_id}_MASTER'.",
    )

    @field_validator("episode_id_pattern", "project_name_pattern")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("naming pattern cannot be empty")
        return v


class FolderStructureConfig(BaseModel):
    """On-disk folder layout for a single episode's working directory."""

    root_path: str = Field(..., description="Base directory under which episode folders are created.")
    subfolders: list[str] = Field(
        default_factory=lambda: ["footage", "graphics", "audio", "exports", "project"],
        description="Subfolders created inside each episode's root folder.",
    )


class RenderPreset(BaseModel):
    """A single named render preset (maps to a DaVinci Resolve render preset)."""

    name: str
    resolve_preset_name: str = Field(..., description="Exact preset name as it exists in DaVinci Resolve.")
    output_subfolder: str = Field(default="exports", description="Subfolder (under the episode folder) to deliver to.")
    filename_template: str | None = Field(default=None, description="Filename stem template, without extension.")
    file_extension: str | None = Field(default=None, description="Explicit output extension, including the leading dot.")
    collision_policy: str = Field(default="reject", description="Render output collision policy.")
    requires_video_payload: bool = Field(
        default=False,
        description=(
            "If true, the renderability preflight rejects a queue request when the target "
            "timeline has zero video TimelineItems, before any SQLite claim or Resolve mutation."
        ),
    )

    @field_validator("filename_template")
    @classmethod
    def filename_template_must_be_plain_stem_template(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip():
            raise ValueError("filename_template cannot be empty")
        if Path(v).is_absolute() or Path(v).name != v or ".." in Path(v).parts:
            raise ValueError("filename_template must be a plain filename template without path separators")
        unknown = filename_template_placeholders(v) - SUPPORTED_FILENAME_PLACEHOLDERS
        if unknown:
            raise ValueError(f"filename_template contains unsupported placeholder(s): {', '.join(sorted(unknown))}")
        return v

    @field_validator("file_extension")
    @classmethod
    def file_extension_must_be_explicit(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip():
            raise ValueError("file_extension cannot be empty")
        if _RENDER_EXTENSION_RE.fullmatch(v) is None:
            raise ValueError("file_extension must include the leading dot and be a single extension segment")
        return v

    @field_validator("collision_policy")
    @classmethod
    def collision_policy_must_be_known(cls, v: str) -> str:
        normalized = v.strip().casefold()
        if normalized != "reject":
            raise ValueError("unknown render collision policy")
        return normalized


class RenderPresetsConfig(BaseModel):
    presets: list[RenderPreset] = Field(default_factory=list)

    def get(self, name: str) -> RenderPreset | None:
        return next((p for p in self.presets if p.name == name), None)


class PathsConfig(BaseModel):
    """Global filesystem paths Redline OS needs to know about."""

    ingest_path: str = Field(..., description="Where raw incoming media lands before being matched to an episode.")
    archive_path: str = Field(..., description="Where completed episode packages are moved to.")
    assets_path: str = Field(
        ..., description="Where approved graphics/assets (Asset IDs from the Universe project) live on disk."
    )
    master_project_template: str = Field(
        ..., description="Path or name of the master DaVinci Resolve project to duplicate per episode."
    )
    evidence_path: str | None = Field(
        default=None,
        description=(
            "Parent directory containing episode-scoped production-evidence directories "
            "(<evidence_path>/<episode_id>/...), consumed by Archive Rev1 (Phase 15 Mission 15G.1). "
            "Optional and unset by default -- an episode's directory location, not evidence content "
            "itself, is what makes evidence authoritative; see ArchiveManager for the fail-open "
            "('not configured' -> zero evidence) vs. fail-closed ('configured but missing/unsafe on "
            "disk' -> error) distinction this field's absence-vs-presence drives."
        ),
    )
    backup_path: str | None = Field(
        default=None,
        description=(
            "Root directory for Backup Manager (Mission 1A) system-of-record backups: "
            "<backup_path>/system_backups/<backup_id>/. Optional and unset by default -- an existing "
            "paths.yaml written before Mission 1A continues to load unchanged. Mirrors evidence_path's "
            "same fail-open-on-parse/fail-closed-on-use split: an unset backup_path is not an error "
            "here, but BackupManager.create_backup() fails closed (BackupConfigurationError) without "
            "it configured. Must not equal, contain, or be contained by REDLINE_DB_PATH's directory "
            "or REDLINE_CONFIG_DIR -- BackupManager validates this structurally at every create_backup() "
            "call, never assumed from configuration alone."
        ),
    )


class AssetDefinition(BaseModel):
    """A single approved asset, identified by an Asset ID owned by the Universe project.

    Redline OS does not create or name these — it only records where the
    already-approved file lives so it can verify it exists before an episode
    that needs it proceeds.
    """

    asset_id: str = Field(..., description="Asset ID as defined by the Universe project, e.g. 'RLG-001'.")
    description: str = Field(default="", description="Human-readable description, for logging/debugging only.")
    filename: str = Field(..., description="Filename of the approved asset, relative to paths.assets_path.")


class AssetsConfig(BaseModel):
    """Registry of approved assets, plus which ones every episode requires by default."""

    assets: list[AssetDefinition] = Field(default_factory=list)
    required_for_episode: list[str] = Field(
        default_factory=list,
        description="Asset IDs that must be present for every episode, unless overridden by the caller.",
    )

    def get(self, asset_id: str) -> AssetDefinition | None:
        return next((a for a in self.assets if a.asset_id == asset_id), None)


class MarkerDefinition(BaseModel):
    """A single timeline marker, applied per the Broadcast Package spec.

    `color` should be one of Resolve's built-in marker colors (Blue, Cyan,
    Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint,
    Lemon, Sand, Cocoa, Cream) — Resolve will reject anything else, but that
    validation happens at the adapter layer (Phase 6+), not here.
    """

    frame: int = Field(..., ge=0, description="Frame number on the timeline to place the marker at.")
    color: str = Field(..., description="Resolve marker color name, e.g. 'Blue'.")
    name: str = Field(..., description="Marker name shown in Resolve's timeline/marker list.")
    note: str = Field(default="", description="Optional marker note/description.")


class TimelineTemplateConfig(BaseModel):
    """Data-driven timeline layout: naming + the standard marker set from the
    Broadcast Package spec. None of these values are invented by Redline OS —
    they mirror what the Universe project's Broadcast Package already defines.
    """

    timeline_name_pattern: str = Field(
        ..., description="Pattern for the timeline name, e.g. '{episode_id}_TIMELINE'."
    )
    markers: list[MarkerDefinition] = Field(
        default_factory=list, description="Standard marker set applied to every new episode timeline."
    )


class RedlineConfig(BaseModel):
    """Aggregate config object returned by redline_core.config.loader.load_config()."""

    naming: NamingConfig
    folder_structure: FolderStructureConfig
    render_presets: RenderPresetsConfig
    paths: PathsConfig
    assets: AssetsConfig
    timeline: TimelineTemplateConfig
