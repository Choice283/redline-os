"""Phase 15 Mission 15E.2 -- complete-content-plan tests, exercising
`redline_core.archive.content` and the extended `redline_core.archive.package`
directly (no DB, no ArchiveManager, no Resolve). ArchiveManager-level
provenance discovery / legacy-fallback / render-master tests live in
test_archive_manager.py; Mission 15D's workspace-only package tests live
in test_archive_package.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redline_core.archive import package
from redline_core.archive.content import (
    ArchiveArtifact,
    ArchiveContentPlanError,
    ArchiveSourceKind,
    build_content_plan,
    compute_content_set_digest,
)
from redline_core.archive.exceptions import ArchiveSourceChangedError
from redline_core.archive.integrity import build_source_inventory
from redline_core.archive.manager import ArchiveManager

_FIXED_CLOCK = lambda: datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# -- helpers ------------------------------------------------------------------


def _workspace_inventory(tmp_path: Path, name: str = "workspace"):
    root = tmp_path / name
    (root / "exports").mkdir(parents=True)
    (root / "exports" / "master.mov").write_bytes(b"master-content")
    return root, build_source_inventory(root)


def _media_artifact(path: Path, *, archive_relative_path: str, source_root: str, source_relative_path: str) -> ArchiveArtifact:
    from redline_core import fsutil

    sha256, size_bytes = fsutil.hash_stable_file(path)
    return ArchiveArtifact(
        absolute_source_path=path.resolve(),
        archive_relative_path=archive_relative_path,
        size_bytes=size_bytes,
        sha256=sha256,
        classifications=("source_media",),
        source_kind=ArchiveSourceKind.SOURCE_MEDIA,
        source_root=source_root,
        source_relative_path=source_relative_path,
    )


# -- dedup / classification semantics ------------------------------------------------


def test_root_mapping_distinct_basenames_do_not_collide(tmp_path):
    _, inventory = _workspace_inventory(tmp_path)

    ingest_file = tmp_path / "_ingest" / "a" / "file.mov"
    ingest_file.parent.mkdir(parents=True)
    ingest_file.write_bytes(b"ingest-bytes")
    asset_file = tmp_path / "_assets" / "b" / "file.mov"
    asset_file.parent.mkdir(parents=True)
    asset_file.write_bytes(b"asset-bytes")

    artifact_a = _media_artifact(
        ingest_file, archive_relative_path="external/source_media/ingest/a/file.mov", source_root="ingest", source_relative_path="a/file.mov"
    )
    artifact_b = _media_artifact(
        asset_file, archive_relative_path="external/source_media/assets/b/file.mov", source_root="assets", source_relative_path="b/file.mov"
    )

    plan = build_content_plan(inventory, (artifact_a, artifact_b))
    assert {a.archive_relative_path for a in plan.artifacts} == {
        "external/source_media/ingest/a/file.mov",
        "external/source_media/assets/b/file.mov",
    }


def test_same_hash_different_paths_remain_two_artifacts(tmp_path):
    _, inventory = _workspace_inventory(tmp_path)

    file_a = tmp_path / "_ingest" / "a.mov"
    file_a.parent.mkdir(parents=True)
    file_a.write_bytes(b"identical-bytes")
    file_b = tmp_path / "_assets" / "b.mov"
    file_b.parent.mkdir(parents=True)
    file_b.write_bytes(b"identical-bytes")  # same content, different physical path

    artifact_a = _media_artifact(
        file_a, archive_relative_path="external/source_media/ingest/a.mov", source_root="ingest", source_relative_path="a.mov"
    )
    artifact_b = _media_artifact(
        file_b, archive_relative_path="external/source_media/assets/b.mov", source_root="assets", source_relative_path="b.mov"
    )
    assert artifact_a.sha256 == artifact_b.sha256  # same hash

    plan = build_content_plan(inventory, (artifact_a, artifact_b))
    assert len(plan.artifacts) == 2  # never collapsed by hash alone


def test_same_physical_path_multiple_classifications_single_artifact(tmp_path):
    workspace_root, inventory = _workspace_inventory(tmp_path)
    master_file = inventory.files[0]

    overlay = ArchiveArtifact(
        absolute_source_path=master_file.absolute_source_path,
        archive_relative_path=f"workspace/{master_file.relative_path}",
        size_bytes=master_file.size_bytes,
        sha256=master_file.sha256,
        classifications=("workspace", "render_master", "episode_manifest"),
        source_kind=ArchiveSourceKind.WORKSPACE,
    )
    plan = build_content_plan(inventory, (overlay,))
    assert len(plan.artifacts) == 1
    assert set(plan.artifacts[0].classifications) == {"workspace", "render_master", "episode_manifest"}


def test_duplicate_absolute_path_across_artifacts_rejected(tmp_path):
    _, inventory = _workspace_inventory(tmp_path)
    media_file = tmp_path / "_ingest" / "clip.mov"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"clip-bytes")

    artifact_a = _media_artifact(
        media_file, archive_relative_path="external/source_media/ingest/clip.mov", source_root="ingest", source_relative_path="clip.mov"
    )
    artifact_b = _media_artifact(
        media_file, archive_relative_path="external/source_media/ingest/clip_alias.mov", source_root="ingest", source_relative_path="clip.mov"
    )

    with pytest.raises(ArchiveContentPlanError):
        build_content_plan(inventory, (artifact_a, artifact_b))


def test_duplicate_archive_relative_path_rejected(tmp_path):
    _, inventory = _workspace_inventory(tmp_path)
    file_a = tmp_path / "_ingest" / "a.mov"
    file_a.parent.mkdir(parents=True)
    file_a.write_bytes(b"a-bytes")
    file_b = tmp_path / "_ingest" / "b.mov"
    file_b.write_bytes(b"b-bytes")

    artifact_a = _media_artifact(
        file_a, archive_relative_path="external/source_media/ingest/same.mov", source_root="ingest", source_relative_path="a.mov"
    )
    artifact_b = _media_artifact(
        file_b, archive_relative_path="external/source_media/ingest/same.mov", source_root="ingest", source_relative_path="b.mov"
    )

    with pytest.raises(ArchiveContentPlanError):
        build_content_plan(inventory, (artifact_a, artifact_b))


# -- aggregate digest ---------------------------------------------------------------


def test_content_set_digest_changes_when_workspace_bytes_change(tmp_path):
    root_a, inventory_a = _workspace_inventory(tmp_path, "workspace_a")
    plan_a = build_content_plan(inventory_a, ())

    root_b, _ = _workspace_inventory(tmp_path, "workspace_b")
    (root_b / "exports" / "master.mov").write_bytes(b"different-content")
    inventory_b = build_source_inventory(root_b)
    plan_b = build_content_plan(inventory_b, ())

    assert plan_a.content_set_digest != plan_b.content_set_digest


def test_content_set_digest_changes_when_workspace_topology_changes(tmp_path):
    root_a, inventory_a = _workspace_inventory(tmp_path, "workspace_a")
    plan_a = build_content_plan(inventory_a, ())

    root_b, _ = _workspace_inventory(tmp_path, "workspace_b")
    (root_b / "exports" / "extra.mov").write_bytes(b"extra")
    inventory_b = build_source_inventory(root_b)
    plan_b = build_content_plan(inventory_b, ())

    assert plan_a.content_set_digest != plan_b.content_set_digest


def test_content_set_digest_changes_when_external_media_bytes_change(tmp_path):
    _, inventory = _workspace_inventory(tmp_path)
    media_a = tmp_path / "_ingest" / "clip.mov"
    media_a.parent.mkdir(parents=True)
    media_a.write_bytes(b"version-1")
    artifact_a = _media_artifact(media_a, archive_relative_path="external/source_media/ingest/clip.mov", source_root="ingest", source_relative_path="clip.mov")
    plan_a = build_content_plan(inventory, (artifact_a,))

    media_a.write_bytes(b"version-2-different-length")
    artifact_b = _media_artifact(media_a, archive_relative_path="external/source_media/ingest/clip.mov", source_root="ingest", source_relative_path="clip.mov")
    plan_b = build_content_plan(inventory, (artifact_b,))

    assert plan_a.content_set_digest != plan_b.content_set_digest


def test_content_set_digest_changes_when_external_media_logical_path_changes(tmp_path):
    _, inventory = _workspace_inventory(tmp_path)
    media = tmp_path / "_ingest" / "clip.mov"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"clip-bytes")

    artifact_a = _media_artifact(media, archive_relative_path="external/source_media/ingest/clip.mov", source_root="ingest", source_relative_path="clip.mov")
    artifact_b = _media_artifact(media, archive_relative_path="external/source_media/ingest/renamed.mov", source_root="ingest", source_relative_path="renamed.mov")

    plan_a = build_content_plan(inventory, (artifact_a,))
    plan_b = build_content_plan(inventory, (artifact_b,))

    assert plan_a.content_set_digest != plan_b.content_set_digest


def test_content_set_digest_changes_when_classification_changes(tmp_path):
    _, inventory = _workspace_inventory(tmp_path)
    master_file = inventory.files[0]

    overlay_a = ArchiveArtifact(
        absolute_source_path=master_file.absolute_source_path,
        archive_relative_path=f"workspace/{master_file.relative_path}",
        size_bytes=master_file.size_bytes,
        sha256=master_file.sha256,
        classifications=("workspace",),
        source_kind=ArchiveSourceKind.WORKSPACE,
    )
    overlay_b = ArchiveArtifact(
        absolute_source_path=master_file.absolute_source_path,
        archive_relative_path=f"workspace/{master_file.relative_path}",
        size_bytes=master_file.size_bytes,
        sha256=master_file.sha256,
        classifications=("workspace", "render_master"),
        source_kind=ArchiveSourceKind.WORKSPACE,
    )

    digest_a = compute_content_set_digest(inventory.source_set_digest, (overlay_a,))
    digest_b = compute_content_set_digest(inventory.source_set_digest, (overlay_b,))
    assert digest_a != digest_b


def test_content_set_digest_stable_when_absolute_root_relocates_but_logical_identity_unchanged(tmp_path):
    """Two artifacts with different absolute_source_path (simulating an
    approved root that relocated) but identical archive_relative_path/
    source_root/source_relative_path/size/sha256/classifications/source_kind
    must produce the *same* digest -- absolute_source_path is provenance-
    only, never part of content identity (Mission 15E.2 item 20)."""
    _, inventory = _workspace_inventory(tmp_path)

    old_root_media = tmp_path / "_ingest_old" / "clip.mov"
    old_root_media.parent.mkdir(parents=True)
    old_root_media.write_bytes(b"stable-bytes")
    new_root_media = tmp_path / "_ingest_new" / "clip.mov"
    new_root_media.parent.mkdir(parents=True)
    new_root_media.write_bytes(b"stable-bytes")

    artifact_old = _media_artifact(old_root_media, archive_relative_path="external/source_media/ingest/clip.mov", source_root="ingest", source_relative_path="clip.mov")
    artifact_new = _media_artifact(new_root_media, archive_relative_path="external/source_media/ingest/clip.mov", source_root="ingest", source_relative_path="clip.mov")

    assert artifact_old.absolute_source_path != artifact_new.absolute_source_path

    digest_old = compute_content_set_digest(inventory.source_set_digest, (artifact_old,))
    digest_new = compute_content_set_digest(inventory.source_set_digest, (artifact_new,))
    assert digest_old == digest_new


# -- archive ID -----------------------------------------------------------------------


def test_archive_id_deterministic_and_content_bound():
    same_id_a = ArchiveManager._derive_archive_id("RLC-E025", "abc123def456abc123def456")
    same_id_b = ArchiveManager._derive_archive_id("RLC-E025", "abc123def456abc123def456")
    different_id = ArchiveManager._derive_archive_id("RLC-E025", "000000000000000000000000")

    assert same_id_a == same_id_b == "RLC-E025-a1-abc123def456"
    assert same_id_a != different_id


# -- complete package (workspace + external source media + legacy manifest) ----------


def test_complete_package_layout_manifest_and_publication(tmp_path):
    workspace_root, inventory = _workspace_inventory(tmp_path)
    (workspace_root / "footage").mkdir()
    (workspace_root / "footage" / "clip.mov").write_bytes(b"workspace-clip")
    inventory = build_source_inventory(workspace_root)

    ingest_media = tmp_path / "_ingest" / "EpisodeA" / "camera.mov"
    ingest_media.parent.mkdir(parents=True)
    ingest_media.write_bytes(b"ingest-camera-bytes")
    asset_media = tmp_path / "_assets" / "graphics" / "logo.png"
    asset_media.parent.mkdir(parents=True)
    asset_media.write_bytes(b"asset-logo-bytes")
    legacy_manifest = tmp_path / "_legacy" / "episode.yaml"
    legacy_manifest.parent.mkdir(parents=True)
    # newline="" avoids Windows' \n -> \r\n text-mode translation, so the
    # byte-for-byte assertions below compare against the real on-disk bytes.
    legacy_manifest.write_text("schema_version: 1\n", encoding="utf-8", newline="")

    from redline_core import fsutil

    manifest_sha256, manifest_size = fsutil.hash_stable_file(legacy_manifest)
    legacy_artifact = ArchiveArtifact(
        absolute_source_path=legacy_manifest.resolve(),
        archive_relative_path="external/episode_manifest/episode.yaml",
        size_bytes=manifest_size,
        sha256=manifest_sha256,
        classifications=("episode_manifest",),
        source_kind=ArchiveSourceKind.EPISODE_MANIFEST,
    )
    ingest_artifact = _media_artifact(
        ingest_media, archive_relative_path="external/source_media/ingest/EpisodeA/camera.mov", source_root="ingest", source_relative_path="EpisodeA/camera.mov"
    )
    asset_artifact = _media_artifact(
        asset_media, archive_relative_path="external/source_media/assets/graphics/logo.png", source_root="assets", source_relative_path="graphics/logo.png"
    )

    plan = build_content_plan(inventory, (legacy_artifact, ingest_artifact, asset_artifact))
    archive_root = tmp_path / "_archive_root"

    result = package.build_archive_package(
        plan, episode_id="EP0300", archive_id="ARC0300", archive_root=archive_root, clock=_FIXED_CLOCK
    )

    payload = result.final_path / "payload"
    assert (payload / "workspace" / "exports" / "master.mov").read_bytes() == b"master-content"
    assert (payload / "workspace" / "footage" / "clip.mov").read_bytes() == b"workspace-clip"
    assert (payload / "external" / "source_media" / "ingest" / "EpisodeA" / "camera.mov").read_bytes() == b"ingest-camera-bytes"
    assert (payload / "external" / "source_media" / "assets" / "graphics" / "logo.png").read_bytes() == b"asset-logo-bytes"
    assert (payload / "external" / "episode_manifest" / "episode.yaml").read_bytes() == b"schema_version: 1\n"

    manifest = json.loads((result.final_path / "archive_manifest.json").read_bytes())
    archive_relative_paths = {a["archive_relative_path"] for a in manifest["artifacts"]}
    assert archive_relative_paths == {
        "workspace/exports/master.mov",
        "workspace/footage/clip.mov",
        "external/source_media/ingest/EpisodeA/camera.mov",
        "external/source_media/assets/graphics/logo.png",
        "external/episode_manifest/episode.yaml",
    }
    by_path = {a["archive_relative_path"]: a for a in manifest["artifacts"]}
    assert by_path["external/source_media/ingest/EpisodeA/camera.mov"]["source_root"] == "ingest"
    assert by_path["external/source_media/ingest/EpisodeA/camera.mov"]["source_relative_path"] == "EpisodeA/camera.mov"
    assert manifest["content"]["content_set_digest"] == plan.content_set_digest

    assert (result.final_path / "PACKAGE_COMPLETE").is_file()
    assert not result.final_path.with_name(result.final_path.name + ".partial").exists()

    # source untouched
    assert workspace_root.is_dir()
    assert ingest_media.read_bytes() == b"ingest-camera-bytes"
    assert asset_media.read_bytes() == b"asset-logo-bytes"
    assert legacy_manifest.read_bytes() == b"schema_version: 1\n"


# -- external source mutation --------------------------------------------------------


def test_external_media_mutation_after_planning_before_copy_fails_closed(tmp_path):
    _, inventory = _workspace_inventory(tmp_path)
    media = tmp_path / "_ingest" / "clip.mov"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"original-bytes")

    artifact = _media_artifact(media, archive_relative_path="external/source_media/ingest/clip.mov", source_root="ingest", source_relative_path="clip.mov")
    plan = build_content_plan(inventory, (artifact,))

    media.write_bytes(b"mutated-before-copy-longer")
    archive_root = tmp_path / "_archive_root"

    with pytest.raises(ArchiveSourceChangedError):
        package.build_archive_package(
            plan, episode_id="EP0301", archive_id="ARC0301", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    assert not (archive_root / "episodes").exists()
    assert media.read_bytes() == b"mutated-before-copy-longer"  # test's own mutation preserved


def test_external_media_mutation_after_copy_before_final_reconciliation_fails_closed(tmp_path):
    _, inventory = _workspace_inventory(tmp_path)
    media = tmp_path / "_ingest" / "clip.mov"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"original-bytes")

    artifact = _media_artifact(media, archive_relative_path="external/source_media/ingest/clip.mov", source_root="ingest", source_relative_path="clip.mov")
    plan = build_content_plan(inventory, (artifact,))
    archive_root = tmp_path / "_archive_root"

    staged = package.build_staged_package(
        plan, episode_id="EP0302", archive_id="ARC0302", archive_root=archive_root, clock=_FIXED_CLOCK
    )

    # mutate the external SOURCE (not the copied payload) after the
    # staged package was already successfully sealed
    media.write_bytes(b"mutated-after-sealing-longer")

    with pytest.raises(ArchiveSourceChangedError):
        package.publish_package(staged)

    assert not staged.final_path.exists()
    assert media.read_bytes() == b"mutated-after-sealing-longer"
