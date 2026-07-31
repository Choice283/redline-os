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
from redline_core.render.exceptions import (
    RenderError,
    RenderConfigurationError,
    RenderJobNotFoundError,
    RenderOutputCollisionError,
    RenderPersistenceError,
    RenderPresetNotFoundError,
    RenderReconciliationRequiredError,
)
from redline_core.render.manager import RenderManager
from redline_core.render.plan import build_render_output_plan
from redline_core.resolve.mock import MockResolveAdapter


def make_manager(tmp_path: Path):
    config = RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(
            presets=[
                RenderPreset(
                    name="broadcast_master",
                    resolve_preset_name="Redline Broadcast Master",
                    output_subfolder="exports",
                    filename_template="{episode_id}",
                    file_extension=".mov",
                    collision_policy="reject",
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


def test_queue_render_success(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    assert job.status == RenderJobStatus.QUEUED
    assert job.resolve_job_id is not None
    assert job.output_path == str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025.mov")
    assert job.project_name == "RLC-E025_MASTER"
    assert job.timeline_name == "RLC-E025_TIMELINE"
    assert resolve.render_job_metadata[job.resolve_job_id]["TargetDir"] == str(
        tmp_path / "_episodes" / "RLC-E025" / "exports"
    )
    assert resolve.render_job_metadata[job.resolve_job_id]["CustomName"] == "RLC-E025"

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


def test_render_configuration_error_is_render_domain_error():
    assert issubclass(RenderConfigurationError, RenderError)


def test_queue_render_incomplete_preset_fails_closed_before_mutation(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    manager.config.render_presets.presets[0].filename_template = None
    manager.config.render_presets.presets[0].file_extension = None
    output_directory = tmp_path / "_episodes" / "RLC-E025" / "exports"

    with pytest.raises(RenderConfigurationError, match="filename_template"):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    assert resolve.render_jobs == {}
    assert not output_directory.exists()


def test_queue_render_missing_episode_workspace_fails_closed_before_mutation(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    db.update_episode_paths("RLC-E025", project_path="/mock/x.drp", folder_path="")
    output_directory = tmp_path / "exports"

    with pytest.raises(RenderConfigurationError, match="no configured workspace"):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    assert resolve.render_jobs == {}
    assert not output_directory.exists()


def test_queue_render_missing_episode_workspace_directory_fails_closed_before_mutation(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    missing_workspace = tmp_path / "_episodes" / "missing"
    db.update_episode_paths("RLC-E025", project_path="/mock/x.drp", folder_path=str(missing_workspace))

    with pytest.raises(RenderConfigurationError, match="Episode workspace does not exist"):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    assert resolve.render_jobs == {}
    assert not missing_workspace.exists()


def test_get_render_status_syncs_from_resolve(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    resolve.simulate_render_complete(job.resolve_job_id)
    updated = manager.get_render_status(job.id)

    assert updated.status == RenderJobStatus.COMPLETE
    assert updated.project_name == "RLC-E025_MASTER"
    assert updated.timeline_name == "RLC-E025_TIMELINE"
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

    jobs = manager.list_render_jobs_for_episode("RLC-E025")
    assert len(jobs) == 1
    assert jobs[0].project_name == "RLC-E025_MASTER"
    assert jobs[0].timeline_name == "RLC-E025_TIMELINE"


def test_output_plan_is_deterministic_and_under_export_directory(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    episode = db.get_episode_by_episode_id("RLC-E025")
    preset = manager.config.render_presets.get("broadcast_master")

    plan_a = build_render_output_plan(episode, preset, "RLC-E025_TIMELINE")
    plan_b = build_render_output_plan(episode, preset, "RLC-E025_TIMELINE")

    assert plan_a == plan_b
    assert plan_a.output_directory == tmp_path / "_episodes" / "RLC-E025" / "exports"
    assert plan_a.output_path == plan_a.output_directory / "RLC-E025.mov"


def test_output_plan_rejects_rendered_stem_containing_separator(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    episode = db.get_episode_by_episode_id("RLC-E025")
    preset = manager.config.render_presets.get("broadcast_master")
    preset.filename_template = "{episode_id}/master"

    with pytest.raises(RenderConfigurationError, match="invalid output filename"):
        build_render_output_plan(episode, preset, "RLC-E025_TIMELINE")


def test_queue_render_rejects_existing_exact_output_file_before_mutation(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    output = tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025.mov"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"existing")

    with pytest.raises(RenderOutputCollisionError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    assert resolve.render_jobs == {}


def test_queue_render_rejects_active_database_job_same_output_before_resolve(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    output = str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025.mov")
    db.create_render_job("RLC-E025", "broadcast_master", resolve_job_id="old", output_path=output)

    with pytest.raises(RenderOutputCollisionError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert resolve.render_jobs == {}


def test_queue_render_allows_terminal_historical_job_when_output_absent(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    output = str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025.mov")
    old_job = db.create_render_job("RLC-E025", "broadcast_master", resolve_job_id="old", output_path=output)
    db.update_render_job(old_job.id, status=RenderJobStatus.COMPLETE)

    job = manager.queue_render("RLC-E025", "broadcast_master")

    assert job.resolve_job_id != "old"


def test_queue_render_rejects_matching_resolve_queue_job_before_database_insert(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    resolve.render_jobs["resolve-existing"] = "queued"
    resolve.render_job_metadata["resolve-existing"] = {
        "JobId": "resolve-existing",
        "ProjectName": "RLC-E025_MASTER",
        "TimelineName": "RLC-E025_TIMELINE",
        "TargetDir": str(tmp_path / "_episodes" / "RLC-E025" / "exports"),
        "CustomName": "RLC-E025",
    }

    with pytest.raises(RenderOutputCollisionError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []


class RecordingResolve(MockResolveAdapter):
    def __init__(self, calls: list[str]):
        super().__init__()
        self.calls = calls

    def queue_render_job(self, **kwargs) -> str:
        self.calls.append("AddRenderJob")
        return super().queue_render_job(**kwargs)


class RecordingDatabase(Database):
    def __init__(self, path: Path, calls: list[str]):
        super().__init__(path)
        self.calls = calls

    def create_render_job(self, *args, **kwargs):
        self.calls.append("create_render_job")
        return super().create_render_job(*args, **kwargs)

    def create_accepted_render_job(self, *args, **kwargs):
        self.calls.append("create_accepted_render_job")
        return super().create_accepted_render_job(*args, **kwargs)


def test_queue_render_adds_resolve_job_before_database_insert(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    db.close()
    calls: list[str] = []
    recording_db = RecordingDatabase(tmp_path / "ordered.db", calls).connect()
    recording_db.init_schema()
    recording_db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    folder = tmp_path / "_episodes" / "RLC-E025"
    recording_db.update_episode_paths("RLC-E025", project_path="/mock/x.drp", folder_path=str(folder))
    recording_resolve = RecordingResolve(calls)
    recording_resolve.connect()
    recording_resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    recording_resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    manager = RenderManager(manager.config, recording_db, recording_resolve)

    manager.queue_render("RLC-E025", "broadcast_master")

    assert calls == ["AddRenderJob", "create_accepted_render_job"]


class FailingCreateDatabase(Database):
    def create_accepted_render_job(self, *args, **kwargs):
        raise RuntimeError("insert failed")


class DeleteRecordingResolve(MockResolveAdapter):
    def __init__(self):
        super().__init__()
        self.deleted_job_ids: list[str] = []

    def delete_render_job(self, project_name: str, resolve_job_id: str) -> None:
        self.deleted_job_ids.append(resolve_job_id)
        super().delete_render_job(project_name, resolve_job_id)


def test_database_insert_failure_deletes_accepted_resolve_job(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    resolve = DeleteRecordingResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    db.close()
    failing_db = FailingCreateDatabase(tmp_path / "failing.db").connect()
    failing_db.init_schema()
    failing_db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    failing_db.update_episode_paths(
        "RLC-E025", project_path="/mock/x.drp", folder_path=str(tmp_path / "_episodes" / "RLC-E025")
    )
    manager = RenderManager(manager.config, failing_db, resolve)

    with pytest.raises(RenderPersistenceError, match="removed"):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert resolve.render_jobs == {}
    assert resolve.deleted_job_ids == ["mock-job-1"]


class FailingEpisodeStatusDatabase(Database):
    def _mark_episode_render_queued(self, episode_id: str) -> None:
        raise RuntimeError("status update failed")


def test_episode_status_update_failure_rolls_back_render_row_and_deletes_resolve_job(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    db.close()
    failing_db = FailingEpisodeStatusDatabase(tmp_path / "failing-status.db").connect()
    failing_db.init_schema()
    failing_db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    failing_db.update_episode_paths(
        "RLC-E025", project_path="/mock/x.drp", folder_path=str(tmp_path / "_episodes" / "RLC-E025")
    )
    manager = RenderManager(manager.config, failing_db, resolve)

    with pytest.raises(RenderPersistenceError, match="removed"):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert failing_db.list_render_jobs_for_episode("RLC-E025") == []
    assert failing_db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.CREATED
    assert resolve.render_jobs == {}


class DeleteFailingResolve(MockResolveAdapter):
    def delete_render_job(self, project_name: str, resolve_job_id: str) -> None:
        raise RuntimeError("delete failed")


def test_failed_compensation_surfaces_resolve_job_id(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    resolve = DeleteFailingResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    db.close()
    failing_db = FailingCreateDatabase(tmp_path / "failing-comp.db").connect()
    failing_db.init_schema()
    failing_db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    failing_db.update_episode_paths(
        "RLC-E025", project_path="/mock/x.drp", folder_path=str(tmp_path / "_episodes" / "RLC-E025")
    )
    manager = RenderManager(manager.config, failing_db, resolve)

    with pytest.raises(RenderReconciliationRequiredError, match="mock-job-1"):
        manager.queue_render("RLC-E025", "broadcast_master")
