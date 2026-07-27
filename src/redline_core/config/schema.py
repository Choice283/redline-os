"""Pydantic schema for Redline OS configuration.

Redline OS does NOT define naming, folder, or asset-ID conventions itself —
those belong to the Redline Universe project (Showrunner Bible, Broadcast
Package V1.0). These models only describe the *shape* Redline OS expects
that data to arrive in via YAML config files under /config. If the Universe
conventions change, only the YAML files change — not this code.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
