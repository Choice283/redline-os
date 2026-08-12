"""Phase 15 Mission 15E.2 -- canonical episode-manifest provenance
persistence tests.

Scope: redline_core.build.manifest_provenance only. No DB, no Resolve, no
ArchiveManager -- every test operates on tmp_path fixtures used as a
synthetic episode workspace/ingest/assets root.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from redline_core import fsutil
from redline_core.build.manifest_provenance import (
    ManifestProvenanceError,
    map_media_paths_to_approved_roots,
    persist_manifest_provenance,
)
from redline_core.config.schema import PathsConfig, RedlineConfig
from redline_core.manifest.models import ValidatedEpisodePlan


def _config(tmp_path: Path) -> RedlineConfig:
    from redline_core.config.schema import (
        AssetsConfig,
        FolderStructureConfig,
        NamingConfig,
        RenderPresetsConfig,
        TimelineTemplateConfig,
    )

    return RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path=str(tmp_path / "_ingest"),
            archive_path=str(tmp_path / "_archive"),
            assets_path=str(tmp_path / "_assets"),
            master_project_template="RLC_MASTER_TEMPLATE",
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )


def _episode_workspace(tmp_path: Path) -> Path:
    folder = tmp_path / "_episodes" / "RLC-E025"
    for sub in ("footage", "graphics", "audio", "exports", "project"):
        (folder / sub).mkdir(parents=True)
    return folder


def _seed_media(tmp_path: Path) -> tuple[Path, Path]:
    ingest_file = tmp_path / "_ingest" / "EpisodeA" / "camera.mov"
    ingest_file.parent.mkdir(parents=True)
    ingest_file.write_bytes(b"ingest-footage")

    asset_file = tmp_path / "_assets" / "graphics" / "logo.png"
    asset_file.parent.mkdir(parents=True)
    asset_file.write_bytes(b"logo-bytes")

    return ingest_file, asset_file


def _plan(media_paths: tuple[str, ...]) -> ValidatedEpisodePlan:
    return ValidatedEpisodePlan(episode_id="RLC-E025", media_paths=media_paths)


# -- exact manifest preservation ------------------------------------------------


def test_manifest_preserved_byte_for_byte(tmp_path):
    config = _config(tmp_path)
    workspace = _episode_workspace(tmp_path)
    ingest_file, asset_file = _seed_media(tmp_path)

    manifest_path = tmp_path / "manifests" / "episode.yaml"
    manifest_path.parent.mkdir()
    manifest_body = "schema_version: 1\nepisode:\n  id: RLC-E025\n"
    # newline="" avoids Windows' default \n -> \r\n text-mode translation,
    # so the source file's actual on-disk bytes match `manifest_body`
    # exactly -- required for a meaningful byte-for-byte comparison below.
    manifest_path.write_text(manifest_body, encoding="utf-8", newline="")

    plan = _plan((str(ingest_file), str(asset_file)))

    result = persist_manifest_provenance(
        original_manifest_path=manifest_path,
        plan=plan,
        config=config,
        episode_folder_path=workspace,
    )

    # source untouched
    assert manifest_path.read_text(encoding="utf-8") == manifest_body

    # canonical copy exists, byte-identical, correct SHA/size
    canonical = workspace / "project" / "episode_manifest" / "episode.yaml"
    assert canonical.is_file()
    assert canonical.read_bytes() == manifest_body.encode("utf-8")
    expected_sha256 = hashlib.sha256(manifest_body.encode("utf-8")).hexdigest()
    assert result.manifest_sha256 == expected_sha256
    assert result.manifest_size_bytes == len(manifest_body.encode("utf-8"))
    assert result.canonical_manifest_path == canonical

    provenance_path = workspace / "project" / "episode_manifest" / "manifest_provenance.json"
    assert provenance_path.is_file()
    assert result.provenance_path == provenance_path
    provenance = json.loads(provenance_path.read_bytes())
    assert provenance["schema_version"] == 1
    assert provenance["manifest_sha256"] == expected_sha256
    assert provenance["original_manifest_filename"] == "episode.yaml"
    assert provenance["original_manifest_path"] == str(manifest_path.resolve())


# -- relative media mapping provenance -------------------------------------------


def test_provenance_media_mapping_survives_manifest_relocation(tmp_path):
    """The manifest validator resolves relative media paths against the
    *original* manifest's own directory. Once the manifest is copied into
    the workspace, that original directory is gone from the picture --
    provenance must have already captured root-relative identity
    (source_root + source_relative_path) at persist time, not something
    that requires re-deriving from the manifest's new location."""
    config = _config(tmp_path)
    workspace = _episode_workspace(tmp_path)
    ingest_file, asset_file = _seed_media(tmp_path)

    manifest_path = tmp_path / "manifests" / "episode.yaml"
    manifest_path.parent.mkdir()
    manifest_path.write_text("schema_version: 1\n", encoding="utf-8")

    plan = _plan((str(ingest_file), str(asset_file)))

    result = persist_manifest_provenance(
        original_manifest_path=manifest_path,
        plan=plan,
        config=config,
        episode_folder_path=workspace,
    )

    provenance = json.loads(result.provenance_path.read_bytes())
    media = {(m["source_root"], m["source_relative_path"]) for m in provenance["media"]}
    assert media == {
        ("ingest", "EpisodeA/camera.mov"),
        ("assets", "graphics/logo.png"),
    }

    # provenance is resolvable purely from (source_root, source_relative_path)
    # against the *currently configured* roots -- not from the manifest's
    # own (now-irrelevant) original directory.
    for entry in provenance["media"]:
        root = config.paths.ingest_path if entry["source_root"] == "ingest" else config.paths.assets_path
        reconstructed = Path(root) / entry["source_relative_path"]
        assert reconstructed.is_file()


# -- deterministic provenance -----------------------------------------------------


def test_provenance_json_deterministic_for_identical_inputs(tmp_path):
    config = _config(tmp_path)
    ingest_file, asset_file = _seed_media(tmp_path)
    plan = _plan((str(ingest_file), str(asset_file)))

    manifest_path_a = tmp_path / "manifests_a" / "episode.yaml"
    manifest_path_a.parent.mkdir()
    manifest_path_a.write_text("schema_version: 1\n", encoding="utf-8")
    workspace_a = tmp_path / "_episodes" / "RLC-E025"
    for sub in ("footage", "graphics", "audio", "exports", "project"):
        (workspace_a / sub).mkdir(parents=True)

    result_a = persist_manifest_provenance(
        original_manifest_path=manifest_path_a, plan=plan, config=config, episode_folder_path=workspace_a
    )

    # second, independent episode workspace, identical manifest content and media
    manifest_path_b = tmp_path / "manifests_b" / "episode.yaml"
    manifest_path_b.parent.mkdir()
    manifest_path_b.write_text("schema_version: 1\n", encoding="utf-8")
    workspace_b = tmp_path / "_episodes2" / "RLC-E025"
    for sub in ("footage", "graphics", "audio", "exports", "project"):
        (workspace_b / sub).mkdir(parents=True)

    result_b = persist_manifest_provenance(
        original_manifest_path=manifest_path_b, plan=plan, config=config, episode_folder_path=workspace_b
    )

    provenance_a = result_a.provenance_path.read_bytes()
    provenance_b = result_b.provenance_path.read_bytes()
    # original_manifest_path differs (different tmp dirs) by construction;
    # strip that one non-deterministic-by-design field and compare the rest.
    payload_a = json.loads(provenance_a)
    payload_b = json.loads(provenance_b)
    del payload_a["original_manifest_path"]
    del payload_b["original_manifest_path"]
    assert payload_a == payload_b
    assert result_a.manifest_sha256 == result_b.manifest_sha256


# -- missing / unmappable media ----------------------------------------------------


def test_missing_media_root_fails_closed(tmp_path):
    config = _config(tmp_path)
    workspace = _episode_workspace(tmp_path)
    outside_file = tmp_path / "_outside" / "clip.mov"
    outside_file.parent.mkdir()
    outside_file.write_bytes(b"outside-bytes")

    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text("schema_version: 1\n", encoding="utf-8")
    plan = _plan((str(outside_file),))

    with pytest.raises(ManifestProvenanceError):
        persist_manifest_provenance(
            original_manifest_path=manifest_path, plan=plan, config=config, episode_folder_path=workspace
        )

    # nothing partially persisted
    assert not (workspace / "project" / "episode_manifest").exists()


def test_missing_project_subfolder_fails_closed(tmp_path):
    config = _config(tmp_path)
    workspace = tmp_path / "_episodes" / "RLC-E025"
    workspace.mkdir(parents=True)  # deliberately no "project" subfolder
    ingest_file, _ = _seed_media(tmp_path)

    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text("schema_version: 1\n", encoding="utf-8")
    plan = _plan((str(ingest_file),))

    with pytest.raises(ManifestProvenanceError):
        persist_manifest_provenance(
            original_manifest_path=manifest_path, plan=plan, config=config, episode_folder_path=workspace
        )


# -- manifest source mutation during provenance copy --------------------------------


class _MutatedFstat:
    """Fake fstat() result carrying a deliberately-wrong identity field --
    same shape/purpose as test_archive_integrity.py's/test_archive_package.py's
    own helper of this name, since this exercises the identical
    fsutil.open_stable_source() fstat-fingerprint contract."""

    def __init__(self, real, *, mtime_ns_delta: int = 0):
        self.st_mode = real.st_mode
        self.st_size = real.st_size
        self.st_mtime_ns = real.st_mtime_ns + mtime_ns_delta
        self.st_ino = getattr(real, "st_ino", 0)
        self.st_dev = getattr(real, "st_dev", 0)
        if hasattr(real, "st_file_attributes"):
            self.st_file_attributes = real.st_file_attributes


def test_manifest_source_mutation_during_copy_fails_closed(tmp_path, monkeypatch):
    """Deterministic monkeypatch of fsutil.os.fstat, matching the exact
    technique test_archive_package.py already uses to prove
    open_stable_source() detects a mid-stream identity change -- not
    racing threads, and not a pre-open mutation open_stable_source() has
    no prior state to compare against."""
    config = _config(tmp_path)
    workspace = _episode_workspace(tmp_path)
    ingest_file, _ = _seed_media(tmp_path)

    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text("schema_version: 1\n", encoding="utf-8")
    plan = _plan((str(ingest_file),))

    import os

    real_fstat = os.fstat
    target_stat = os.stat(manifest_path)
    call_count = {"n": 0}

    def fake_fstat(fd, *a, **kw):
        real = real_fstat(fd, *a, **kw)
        if getattr(real, "st_ino", None) == target_stat.st_ino and getattr(real, "st_dev", None) == target_stat.st_dev:
            call_count["n"] += 1
            if call_count["n"] == 2:  # second fstat = post-streaming checkpoint
                return _MutatedFstat(real, mtime_ns_delta=1)
        return real

    monkeypatch.setattr(fsutil.os, "fstat", fake_fstat)

    # persist_manifest_provenance() translates the underlying
    # fsutil.SafeFileError into its own ManifestProvenanceError -- the one
    # exception type this module's public function raises for every
    # failure mode (see _copy_manifest_bytes()).
    with pytest.raises(ManifestProvenanceError):
        persist_manifest_provenance(
            original_manifest_path=manifest_path, plan=plan, config=config, episode_folder_path=workspace
        )

    # source untouched -- and, per this repository's established
    # fail-closed convention (matching package.py: never auto-repair or
    # clean up a failed attempt), a partial canonical copy is allowed to
    # remain for forensic inspection rather than being silently deleted;
    # provenance's own already-exists guard means a retry fails closed
    # too rather than silently overwriting it.
    assert manifest_path.is_file()
    assert manifest_path.read_text(encoding="utf-8") == "schema_version: 1\n"


# -- writer duplicate-free media identity invariant -----------------------------------


def test_map_media_paths_produces_exactly_one_entry_per_identity(tmp_path):
    """Normally generated build provenance -- distinct validated media
    paths -- must contain exactly one entry per normalized
    (source_root, source_relative_path) identity. No collapsing, no
    surprise loss: entry count matches input count exactly."""
    config = _config(tmp_path)
    ingest_file, asset_file = _seed_media(tmp_path)

    entries = map_media_paths_to_approved_roots((str(ingest_file), str(asset_file)), config)

    assert len(entries) == 2
    identities = {(e["source_root"], e["source_relative_path"].casefold()) for e in entries}
    assert len(identities) == len(entries)
    assert identities == {("ingest", "episodea/camera.mov"), ("assets", "graphics/logo.png")}


def test_map_media_paths_fails_closed_on_case_equivalent_duplicate_identity(tmp_path):
    """Defensive writer invariant (Mission 15E.2 narrow correction):
    `validate_manifest()`'s own duplicate-media-path guard is only
    case-insensitive on Windows, but this function's downstream identity
    is *always* case-folded (Archive Rev1 targets a Windows production
    filesystem regardless of which OS builds the inventory). Two distinct
    resolved media paths that collide once case-folded must therefore be
    rejected here rather than silently persisted as two provenance
    entries that would collide on restore."""
    config = _config(tmp_path)
    ingest_dir = tmp_path / "_ingest" / "EpisodeA"
    ingest_dir.mkdir(parents=True)

    # Two distinct (never-touched-on-disk, path-arithmetic-only) resolved
    # media paths differing only by case -- map_media_paths_to_approved_roots()
    # does not read file bytes, only resolves and maps paths, so no real
    # filesystem case-sensitivity is required to exercise this.
    lower_path = ingest_dir / "camera.mov"
    upper_path = ingest_dir / "CAMERA.MOV"

    with pytest.raises(ManifestProvenanceError):
        map_media_paths_to_approved_roots((str(lower_path), str(upper_path)), config)


# -- no build success without required provenance -----------------------------------


def test_provenance_persistence_failure_is_not_silently_ignored(tmp_path):
    """persist_manifest_provenance() itself must raise (not return a
    partial/degraded result) when it cannot safely complete -- callers
    (BuildOrchestrator) rely on this to avoid ever reporting a successful
    build without required provenance."""
    config = _config(tmp_path)
    workspace = _episode_workspace(tmp_path)
    ingest_file, _ = _seed_media(tmp_path)

    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text("schema_version: 1\n", encoding="utf-8")
    plan = _plan((str(ingest_file),))

    # First call succeeds and persists canonical provenance.
    persist_manifest_provenance(
        original_manifest_path=manifest_path, plan=plan, config=config, episode_folder_path=workspace
    )

    # A second call for the same (already-provenanced) episode must fail
    # closed rather than silently overwrite/return a half-formed result.
    with pytest.raises(ManifestProvenanceError):
        persist_manifest_provenance(
            original_manifest_path=manifest_path, plan=plan, config=config, episode_folder_path=workspace
        )
