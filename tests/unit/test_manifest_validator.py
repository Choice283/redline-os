from pathlib import Path

import pytest
from pydantic import ValidationError

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
from redline_core.manifest import (
    ManifestPathError,
    ManifestValidationError,
    ValidatedMarker,
    load_manifest,
    validate_manifest,
)
from redline_core.manifest import validator as manifest_validator
from redline_core.manifest.models import ValidatedEpisodePlan


def make_config(tmp_path: Path, *, ingest_path: str | None = None, assets_path: str | None = None) -> RedlineConfig:
    ingest = Path(ingest_path) if ingest_path is not None else tmp_path / "_ingest"
    assets = Path(assets_path) if assets_path is not None else tmp_path / "_assets"
    ingest.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
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


def write_manifest(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def manifest_body(*, media: list[str], bin_name: str | None = None, markers: str = "") -> str:
    bin_section = f"  bin_name: {bin_name}\n" if bin_name is not None else ""
    media_section = "".join(f"    - path: {path}\n" for path in media)
    return f"""\
schema_version: 1
episode:
  id: RLC-E025
assembly:
{bin_section}  media:
{media_section}{markers}"""


def load_and_validate(manifest_path: Path, config: RedlineConfig) -> ValidatedEpisodePlan:
    return validate_manifest(load_manifest(manifest_path), manifest_path=manifest_path, config=config)


def test_validate_manifest_relative_media_path_from_manifest_directory(tmp_path):
    config = make_config(tmp_path)
    manifest_dir = tmp_path / "drafts"
    media_dir = manifest_dir / "media"
    media_dir.mkdir(parents=True)
    media_file = media_dir / "clip.wav"
    media_file.write_bytes(b"x")
    config.paths.ingest_path = str(manifest_dir)
    manifest_path = write_manifest(manifest_dir / "episode.yaml", manifest_body(media=["media/clip.wav"]))

    plan = load_and_validate(manifest_path, config)

    assert plan.media_paths == (str(media_file.resolve()),)


def test_validate_manifest_absolute_media_path(tmp_path):
    config = make_config(tmp_path)
    media_file = Path(config.paths.ingest_path) / "clip.wav"
    media_file.write_bytes(b"x")
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(media_file)]))

    plan = load_and_validate(manifest_path, config)

    assert plan.media_paths == (str(media_file.resolve()),)


def test_validate_manifest_media_under_assets_path(tmp_path):
    config = make_config(tmp_path)
    media_file = Path(config.paths.assets_path) / "graphic.png"
    media_file.write_bytes(b"x")
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(media_file)]))

    plan = load_and_validate(manifest_path, config)

    assert plan.media_paths == (str(media_file.resolve()),)


def test_validate_manifest_rejects_media_outside_roots(tmp_path):
    config = make_config(tmp_path)
    outside = tmp_path / "outside" / "clip.wav"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(outside)]))

    with pytest.raises(ManifestPathError, match="outside approved"):
        load_and_validate(manifest_path, config)


def test_validate_manifest_rejects_parent_traversal_escaping_roots(tmp_path):
    config = make_config(tmp_path)
    manifest_dir = Path(config.paths.ingest_path) / "drafts"
    manifest_dir.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"x")
    manifest_path = write_manifest(manifest_dir / "episode.yaml", manifest_body(media=["../../outside.wav"]))

    with pytest.raises(ManifestPathError, match="outside approved"):
        load_and_validate(manifest_path, config)


def test_validate_manifest_allows_parent_traversal_remaining_within_root(tmp_path):
    config = make_config(tmp_path)
    ingest = Path(config.paths.ingest_path)
    nested = ingest / "drafts" / "nested"
    nested.mkdir(parents=True)
    media_file = ingest / "clip.wav"
    media_file.write_bytes(b"x")
    manifest_path = write_manifest(nested / "episode.yaml", manifest_body(media=["../../clip.wav"]))

    plan = load_and_validate(manifest_path, config)

    assert plan.media_paths == (str(media_file.resolve()),)


def test_validate_manifest_rejects_common_prefix_sibling(tmp_path):
    approved = tmp_path / "approved"
    sibling = tmp_path / "approved-evil"
    approved.mkdir()
    sibling.mkdir()
    config = make_config(tmp_path, ingest_path=str(approved), assets_path=str(tmp_path / "_assets"))
    media_file = sibling / "clip.wav"
    media_file.write_bytes(b"x")
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(media_file)]))

    with pytest.raises(ManifestPathError, match="outside approved"):
        load_and_validate(manifest_path, config)


def test_validate_manifest_rejects_duplicate_normalized_media_paths(tmp_path):
    config = make_config(tmp_path)
    ingest = Path(config.paths.ingest_path)
    media_file = ingest / "clip.wav"
    media_file.write_bytes(b"x")
    manifest_path = write_manifest(
        ingest / "episode.yaml",
        manifest_body(media=["clip.wav", "./subdir/../clip.wav"]),
    )
    (ingest / "subdir").mkdir()

    with pytest.raises(ManifestPathError, match="duplicate"):
        load_and_validate(manifest_path, config)


def test_windows_duplicate_key_strategy_is_case_insensitive(monkeypatch):
    # Patch the module-local ``_is_windows()`` indirection, not the shared
    # ``os`` module's ``name`` attribute -- the latter is a process-wide
    # singleton, and mutating it (even via ``monkeypatch``, even though
    # ``monkeypatch`` reverts it after this test) previously interacted
    # badly with pytest's own internal ``pathlib.Path()`` usage later in
    # the same session, causing an unrelated ``WindowsPath``
    # ``INTERNALERROR`` at full-suite teardown/report time. Patching this
    # function exercises the exact same Windows-specific casefold branch
    # in ``_duplicate_key`` without touching any global interpreter state.
    monkeypatch.setattr(manifest_validator, "_is_windows", lambda: True)

    assert manifest_validator._duplicate_key(Path("C:/Media/Clip.WAV")) == manifest_validator._duplicate_key(
        Path("C:/media/clip.wav")
    )


def test_validate_manifest_rejects_missing_media_file(tmp_path):
    config = make_config(tmp_path)
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(Path(config.paths.ingest_path) / "missing.wav")]))

    with pytest.raises(ManifestPathError, match="cannot be resolved"):
        load_and_validate(manifest_path, config)


def test_validate_manifest_rejects_directory_as_media(tmp_path):
    config = make_config(tmp_path)
    media_dir = Path(config.paths.ingest_path) / "folder"
    media_dir.mkdir()
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(media_dir)]))

    with pytest.raises(ManifestPathError, match="not a file"):
        load_and_validate(manifest_path, config)


def test_validate_manifest_rejects_broken_symlink(tmp_path):
    config = make_config(tmp_path)
    symlink = Path(config.paths.ingest_path) / "broken.wav"
    try:
        symlink.symlink_to(Path(config.paths.ingest_path) / "missing.wav")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not supported in this environment")
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(symlink)]))

    with pytest.raises(ManifestPathError):
        load_and_validate(manifest_path, config)


def test_validate_manifest_rejects_symlink_escape(tmp_path):
    config = make_config(tmp_path)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"x")
    symlink = Path(config.paths.ingest_path) / "escape.wav"
    try:
        symlink.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not supported in this environment")
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(symlink)]))

    with pytest.raises(ManifestPathError, match="outside approved"):
        load_and_validate(manifest_path, config)


def test_validate_manifest_relative_configured_roots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = make_config(tmp_path, ingest_path="_ingest", assets_path="_assets")
    media_file = Path("_ingest") / "clip.wav"
    media_file.write_bytes(b"x")
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(media_file)]))

    plan = load_and_validate(manifest_path, config)

    assert plan.media_paths == (str(media_file.resolve()),)


def test_manifest_outside_approved_roots_can_reference_valid_media(tmp_path):
    config = make_config(tmp_path)
    media_file = Path(config.paths.ingest_path) / "clip.wav"
    media_file.write_bytes(b"x")
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    manifest_path = write_manifest(manifest_dir / "episode.yaml", manifest_body(media=[str(media_file)]))

    plan = load_and_validate(manifest_path, config)

    assert plan.media_paths == (str(media_file.resolve()),)


def test_validate_manifest_rejects_unc_like_path_outside_roots(tmp_path):
    config = make_config(tmp_path)
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[r"\\unapproved-server\share\clip.mov"]))

    with pytest.raises(ManifestPathError):
        load_and_validate(manifest_path, config)


def test_validate_manifest_default_and_explicit_bin_name(tmp_path):
    config = make_config(tmp_path)
    media_file = Path(config.paths.ingest_path) / "clip.wav"
    media_file.write_bytes(b"x")
    default_manifest = write_manifest(tmp_path / "default.yaml", manifest_body(media=[str(media_file)]))
    explicit_manifest = write_manifest(tmp_path / "explicit.yaml", manifest_body(media=[str(media_file)], bin_name="selects"))

    assert load_and_validate(default_manifest, config).bin_name == "footage"
    assert load_and_validate(explicit_manifest, config).bin_name == "selects"


def test_validate_manifest_markers_preserve_order_and_translate(tmp_path):
    config = make_config(tmp_path)
    media_file = Path(config.paths.ingest_path) / "clip.wav"
    media_file.write_bytes(b"x")
    markers = """\
  markers:
    - frame: 0
      color: Blue
      name: Start
      note: Opening
    - frame: 48
      color: Yellow
      name: Beat
"""
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(media_file)], markers=markers))

    plan = load_and_validate(manifest_path, config)
    definition = plan.to_build_definition()

    assert [marker.frame for marker in plan.markers] == [0, 48]
    assert all(isinstance(marker, ValidatedMarker) for marker in plan.markers)
    assert [marker.name for marker in definition.markers] == ["Start", "Beat"]
    assert definition.markers[1].note == ""


def test_validate_manifest_rejects_invalid_manifest_type(tmp_path):
    config = make_config(tmp_path)

    with pytest.raises(ManifestValidationError, match="EpisodeManifest"):
        validate_manifest(object(), manifest_path=tmp_path / "episode.yaml", config=config)


def test_validated_plan_is_immutable_and_translation_copies_collections(tmp_path):
    config = make_config(tmp_path)
    media_file = Path(config.paths.ingest_path) / "clip.wav"
    media_file.write_bytes(b"x")
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(media_file)]))
    manifest = load_manifest(manifest_path)
    plan = validate_manifest(manifest, manifest_path=manifest_path, config=config)

    with pytest.raises(Exception):
        plan.media_paths += ("other",)
    definition = plan.to_build_definition()
    definition.media_paths.append("mutated")

    assert isinstance(definition, EpisodeBuildDefinition)
    assert plan.media_paths == (str(media_file.resolve()),)
    assert manifest.assembly.media[0].path == str(media_file)


def test_validated_plan_stores_immutable_marker_values_and_translates_fresh_markers(tmp_path):
    config = make_config(tmp_path)
    media_file = Path(config.paths.ingest_path) / "clip.wav"
    media_file.write_bytes(b"x")
    markers = """\
  markers:
    - frame: 0
      color: Blue
      name: Start
      note: Opening
    - frame: 48
      color: Yellow
      name: Beat
"""
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(media_file)], markers=markers))

    plan = load_and_validate(manifest_path, config)

    assert [marker.name for marker in plan.markers] == ["Start", "Beat"]
    assert all(isinstance(marker, ValidatedMarker) for marker in plan.markers)
    with pytest.raises(Exception):
        plan.markers += (ValidatedMarker(frame=96, color="Red", name="Outro"),)
    with pytest.raises(Exception):
        plan.markers[0].name = "Changed"

    first = plan.to_build_definition()
    second = plan.to_build_definition()

    assert [marker.name for marker in first.markers] == ["Start", "Beat"]
    assert first.markers[0] is not second.markers[0]
    first.markers[0].name = "Changed"
    assert plan.markers[0].name == "Start"
    assert second.markers[0].name == "Start"


def test_to_build_definition_omitted_markers_remain_empty(tmp_path):
    config = make_config(tmp_path)
    media_file = Path(config.paths.ingest_path) / "clip.wav"
    media_file.write_bytes(b"x")
    manifest_path = write_manifest(tmp_path / "episode.yaml", manifest_body(media=[str(media_file)]))

    definition = load_and_validate(manifest_path, config).to_build_definition()

    assert definition.markers == []


@pytest.mark.parametrize(
    "body, expected",
    [
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  bin_name: '   '\n  media:\n    - path: a\n",
            "bin_name",
        ),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n  markers:\n    - frame: -1\n      color: Blue\n      name: A\n",
            "frame",
        ),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n  markers:\n    - frame: true\n      color: Blue\n      name: A\n",
            "frame",
        ),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n  markers:\n    - frame: 0\n      color: ''\n      name: A\n",
            "color",
        ),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n  markers:\n    - frame: 0\n      color: Blue\n      name: 123\n",
            "name",
        ),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n  markers:\n    - frame: 0\n      color: Blue\n      name: A\n      note: 123\n",
            "note",
        ),
    ],
)
def test_domain_schema_rules_fail_before_path_validation(tmp_path, body, expected):
    manifest_path = write_manifest(tmp_path / "episode.yaml", body)

    with pytest.raises(Exception, match=expected):
        load_manifest(manifest_path)
