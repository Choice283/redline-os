"""Tests for the CLI's canonical `archive recover <episode_id> --archive-id
<archive_id>` command (Phase 15 Mission 15H).

A thin wrapper calling `ArchiveManager.recover_archive()` directly.
`--archive-id` is required; there is no arbitrary package-path option, no
`--force`, and no repair mode.
"""
from pathlib import Path

from redline_core.archive.manager import ArchiveManager
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
from redline_core.db.models import EpisodeStatus, RenderJobStatus
from redline_core.manifest.models import ValidatedEpisodePlan
from redline_core.runtime.composition import PersistenceServices

from cli.archive_commands import _print_archive_recover_result, _run_archive_create, _run_archive_recover
from cli.main import _build_parser


def make_persistence_services(tmp_path: Path) -> PersistenceServices:
    evidence_root = tmp_path / "_evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    config = RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path=str(tmp_path / "_ingest"),
            archive_path=str(tmp_path / "_archive"),
            assets_path=str(tmp_path / "_assets"),
            master_project_template="RLC_MASTER_TEMPLATE",
            evidence_path=str(evidence_root),
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )
    db = Database(tmp_path / "test.db").connect()
    db.init_schema()
    return PersistenceServices(config=config, db=db, archive_manager=ArchiveManager(config, db))


def seed_rendered_episode(services: PersistenceServices, tmp_path: Path, episode_number: int, episode_id: str) -> Path:
    services.db.create_episode(episode_number, episode_id, f"{episode_id}_MASTER")
    folder = tmp_path / "_episodes" / episode_id
    for sub in ("exports", "footage", "graphics", "audio", "project"):
        (folder / sub).mkdir(parents=True)
    services.db.update_episode_paths(episode_id, folder_path=str(folder))
    services.db.update_episode_status(episode_id, EpisodeStatus.RENDERED)

    output_path = folder / "exports" / f"{episode_id}_MASTER.mov"
    output_path.write_bytes(b"rendered-master-bytes")
    services.db.create_render_job(
        episode_id,
        "broadcast_master",
        resolve_job_id=f"resolve-{episode_id}",
        project_name=f"{episode_id}_MASTER",
        timeline_name=f"{episode_id}_TIMELINE",
        output_path=str(output_path),
        status=RenderJobStatus.COMPLETE,
    )

    ingest_file = tmp_path / "_ingest" / episode_id / "camera.mov"
    ingest_file.parent.mkdir(parents=True, exist_ok=True)
    ingest_file.write_bytes(b"ingest-bytes")
    asset_file = tmp_path / "_assets" / "graphics" / f"{episode_id}_logo.png"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"asset-bytes")

    manifest_src = tmp_path / "_source_manifests" / f"{episode_id}.yaml"
    manifest_src.parent.mkdir(parents=True, exist_ok=True)
    manifest_src.write_text(f"schema_version: 1\nepisode:\n  id: {episode_id}\n", encoding="utf-8", newline="")
    plan = ValidatedEpisodePlan(episode_id=episode_id, media_paths=(str(ingest_file), str(asset_file)))
    persist_manifest_provenance(
        original_manifest_path=manifest_src, plan=plan, config=services.config, episode_folder_path=folder
    )
    return folder


def force_verified_unregistered(services: PersistenceServices, episode_id: str) -> dict:
    original_commit = services.db.commit_verified_archive

    def _raise_commit_error(**kwargs):
        raise ArchiveCommitError("simulated database failure after publication")

    services.db.commit_verified_archive = _raise_commit_error
    try:
        created = _run_archive_create(services, episode_id)
    finally:
        services.db.commit_verified_archive = original_commit
    assert created["success"] is False
    assert created["classification"] == "verified_unregistered"
    return created


# -- _run_archive_recover ----------------------------------------------------------


def test_run_archive_recover_registered(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_rendered_episode(services, tmp_path, 25, "RLC-E025")
    unregistered = force_verified_unregistered(services, "RLC-E025")

    result = _run_archive_recover(services, "RLC-E025", archive_id=unregistered["archive_id"])

    assert result["success"] is True
    recovery = result["recovery"]
    assert recovery["episode_id"] == "RLC-E025"
    assert recovery["archive_id"] == unregistered["archive_id"]
    assert recovery["classification"] == "recovered"
    assert services.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.ARCHIVED


def test_run_archive_recover_already_registered_on_second_call(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_rendered_episode(services, tmp_path, 25, "RLC-E025")
    unregistered = force_verified_unregistered(services, "RLC-E025")
    first = _run_archive_recover(services, "RLC-E025", archive_id=unregistered["archive_id"])
    assert first["success"] is True

    second = _run_archive_recover(services, "RLC-E025", archive_id=unregistered["archive_id"])

    assert second["success"] is True
    assert second["recovery"]["classification"] == "already_registered"


def test_run_archive_recover_package_corruption_fails(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_rendered_episode(services, tmp_path, 25, "RLC-E025")
    unregistered = force_verified_unregistered(services, "RLC-E025")
    tampered = Path(unregistered["archive_path"]) / "payload" / "workspace" / "exports" / "RLC-E025_MASTER.mov"
    tampered.write_bytes(b"tampered-different-length-bytes")

    result = _run_archive_recover(services, "RLC-E025", archive_id=unregistered["archive_id"])

    assert result["success"] is False
    assert services.db.get_archive_by_episode_id("RLC-E025") is None


def test_run_archive_recover_conflict_fails(tmp_path):
    services = make_persistence_services(tmp_path)
    render_job_output = seed_rendered_episode(services, tmp_path, 25, "RLC-E025")
    unregistered = force_verified_unregistered(services, "RLC-E025")
    render_job = services.db.list_render_jobs_for_episode("RLC-E025")[0]
    services.db.conn.execute("UPDATE render_jobs SET status = 'failed' WHERE id = ?", (render_job.id,))
    services.db.conn.commit()

    result = _run_archive_recover(services, "RLC-E025", archive_id=unregistered["archive_id"])

    assert result["success"] is False
    assert services.db.get_archive_by_episode_id("RLC-E025") is None


def test_run_archive_recover_unknown_package_not_found(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_rendered_episode(services, tmp_path, 25, "RLC-E025")

    result = _run_archive_recover(services, "RLC-E025", archive_id="RLC-E025-a1-000000000000")

    assert result["success"] is False


def test_run_archive_recover_unsafe_archive_id_rejected(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_rendered_episode(services, tmp_path, 25, "RLC-E025")

    result = _run_archive_recover(services, "RLC-E025", archive_id="../../../etc/passwd")

    assert result["success"] is False


# -- _print_archive_recover_result -------------------------------------------------


def test_print_archive_recover_result_recovered(capsys):
    _print_archive_recover_result(
        {
            "success": True,
            "recovery": {
                "episode_id": "RLC-E025",
                "archive_id": "RLC-E025-a1-abc123abc123",
                "archive_path": "/archive/RLC-E025",
                "manifest_sha256": "a" * 64,
                "render_job_id": 1,
                "classification": "recovered",
            },
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "recovered" in out


def test_print_archive_recover_result_already_registered(capsys):
    _print_archive_recover_result(
        {
            "success": True,
            "recovery": {
                "episode_id": "RLC-E025",
                "archive_id": "RLC-E025-a1-abc123abc123",
                "archive_path": "/archive/RLC-E025",
                "manifest_sha256": "a" * 64,
                "render_job_id": 1,
                "classification": "already_registered",
            },
        }
    )

    out = capsys.readouterr().out
    assert "already_registered" in out


def test_print_archive_recover_result_verified_unregistered(capsys):
    _print_archive_recover_result(
        {
            "success": False,
            "classification": "verified_unregistered",
            "error": "database registration failed",
            "episode_id": "RLC-E025",
            "archive_id": "RLC-E025-a1-abc123abc123",
            "archive_path": "/archive/RLC-E025",
            "manifest_path": "/archive/RLC-E025/archive_manifest.json",
            "manifest_sha256": "a" * 64,
        }
    )

    out = capsys.readouterr().out
    assert "NOT deleted, moved, or overwritten" in out
    assert "retried" in out


def test_print_archive_recover_result_failure(capsys):
    _print_archive_recover_result({"success": False, "classification": "error", "error": "no such package"})

    out = capsys.readouterr().out
    assert "Archive recover failed:" in out
    assert "no such package" in out


# -- argument parsing -----------------------------------------------------------


def test_parser_archive_recover_requires_archive_id():
    parser = _build_parser()
    import pytest

    with pytest.raises(SystemExit):
        parser.parse_args(["archive", "recover", "RLC-E025"])


def test_parser_archive_recover_parses_episode_id_and_archive_id():
    parser = _build_parser()
    args = parser.parse_args(["archive", "recover", "RLC-E025", "--archive-id", "RLC-E025-a1-abc123abc123"])
    assert args.resource == "archive"
    assert args.action == "recover"
    assert args.episode_id == "RLC-E025"
    assert args.archive_id == "RLC-E025-a1-abc123abc123"


def test_parser_archive_recover_has_no_force_flag():
    parser = _build_parser()
    import pytest

    with pytest.raises(SystemExit):
        parser.parse_args(["archive", "recover", "RLC-E025", "--archive-id", "x", "--force"])


def test_parser_archive_recover_has_no_arbitrary_package_path_option():
    parser = _build_parser()
    import pytest

    with pytest.raises(SystemExit):
        parser.parse_args(["archive", "recover", "RLC-E025", "--package-path", "/anywhere"])


# -- direct recover_archive() call --------------------------------------------------


def test_direct_recover_archive_call_via_manager(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_rendered_episode(services, tmp_path, 25, "RLC-E025")
    unregistered = force_verified_unregistered(services, "RLC-E025")

    result = services.archive_manager.recover_archive("RLC-E025", archive_id=unregistered["archive_id"])

    assert result.classification == "recovered"
