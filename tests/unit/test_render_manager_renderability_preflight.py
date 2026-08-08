"""Tests for the renderability preflight (Phase 14 Test D follow-up).

Test D found that the known-working disposable Control timeline stopped
being queueable once its sole video TimelineItem was removed, with audio,
markers, Media Pool inventory, settings, and render context otherwise
unchanged (see docs/CHANGELOG.md and docs/ROADMAP.md Phase 14). These tests
prove `RenderManager` now fails closed on that exact condition, before any
SQLite output claim or Resolve queue mutation, for presets configured with
`requires_video_payload: true` — without over-applying that rule to presets
that don't declare the requirement.
"""
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
from redline_core.render.exceptions import RenderTimelineNotRenderableError
from redline_core.render.manager import RenderManager
from redline_core.resolve.exceptions import TimelineOperationError
from redline_core.resolve.mock import MockResolveAdapter


def make_manager(tmp_path: Path, *, requires_video_payload: bool = True):
    config = RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(
            presets=[
                RenderPreset(
                    name="broadcast_master",
                    resolve_preset_name="Redline Broadcast Master",
                    output_subfolder="exports",
                    filename_template="{project_name}",
                    file_extension=".mov",
                    collision_policy="reject",
                    requires_video_payload=requires_video_payload,
                ),
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
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")

    return RenderManager(config, db, resolve), db, resolve


class RecordingResolve(MockResolveAdapter):
    """Records whether Resolve queue mutation was ever attempted."""

    def __init__(self):
        super().__init__()
        self.queue_render_job_calls = 0

    def queue_render_job(self, **kwargs) -> str:
        self.queue_render_job_calls += 1
        return super().queue_render_job(**kwargs)


class RaisingInspectionResolve(MockResolveAdapter):
    """Simulates missing/invalid Resolve inspection data."""

    def get_video_timeline_item_count(self, project_name: str, timeline_name: str) -> int:
        raise TimelineOperationError("Resolve returned an invalid video track count.")


def test_zero_video_items_fails_preflight(tmp_path):
    manager, _db, _resolve = make_manager(tmp_path)

    with pytest.raises(RenderTimelineNotRenderableError, match="no video TimelineItems"):
        manager.queue_render("RLC-E025", "broadcast_master")


def test_zero_video_failure_message_identifies_target_and_preset(tmp_path):
    manager, _db, _resolve = make_manager(tmp_path)

    with pytest.raises(RenderTimelineNotRenderableError) as exc_info:
        manager.queue_render("RLC-E025", "broadcast_master")

    message = str(exc_info.value)
    assert "RLC-E025_TIMELINE" in message
    assert "RLC-E025_MASTER" in message
    assert "broadcast_master" in message
    assert "not attempted" in message


def test_zero_video_failure_occurs_before_sqlite_claim(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    output = str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025_MASTER.mov")

    with pytest.raises(RenderTimelineNotRenderableError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    # No claim was left behind: a fresh claim for the same output must still succeed.
    claim = db.claim_render_output(
        episode_id="RLC-E025",
        preset_name="broadcast_master",
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        output_path=output,
    )
    assert claim is not None


def test_zero_video_failure_never_calls_resolve_queue_job(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    db.close()
    recording_db = Database(tmp_path / "recording.db").connect()
    recording_db.init_schema()
    recording_db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    folder = tmp_path / "_episodes" / "RLC-E025"
    recording_db.update_episode_paths("RLC-E025", project_path="/mock/x.drp", folder_path=str(folder))

    resolve = RecordingResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")

    manager = RenderManager(manager.config, recording_db, resolve)

    with pytest.raises(RenderTimelineNotRenderableError):
        manager.queue_render("RLC-E025", "broadcast_master")

    # queue_render_job() is the sole path to LoadRenderPreset()/SetRenderSettings()/
    # AddRenderJob() on the real adapter, so proving it is never called proves
    # those three Resolve mutations are unreachable on this failure path.
    assert resolve.queue_render_job_calls == 0
    assert recording_db.list_render_jobs_for_episode("RLC-E025") == []


def test_video_present_passes_preflight_and_queues_normally(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)

    job = manager.queue_render("RLC-E025", "broadcast_master")

    assert job.status == RenderJobStatus.QUEUED
    assert job.resolve_job_id is not None
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.status == EpisodeStatus.RENDER_QUEUED


def test_preset_without_video_requirement_is_not_subjected_to_broadcast_master_rule(tmp_path):
    manager, db, resolve = make_manager(tmp_path, requires_video_payload=False)
    assert resolve.get_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE") == 0

    job = manager.queue_render("RLC-E025", "broadcast_master")

    assert job.status == RenderJobStatus.QUEUED


def test_missing_inspection_data_fails_closed_not_renderable(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    resolve = RaisingInspectionResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    manager = RenderManager(manager.config, db, resolve)

    with pytest.raises(TimelineOperationError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    assert resolve.render_jobs == {}


def test_mock_adapter_video_item_count_defaults_to_zero(tmp_path):
    _manager, _db, resolve = make_manager(tmp_path)
    assert resolve.get_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE") == 0


def test_mock_adapter_video_item_count_reflects_test_helper(tmp_path):
    _manager, _db, resolve = make_manager(tmp_path)
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 3)
    assert resolve.get_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE") == 3
