"""Tests for the CLI's `archive episode <episode_id>` command.

A thin, mutating wrapper over the existing, already-tested
ArchiveManager.archive_episode(), routed through PersistenceServices
(config + DB composition — no Resolve). Success output reports only the
returned ArchiveRecord's fields (episode_id/archive_path/archived_at) —
no progress checklist, no additional DB or filesystem reads. Failure
messages are the manager's own, passed through unchanged.

The "destination already exists" case is tested at two independent
levels, per explicit instruction: tests/unit/test_archive_manager.py
proves ArchiveManager itself raises ArchiveError for that condition; the
tests below prove only that the CLI passes that manager error through
unchanged and exits 1 — this file is not that branch's only coverage.
"""
from pathlib import Path

from redline_core.archive import integrity as archive_integrity
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
from cli.archive_commands import _print_archive_episode_result, _run_archive_episode
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


def seed_rendered_episode(services: PersistenceServices, tmp_path: Path, episode_number: int, episode_id: str):
    """Seed a fully Rev1-eligible episode (Phase 15 Mission 15E,
    ArchiveManager.create_archive()'s eligibility gate): created, real
    workspace on disk (including the "project" subfolder canonical
    manifest provenance lives under — Mission 15E.2), folder_path set,
    status forced to RENDERED, one real completed render job whose output
    lives inside that workspace, and canonical manifest provenance
    referencing real ingest/assets media — the complete-content contract
    ArchiveManager.archive_episode() (a non-destructive compatibility
    wrapper over create_archive()) now requires. A bare folder with no
    render history or provenance (the pre-Mission-15E fixture shape) is
    no longer archivable at all."""
    services.db.create_episode(episode_number, episode_id, f"{episode_id}_MASTER")
    folder = tmp_path / "_episodes" / episode_id
    for sub in ("exports", "footage", "graphics", "audio", "project"):
        (folder / sub).mkdir(parents=True)
    (folder / "footage" / "clip1.mov").write_bytes(b"raw-footage")
    services.db.update_episode_paths(episode_id, folder_path=str(folder))
    services.db.update_episode_status(episode_id, EpisodeStatus.RENDERED)

    output_path = folder / "exports" / f"{episode_id}_MASTER.mov"
    output_path.write_bytes(b"rendered-master-bytes")
    render_job = services.db.create_render_job(
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

    return folder, render_job


# -- _run_archive_episode -----------------------------------------------------------

def test_run_archive_episode_success(tmp_path):
    """Phase 15 Mission 15E: archive_episode() is now a non-destructive
    compatibility wrapper over ArchiveManager.create_archive() — success
    means a verified filesystem package plus a committed Rev1 DB row, with
    the source workspace preserved exactly where it was, not "folder
    moved to archive_path/episode_id"."""
    services = make_persistence_services(tmp_path)
    folder, render_job = seed_rendered_episode(services, tmp_path, 25, "RLC-E025")

    result = _run_archive_episode(services, "RLC-E025")

    assert result["success"] is True
    assert result["archive"]["episode_id"] == "RLC-E025"
    assert result["archive"]["archived_at"] is not None
    archive_path = Path(result["archive"]["archive_path"])
    assert archive_path.is_dir()
    assert (archive_path / "PACKAGE_COMPLETE").is_file()

    # non-destructive: source workspace preserved, byte-identical
    assert folder.is_dir()
    assert (folder / "footage" / "clip1.mov").read_bytes() == b"raw-footage"

    episode = services.db.get_episode_by_episode_id("RLC-E025")
    assert episode.status == EpisodeStatus.ARCHIVED
    assert episode.folder_path == str(folder)


def test_run_archive_episode_unknown_episode(tmp_path):
    services = make_persistence_services(tmp_path)

    result = _run_archive_episode(services, "RLC-E999")

    assert result["success"] is False
    assert "RLC-E999" in result["error"]


def test_run_archive_episode_already_archived(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_rendered_episode(services, tmp_path, 25, "RLC-E025")
    _run_archive_episode(services, "RLC-E025")

    result = _run_archive_episode(services, "RLC-E025")

    assert result["success"] is False
    assert "already has a committed" in result["error"]


def test_run_archive_episode_missing_folder_path(tmp_path):
    services = make_persistence_services(tmp_path)
    services.db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    services.db.update_episode_status("RLC-E025", EpisodeStatus.RENDERED)
    # No update_episode_paths() call: folder_path stays None.

    result = _run_archive_episode(services, "RLC-E025")

    assert result["success"] is False
    assert "no working folder" in result["error"]


def test_run_archive_episode_destination_already_exists(tmp_path):
    """Proves only that the CLI passes ArchiveManager's ArchiveError through
    unchanged for this condition — the manager-level branch itself is
    proven separately in test_archive_manager.py."""
    services = make_persistence_services(tmp_path)
    folder, render_job = seed_rendered_episode(services, tmp_path, 25, "RLC-E025")

    # archive_id is content-bound (Mission 15E.2: derived from the
    # complete-content digest, not the workspace-only one) -- derive it
    # via the manager's own private resolution helpers so the collision
    # lands on the real destination _run_archive_episode() will compute.
    manager = services.archive_manager
    inventory = archive_integrity.build_source_inventory(folder)
    render_master_file = manager._require_render_master_is_inventory_file(render_job, inventory)
    plan = manager._build_content_plan(
        episode_id="RLC-E025", workspace_inventory=inventory, render_master_file=render_master_file, manifest_path=None
    )
    archive_id = manager._derive_archive_id("RLC-E025", plan.content_set_digest)
    (tmp_path / "_archive" / "episodes" / "RLC-E025" / archive_id).mkdir(parents=True)

    result = _run_archive_episode(services, "RLC-E025")

    assert result["success"] is False
    assert "already exists" in result["error"]


# -- _print_archive_episode_result --------------------------------------------------

def test_print_archive_episode_result_success(capsys):
    _print_archive_episode_result(
        {
            "success": True,
            "archive": {
                "episode_id": "RLC-E025",
                "archive_path": "/archive/RLC-E025",
                "archived_at": "2026-07-29 19:00:47",
            },
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "/archive/RLC-E025" in out
    assert "2026-07-29 19:00:47" in out
    # No progress/checklist narration.
    assert "✓" not in out


def test_print_archive_episode_result_failure(capsys):
    _print_archive_episode_result({"success": False, "error": "No episode with episode_id=RLC-E999."})

    out = capsys.readouterr().out
    assert "Archive failed:" in out
    assert "RLC-E999" in out


# -- argument parsing -----------------------------------------------------------

def test_parser_archive_episode_parses_episode_id():
    parser = _build_parser()
    args = parser.parse_args(["archive", "episode", "RLC-E025"])
    assert args.resource == "archive"
    assert args.action == "episode"
    assert args.episode_id == "RLC-E025"


# -- main() end-to-end: proves genuine Resolve independence ---------------------

def write_isolated_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    (config_dir / "naming.yaml").write_text(
        'episode_id_pattern: "RLC-E{episode_number:03d}"\nproject_name_pattern: "{episode_id}_MASTER"\n'
    )
    (config_dir / "folder_structure.yaml").write_text(f'root_path: "{tmp_path / "_episodes"}"\n')
    (config_dir / "render_presets.yaml").write_text("presets: []\n")
    (config_dir / "paths.yaml").write_text(
        f'ingest_path: "{tmp_path / "_ingest"}"\n'
        f'archive_path: "{tmp_path / "_archive"}"\n'
        f'assets_path: "{assets_path}"\n'
        'master_project_template: "RLC_MASTER_TEMPLATE"\n'
    )
    (config_dir / "assets.yaml").write_text("assets: []\nrequired_for_episode: []\n")
    (config_dir / "timeline_template.yaml").write_text(
        'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n'
    )
    return config_dir


def test_main_archive_episode_end_to_end_without_mock_resolve(tmp_path, monkeypatch, capsys):
    """No --mock-resolve set at all — an `episode` command in this same
    environment would either fail (real Resolve not running in this
    sandbox) or require the flag. `archive episode` must do neither,
    because it's routed through PersistenceServices, which never touches
    Resolve.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    db_path = tmp_path / "redline.db"
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    # Seed the episode+folder through the same DB main() will open.
    from redline_core.config.loader import load_config

    config = load_config(config_dir)
    db = Database(db_path).connect()
    db.init_schema()
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    folder = tmp_path / "_episodes" / "RLC-E025"
    folder.mkdir(parents=True)
    db.update_episode_paths("RLC-E025", folder_path=str(folder))

    exit_code = cli_main.main(["archive", "episode", "RLC-E025"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert not folder.exists()
    assert (tmp_path / "_archive" / "RLC-E025").is_dir()


def test_main_archive_episode_unknown_is_clean_error(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "redline.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["archive", "episode", "RLC-E999"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Archive failed:" in out
