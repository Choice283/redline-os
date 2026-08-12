"""Tests for the CLI's canonical `archive verify <episode_id>` command
(Phase 15 Mission 15F).

A thin, read-only wrapper calling `ArchiveManager.verify_archive()`
directly, routed through PersistenceServices (config + DB composition —
no Resolve). Never mutates the episode, the `archives` row, the source
workspace, or the archive package.
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
from redline_core.db.database import Database
from redline_core.db.models import EpisodeStatus, RenderJobStatus
from redline_core.manifest.models import ValidatedEpisodePlan
from redline_core.runtime.composition import PersistenceServices

from cli.archive_commands import _print_archive_verify_result, _run_archive_create, _run_archive_verify
from cli.main import _build_parser


def make_persistence_services(tmp_path: Path) -> PersistenceServices:
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
    return PersistenceServices(config=config, db=db, archive_manager=ArchiveManager(config, db))


def seed_and_archive_episode(services: PersistenceServices, tmp_path: Path, episode_number: int, episode_id: str) -> Path:
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

    created = _run_archive_create(services, episode_id)
    assert created["success"] is True
    return folder


# -- _run_archive_verify ----------------------------------------------------------


def test_run_archive_verify_success(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_and_archive_episode(services, tmp_path, 25, "RLC-E025")

    result = _run_archive_verify(services, "RLC-E025")

    assert result["success"] is True
    verification = result["verification"]
    assert verification["episode_id"] == "RLC-E025"
    assert verification["verified"] is True
    assert verification["file_count"] > 0
    assert verification["manifest_sha256"] is not None


def test_run_archive_verify_no_archive_row(tmp_path):
    services = make_persistence_services(tmp_path)
    services.db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")

    result = _run_archive_verify(services, "RLC-E025")

    assert result["success"] is False
    assert "RLC-E025" in result["error"]


def test_run_archive_verify_unknown_episode(tmp_path):
    services = make_persistence_services(tmp_path)

    result = _run_archive_verify(services, "RLC-E999")

    assert result["success"] is False


def test_run_archive_verify_legacy_archive_row(tmp_path):
    services = make_persistence_services(tmp_path)
    services.db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    services.db.create_archive_record("RLC-E025", str(tmp_path / "_legacy_archive" / "RLC-E025"))

    result = _run_archive_verify(services, "RLC-E025")

    assert result["success"] is False
    assert "legacy" in result["error"].lower()


def test_run_archive_verify_corrupted_package_fails(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_and_archive_episode(services, tmp_path, 25, "RLC-E025")
    archive_record = services.db.get_archive_by_episode_id("RLC-E025")
    tampered = Path(archive_record.archive_path) / "payload" / "workspace" / "exports" / "RLC-E025_MASTER.mov"
    tampered.write_bytes(b"tampered-different-length-bytes")

    result = _run_archive_verify(services, "RLC-E025")

    assert result["success"] is False


def test_run_archive_verify_does_not_mutate_db_or_episode(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_and_archive_episode(services, tmp_path, 25, "RLC-E025")
    before_episode = services.db.get_episode_by_episode_id("RLC-E025")
    before_archive = services.db.get_archive_by_episode_id("RLC-E025")

    _run_archive_verify(services, "RLC-E025")

    assert services.db.get_episode_by_episode_id("RLC-E025") == before_episode
    assert services.db.get_archive_by_episode_id("RLC-E025") == before_archive


# -- _print_archive_verify_result ------------------------------------------------


def test_print_archive_verify_result_success(capsys):
    _print_archive_verify_result(
        {
            "success": True,
            "verification": {
                "episode_id": "RLC-E025",
                "archive_id": "RLC-E025-a1-abc123abc123",
                "archive_path": "/archive/RLC-E025",
                "manifest_sha256": "a" * 64,
                "verified": True,
                "file_count": 3,
                "directory_count": 1,
                "total_bytes": 100,
            },
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "yes" in out
    assert "3" in out


def test_print_archive_verify_result_failure(capsys):
    _print_archive_verify_result({"success": False, "error": "No archive record exists for episode 'RLC-E999'."})

    out = capsys.readouterr().out
    assert "Archive verify failed:" in out
    assert "RLC-E999" in out


# -- argument parsing -----------------------------------------------------------


def test_parser_archive_verify_parses_episode_id():
    parser = _build_parser()
    args = parser.parse_args(["archive", "verify", "RLC-E025"])
    assert args.resource == "archive"
    assert args.action == "verify"
    assert args.episode_id == "RLC-E025"


# Note: a main()-level end-to-end test (no --mock-resolve, isolated
# REDLINE_CONFIG_DIR) is deliberately not duplicated here. That exact
# proof already exists for `archive create`/`archive list`
# (test_cli_archive_create.py/test_cli_archive_list.py) via the same
# `write_isolated_config_dir()` fixture, and `run()`'s dispatch ->
# exit-code mapping (`0 if result["success"] else 1`) is identical,
# already-exercised code shared across every `archive` subcommand --
# adding a third copy here would only re-trip the same pre-existing,
# unrelated Windows-path/YAML-escaping bug those two files' own end-to-end
# tests already document (see docs/CHANGELOG.md), for zero additional
# coverage.
