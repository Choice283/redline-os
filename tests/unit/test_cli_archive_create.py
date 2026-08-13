"""Tests for the CLI's canonical `archive create <episode_id>` command
(Phase 15 Mission 15F).

A thin, mutating wrapper calling `ArchiveManager.create_archive()`
directly (never the retired `archive_episode()` compatibility bridge),
routed through PersistenceServices (config + DB composition — no
Resolve). Success output reports the archive's identity fields; failure
messages are the manager's own, passed through unchanged, except
`ArchiveVerifiedUnregisteredError`, which is classified distinctly (see
`test_run_archive_create_verified_unregistered_is_classified_distinctly`).

The legacy `redline archive episode <episode_id>` command is retired
entirely -- `test_parser_archive_episode_is_not_registered` proves the
parser no longer accepts it.
"""
from pathlib import Path

from redline_core.archive import integrity as archive_integrity
from redline_core.archive.exceptions import ArchiveVerifiedUnregisteredError
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
from cli.archive_commands import _print_archive_create_result, _run_archive_create
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


def seed_rendered_episode(
    services: PersistenceServices, tmp_path: Path, episode_number: int, episode_id: str, *, with_provenance: bool = True
):
    """Seed a fully Rev1-eligible episode: created, real workspace on disk
    (including the "project" subfolder canonical manifest provenance
    lives under), folder_path set, status forced to RENDERED, one real
    completed render job whose output lives inside that workspace, and
    (unless with_provenance=False, for legacy-fallback tests) canonical
    manifest provenance referencing real ingest/assets media."""
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

    if with_provenance:
        manifest_src = tmp_path / "_source_manifests" / f"{episode_id}.yaml"
        manifest_src.parent.mkdir(parents=True, exist_ok=True)
        manifest_src.write_text(f"schema_version: 1\nepisode:\n  id: {episode_id}\n", encoding="utf-8", newline="")
        plan = ValidatedEpisodePlan(episode_id=episode_id, media_paths=(str(ingest_file), str(asset_file)))
        persist_manifest_provenance(
            original_manifest_path=manifest_src, plan=plan, config=services.config, episode_folder_path=folder
        )

    return folder, render_job, (ingest_file, asset_file)


# -- _run_archive_create --------------------------------------------------------


def test_run_archive_create_success(tmp_path):
    services = make_persistence_services(tmp_path)
    folder, render_job, _ = seed_rendered_episode(services, tmp_path, 25, "RLC-E025")

    result = _run_archive_create(services, "RLC-E025")

    assert result["success"] is True
    archive = result["archive"]
    assert archive["episode_id"] == "RLC-E025"
    assert archive["render_job_id"] == render_job.id
    assert archive["status"] == "complete"
    assert archive["manifest_sha256"] is not None
    assert archive["archived_at"] is not None
    archive_path = Path(archive["archive_path"])
    assert archive_path.is_dir()
    assert (archive_path / "PACKAGE_COMPLETE").is_file()

    # non-destructive: source workspace preserved, byte-identical
    assert folder.is_dir()
    assert (folder / "footage" / "clip1.mov").read_bytes() == b"raw-footage"

    episode = services.db.get_episode_by_episode_id("RLC-E025")
    assert episode.status == EpisodeStatus.ARCHIVED
    assert episode.folder_path == str(folder)


def test_run_archive_create_explicit_render_job_id_passed_through(tmp_path):
    """Two completed render jobs -> ambiguous without an explicit
    render_job_id; the CLI passes the caller-supplied value straight to
    ArchiveManager, never re-implementing selection itself."""
    services = make_persistence_services(tmp_path)
    folder, first_job, _ = seed_rendered_episode(services, tmp_path, 25, "RLC-E025")

    second_output = folder / "exports" / "RLC-E025_MASTER_2.mov"
    second_output.write_bytes(b"second-rendered-master-bytes")
    second_job = services.db.create_render_job(
        "RLC-E025",
        "broadcast_master",
        resolve_job_id="resolve-RLC-E025-2",
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        output_path=str(second_output),
        status=RenderJobStatus.COMPLETE,
    )

    ambiguous = _run_archive_create(services, "RLC-E025")
    assert ambiguous["success"] is False

    result = _run_archive_create(services, "RLC-E025", render_job_id=second_job.id)
    assert result["success"] is True
    assert result["archive"]["render_job_id"] == second_job.id


def test_run_archive_create_manifest_path_passed_through_for_legacy_fallback(tmp_path):
    services = make_persistence_services(tmp_path)
    folder, render_job, (ingest_file, asset_file) = seed_rendered_episode(
        services, tmp_path, 25, "RLC-E025", with_provenance=False
    )

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

    without_fallback = _run_archive_create(services, "RLC-E025")
    assert without_fallback["success"] is False

    result = _run_archive_create(services, "RLC-E025", manifest_path=str(manifest_path))
    assert result["success"] is True


def test_run_archive_create_unknown_episode(tmp_path):
    services = make_persistence_services(tmp_path)

    result = _run_archive_create(services, "RLC-E999")

    assert result["success"] is False
    assert result["classification"] == "error"
    assert "RLC-E999" in result["error"]


def test_run_archive_create_already_archived(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_rendered_episode(services, tmp_path, 25, "RLC-E025")
    _run_archive_create(services, "RLC-E025")

    result = _run_archive_create(services, "RLC-E025")

    assert result["success"] is False
    assert "already has a committed" in result["error"]


def test_run_archive_create_missing_folder_path(tmp_path):
    services = make_persistence_services(tmp_path)
    services.db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    services.db.update_episode_status("RLC-E025", EpisodeStatus.RENDERED)
    # No update_episode_paths() call: folder_path stays None.

    result = _run_archive_create(services, "RLC-E025")

    assert result["success"] is False
    assert "no working folder" in result["error"]


def test_run_archive_create_destination_already_exists(tmp_path):
    """Phase 15 Mission 15H: a pre-existing, non-package (garbage/partial)
    directory at the canonical destination is independently verified --
    and fails, since it is not a real Rev1 package -- rather than being
    reported as a bare collision or silently overwritten."""
    services = make_persistence_services(tmp_path)
    folder, render_job, _ = seed_rendered_episode(services, tmp_path, 25, "RLC-E025")

    manager = services.archive_manager
    inventory = archive_integrity.build_source_inventory(folder)
    render_master_file = manager._require_render_master_is_inventory_file(render_job, inventory)
    plan = manager._build_content_plan(
        episode_id="RLC-E025", workspace_inventory=inventory, render_master_file=render_master_file, manifest_path=None
    )
    archive_id = manager._derive_archive_id("RLC-E025", plan.content_set_digest)
    collision_dir = tmp_path / "_archive" / "episodes" / "RLC-E025" / archive_id
    collision_dir.mkdir(parents=True)
    sentinel = collision_dir / "sentinel-garbage.txt"
    sentinel.write_bytes(b"pre-existing garbage payload")
    before_entries = sorted(p.name for p in collision_dir.iterdir())
    before_bytes = sentinel.read_bytes()

    result = _run_archive_create(services, "RLC-E025")

    assert result["success"] is False
    assert result["classification"] == "error"
    assert "unexpected root-level package content" in result["error"]
    assert sentinel.name in result["error"]
    assert collision_dir.is_dir()
    assert sorted(p.name for p in collision_dir.iterdir()) == before_entries
    assert sentinel.read_bytes() == before_bytes
    assert not (collision_dir / "archive_manifest.json").exists()
    assert not (collision_dir / "archive_manifest.sha256").exists()
    assert not (collision_dir / "PACKAGE_COMPLETE").exists()
    assert services.db.get_archive_by_episode_id("RLC-E025") is None
    assert services.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED


def test_run_archive_create_verified_unregistered_is_classified_distinctly(tmp_path, monkeypatch):
    """DB commit failure after a successful, verified publication must be
    reported with its own distinct classification -- never collapsed into
    a generic "archive failed, nothing happened" message, since a real
    verified package now exists on disk."""
    services = make_persistence_services(tmp_path)
    seed_rendered_episode(services, tmp_path, 25, "RLC-E025")

    from redline_core.db.database import ArchiveCommitError

    def _forced_failure(*args, **kwargs):
        raise ArchiveCommitError("simulated DB commit failure")

    monkeypatch.setattr(services.db, "commit_verified_archive", _forced_failure)

    result = _run_archive_create(services, "RLC-E025")

    assert result["success"] is False
    assert result["classification"] == "verified_unregistered"
    assert result["episode_id"] == "RLC-E025"
    assert result["archive_id"] is not None
    assert Path(result["archive_path"]).is_dir()
    assert result["manifest_sha256"] is not None
    # episode never transitions to archived; no archive DB row committed
    assert services.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED
    assert services.db.get_archive_by_episode_id("RLC-E025") is None


# -- _print_archive_create_result ------------------------------------------------


def test_print_archive_create_result_success(capsys):
    _print_archive_create_result(
        {
            "success": True,
            "archive": {
                "episode_id": "RLC-E025",
                "archive_id": "RLC-E025-a1-abc123abc123",
                "archive_path": "/archive/RLC-E025",
                "render_job_id": 7,
                "manifest_sha256": "a" * 64,
                "archived_at": "2026-07-29 19:00:47",
                "status": "complete",
            },
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "RLC-E025-a1-abc123abc123" in out
    assert "/archive/RLC-E025" in out
    assert "7" in out
    assert "a" * 64 in out
    assert "complete" in out


def test_print_archive_create_result_failure(capsys):
    _print_archive_create_result(
        {"success": False, "classification": "error", "error": "No episode with episode_id=RLC-E999."}
    )

    out = capsys.readouterr().out
    assert "Archive create failed:" in out
    assert "RLC-E999" in out


def test_print_archive_create_result_verified_unregistered(capsys):
    _print_archive_create_result(
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
    assert "verified and published" in out
    assert "database registration FAILED" in out
    assert "RLC-E025" in out
    assert "NOT deleted, moved, or overwritten" in out


# -- argument parsing -----------------------------------------------------------


def test_parser_archive_create_parses_episode_id():
    parser = _build_parser()
    args = parser.parse_args(["archive", "create", "RLC-E025"])
    assert args.resource == "archive"
    assert args.action == "create"
    assert args.episode_id == "RLC-E025"
    assert args.render_job_id is None
    assert args.manifest_path is None


def test_parser_archive_create_parses_optional_render_job_id_and_manifest():
    parser = _build_parser()
    args = parser.parse_args(
        ["archive", "create", "RLC-E025", "--render-job-id", "7", "--manifest", "legacy.yaml"]
    )
    assert args.render_job_id == 7
    assert args.manifest_path == "legacy.yaml"


def test_parser_archive_episode_is_not_registered():
    """Phase 15 Mission 15F: the legacy `archive episode` command is
    retired entirely, not left as an undocumented alias for `archive
    create`. There is exactly one canonical way to archive an episode."""
    import pytest

    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["archive", "episode", "RLC-E025"])


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


def test_main_archive_create_end_to_end_without_mock_resolve(tmp_path, monkeypatch, capsys):
    """No --mock-resolve set at all — an `episode` command in this same
    environment would either fail (real Resolve not running in this
    sandbox) or require the flag. `archive create` must do neither,
    because it's routed through PersistenceServices, which never touches
    Resolve.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    db_path = tmp_path / "redline.db"
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    from redline_core.config.loader import load_config

    config = load_config(config_dir)
    db = Database(db_path).connect()
    db.init_schema()
    services = PersistenceServices(config=config, db=db, archive_manager=ArchiveManager(config, db))
    folder, _, _ = seed_rendered_episode(services, tmp_path, 25, "RLC-E025")
    db.close()

    exit_code = cli_main.main(["archive", "create", "RLC-E025"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert folder.is_dir()


def test_main_archive_create_unknown_is_clean_error(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "redline.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["archive", "create", "RLC-E999"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Archive create failed:" in out


def test_main_archive_episode_is_a_clean_argparse_error(tmp_path, monkeypatch, capsys):
    """End-to-end proof that the legacy command is gone from the real
    parser main() builds, not just from a standalone _build_parser() call."""
    import pytest

    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "redline.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit):
        cli_main.main(["archive", "episode", "RLC-E025"])
