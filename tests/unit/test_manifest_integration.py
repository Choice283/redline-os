from pathlib import Path

from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.episode.models import EpisodeBuildDefinition
from redline_core.manifest import load_manifest, validate_manifest


class FakeAssemblyBoundary:
    def __init__(self):
        self.calls = []

    def accept_definition(self, definition: EpisodeBuildDefinition) -> None:
        self.calls.append(definition)


def make_config(tmp_path: Path) -> RedlineConfig:
    ingest = tmp_path / "configured" / "ingest"
    assets = tmp_path / "configured" / "assets"
    ingest.mkdir(parents=True)
    assets.mkdir(parents=True)
    return RedlineConfig(
        naming=NamingConfig(
            episode_id_pattern="RLC-E{episode_number:03d}",
            project_name_pattern="{episode_id}_MASTER",
        ),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path=str(ingest),
            archive_path=str(tmp_path / "_archive"),
            assets_path=str(assets),
            master_project_template="RLC_MASTER_TEMPLATE",
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )


def test_manifest_load_validate_translate_to_existing_assembly_boundary(tmp_path):
    config = make_config(tmp_path)
    manifest_dir = tmp_path / "drafts"
    media_dir = manifest_dir / "media"
    manifest_dir.mkdir()
    media_dir.mkdir()
    clip = media_dir / "clip.wav"
    clip.write_bytes(b"x")
    config.paths.ingest_path = str(manifest_dir)
    manifest_path = manifest_dir / "episode.yaml"
    manifest_path.write_text(
        """\
schema_version: 1
episode:
  id: RLC-E025
assembly:
  media:
    - path: media/clip.wav
  markers:
    - frame: 0
      color: Blue
      name: Start
""",
        encoding="utf-8",
    )
    boundary = FakeAssemblyBoundary()

    manifest = load_manifest(manifest_path)
    plan = validate_manifest(manifest, manifest_path=manifest_path, config=config)
    definition = plan.to_build_definition()
    boundary.accept_definition(definition)

    assert isinstance(definition, EpisodeBuildDefinition)
    assert definition.episode_id == "RLC-E025"
    assert definition.media_paths == [str(clip.resolve())]
    assert definition.bin_name == "footage"
    assert [marker.name for marker in definition.markers] == ["Start"]
    assert boundary.calls == [definition]
