from pathlib import Path

import pytest

from redline_core.manifest import (
    ManifestLoadError,
    ManifestParseError,
    ManifestSchemaError,
    ManifestVersionError,
    load_manifest,
)


def write_manifest(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def minimal_manifest() -> str:
    return """\
schema_version: 1
episode:
  id: RLC-E025
assembly:
  media:
    - path: media/clip.wav
"""


def test_load_manifest_valid_readable_yaml(tmp_path):
    manifest_path = write_manifest(tmp_path / "episode.yaml", minimal_manifest())

    manifest = load_manifest(manifest_path)

    assert manifest.schema_version == 1
    assert manifest.episode.id == "RLC-E025"
    assert manifest.assembly.bin_name == "footage"
    assert [entry.path for entry in manifest.assembly.media] == ["media/clip.wav"]
    assert manifest.assembly.markers == ()


def test_load_manifest_valid_complete_yaml_preserves_order(tmp_path):
    manifest_path = write_manifest(
        tmp_path / "episode.yml",
        """\
schema_version: 1
episode:
  id: RLC-E025
assembly:
  bin_name: selects
  media:
    - path: media/a.wav
    - path: media/b.png
  markers:
    - frame: 0
      color: Blue
      name: Start
      note: Opening
    - frame: 48
      color: Yellow
      name: Beat
""",
    )

    manifest = load_manifest(manifest_path)

    assert manifest.assembly.bin_name == "selects"
    assert [entry.path for entry in manifest.assembly.media] == ["media/a.wav", "media/b.png"]
    assert [marker.frame for marker in manifest.assembly.markers] == [0, 48]
    assert manifest.assembly.markers[1].note == ""


def test_load_manifest_missing_file_raises_load_error(tmp_path):
    with pytest.raises(ManifestLoadError):
        load_manifest(tmp_path / "missing.yaml")


def test_load_manifest_unsupported_extension_raises_load_error(tmp_path):
    manifest_path = write_manifest(tmp_path / "episode.json", minimal_manifest())

    with pytest.raises(ManifestLoadError, match="extension"):
        load_manifest(manifest_path)


def test_load_manifest_invalid_utf8_raises_load_error(tmp_path):
    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(ManifestLoadError, match="UTF-8"):
        load_manifest(manifest_path)


def test_load_manifest_empty_file_fails(tmp_path):
    manifest_path = write_manifest(tmp_path / "episode.yaml", "")

    with pytest.raises(ManifestParseError, match="empty"):
        load_manifest(manifest_path)


def test_load_manifest_malformed_yaml_fails(tmp_path):
    manifest_path = write_manifest(tmp_path / "episode.yaml", "schema_version: 1\n  bad: true\n")

    with pytest.raises(ManifestParseError):
        load_manifest(manifest_path)


@pytest.mark.parametrize(
    "body, expected",
    [
        ("schema_version: 1\nschema_version: 1\n", "duplicate key"),
        ("schema_version: 1\nepisode:\n  id: A\n  id: B\nassembly:\n  media:\n    - path: a\n", "duplicate key"),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n      path: b\n",
            "duplicate key",
        ),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n  markers:\n    - frame: 0\n      color: Blue\n      name: A\n      name: B\n",
            "duplicate key",
        ),
    ],
)
def test_load_manifest_duplicate_keys_fail_before_schema_validation(tmp_path, body, expected):
    manifest_path = write_manifest(tmp_path / "episode.yaml", body)

    with pytest.raises(ManifestParseError, match=expected):
        load_manifest(manifest_path)


def test_load_manifest_multiple_documents_fail(tmp_path):
    manifest_path = write_manifest(tmp_path / "episode.yaml", minimal_manifest() + "---\nschema_version: 1\n")

    with pytest.raises(ManifestParseError, match="exactly one"):
        load_manifest(manifest_path)


@pytest.mark.parametrize("body", ["hello\n", "- a\n- b\n", "null\n"])
def test_load_manifest_root_must_be_mapping(tmp_path, body):
    manifest_path = write_manifest(tmp_path / "episode.yaml", body)

    with pytest.raises(ManifestParseError):
        load_manifest(manifest_path)


def test_load_manifest_non_string_mapping_key_fails(tmp_path):
    manifest_path = write_manifest(tmp_path / "episode.yaml", "1: one\n")

    with pytest.raises(ManifestParseError, match="non-string"):
        load_manifest(manifest_path)


def test_load_manifest_unsafe_python_object_tag_fails(tmp_path):
    manifest_path = write_manifest(
        tmp_path / "episode.yaml",
        "!!python/object/apply:os.system ['echo unsafe']\n",
    )

    with pytest.raises(ManifestParseError):
        load_manifest(manifest_path)


def test_load_manifest_yaml_merge_keys_are_not_supported(tmp_path):
    manifest_path = write_manifest(
        tmp_path / "episode.yaml",
        """\
schema_version: 1
episode:
  id: RLC-E025
defaults: &defaults
  path: media/clip.wav
assembly:
  media:
    - <<: *defaults
""",
    )

    with pytest.raises(ManifestParseError):
        load_manifest(manifest_path)


@pytest.mark.parametrize(
    "body, exc_type, expected",
    [
        ("episode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n", ManifestVersionError, "schema_version"),
        (
            "schema_version: true\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n",
            ManifestVersionError,
            "schema_version",
        ),
        (
            "schema_version: '1'\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n",
            ManifestVersionError,
            "schema_version",
        ),
        (
            "schema_version: 2\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n",
            ManifestVersionError,
            "unsupported",
        ),
        (
            "schema_version: 1\nunknown: value\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n",
            ManifestSchemaError,
            "extra",
        ),
        ("schema_version: 1\nassembly:\n  media:\n    - path: a\n", ManifestSchemaError, "episode"),
        ("schema_version: 1\nepisode: {}\nassembly:\n  media:\n    - path: a\n", ManifestSchemaError, "id"),
        ("schema_version: 1\nepisode:\n  id: ''\nassembly:\n  media:\n    - path: a\n", ManifestSchemaError, "episode.id"),
        ("schema_version: 1\nepisode:\n  id: RLC-E025\n", ManifestSchemaError, "assembly"),
        ("schema_version: 1\nepisode:\n  id: RLC-E025\nassembly: {}\n", ManifestSchemaError, "media"),
        ("schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media: []\n", ManifestSchemaError, "media"),
        ("schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - media/clip.wav\n", ManifestSchemaError, "media"),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n      role: dialogue\n",
            ManifestSchemaError,
            "extra",
        ),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n  markers: bad\n",
            ManifestSchemaError,
            "markers",
        ),
        (
            "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: a\n  markers:\n    - frame: 0\n      color: Blue\n      name: A\n      duration: 1\n",
            ManifestSchemaError,
            "extra",
        ),
    ],
)
def test_load_manifest_schema_failures(tmp_path, body, exc_type, expected):
    manifest_path = write_manifest(tmp_path / "episode.yaml", body)

    with pytest.raises(exc_type, match=expected):
        load_manifest(manifest_path)
