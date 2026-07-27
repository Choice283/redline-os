"""Pydantic schema and validated runtime models for Episode Manifest V1."""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError, field_validator

from redline_core.config.schema import MarkerDefinition
from redline_core.episode.models import EpisodeBuildDefinition
from redline_core.manifest.exceptions import ManifestSchemaError, ManifestVersionError

SUPPORTED_SCHEMA_VERSION = 1


class ManifestBaseModel(BaseModel):
    """Strict manifest model base."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EpisodeSection(ManifestBaseModel):
    id: StrictStr

    @field_validator("id")
    @classmethod
    def id_must_be_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("episode.id must be a non-empty string")
        return value


class MediaEntry(ManifestBaseModel):
    path: StrictStr

    @field_validator("path")
    @classmethod
    def path_must_be_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("assembly.media[].path must be a non-empty string")
        return value


class MarkerEntry(ManifestBaseModel):
    frame: StrictInt = Field(..., ge=0)
    color: StrictStr
    name: StrictStr
    note: StrictStr = ""

    @field_validator("color")
    @classmethod
    def color_must_be_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("marker color must be a non-empty string")
        return value


class AssemblySection(ManifestBaseModel):
    media: tuple[MediaEntry, ...]
    bin_name: StrictStr = "footage"
    markers: tuple[MarkerEntry, ...] = ()

    @field_validator("media", "markers", mode="before")
    @classmethod
    def yaml_lists_become_tuples(cls, value):
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("bin_name")
    @classmethod
    def bin_name_must_be_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("assembly.bin_name must be a non-empty string")
        return value

    @field_validator("media")
    @classmethod
    def media_must_not_be_empty(cls, value: tuple[MediaEntry, ...]) -> tuple[MediaEntry, ...]:
        if not value:
            raise ValueError("assembly.media must contain at least one item")
        return value


class EpisodeManifest(ManifestBaseModel):
    schema_version: StrictInt
    episode: EpisodeSection
    assembly: AssemblySection

    @field_validator("schema_version")
    @classmethod
    def schema_version_must_be_supported(cls, value: int) -> int:
        if value != SUPPORTED_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {value}")
        return value


@dataclass(frozen=True)
class ValidatedMarker:
    """Immutable manifest-owned marker value stored in a validated plan."""

    frame: int
    color: str
    name: str
    note: str = ""


@dataclass(frozen=True)
class ValidatedEpisodePlan:
    """Point-in-time validated manifest intent for existing episode assembly.

    This plan is deterministic intent, not guaranteed historical
    reproducibility. It does not snapshot or hash media, freeze configuration,
    persist the manifest, or persist build history. Runtime imports may still
    fail after validation.
    """

    episode_id: str
    media_paths: tuple[str, ...]
    markers: tuple[ValidatedMarker, ...] = ()
    bin_name: str = "footage"

    def to_build_definition(self) -> EpisodeBuildDefinition:
        """Translate validated intent to the existing Episode Assembly contract."""
        return EpisodeBuildDefinition(
            episode_id=self.episode_id,
            media_paths=list(self.media_paths),
            markers=[
                MarkerDefinition(
                    frame=marker.frame,
                    color=marker.color,
                    name=marker.name,
                    note=marker.note,
                )
                for marker in self.markers
            ],
            bin_name=self.bin_name,
        )


def build_manifest_model(data: object) -> EpisodeManifest:
    """Construct an EpisodeManifest while preserving typed manifest exceptions."""
    if not isinstance(data, dict):
        raise ManifestSchemaError("manifest root must be a mapping", code="manifest.root_invalid")
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ManifestVersionError(
            "schema_version must be the integer 1",
            code="manifest.version_invalid",
        )
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ManifestVersionError(
            f"unsupported schema_version: {version}",
            code="manifest.version_unsupported",
        )
    try:
        return EpisodeManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestSchemaError(
            f"manifest schema validation failed: {exc}",
            code="manifest.schema_invalid",
        ) from exc
