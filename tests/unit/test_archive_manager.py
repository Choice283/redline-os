"""Tests for ArchiveManager Rev1 orchestration (Phase 15 Mission 15E),
extended by Mission 15E.2 to the complete-content-plan contract: canonical
manifest provenance discovery, the legacy manifest_path fallback, and the
render-master InventoryFile correction. Against a temp DB, a synthetic
workspace/ingest/assets tree under tmp_path, and a synthetic archive root
under tmp_path -- no Resolve involved anywhere in this file.
"""
from __future__ import annotations

import ast
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redline_core.archive import integrity
from redline_core.archive.exceptions import (
    ArchiveDestinationCollisionError,
    ArchiveEligibilityError,
    ArchiveLegacyRecordError,
    ArchiveManifestMismatchError,
    ArchiveManifestProvenanceError,
    ArchiveNotFoundError,
    ArchivePackageVerificationError,
    ArchivePathError,
    ArchiveRenderSelectionError,
    ArchiveVerifiedUnregisteredError,
    EpisodeAlreadyArchivedError,
)
from redline_core.archive.manager import (
    ArchiveManager,
    ArchiveResult,
    ArchiveVerificationResult,
    _find_inventory_file_by_absolute_path,
)
from redline_core.build.manifest_provenance import persist_manifest_provenance
from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.db.database import ArchiveCommitError, Database
from redline_core.db.models import ArchiveState, EpisodeStatus, RenderJobStatus
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.manifest.models import ValidatedEpisodePlan

_FIXED_MOMENT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_WORKSPACE_SUBFOLDERS = ("footage", "graphics", "audio", "exports", "project")


# -- helpers ------------------------------------------------------------------


def make_manager(tmp_path: Path, *, clock=None):
    config = RedlineConfig(
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
    db = Database(tmp_path / "test.db").connect()
    db.init_schema()
    kwargs = {"clock": clock} if clock is not None else {}
    return ArchiveManager(config, db, **kwargs), db, config


def seed_workspace(tmp_path: Path, episode_id: str) -> Path:
    folder = tmp_path / "_episodes" / episode_id
    for sub in _WORKSPACE_SUBFOLDERS:
        (folder / sub).mkdir(parents=True)
    (folder / "footage" / "clip1.mov").write_bytes(b"raw-footage")
    return folder


def seed_media(tmp_path: Path, *, name: str = "camera") -> tuple[Path, Path]:
    ingest_file = tmp_path / "_ingest" / "EpisodeA" / f"{name}.mov"
    ingest_file.parent.mkdir(parents=True, exist_ok=True)
    ingest_file.write_bytes(f"{name}-ingest-bytes".encode())

    asset_file = tmp_path / "_assets" / "graphics" / f"{name}_logo.png"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(f"{name}-logo-bytes".encode())

    return ingest_file, asset_file


def seed_canonical_provenance(
    config: RedlineConfig, workspace: Path, episode_id: str, media_paths: tuple[Path, ...], tmp_path: Path
) -> None:
    manifest_src = tmp_path / "_source_manifests" / f"{episode_id}.yaml"
    manifest_src.parent.mkdir(parents=True, exist_ok=True)
    manifest_src.write_text(f"schema_version: 1\nepisode:\n  id: {episode_id}\n", encoding="utf-8", newline="")
    plan = ValidatedEpisodePlan(episode_id=episode_id, media_paths=tuple(str(p) for p in media_paths))
    persist_manifest_provenance(
        original_manifest_path=manifest_src, plan=plan, config=config, episode_folder_path=workspace
    )


def seed_rendered_episode(
    db: Database,
    config: RedlineConfig,
    tmp_path: Path,
    *,
    episode_number: int = 25,
    episode_id: str = "RLC-E025",
    render_status: RenderJobStatus = RenderJobStatus.COMPLETE,
    with_provenance: bool = True,
):
    """Seed a fully Rev1-eligible episode: created, real workspace on disk
    (with a "project" subfolder, matching production folder_structure),
    folder_path set, episode.status forced to RENDERED, one render job at
    `render_status` whose output is a real file inside that workspace,
    and (unless `with_provenance=False`, for legacy-episode tests)
    canonical manifest provenance referencing real ingest/assets media."""
    db.create_episode(episode_number, episode_id, f"{episode_id}_MASTER")
    folder = seed_workspace(tmp_path, episode_id)
    db.update_episode_paths(episode_id, folder_path=str(folder))
    db.update_episode_status(episode_id, EpisodeStatus.RENDERED)

    output_path = folder / "exports" / f"{episode_id}_MASTER.mov"
    output_path.write_bytes(b"rendered-master-bytes")

    render_job = db.create_render_job(
        episode_id,
        "broadcast_master",
        resolve_job_id=f"resolve-{episode_id}",
        project_name=f"{episode_id}_MASTER",
        timeline_name=f"{episode_id}_TIMELINE",
        output_path=str(output_path),
        status=render_status,
    )

    ingest_file, asset_file = seed_media(tmp_path, name=episode_id)
    if with_provenance:
        seed_canonical_provenance(config, folder, episode_id, (ingest_file, asset_file), tmp_path)

    return folder, render_job, (ingest_file, asset_file)


# -- successful archive ---------------------------------------------------------


def test_create_archive_success(tmp_path):
    """Full success proof: source preserved, complete package verified
    (workspace + external media + manifest), DB row complete/schema1,
    episode archived, render job unchanged. Also the "exactly one
    completed render job -> auto-selected" case."""
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, render_job, (ingest_file, asset_file) = seed_rendered_episode(db, config, tmp_path)
    original_folder_path = db.get_episode_by_episode_id("RLC-E025").folder_path

    result = manager.create_archive("RLC-E025")

    # source preserved, byte-identical
    assert folder.is_dir()
    assert (folder / "footage" / "clip1.mov").read_bytes() == b"raw-footage"
    assert (folder / "exports" / "RLC-E025_MASTER.mov").read_bytes() == b"rendered-master-bytes"
    assert ingest_file.is_file()
    assert asset_file.is_file()

    # package verified: workspace + external media + manifest
    assert result.archive_path.is_dir()
    assert (result.archive_path / "PACKAGE_COMPLETE").is_file()
    manifest = json.loads((result.archive_path / "archive_manifest.json").read_bytes())
    assert manifest["schema_version"] == 1
    assert manifest["archive_id"] == result.archive_id
    assert manifest["episode_id"] == "RLC-E025"
    assert manifest["content"]["content_set_digest"] == result.content_set_digest

    archive_relative_paths = {a["archive_relative_path"] for a in manifest["artifacts"]}
    assert "workspace/exports/RLC-E025_MASTER.mov" in archive_relative_paths
    assert "workspace/project/episode_manifest/RLC-E025.yaml" in archive_relative_paths
    assert "workspace/project/episode_manifest/manifest_provenance.json" in archive_relative_paths
    assert "external/source_media/ingest/EpisodeA/RLC-E025.mov" in archive_relative_paths
    assert "external/source_media/assets/graphics/RLC-E025_logo.png" in archive_relative_paths

    by_path = {a["archive_relative_path"]: a for a in manifest["artifacts"]}
    assert by_path["workspace/exports/RLC-E025_MASTER.mov"]["classifications"] == ["render_master", "workspace"]
    assert by_path["workspace/project/episode_manifest/RLC-E025.yaml"]["classifications"] == [
        "episode_manifest",
        "workspace",
    ]

    # DB row: complete, schema version 1
    archive_record = db.get_archive_by_episode_id("RLC-E025")
    assert archive_record.archive_state == ArchiveState.COMPLETE
    assert archive_record.archive_schema_version == 1
    assert archive_record.archive_id == result.archive_id
    assert archive_record.render_job_id == render_job.id
    assert archive_record.manifest_sha256 == result.manifest_sha256

    # episode archived, folder_path unchanged
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.status == EpisodeStatus.ARCHIVED
    assert episode.folder_path == original_folder_path

    # render job untouched
    reloaded_job = db.get_render_job_by_id(render_job.id)
    assert reloaded_job.status == RenderJobStatus.COMPLETE

    # result fields
    assert result.episode_id == "RLC-E025"
    assert result.render_job_id == render_job.id
    assert result.archive_id == f"RLC-E025-a1-{result.content_set_digest[:12]}"


def test_create_archive_leaves_folder_path_exactly_unchanged(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, _, _ = seed_rendered_episode(db, config, tmp_path)
    before = db.get_episode_by_episode_id("RLC-E025").folder_path

    manager.create_archive("RLC-E025")

    after = db.get_episode_by_episode_id("RLC-E025").folder_path
    assert after == before == str(folder)


def test_list_archives(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path, episode_number=25, episode_id="RLC-E025")
    seed_rendered_episode(db, config, tmp_path, episode_number=26, episode_id="RLC-E026")

    manager.create_archive("RLC-E025")
    manager.create_archive("RLC-E026")

    archives = manager.list_archives()
    assert {a.episode_id for a in archives} == {"RLC-E025", "RLC-E026"}
    assert all(a.archive_state == ArchiveState.COMPLETE for a in archives)


# -- eligibility failures ---------------------------------------------------------


def test_create_archive_unknown_episode_raises(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    with pytest.raises(EpisodeNotFoundError):
        manager.create_archive("RLC-E999")


@pytest.mark.parametrize("status", [EpisodeStatus.CREATED, EpisodeStatus.ASSEMBLED, EpisodeStatus.RENDER_QUEUED])
def test_create_archive_rejects_non_rendered_episode(tmp_path, status):
    manager, db, config = make_manager(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    folder = seed_workspace(tmp_path, "RLC-E025")
    db.update_episode_paths("RLC-E025", folder_path=str(folder))
    db.update_episode_status("RLC-E025", status)

    with pytest.raises(ArchiveEligibilityError):
        manager.create_archive("RLC-E025")

    assert folder.is_dir()
    assert db.get_archive_by_episode_id("RLC-E025") is None
    assert db.get_episode_by_episode_id("RLC-E025").status == status
    assert not (tmp_path / "_archive").exists()


def test_create_archive_rejects_episode_without_folder(tmp_path):
    manager, db, config = make_manager(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.RENDERED)

    with pytest.raises(ArchiveEligibilityError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_rejects_active_assembly_claim(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, _, _ = seed_rendered_episode(db, config, tmp_path)
    db.conn.execute(
        "UPDATE episodes SET assembly_claim_token = ?, assembly_claimed_at = datetime('now') WHERE episode_id = ?",
        ("forced-claim-token", "RLC-E025"),
    )
    db.conn.commit()

    with pytest.raises(ArchiveEligibilityError):
        manager.create_archive("RLC-E025")

    assert folder.is_dir()
    assert not (tmp_path / "_archive").exists()


# -- render eligibility / selection ------------------------------------------------


def test_create_archive_rejects_episode_with_no_completed_render(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, _, _ = seed_rendered_episode(db, config, tmp_path, render_status=RenderJobStatus.FAILED)

    with pytest.raises(ArchiveRenderSelectionError):
        manager.create_archive("RLC-E025")

    assert folder.is_dir()
    assert not (tmp_path / "_archive").exists()


@pytest.mark.parametrize(
    "active_status", [RenderJobStatus.CLAIMING, RenderJobStatus.QUEUED, RenderJobStatus.RENDERING]
)
def test_create_archive_rejects_when_active_render_job_exists(tmp_path, active_status):
    manager, db, config = make_manager(tmp_path)
    folder, complete_job, _ = seed_rendered_episode(db, config, tmp_path)
    db.create_render_job(
        "RLC-E025",
        "broadcast_master_alt",
        output_path=str(folder / "exports" / "second.mov"),
        status=active_status,
    )

    with pytest.raises(ArchiveEligibilityError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_rejects_ambiguous_multiple_completed_renders(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, job1, _ = seed_rendered_episode(db, config, tmp_path)
    db.create_render_job(
        "RLC-E025",
        "broadcast_master_alt",
        output_path=str(folder / "exports" / "second.mov"),
        status=RenderJobStatus.COMPLETE,
    )

    with pytest.raises(ArchiveRenderSelectionError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_explicit_render_selection_used(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, job1, _ = seed_rendered_episode(db, config, tmp_path)
    output2 = folder / "exports" / "second.mov"
    output2.write_bytes(b"second-render")
    job2 = db.create_render_job(
        "RLC-E025",
        "broadcast_master_alt",
        output_path=str(output2),
        status=RenderJobStatus.COMPLETE,
    )

    result = manager.create_archive("RLC-E025", render_job_id=job2.id)

    assert result.render_job_id == job2.id


def test_create_archive_rejects_render_job_from_another_episode(tmp_path):
    manager, db, config = make_manager(tmp_path)
    seed_rendered_episode(db, config, tmp_path, episode_number=25, episode_id="RLC-E025")
    _, other_job, _ = seed_rendered_episode(db, config, tmp_path, episode_number=26, episode_id="RLC-E026")

    with pytest.raises(ArchiveRenderSelectionError):
        manager.create_archive("RLC-E025", render_job_id=other_job.id)

    assert not (tmp_path / "_archive" / "episodes" / "RLC-E025").exists()


def test_create_archive_rejects_missing_render_output(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    Path(render_job.output_path).unlink()

    with pytest.raises(ArchiveRenderSelectionError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_rejects_render_master_not_in_inventory(tmp_path, monkeypatch):
    """Mission 15E.2's render-master correction: even when the output
    path exists and resolves inside the workspace, the archive must fail
    closed if it does not correspond to an actual InventoryFile in the
    trusted workspace inventory."""
    manager, db, config = make_manager(tmp_path)
    seed_rendered_episode(db, config, tmp_path)

    import redline_core.archive.manager as manager_module

    monkeypatch.setattr(manager_module, "_find_inventory_file_by_absolute_path", lambda inventory, path: None)

    with pytest.raises(ArchiveRenderSelectionError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


# -- existing archive / collision --------------------------------------------------


def test_create_archive_rejects_second_call_after_committed_archive(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path)
    first = manager.create_archive("RLC-E025")

    with pytest.raises(EpisodeAlreadyArchivedError):
        manager.create_archive("RLC-E025")

    episode_dir = tmp_path / "_archive" / "episodes" / "RLC-E025"
    assert [p.name for p in episode_dir.iterdir()] == [first.archive_id]


def test_create_archive_rejects_legacy_archive_record(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, _, _ = seed_rendered_episode(db, config, tmp_path)
    db.create_archive_record("RLC-E025", str(tmp_path / "_legacy_archive" / "RLC-E025"))

    with pytest.raises(ArchiveLegacyRecordError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()
    assert folder.is_dir()


def test_create_archive_rejects_destination_collision(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, _, _ = seed_rendered_episode(db, config, tmp_path)

    # Derive the exact archive_id this episode will compute, using the
    # manager's own private resolution helpers directly (same inventory,
    # same content plan, same digest the real create_archive() call below
    # will independently recompute) so the collision lands on the real
    # destination.
    inventory = integrity.build_source_inventory(folder)
    render_job = db.list_render_jobs_for_episode("RLC-E025")[0]
    render_master_file = manager._require_render_master_is_inventory_file(render_job, inventory)
    plan = manager._build_content_plan(
        episode_id="RLC-E025",
        workspace_inventory=inventory,
        render_master_file=render_master_file,
        manifest_path=None,
    )
    archive_id = manager._derive_archive_id("RLC-E025", plan.content_set_digest)

    collision_dir = tmp_path / "_archive" / "episodes" / "RLC-E025" / archive_id
    collision_dir.mkdir(parents=True)
    (collision_dir / "sentinel.txt").write_text("pre-existing")

    with pytest.raises(ArchiveDestinationCollisionError):
        manager.create_archive("RLC-E025")

    assert (collision_dir / "sentinel.txt").read_text() == "pre-existing"
    assert db.get_archive_by_episode_id("RLC-E025") is None
    assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED
    assert folder.is_dir()


# -- DB commit failure after publication (mandatory) -------------------------------


def test_create_archive_db_commit_failure_after_publication_is_verified_unregistered(tmp_path, monkeypatch):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)

    def _raise_commit_error(**kwargs):
        raise ArchiveCommitError("simulated database failure after publication")

    monkeypatch.setattr(db, "commit_verified_archive", _raise_commit_error)

    with pytest.raises(ArchiveVerifiedUnregisteredError) as exc_info:
        manager.create_archive("RLC-E025")

    err = exc_info.value
    assert Path(err.archive_path).is_dir()
    assert (Path(err.archive_path) / "PACKAGE_COMPLETE").is_file()
    assert (Path(err.archive_path) / "archive_manifest.json").is_file()
    assert folder.is_dir()
    assert (folder / "footage" / "clip1.mov").read_bytes() == b"raw-footage"
    assert db.get_archive_by_episode_id("RLC-E025") is None
    assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED


# -- no destructive operations -----------------------------------------------------


def test_create_archive_never_calls_source_cleanup_operations(tmp_path, monkeypatch):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, _, _ = seed_rendered_episode(db, config, tmp_path)

    def _forbidden(*args, **kwargs):
        raise AssertionError("a source-cleanup operation must not be called by the Rev1 archive path")

    monkeypatch.setattr(shutil, "move", _forbidden)
    monkeypatch.setattr(shutil, "rmtree", _forbidden)
    monkeypatch.setattr(Path, "unlink", _forbidden)

    result = manager.create_archive("RLC-E025")

    assert result.episode_id == "RLC-E025"
    assert folder.is_dir()


# -- Resolve independence -----------------------------------------------------------


def test_archive_manager_module_never_imports_resolve():
    import redline_core.archive.manager as manager_module

    tree = ast.parse(Path(manager_module.__file__).read_text(encoding="utf-8"))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    assert not any("resolve" in name.lower() for name in imported_names)


def test_create_archive_succeeds_with_no_resolve_dependency(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path)

    result = manager.create_archive("RLC-E025")

    assert result.episode_id == "RLC-E025"


# -- legacy manifest_path fallback ---------------------------------------------------


def test_create_archive_fails_closed_with_no_provenance_and_no_manifest_path(tmp_path):
    manager, db, config = make_manager(tmp_path)
    seed_rendered_episode(db, config, tmp_path, with_provenance=False)

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()
    assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED


def test_create_archive_legacy_manifest_path_fallback_succeeds(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, render_job, (ingest_file, asset_file) = seed_rendered_episode(db, config, tmp_path, with_provenance=False)

    manifest_dir = tmp_path / "_legacy_manifests"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "RLC-E025.yaml"
    manifest_path.write_text(
        "schema_version: 1\n"
        "episode:\n"
        "  id: RLC-E025\n"
        "assembly:\n"
        "  media:\n"
        f"    - path: {ingest_file}\n"
        f"    - path: {asset_file}\n",
        encoding="utf-8",
    )

    result = manager.create_archive("RLC-E025", manifest_path=manifest_path)

    assert result.episode_id == "RLC-E025"
    manifest = json.loads((result.archive_path / "archive_manifest.json").read_bytes())
    archive_relative_paths = {a["archive_relative_path"] for a in manifest["artifacts"]}
    assert "external/episode_manifest/RLC-E025.yaml" in archive_relative_paths
    assert "external/source_media/ingest/EpisodeA/RLC-E025.mov" in archive_relative_paths
    assert "external/source_media/assets/graphics/RLC-E025_logo.png" in archive_relative_paths
    # legacy manifest preserved byte-for-byte at its documented location
    preserved = (result.archive_path / "payload" / "external" / "episode_manifest" / "RLC-E025.yaml").read_bytes()
    assert preserved == manifest_path.read_bytes()

    # original manifest and media untouched
    assert manifest_path.is_file()
    assert ingest_file.is_file()
    assert asset_file.is_file()


def test_create_archive_legacy_manifest_relative_media_resolved_against_original_directory(tmp_path):
    """The legacy manifest validator resolves relative media paths
    against the *manifest's own* directory -- never the episode
    workspace, which has nothing to do with where the legacy manifest
    happens to live."""
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path, with_provenance=False)

    manifest_dir = tmp_path / "_ingest" / "_legacy_manifests"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "RLC-E025.yaml"
    # relative path resolved against manifest_dir, landing inside ingest_path
    relative_media = manifest_dir / "clip_relative.mov"
    relative_media.write_bytes(b"relative-ingest-clip")
    manifest_path.write_text(
        "schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media:\n    - path: clip_relative.mov\n",
        encoding="utf-8",
    )

    result = manager.create_archive("RLC-E025", manifest_path=manifest_path)

    manifest = json.loads((result.archive_path / "archive_manifest.json").read_bytes())
    archive_relative_paths = {a["archive_relative_path"] for a in manifest["artifacts"]}
    assert "external/source_media/ingest/_legacy_manifests/clip_relative.mov" in archive_relative_paths


def test_create_archive_canonical_provenance_present_conflicting_manifest_path_rejected(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)  # with_provenance=True (default)

    conflicting = tmp_path / "conflicting.yaml"
    conflicting.write_text("schema_version: 1\nepisode:\n  id: RLC-E025\n", encoding="utf-8")

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025", manifest_path=conflicting)

    assert not (tmp_path / "_archive").exists()
    assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED


def test_create_archive_canonical_provenance_present_matching_manifest_path_accepted(tmp_path):
    """A redundant but byte-identical override is accepted -- canonical
    provenance remains the authority, the override is not substituted."""
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)

    canonical_copy = folder / "project" / "episode_manifest" / "RLC-E025.yaml"
    matching_override = tmp_path / "matching_copy.yaml"
    matching_override.write_bytes(canonical_copy.read_bytes())

    result = manager.create_archive("RLC-E025", manifest_path=matching_override)

    manifest = json.loads((result.archive_path / "archive_manifest.json").read_bytes())
    archive_relative_paths = {a["archive_relative_path"] for a in manifest["artifacts"]}
    # canonical (workspace) manifest used -- no external episode_manifest copy
    assert "workspace/project/episode_manifest/RLC-E025.yaml" in archive_relative_paths
    assert not any(p.startswith("external/episode_manifest/") for p in archive_relative_paths)


# -- canonical provenance failures ---------------------------------------------------


def test_create_archive_fails_closed_when_provenance_json_missing(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    (folder / "project" / "episode_manifest" / "manifest_provenance.json").unlink()

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_fails_closed_on_multiple_canonical_manifests(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    extra = folder / "project" / "episode_manifest" / "second.yaml"
    extra.write_text("schema_version: 1\n", encoding="utf-8")

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_fails_closed_on_manifest_sha_mismatch(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    canonical = folder / "project" / "episode_manifest" / "RLC-E025.yaml"
    canonical.write_text("schema_version: 1\ntampered: true\n", encoding="utf-8")

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_fails_closed_on_unsupported_provenance_schema(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    provenance_path = folder / "project" / "episode_manifest" / "manifest_provenance.json"
    data = json.loads(provenance_path.read_bytes())
    data["schema_version"] = 2
    provenance_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_fails_closed_on_malformed_provenance_json(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    provenance_path = folder / "project" / "episode_manifest" / "manifest_provenance.json"
    provenance_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_fails_closed_on_duplicate_provenance_media_identity(tmp_path):
    """Control Room correction (Mission 15E.2 narrow follow-up): canonical
    `manifest_provenance.json` is generated once, from an already-validated
    build. A duplicate `(source_root, source_relative_path)` identity
    surviving into that file is not legitimate canonical state -- it
    indicates tampering, corruption, or a manual/unsupported edit -- and
    must fail closed rather than being silently deduplicated."""
    manager, db, config = make_manager(tmp_path)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    provenance_path = folder / "project" / "episode_manifest" / "manifest_provenance.json"
    data = json.loads(provenance_path.read_bytes())
    assert len(data["media"]) >= 1
    data["media"].append(dict(data["media"][0]))  # exact duplicate identity
    provenance_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025")

    # no final archive package, no archive DB row, episode remains rendered,
    # source workspace untouched
    assert not (tmp_path / "_archive").exists()
    assert db.get_archive_by_episode_id("RLC-E025") is None
    assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED
    assert (folder / "footage" / "clip1.mov").read_bytes() == b"raw-footage"


def test_create_archive_fails_closed_on_case_equivalent_duplicate_provenance_media_identity(tmp_path):
    """Duplicate detection uses the same unconditional-casefold identity
    policy as `archive.integrity` (Archive Rev1 targets a Windows
    production filesystem regardless of which OS built the inventory) --
    so two entries whose `source_relative_path` differs only by case must
    be caught as the same media identity, not treated as two distinct
    files."""
    manager, db, config = make_manager(tmp_path)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    provenance_path = folder / "project" / "episode_manifest" / "manifest_provenance.json"
    data = json.loads(provenance_path.read_bytes())
    assert len(data["media"]) >= 1
    case_flipped = dict(data["media"][0])
    case_flipped["source_relative_path"] = case_flipped["source_relative_path"].upper()
    assert case_flipped["source_relative_path"] != data["media"][0]["source_relative_path"]
    data["media"].append(case_flipped)
    provenance_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()
    assert db.get_archive_by_episode_id("RLC-E025") is None
    assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED
    assert (folder / "footage" / "clip1.mov").read_bytes() == b"raw-footage"


def test_create_archive_fails_closed_on_invalid_source_root(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    provenance_path = folder / "project" / "episode_manifest" / "manifest_provenance.json"
    data = json.loads(provenance_path.read_bytes())
    data["media"][0]["source_root"] = "other"
    provenance_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ArchiveManifestProvenanceError):
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()


def test_create_archive_fails_closed_when_referenced_media_missing(tmp_path):
    manager, db, config = make_manager(tmp_path)
    folder, render_job, (ingest_file, asset_file) = seed_rendered_episode(db, config, tmp_path)
    ingest_file.unlink()

    with pytest.raises(ArchivePathError):  # Mission 15C's own exception, reused as-is, not re-wrapped
        manager.create_archive("RLC-E025")

    assert not (tmp_path / "_archive").exists()
    assert asset_file.is_file()


# -- verify_archive(): read-only Rev1 verification (Phase 15 Mission 15F) -----------


def test_verify_archive_valid_committed_archive_succeeds(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    created = manager.create_archive("RLC-E025")

    result = manager.verify_archive("RLC-E025")

    assert isinstance(result, ArchiveVerificationResult)
    assert result.verified is True
    assert result.episode_id == "RLC-E025"
    assert result.archive_id == created.archive_id
    assert result.archive_path == created.archive_path
    assert result.manifest_sha256 == created.manifest_sha256
    assert result.file_count == created.file_count
    assert result.directory_count == created.directory_count
    assert result.total_bytes == created.total_bytes


def test_verify_archive_no_archive_row_fails(tmp_path):
    manager, db, config = make_manager(tmp_path)
    seed_rendered_episode(db, config, tmp_path)  # rendered, never archived

    with pytest.raises(ArchiveNotFoundError):
        manager.verify_archive("RLC-E025")


def test_verify_archive_unknown_episode_fails(tmp_path):
    manager, db, config = make_manager(tmp_path)

    with pytest.raises(ArchiveNotFoundError):
        manager.verify_archive("RLC-E999")


def test_verify_archive_legacy_archive_row_fails(tmp_path):
    manager, db, config = make_manager(tmp_path)
    seed_rendered_episode(db, config, tmp_path)
    db.create_archive_record("RLC-E025", str(tmp_path / "_legacy_archive" / "RLC-E025"))

    with pytest.raises(ArchiveLegacyRecordError):
        manager.verify_archive("RLC-E025")


def test_verify_archive_db_path_missing_fails(tmp_path):
    """The committed row's archive_path no longer exists on disk --
    package.verify_archive_package()'s own root-validation failure
    propagates unchanged; verify_archive() adds no second, weaker check."""
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path)
    created = manager.create_archive("RLC-E025")
    shutil.rmtree(created.archive_path)

    with pytest.raises(ArchivePathError):
        manager.verify_archive("RLC-E025")


def test_verify_archive_db_manifest_path_mismatch_fails(tmp_path):
    """The filesystem package itself is perfectly intact -- only the
    committed row's own manifest_path column has diverged from what the
    package actually contains -- so this must be classified distinctly
    from filesystem corruption (ArchiveManifestMismatchError, not
    ArchivePackageVerificationError)."""
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path)
    manager.create_archive("RLC-E025")
    db.conn.execute(
        "UPDATE archives SET manifest_path = ? WHERE episode_id = ?",
        (str(tmp_path / "not_the_real_manifest.json"), "RLC-E025"),
    )
    db.conn.commit()

    with pytest.raises(ArchiveManifestMismatchError):
        manager.verify_archive("RLC-E025")


def test_verify_archive_db_manifest_sha_mismatch_fails(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path)
    manager.create_archive("RLC-E025")
    db.conn.execute(
        "UPDATE archives SET manifest_sha256 = ? WHERE episode_id = ?",
        ("0" * 64, "RLC-E025"),
    )
    db.conn.commit()

    with pytest.raises(ArchiveManifestMismatchError):
        manager.verify_archive("RLC-E025")


def test_verify_archive_corrupt_package_fails(tmp_path):
    """A tampered payload file surfaces as ArchivePackageVerificationError
    -- package.py's own algorithm, not re-implemented or weakened here."""
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path)
    created = manager.create_archive("RLC-E025")
    tampered = created.archive_path / "payload" / "workspace" / "footage" / "clip1.mov"
    tampered.write_bytes(b"tampered-bytes-different-length")

    with pytest.raises(ArchivePackageVerificationError):
        manager.verify_archive("RLC-E025")


def test_verify_archive_no_mutation_to_episode_or_archive_db(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path)
    manager.create_archive("RLC-E025")
    before_episode = db.get_episode_by_episode_id("RLC-E025")
    before_archive = db.get_archive_by_episode_id("RLC-E025")

    manager.verify_archive("RLC-E025")

    after_episode = db.get_episode_by_episode_id("RLC-E025")
    after_archive = db.get_archive_by_episode_id("RLC-E025")
    assert after_episode == before_episode
    assert after_archive == before_archive


def test_verify_archive_no_source_workspace_mutation(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    folder, render_job, _ = seed_rendered_episode(db, config, tmp_path)
    manager.create_archive("RLC-E025")

    manager.verify_archive("RLC-E025")

    assert folder.is_dir()
    assert (folder / "footage" / "clip1.mov").read_bytes() == b"raw-footage"


def test_verify_archive_no_resolve_dependency(tmp_path):
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path)
    manager.create_archive("RLC-E025")

    result = manager.verify_archive("RLC-E025")

    assert result.verified is True


def test_verify_archive_idempotent(tmp_path):
    """Running verify_archive() multiple times on an unchanged, valid
    package produces the same result and no mutation between runs."""
    manager, db, config = make_manager(tmp_path, clock=lambda: _FIXED_MOMENT)
    seed_rendered_episode(db, config, tmp_path)
    manager.create_archive("RLC-E025")

    first = manager.verify_archive("RLC-E025")
    second = manager.verify_archive("RLC-E025")
    third = manager.verify_archive("RLC-E025")

    assert first == second == third
