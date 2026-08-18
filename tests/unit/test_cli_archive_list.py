"""Tests for the CLI's `archive list` command.

Read-only wrapper over the existing, already-tested
ArchiveManager.list_archives(), routed through PersistenceServices
(config + DB composition — no Resolve). These tests also prove that
independence at the CLI-invocation level: main() runs `archive list`
successfully with no --mock-resolve flag, which an `episode` command in
this same environment would need.
"""
from pathlib import Path

import yaml

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

from cli import main as cli_main
from cli.archive_commands import _print_archive_list_result, _run_archive_list
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


def create_and_archive_episode(services: PersistenceServices, tmp_path: Path, episode_number: int, episode_id: str) -> None:
    """Seed a fully Rev1-eligible episode (ArchiveManager.create_archive()'s
    eligibility gate), including canonical manifest provenance (Mission
    15E.2's complete-content contract), and archive it by calling
    `create_archive()` directly (Phase 15 Mission 15F retired the
    `archive_episode()` compatibility bridge this helper used to go
    through). A bare folder with no render history or provenance is not
    archivable at all."""
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

    services.archive_manager.create_archive(episode_id)


# -- _run_archive_list -------------------------------------------------------------

def test_run_archive_list_empty(tmp_path):
    services = make_persistence_services(tmp_path)

    result = _run_archive_list(services)

    assert result["success"] is True
    assert result["archives"] == []


def test_run_archive_list_serializes_all_three_fields(tmp_path):
    services = make_persistence_services(tmp_path)
    create_and_archive_episode(services, tmp_path, 25, "RLC-E025")

    result = _run_archive_list(services)

    assert len(result["archives"]) == 1
    archive = result["archives"][0]
    assert archive["episode_id"] == "RLC-E025"
    assert archive["archive_path"].startswith(str(tmp_path / "_archive" / "episodes" / "RLC-E025"))
    assert Path(archive["archive_path"]).is_dir()
    assert archive["archived_at"] is not None


def test_run_archive_list_serializes_rev1_fields(tmp_path):
    """Mission 15F extension: a Rev1 `complete` row carries a real
    archive_id and reports archive_state='complete' -- additive to the
    original three fields, not a replacement of them."""
    services = make_persistence_services(tmp_path)
    create_and_archive_episode(services, tmp_path, 25, "RLC-E025")

    result = _run_archive_list(services)

    archive = result["archives"][0]
    assert archive["archive_state"] == "complete"
    assert archive["archive_id"] is not None
    assert archive["archive_id"].startswith("RLC-E025-a1-")


def test_run_archive_list_distinguishes_legacy_rows(tmp_path):
    """A legacy (pre-Rev1) row has no Rev1 archive_id and is reported as
    archive_state='legacy' -- list never pretends it is a Rev1 row, and
    never performs package verification merely to build the listing."""
    services = make_persistence_services(tmp_path)
    services.db.create_episode(30, "RLC-E030", "RLC-E030_MASTER")
    services.db.create_archive_record("RLC-E030", str(tmp_path / "_legacy_archive" / "RLC-E030"))

    result = _run_archive_list(services)

    archive = result["archives"][0]
    assert archive["episode_id"] == "RLC-E030"
    assert archive["archive_state"] == "legacy"
    assert archive["archive_id"] is None


def test_run_archive_list_multiple_by_membership(tmp_path):
    # Mirrors test_archive_manager.test_list_archives: assert set membership,
    # not order — database.py's ORDER BY archived_at has no secondary sort
    # key, so two archives created in the same instant are not guaranteed a
    # stable relative order. This command doesn't re-sort the manager's result.
    services = make_persistence_services(tmp_path)
    create_and_archive_episode(services, tmp_path, 25, "RLC-E025")
    create_and_archive_episode(services, tmp_path, 26, "RLC-E026")

    result = _run_archive_list(services)

    assert {a["episode_id"] for a in result["archives"]} == {"RLC-E025", "RLC-E026"}


# -- _print_archive_list_result -----------------------------------------------------

def test_print_archive_list_result_empty(capsys):
    _print_archive_list_result({"success": True, "archives": []})

    out = capsys.readouterr().out
    assert "No archives found." in out


def test_print_archive_list_result_multiple(capsys):
    _print_archive_list_result(
        {
            "success": True,
            "archives": [
                {
                    "episode_id": "RLC-E025",
                    "archive_path": "/archive/RLC-E025",
                    "archived_at": "2026-01-01 00:00:00",
                    "archive_id": "RLC-E025-a1-abc123abc123",
                    "archive_state": "complete",
                },
                {
                    "episode_id": "RLC-E026",
                    "archive_path": "/archive/RLC-E026",
                    "archived_at": "2026-01-02 00:00:00",
                    "archive_id": "RLC-E026-a1-def456def456",
                    "archive_state": "complete",
                },
            ],
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "RLC-E026" in out
    assert "/archive/RLC-E025" in out
    assert "2 archive(s)." in out


# -- argument parsing -----------------------------------------------------------

def test_parser_archive_list_takes_no_arguments():
    parser = _build_parser()
    args = parser.parse_args(["archive", "list"])
    assert args.resource == "archive"
    assert args.action == "list"


# -- main() end-to-end: proves genuine Resolve independence ---------------------

def write_isolated_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    # Archive Rev1 (Mission 15G.1) requires `paths.evidence_path` to be
    # configured before `ArchiveManager.create_archive()` will run --
    # this fixture predates that requirement and must provide a valid,
    # authoritative-zero-evidence root (an existing, empty directory),
    # matching the pattern `test_archive_manager.py::make_manager()`
    # already uses, not "no authority configured".
    evidence_path = tmp_path / "_evidence"
    evidence_path.mkdir()
    (config_dir / "naming.yaml").write_text(
        'episode_id_pattern: "RLC-E{episode_number:03d}"\nproject_name_pattern: "{episode_id}_MASTER"\n'
    )
    (config_dir / "folder_structure.yaml").write_text(
        yaml.safe_dump({"root_path": str(tmp_path / "_episodes")})
    )
    (config_dir / "render_presets.yaml").write_text("presets: []\n")
    (config_dir / "paths.yaml").write_text(
        yaml.safe_dump(
            {
                "ingest_path": str(tmp_path / "_ingest"),
                "archive_path": str(tmp_path / "_archive"),
                "assets_path": str(assets_path),
                "master_project_template": "RLC_MASTER_TEMPLATE",
                "evidence_path": str(evidence_path),
            }
        )
    )
    (config_dir / "assets.yaml").write_text("assets: []\nrequired_for_episode: []\n")
    (config_dir / "timeline_template.yaml").write_text(
        'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n'
    )
    return config_dir


def test_main_archive_list_end_to_end_without_mock_resolve(tmp_path, monkeypatch, capsys):
    """No --mock-resolve set at all — an `episode` command in this same
    environment would either fail (real Resolve not running in this
    sandbox) or require the flag. `archive list` must do neither, because
    it's routed through PersistenceServices, which never touches Resolve.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "redline.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["archive", "list"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No archives found." in out


def test_main_archive_list_shows_archived_episode(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    db_path = tmp_path / "redline.db"
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    services = make_persistence_services_from_env(config_dir, db_path, tmp_path)
    create_and_archive_episode(services, tmp_path, 25, "RLC-E025")

    exit_code = cli_main.main(["archive", "list"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert "1 archive(s)." in out


def make_persistence_services_from_env(config_dir: Path, db_path: Path, tmp_path: Path) -> PersistenceServices:
    """Builds a PersistenceServices pointed at the same config dir and DB
    path main() will use, so the pre-seeded archive is visible to it.
    Loads config via the real loader (not an in-memory RedlineConfig) to
    guarantee it matches what main() itself will load."""
    from redline_core.config.loader import load_config

    config = load_config(config_dir)
    db = Database(db_path).connect()
    db.init_schema()
    return PersistenceServices(config=config, db=db, archive_manager=ArchiveManager(config, db))
