"""Tests for RenderManager, against MockResolveAdapter + a temp DB."""
from pathlib import Path

import pytest

from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPreset,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.db.database import Database
from redline_core.db.models import EpisodeStatus, RenderJobStatus
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.render.exceptions import RenderJobNotFoundError, RenderPresetNotFoundError
from redline_core.render.manager import RenderManager
from redline_core.resolve.mock import MockResolveAdapter


def make_manager(tmp_path: Path):
    config = RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(
            presets=[
                RenderPreset(name="broadcast_master", resolve_preset_name="Redline Broadcast Master", output_subfolder="exports"),
            ]
        ),
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
    resolve = MockResolveAdapter()
    resolve.connect()

    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    folder = tmp_path / "_episodes" / "RLC-E025"
    folder.mkdir(parents=True)
    db.update_episode_paths("RLC-E025", project_path="/mock/x.drp", folder_path=str(folder))
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")

    return RenderManager(config, db, resolve), db, resolve


def test_queue_render_success(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    assert job.status == RenderJobStatus.QUEUED
    assert job.resolve_job_id is not None
    assert job.output_path.endswith("exports")

    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.status == EpisodeStatus.RENDER_QUEUED


def test_queue_render_unknown_episode_raises(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    with pytest.raises(EpisodeNotFoundError):
        manager.queue_render("RLC-E999", "broadcast_master")


def test_queue_render_unknown_preset_raises(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    with pytest.raises(RenderPresetNotFoundError):
        manager.queue_render("RLC-E025", "does_not_exist")


def test_get_render_status_syncs_from_resolve(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    resolve.simulate_render_complete(job.resolve_job_id)
    updated = manager.get_render_status(job.id)

    assert updated.status == RenderJobStatus.COMPLETE
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.status == EpisodeStatus.RENDERED


def test_get_render_status_unknown_job_raises(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    with pytest.raises(RenderJobNotFoundError):
        manager.get_render_status(999)


def test_cancel_render(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    cancelled = manager.cancel_render(job.id)
    assert cancelled.status == RenderJobStatus.CANCELLED
    assert resolve.get_render_status(job.resolve_job_id) == "cancelled"


def test_list_render_jobs_for_episode(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    manager.queue_render("RLC-E025", "broadcast_master")
    manager.queue_render("RLC-E025", "broadcast_master")

    jobs = manager.list_render_jobs_for_episode("RLC-E025")
    assert len(jobs) == 2
