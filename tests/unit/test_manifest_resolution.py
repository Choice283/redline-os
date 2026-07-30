from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from redline_core.build import (
    BuildTarget,
    ManifestResolution,
    ManifestResolutionError,
    resolve_manifest_path,
)


def build_target(original_target: str = "Episode_0001") -> BuildTarget:
    return BuildTarget(
        original_target=original_target,
        episode_number=1,
        episode_id="RLC-E001",
    )


def test_resolve_manifest_path_accepts_existing_relative_yaml_path(tmp_path):
    manifest = tmp_path / "manifests" / "custom.yaml"
    manifest.parent.mkdir()
    manifest.touch()

    result = resolve_manifest_path(
        build_target(),
        manifest_path=Path("manifests") / "custom.yaml",
        working_directory=tmp_path,
    )

    assert result == ManifestResolution(path=manifest.resolve(), source="explicit")


def test_resolve_manifest_path_accepts_existing_relative_yml_path(tmp_path):
    manifest = tmp_path / "custom.yml"
    manifest.touch()

    result = resolve_manifest_path(
        build_target(),
        manifest_path="custom.yml",
        working_directory=tmp_path,
    )

    assert result.path == manifest.resolve()
    assert result.source == "explicit"


def test_resolve_manifest_path_accepts_existing_absolute_path(tmp_path):
    manifest = tmp_path / "absolute.yaml"
    manifest.touch()

    result = resolve_manifest_path(
        build_target(),
        manifest_path=manifest,
        working_directory=tmp_path,
    )

    assert result.path == manifest.resolve()
    assert result.source == "explicit"


def test_resolve_manifest_path_explicit_path_precedes_default_candidates(tmp_path):
    explicit = tmp_path / "custom.yaml"
    default_yaml = tmp_path / "Episode_0001.yaml"
    default_yml = tmp_path / "Episode_0001.yml"
    explicit.touch()
    default_yaml.touch()
    default_yml.touch()

    result = resolve_manifest_path(
        build_target(),
        manifest_path="custom.yaml",
        working_directory=tmp_path,
    )

    assert result.path == explicit.resolve()
    assert result.source == "explicit"


def test_resolve_manifest_path_explicit_path_does_not_need_target_filename(tmp_path):
    manifest = tmp_path / "operator-selected.yml"
    manifest.touch()

    result = resolve_manifest_path(
        build_target(),
        manifest_path="operator-selected.yml",
        working_directory=tmp_path,
    )

    assert result.path == manifest.resolve()


def test_resolve_manifest_path_rejects_missing_explicit_path(tmp_path):
    missing = tmp_path / "missing.yaml"

    with pytest.raises(ManifestResolutionError, match="does not exist"):
        resolve_manifest_path(
            build_target(),
            manifest_path=missing,
            working_directory=tmp_path,
        )


def test_resolve_manifest_path_rejects_explicit_directory(tmp_path):
    directory = tmp_path / "directory.yaml"
    directory.mkdir()

    with pytest.raises(ManifestResolutionError, match="not a file"):
        resolve_manifest_path(
            build_target(),
            manifest_path=directory,
            working_directory=tmp_path,
        )


def test_resolve_manifest_path_rejects_invalid_explicit_extension(tmp_path):
    manifest = tmp_path / "episode.YAML"
    manifest.touch()

    with pytest.raises(ManifestResolutionError, match=".yaml or .yml"):
        resolve_manifest_path(
            build_target(),
            manifest_path=manifest,
            working_directory=tmp_path,
        )


def test_resolve_manifest_path_default_yaml_exists(tmp_path):
    manifest = tmp_path / "Episode_0001.yaml"
    manifest.touch()

    result = resolve_manifest_path(build_target(), working_directory=tmp_path)

    assert result == ManifestResolution(path=manifest.resolve(), source="default_yaml")


def test_resolve_manifest_path_default_yml_exists(tmp_path):
    manifest = tmp_path / "Episode_0001.yml"
    manifest.touch()

    result = resolve_manifest_path(build_target(), working_directory=tmp_path)

    assert result == ManifestResolution(path=manifest.resolve(), source="default_yml")


def test_resolve_manifest_path_default_yaml_wins_when_both_exist(tmp_path):
    yaml_manifest = tmp_path / "Episode_0001.yaml"
    yml_manifest = tmp_path / "Episode_0001.yml"
    yaml_manifest.touch()
    yml_manifest.touch()

    result = resolve_manifest_path(build_target(), working_directory=tmp_path)

    assert result.path == yaml_manifest.resolve()
    assert result.source == "default_yaml"


def test_resolve_manifest_path_uses_yml_when_yaml_candidate_is_directory(tmp_path):
    yaml_directory = tmp_path / "Episode_0001.yaml"
    yml_manifest = tmp_path / "Episode_0001.yml"
    yaml_directory.mkdir()
    yml_manifest.touch()

    result = resolve_manifest_path(build_target(), working_directory=tmp_path)

    assert result.path == yml_manifest.resolve()
    assert result.source == "default_yml"


def test_resolve_manifest_path_missing_default_identifies_expected_candidates(tmp_path):
    with pytest.raises(ManifestResolutionError) as error_info:
        resolve_manifest_path(build_target(), working_directory=tmp_path)

    message = str(error_info.value)
    assert "Episode_0001.yaml" in message
    assert "Episode_0001.yml" in message


def test_resolve_manifest_path_uses_original_target_for_default_filename(tmp_path):
    target = BuildTarget(
        original_target="Episode_0007",
        episode_number=1,
        episode_id="RLC-E001",
    )
    manifest = tmp_path / "Episode_0007.yaml"
    wrong_manifest = tmp_path / "Episode_0001.yaml"
    manifest.touch()
    wrong_manifest.touch()

    result = resolve_manifest_path(target, working_directory=tmp_path)

    assert result.path == manifest.resolve()


def test_resolve_manifest_path_rejects_wrong_target_type(tmp_path):
    with pytest.raises(ManifestResolutionError, match="BuildTarget"):
        resolve_manifest_path(object(), working_directory=tmp_path)


def test_resolve_manifest_path_rejects_invalid_working_directory_type():
    with pytest.raises(ManifestResolutionError, match="working_directory"):
        resolve_manifest_path(build_target(), working_directory=object())


def test_resolve_manifest_path_rejects_missing_working_directory(tmp_path):
    with pytest.raises(ManifestResolutionError, match="working_directory"):
        resolve_manifest_path(build_target(), working_directory=tmp_path / "missing")


def test_resolve_manifest_path_rejects_file_working_directory(tmp_path):
    file_working_directory = tmp_path / "not-a-directory"
    file_working_directory.touch()

    with pytest.raises(ManifestResolutionError, match="directory"):
        resolve_manifest_path(build_target(), working_directory=file_working_directory)


def test_resolve_manifest_path_rejects_invalid_explicit_path_type(tmp_path):
    with pytest.raises(ManifestResolutionError, match="manifest_path"):
        resolve_manifest_path(
            build_target(),
            manifest_path=object(),
            working_directory=tmp_path,
        )


def test_manifest_resolution_result_is_immutable(tmp_path):
    manifest = tmp_path / "Episode_0001.yaml"
    manifest.touch()
    result = resolve_manifest_path(build_target(), working_directory=tmp_path)

    with pytest.raises(FrozenInstanceError):
        result.source = "changed"
