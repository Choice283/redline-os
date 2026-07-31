"""Immutable render output planning for queue requests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import TYPE_CHECKING

from redline_core.db.models import Episode
from redline_core.render.exceptions import RenderConfigurationError

if TYPE_CHECKING:
    from redline_core.config.schema import RenderPreset

SUPPORTED_FILENAME_PLACEHOLDERS = frozenset({"episode_id", "preset_name", "project_name", "timeline_name"})


@dataclass(frozen=True)
class RenderOutputPlan:
    episode_id: str
    preset_name: str
    resolve_preset_name: str
    project_name: str
    timeline_name: str
    output_directory: Path
    output_stem: str
    file_extension: str
    output_path: Path


def build_render_output_plan(episode: Episode, preset: "RenderPreset", timeline_name: str) -> RenderOutputPlan:
    if preset.filename_template is None or preset.file_extension is None:
        raise RenderConfigurationError(
            f"Render preset '{preset.name}' does not define an approved filename_template and file_extension."
        )
    if not episode.folder_path or not episode.folder_path.strip():
        raise RenderConfigurationError(f"Episode {episode.episode_id!r} has no configured workspace.")

    episode_directory = Path(episode.folder_path).expanduser().resolve()
    if not episode_directory.is_dir():
        raise RenderConfigurationError(f"Episode workspace does not exist: {episode_directory}")

    output_directory = (episode_directory / preset.output_subfolder).resolve()
    try:
        output_directory.relative_to(episode_directory)
    except ValueError as exc:
        raise RenderConfigurationError(
            f"Render preset '{preset.name}' resolves outside the episode folder."
        ) from exc
    values = {
        "episode_id": episode.episode_id,
        "preset_name": preset.name,
        "project_name": episode.project_name,
        "timeline_name": timeline_name,
    }
    try:
        output_stem = preset.filename_template.format(**values)
        _validate_render_output_stem(output_stem)
    except (AttributeError, IndexError, KeyError, ValueError) as exc:
        raise RenderConfigurationError(
            f"Render preset {preset.name!r} produced an invalid output filename."
        ) from exc
    output_path = output_directory / f"{output_stem}{preset.file_extension}"
    return RenderOutputPlan(
        episode_id=episode.episode_id,
        preset_name=preset.name,
        resolve_preset_name=preset.resolve_preset_name,
        project_name=episode.project_name,
        timeline_name=timeline_name,
        output_directory=output_directory,
        output_stem=output_stem,
        file_extension=preset.file_extension,
        output_path=output_path,
    )


def filename_template_placeholders(template: str) -> set[str]:
    placeholders: set[str] = set()
    try:
        parsed = Formatter().parse(template)
        for _literal, field_name, format_spec, conversion in parsed:
            if conversion is not None or format_spec:
                placeholders.add("")
                continue
            if field_name is not None and field_name:
                placeholders.add(field_name)
    except ValueError:
        placeholders.add("")
    return placeholders


def _validate_render_output_stem(output_stem: str) -> None:
    if not output_stem.strip():
        raise ValueError("render output filename resolved to an empty value")
    path = Path(output_stem)
    if path.is_absolute() or path.name != output_stem or ".." in path.parts:
        raise ValueError("render output filename must resolve to a plain file stem")
