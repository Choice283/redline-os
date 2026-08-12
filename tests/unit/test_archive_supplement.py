"""Phase 15 Mission 15G -- tests for redline_core.archive.supplement:
the package-plan/supplement models, and the identity boundary that
supplements must never influence content_set_digest/archive_id.

Scope: redline_core.archive.supplement only. No DB, no CLI, no MCP, no
Resolve, no production media.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from redline_core.archive.content import ArchiveArtifact, ArchiveSourceKind, build_content_plan
from redline_core.archive.integrity import build_source_inventory
from redline_core.archive.supplement import (
    ArchiveSupplementKind,
    ArchiveSupplementPlanError,
    FileArchiveSupplement,
    GeneratedArchiveSupplement,
    build_generated_supplement,
    build_package_plan,
    supplement_kind,
)


def _make_content_plan(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_bytes(b"hello")
    inventory = build_source_inventory(workspace)
    return build_content_plan(inventory, ())


# -- GeneratedArchiveSupplement / build_generated_supplement ----------------------


def test_build_generated_supplement_computes_fingerprint():
    supplement = build_generated_supplement(
        archive_relative_path="metadata/episode.json",
        canonical_bytes=b'{"a":1}',
        classifications=("generated_metadata",),
        source_kind="generated_metadata",
    )
    assert supplement.sha256 == hashlib.sha256(b'{"a":1}').hexdigest()
    assert supplement.size_bytes == len(b'{"a":1}')
    assert supplement_kind(supplement) == ArchiveSupplementKind.GENERATED


def test_generated_supplement_rejects_mismatched_sha256():
    with pytest.raises(ArchiveSupplementPlanError):
        GeneratedArchiveSupplement(
            archive_relative_path="metadata/episode.json",
            canonical_bytes=b"abc",
            size_bytes=3,
            sha256="0" * 64,
            classifications=("generated_metadata",),
            source_kind="generated_metadata",
        )


def test_generated_supplement_rejects_mismatched_size():
    with pytest.raises(ArchiveSupplementPlanError):
        GeneratedArchiveSupplement(
            archive_relative_path="metadata/episode.json",
            canonical_bytes=b"abc",
            size_bytes=99,
            sha256=hashlib.sha256(b"abc").hexdigest(),
            classifications=("generated_metadata",),
            source_kind="generated_metadata",
        )


def test_generated_supplement_rejects_empty_classifications():
    with pytest.raises(ArchiveSupplementPlanError):
        build_generated_supplement(
            archive_relative_path="metadata/episode.json",
            canonical_bytes=b"abc",
            classifications=(),
            source_kind="generated_metadata",
        )


@pytest.mark.parametrize("bad_path", ["", "/absolute/path.json"])
def test_generated_supplement_rejects_bad_archive_relative_path(bad_path):
    with pytest.raises(ArchiveSupplementPlanError):
        build_generated_supplement(
            archive_relative_path=bad_path,
            canonical_bytes=b"abc",
            classifications=("generated_metadata",),
            source_kind="generated_metadata",
        )


# -- FileArchiveSupplement --------------------------------------------------------


def test_file_supplement_kind(tmp_path):
    supplement = FileArchiveSupplement(
        absolute_source_path=tmp_path / "evidence.json",
        archive_relative_path="external/evidence/render/evidence.json",
        size_bytes=10,
        sha256="a" * 64,
        classifications=("production_evidence",),
        source_kind="render_queue_snapshot",
    )
    assert supplement_kind(supplement) == ArchiveSupplementKind.FILE


def test_file_supplement_rejects_empty_classifications(tmp_path):
    with pytest.raises(ArchiveSupplementPlanError):
        FileArchiveSupplement(
            absolute_source_path=tmp_path / "evidence.json",
            archive_relative_path="external/evidence/render/evidence.json",
            size_bytes=10,
            sha256="a" * 64,
            classifications=(),
            source_kind="render_queue_snapshot",
        )


# -- build_package_plan -----------------------------------------------------------


def test_build_package_plan_success(tmp_path):
    plan = _make_content_plan(tmp_path)
    supplement = build_generated_supplement(
        archive_relative_path="metadata/episode.json",
        canonical_bytes=b'{"a":1}',
        classifications=("generated_metadata",),
        source_kind="generated_metadata",
    )
    package_plan = build_package_plan(plan, (supplement,))
    assert package_plan.content is plan
    assert package_plan.supplements == (supplement,)


def test_build_package_plan_sorts_deterministically(tmp_path):
    plan = _make_content_plan(tmp_path)
    supplement_z = build_generated_supplement(
        archive_relative_path="metadata/z.json", canonical_bytes=b"1", classifications=("generated_metadata",), source_kind="generated_metadata"
    )
    supplement_a = build_generated_supplement(
        archive_relative_path="metadata/a.json", canonical_bytes=b"1", classifications=("generated_metadata",), source_kind="generated_metadata"
    )
    package_plan = build_package_plan(plan, (supplement_z, supplement_a))
    assert [s.archive_relative_path for s in package_plan.supplements] == ["metadata/a.json", "metadata/z.json"]


def test_build_package_plan_requires_content_plan_instance(tmp_path):
    with pytest.raises(ArchiveSupplementPlanError):
        build_package_plan("not-a-plan", ())


def test_build_package_plan_rejects_duplicate_supplement_paths(tmp_path):
    plan = _make_content_plan(tmp_path)
    supplement_a = build_generated_supplement(
        archive_relative_path="metadata/episode.json", canonical_bytes=b"1", classifications=("generated_metadata",), source_kind="generated_metadata"
    )
    supplement_b = build_generated_supplement(
        archive_relative_path="metadata/episode.json", canonical_bytes=b"2", classifications=("generated_metadata",), source_kind="generated_metadata"
    )
    with pytest.raises(ArchiveSupplementPlanError):
        build_package_plan(plan, (supplement_a, supplement_b))


def test_build_package_plan_rejects_supplement_colliding_with_workspace_path(tmp_path):
    plan = _make_content_plan(tmp_path)
    colliding = build_generated_supplement(
        archive_relative_path="workspace/a.txt", canonical_bytes=b"1", classifications=("generated_metadata",), source_kind="generated_metadata"
    )
    with pytest.raises(ArchiveSupplementPlanError):
        build_package_plan(plan, (colliding,))


def test_build_package_plan_rejects_supplement_colliding_with_external_artifact_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_bytes(b"hello")
    inventory = build_source_inventory(workspace)

    external_file = tmp_path / "manifest.yaml"
    external_file.write_bytes(b"schema_version: 1\n")
    from redline_core.archive.integrity import hash_stable_file

    sha256, size_bytes = hash_stable_file(external_file)
    artifact = ArchiveArtifact(
        absolute_source_path=external_file,
        archive_relative_path="external/episode_manifest/manifest.yaml",
        size_bytes=size_bytes,
        sha256=sha256,
        classifications=("episode_manifest",),
        source_kind=ArchiveSourceKind.EPISODE_MANIFEST,
    )
    plan = build_content_plan(inventory, (artifact,))

    colliding = build_generated_supplement(
        archive_relative_path="external/episode_manifest/manifest.yaml",
        canonical_bytes=b"x",
        classifications=("generated_metadata",),
        source_kind="generated_metadata",
    )
    with pytest.raises(ArchiveSupplementPlanError):
        build_package_plan(plan, (colliding,))


# -- identity boundary: supplements never affect content_set_digest/archive_id ----


def test_supplements_never_affect_content_set_digest(tmp_path):
    """Mission 15G's core identity requirement: same ArchiveContentPlan +
    different supplements -> same content_set_digest. Supplements are
    package-plan-level, never read by content.compute_content_set_digest()
    or embedded in ArchiveContentPlan at all."""
    plan = _make_content_plan(tmp_path)
    original_digest = plan.content_set_digest

    supplement_1 = build_generated_supplement(
        archive_relative_path="metadata/episode.json", canonical_bytes=b'{"a":1}', classifications=("generated_metadata",), source_kind="generated_metadata"
    )
    supplement_2 = build_generated_supplement(
        archive_relative_path="metadata/episode.json", canonical_bytes=b'{"a":2}', classifications=("generated_metadata",), source_kind="generated_metadata"
    )

    package_plan_1 = build_package_plan(plan, (supplement_1,))
    package_plan_2 = build_package_plan(plan, (supplement_2,))
    package_plan_empty = build_package_plan(plan, ())

    assert package_plan_1.content.content_set_digest == original_digest
    assert package_plan_2.content.content_set_digest == original_digest
    assert package_plan_empty.content.content_set_digest == original_digest
