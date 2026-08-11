"""Tests for RenderManager, against MockResolveAdapter + a temp DB."""
import threading
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
    RenderJobMissingResolveIdError,
    RenderJobNotFoundError,
    RenderJobNotStartableError,
    RenderOutputCollisionError,
    RenderPersistenceError,
    RenderPresetNotFoundError,
    RenderReconciliationRequiredError,
    RenderStartPersistenceReconciliationRequiredError,
)
from redline_core.render.manager import RenderManager
from redline_core.render.plan import build_render_output_plan
from redline_core.resolve.exceptions import (
    RenderJobError,
    RenderQueueAcceptanceNotObservedError,
    RenderQueueIdentityUnresolvedError,
    RenderStartReconciliationRequiredError,
)
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
                    filename_template="{project_name}",
                    file_extension=".mov",
                    collision_policy="reject",
                    requires_video_payload=True,
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
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)

    return RenderManager(config, db, resolve), db, resolve


def test_queue_render_success(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    assert job.status == RenderJobStatus.QUEUED
    assert job.resolve_job_id is not None
    assert job.output_path == str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025_MASTER.mov")
    assert job.project_name == "RLC-E025_MASTER"
    assert job.timeline_name == "RLC-E025_TIMELINE"
    assert resolve.render_job_metadata[job.resolve_job_id]["TargetDir"] == str(
        tmp_path / "_episodes" / "RLC-E025" / "exports"
    )
    assert resolve.render_job_metadata[job.resolve_job_id]["CustomName"] == "RLC-E025_MASTER"

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


def test_start_render_unknown_job_raises(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    with pytest.raises(RenderJobNotFoundError):
        manager.start_render(999)


def test_start_render_requires_resolve_job_id(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    # claim_render_output() alone (without finalize_render_output_claim())
    # produces exactly the pre-Resolve-acceptance state this test needs:
    # status CLAIMING, resolve_job_id still unset.
    claim = db.claim_render_output(
        episode_id="RLC-E025",
        preset_name="broadcast_master",
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        output_path=str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "unclaimed.mov"),
    )
    assert claim is not None
    assert claim.resolve_job_id is None

    with pytest.raises(RenderJobMissingResolveIdError):
        manager.start_render(claim.id)

    assert resolve.render_jobs == {}


def test_start_render_queued_job_succeeds(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    started = manager.start_render(job.id)

    assert started.status == RenderJobStatus.RENDERING
    assert resolve.get_render_status(job.resolve_job_id) == "rendering"
    persisted = db.get_render_job_by_id(job.id)
    assert persisted.status == RenderJobStatus.RENDERING


@pytest.mark.parametrize(
    "make_status",
    [
        RenderJobStatus.RENDERING,
        RenderJobStatus.COMPLETE,
        RenderJobStatus.FAILED,
        RenderJobStatus.CANCELLED,
        RenderJobStatus.CLAIMING,
    ],
)
def test_start_render_rejects_non_queued_status(tmp_path, make_status):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    db.update_render_job(job.id, status=make_status)

    with pytest.raises(RenderJobNotStartableError, match=make_status.value):
        manager.start_render(job.id)

    # The adapter must never be contacted once the DB-level status check
    # alone is sufficient to reject the request.
    persisted = db.get_render_job_by_id(job.id)
    assert persisted.status == make_status


def test_start_render_adapter_failure_propagates_without_db_write(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    # Simulate the Resolve-side job having vanished without Redline's DB
    # knowing -- the DB row is still QUEUED, so the manager's own
    # precondition checks pass and the adapter is actually contacted.
    del resolve.render_jobs[job.resolve_job_id]

    with pytest.raises(RenderJobError):
        manager.start_render(job.id)

    persisted = db.get_render_job_by_id(job.id)
    assert persisted.status == RenderJobStatus.QUEUED


def test_start_render_does_not_call_adapter_twice(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    manager.start_render(job.id)

    with pytest.raises(RenderJobNotStartableError):
        manager.start_render(job.id)

    # Exactly one Resolve-side transition to "rendering" occurred; the
    # second call was rejected by the manager's own DB-status precondition
    # before ever reaching the adapter again.
    assert resolve.get_render_status(job.resolve_job_id) == "rendering"


def test_start_render_passes_persisted_project_and_timeline_identity_to_adapter(tmp_path):
    """Rev2 Finding 1/2: RenderManager must source project_name/timeline_name
    from the persisted RenderJob and thread them through to the adapter --
    proven here by the fact that MockResolveAdapter.start_render() only
    succeeds when those values match the job's own stored queue metadata."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    started = manager.start_render(job.id)

    assert started.project_name == "RLC-E025_MASTER"
    assert started.timeline_name == "RLC-E025_TIMELINE"
    assert resolve.render_job_metadata[job.resolve_job_id]["ProjectName"] == "RLC-E025_MASTER"
    assert resolve.render_job_metadata[job.resolve_job_id]["TimelineName"] == "RLC-E025_TIMELINE"


def test_start_render_propagates_adapter_output_destination_mismatch(tmp_path):
    """Rev3 Finding 3, threaded end to end through the manager: if the
    Resolve-side queue entry's own recorded destination no longer matches
    the persisted output_path (simulated here the same way live Resolve
    drift would surface -- the queue metadata itself disagrees), the
    adapter's output-destination binding must reject it and the manager
    must propagate that rejection without touching the database."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    resolve.render_job_metadata[job.resolve_job_id]["TargetDir"] = str(tmp_path / "drifted-elsewhere")

    with pytest.raises(RenderJobError, match="not the requested output destination"):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "queued"


def test_start_render_rejects_missing_persisted_project_name_before_adapter_start_call(tmp_path):
    """Rev3 Finding 5: renamed from '..._before_resolve_contact' -- this
    proves only that no start-specific ResolveAdapter.start_render() call
    happened, not that Resolve was never connected to at all (composition
    already connects it unconditionally before any CLI command runs)."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    db.update_render_job(job.id, status=RenderJobStatus.QUEUED)
    db.conn.execute("UPDATE render_jobs SET project_name = NULL WHERE id = ?", (job.id,))
    db.conn.commit()

    with pytest.raises(RenderJobNotStartableError, match="project_name"):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "queued"


def test_start_render_rejects_missing_persisted_timeline_name_before_adapter_start_call(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    db.conn.execute("UPDATE render_jobs SET timeline_name = NULL WHERE id = ?", (job.id,))
    db.conn.commit()

    with pytest.raises(RenderJobNotStartableError, match="timeline_name"):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "queued"


def test_start_render_rejects_existing_output_at_start_time_before_adapter_start_call(tmp_path):
    """Rev2 Finding 8: a start-time recheck distinct from the queue-time
    collision check -- the filesystem can change between queueing and
    starting."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    output = Path(job.output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"appeared after queueing")

    with pytest.raises(RenderOutputCollisionError, match="Render start mutation was not attempted"):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "queued"


def test_start_render_rejects_missing_persisted_output_path_before_adapter_start_call(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    db.conn.execute("UPDATE render_jobs SET output_path = NULL WHERE id = ?", (job.id,))
    db.conn.commit()

    with pytest.raises(RenderJobNotStartableError, match="output_path"):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "queued"


# --- Rev3 Finding 6: persisted identity hardening -----------------------------


@pytest.mark.parametrize(
    "column",
    ["resolve_job_id", "project_name", "timeline_name", "output_path"],
)
def test_start_render_rejects_non_string_typed_persisted_identity(tmp_path, column):
    """Every render_jobs identity column has TEXT affinity, so SQLite
    itself converts an inserted INTEGER/REAL into text -- a literal
    `UPDATE ... SET col = 123` would not actually exercise the non-string
    guard. A BLOB is the one storage class TEXT affinity does NOT convert
    (per SQLite's type-affinity rules), so it's the realistic way a
    non-`str` Python value (here: `bytes`) can end up in one of these
    columns if something other than Redline's own writers touched the
    row; this proves start_render() rejects it rather than silently
    stringifying it."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    db.conn.execute(f"UPDATE render_jobs SET {column} = X'313233' WHERE id = ?", (job.id,))
    db.conn.commit()

    with pytest.raises((RenderJobNotStartableError, RenderJobMissingResolveIdError)):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "queued"


@pytest.mark.parametrize(
    "column",
    ["resolve_job_id", "project_name", "timeline_name", "output_path"],
)
def test_start_render_rejects_whitespace_only_persisted_identity(tmp_path, column):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    db.conn.execute(f"UPDATE render_jobs SET {column} = '   ' WHERE id = ?", (job.id,))
    db.conn.commit()

    with pytest.raises(RenderJobNotStartableError, match="blank or improperly-whitespaced"):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "queued"


@pytest.mark.parametrize(
    "column",
    ["resolve_job_id", "project_name", "timeline_name", "output_path"],
)
def test_start_render_rejects_leading_or_trailing_whitespace_in_persisted_identity(tmp_path, column):
    """Fail-closed rather than silently repairing corrupted persisted
    identity by stripping it: a value with surrounding whitespace is
    rejected outright, not trimmed and accepted."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    original = getattr(job, column)
    db.conn.execute(f"UPDATE render_jobs SET {column} = ? WHERE id = ?", (f"  {original}  ", job.id))
    db.conn.commit()

    with pytest.raises(RenderJobNotStartableError, match="blank or improperly-whitespaced"):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "queued"


def test_start_render_allows_start_when_expected_output_absent(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")
    assert not Path(job.output_path).exists()

    started = manager.start_render(job.id)

    assert started.status == RenderJobStatus.RENDERING


def test_start_render_adapter_reconciliation_required_propagates_without_db_write(tmp_path):
    """When the adapter itself raises RenderStartReconciliationRequiredError
    (StartRendering was attempted; outcome unproven), the manager must not
    write to the database and must not wrap or reword the exception."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    original = RenderStartReconciliationRequiredError("outcome unproven")

    def fake_start_render(*, project_name, timeline_name, resolve_job_id, output_path):
        raise original

    resolve.start_render = fake_start_render

    with pytest.raises(RenderStartReconciliationRequiredError) as exc_info:
        manager.start_render(job.id)

    assert exc_info.value is original
    persisted = db.get_render_job_by_id(job.id)
    assert persisted.status == RenderJobStatus.QUEUED


def test_start_render_db_transition_exception_raises_persistence_reconciliation_required(tmp_path, monkeypatch):
    """Rev2 Finding 7: Resolve is confirmed Rendering, but the guarded DB
    transition itself raises -- this is a split-brain condition, not an
    ordinary failure, and must never trigger a second Resolve mutation."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    def raising_transition(job_id):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(db, "transition_render_job_to_rendering", raising_transition)

    with pytest.raises(RenderStartPersistenceReconciliationRequiredError):
        manager.start_render(job.id)

    # Resolve itself is confirmed rendering -- the split-brain is entirely
    # on the Redline database side, and no second Resolve mutation happened.
    assert resolve.get_render_status(job.resolve_job_id) == "rendering"


def test_start_render_db_transition_zero_rows_raises_persistence_reconciliation_required(tmp_path, monkeypatch):
    """Simulates the row having disappeared or drifted status between the
    manager's own precondition read and the guarded transition (0 rows
    affected) -- covers the same class of split-brain as the exception
    case above, via the transition's own guarded return value instead."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    monkeypatch.setattr(db, "transition_render_job_to_rendering", lambda job_id: False)

    with pytest.raises(RenderStartPersistenceReconciliationRequiredError):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "rendering"


def test_start_render_reload_failure_after_confirmed_transition_raises_persistence_reconciliation_required(
    tmp_path, monkeypatch
):
    """The guarded RENDERING transition itself succeeds, but reloading the
    row afterward fails -- still a persistence-side reconciliation-required
    condition, not an ordinary error."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    original_get = db.get_render_job_by_id
    calls = {"n": 0}

    def flaky_get(job_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return original_get(job_id)
        return None

    monkeypatch.setattr(db, "get_render_job_by_id", flaky_get)

    with pytest.raises(RenderStartPersistenceReconciliationRequiredError):
        manager.start_render(job.id)

    assert resolve.get_render_status(job.resolve_job_id) == "rendering"


def test_start_render_successful_guarded_transition_persists_exactly_one_row(tmp_path):
    """The ordinary success path: the guarded QUEUED -> RENDERING
    transition affects exactly the one target row."""
    manager, db, resolve = make_manager(tmp_path)
    job = manager.queue_render("RLC-E025", "broadcast_master")

    started = manager.start_render(job.id)

    assert started.status == RenderJobStatus.RENDERING
    row = db.conn.execute("SELECT status FROM render_jobs WHERE id = ?", (job.id,)).fetchone()
    assert row["status"] == RenderJobStatus.RENDERING.value


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
    assert plan_a.output_stem == "RLC-E025_MASTER"
    assert plan_a.output_path == plan_a.output_directory / "RLC-E025_MASTER.mov"


def test_output_plan_rejects_rendered_stem_containing_separator(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    episode = db.get_episode_by_episode_id("RLC-E025")
    preset = manager.config.render_presets.get("broadcast_master")
    preset.filename_template = "{episode_id}/master"

    with pytest.raises(RenderConfigurationError, match="invalid output filename"):
        build_render_output_plan(episode, preset, "RLC-E025_TIMELINE")


def test_queue_render_rejects_existing_exact_output_file_before_mutation(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    output = tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025_MASTER.mov"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"existing")

    with pytest.raises(RenderOutputCollisionError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    assert resolve.render_jobs == {}


def test_queue_render_rejects_active_database_job_same_output_before_resolve(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    output = str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025_MASTER.mov")
    db.create_render_job("RLC-E025", "broadcast_master", resolve_job_id="old", output_path=output)

    with pytest.raises(RenderOutputCollisionError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert resolve.render_jobs == {}


def test_queue_render_allows_terminal_historical_job_when_output_absent(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    output = str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025_MASTER.mov")
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
        "CustomName": "RLC-E025_MASTER",
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

    def claim_render_output(self, *args, **kwargs):
        self.calls.append("claim_render_output")
        return super().claim_render_output(*args, **kwargs)

    def finalize_render_output_claim(self, *args, **kwargs):
        self.calls.append("finalize_render_output_claim")
        return super().finalize_render_output_claim(*args, **kwargs)


def test_queue_render_claims_output_before_adding_resolve_job(tmp_path):
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
    recording_resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)
    manager = RenderManager(manager.config, recording_db, recording_resolve)

    manager.queue_render("RLC-E025", "broadcast_master")

    assert calls == ["claim_render_output", "AddRenderJob", "finalize_render_output_claim"]


class FailingFinalizeDatabase(Database):
    def finalize_render_output_claim(self, *args, **kwargs):
        raise RuntimeError("finalize failed")


class DeleteRecordingResolve(MockResolveAdapter):
    def __init__(self):
        super().__init__()
        self.deleted_job_ids: list[str] = []

    def delete_render_job(self, project_name: str, resolve_job_id: str) -> None:
        self.deleted_job_ids.append(resolve_job_id)
        super().delete_render_job(project_name, resolve_job_id)


def test_database_finalize_failure_deletes_accepted_resolve_job_and_releases_claim(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    resolve = DeleteRecordingResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)
    db.close()
    failing_db = FailingFinalizeDatabase(tmp_path / "failing.db").connect()
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
    assert failing_db.list_render_jobs_for_episode("RLC-E025") == []


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
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)
    db.close()
    failing_db = FailingFinalizeDatabase(tmp_path / "failing-comp.db").connect()
    failing_db.init_schema()
    failing_db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    failing_db.update_episode_paths(
        "RLC-E025", project_path="/mock/x.drp", folder_path=str(tmp_path / "_episodes" / "RLC-E025")
    )
    manager = RenderManager(manager.config, failing_db, resolve)

    with pytest.raises(RenderReconciliationRequiredError, match="mock-job-1"):
        manager.queue_render("RLC-E025", "broadcast_master")


class FailingQueueResolve(MockResolveAdapter):
    def queue_render_job(self, **kwargs) -> str:
        raise RuntimeError("resolve queue failed")


def test_resolve_failure_releases_output_claim_for_retry(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    resolve = FailingQueueResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)
    manager = RenderManager(manager.config, db, resolve)
    output = str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025_MASTER.mov")

    with pytest.raises(RuntimeError, match="resolve queue failed"):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    assert db.claim_render_output(
        episode_id="RLC-E025",
        preset_name="broadcast_master",
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        output_path=output,
    ) is not None


class RaisingIdentityUnresolvedResolve(MockResolveAdapter):
    def queue_render_job(self, **kwargs) -> str:
        raise RenderQueueIdentityUnresolvedError("Resolve added a render job but returned no usable job ID.")


class ReleaseRecordingDatabase(Database):
    def __init__(self, path: Path, calls: list):
        super().__init__(path)
        self.calls = calls
        self.claimed_id = None

    def claim_render_output(self, *args, **kwargs):
        claim = super().claim_render_output(*args, **kwargs)
        self.claimed_id = claim.id if claim is not None else None
        self.calls.append(("claim_render_output", self.claimed_id))
        return claim

    def release_render_output_claim(self, claim_id, *args, **kwargs):
        self.calls.append(("release_render_output_claim", claim_id))
        return super().release_render_output_claim(claim_id, *args, **kwargs)

    def finalize_render_output_claim(self, *args, **kwargs):
        self.calls.append(("finalize_render_output_claim",))
        return super().finalize_render_output_claim(*args, **kwargs)


def test_identity_unresolved_failure_releases_exact_claim_and_skips_finalize(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    resolve = RaisingIdentityUnresolvedResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)
    db.close()
    calls: list = []
    recording_db = ReleaseRecordingDatabase(tmp_path / "identity-unresolved.db", calls).connect()
    recording_db.init_schema()
    recording_db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    recording_db.update_episode_paths(
        "RLC-E025", project_path="/mock/x.drp", folder_path=str(tmp_path / "_episodes" / "RLC-E025")
    )
    manager = RenderManager(manager.config, recording_db, resolve)

    with pytest.raises(RenderQueueIdentityUnresolvedError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert recording_db.claimed_id is not None
    assert ("release_render_output_claim", recording_db.claimed_id) in recording_db.calls
    assert not any(call[0] == "finalize_render_output_claim" for call in recording_db.calls)


def test_identity_unresolved_failure_leaves_no_render_row_and_episode_created(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    resolve = RaisingIdentityUnresolvedResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)
    manager = RenderManager(manager.config, db, resolve)

    with pytest.raises(RenderQueueIdentityUnresolvedError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.CREATED


class RaisingAcceptanceNotObservedResolve(MockResolveAdapter):
    def queue_render_job(self, **kwargs) -> str:
        raise RenderQueueAcceptanceNotObservedError(
            "Resolve AddRenderJob() returned an empty string and the render-job ID multiset was unchanged."
        )


def test_acceptance_not_observed_failure_releases_exact_claim_and_skips_finalize(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    resolve = RaisingAcceptanceNotObservedResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)
    db.close()
    calls: list = []
    recording_db = ReleaseRecordingDatabase(tmp_path / "acceptance-not-observed.db", calls).connect()
    recording_db.init_schema()
    recording_db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    recording_db.update_episode_paths(
        "RLC-E025", project_path="/mock/x.drp", folder_path=str(tmp_path / "_episodes" / "RLC-E025")
    )
    manager = RenderManager(manager.config, recording_db, resolve)

    with pytest.raises(RenderQueueAcceptanceNotObservedError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert recording_db.claimed_id is not None
    assert ("release_render_output_claim", recording_db.claimed_id) in recording_db.calls
    assert not any(call[0] == "finalize_render_output_claim" for call in recording_db.calls)


def test_acceptance_not_observed_failure_leaves_no_render_row_and_episode_created(tmp_path):
    manager, db, _resolve = make_manager(tmp_path)
    resolve = RaisingAcceptanceNotObservedResolve()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)
    manager = RenderManager(manager.config, db, resolve)

    with pytest.raises(RenderQueueAcceptanceNotObservedError):
        manager.queue_render("RLC-E025", "broadcast_master")

    assert db.list_render_jobs_for_episode("RLC-E025") == []
    assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.CREATED


class CountingResolve(MockResolveAdapter):
    def __init__(self):
        super().__init__()
        self.queue_calls = 0
        self.lock = threading.Lock()

    def queue_render_job(self, **kwargs) -> str:
        with self.lock:
            self.queue_calls += 1
        return super().queue_render_job(**kwargs)


class BarrierClaimDatabase(Database):
    barrier: threading.Barrier | None = None

    def claim_render_output(self, *args, **kwargs):
        self.barrier.wait(timeout=5)
        return super().claim_render_output(*args, **kwargs)


def test_concurrent_queue_attempts_only_one_claim_reaches_resolve(tmp_path):
    manager, db, resolve = make_manager(tmp_path)
    config = manager.config
    db_path = db.db_path
    db.close()
    counting_resolve = CountingResolve()
    counting_resolve.connect()
    counting_resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    counting_resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    counting_resolve.set_video_timeline_item_count("RLC-E025_MASTER", "RLC-E025_TIMELINE", 1)
    BarrierClaimDatabase.barrier = threading.Barrier(2)
    results: list[object] = []

    def run_queue() -> None:
        local_db = BarrierClaimDatabase(db_path).connect()
        try:
            local_manager = RenderManager(config, local_db, counting_resolve)
            results.append(local_manager.queue_render("RLC-E025", "broadcast_master"))
        except Exception as exc:
            results.append(exc)
        finally:
            local_db.close()

    threads = [threading.Thread(target=run_queue), threading.Thread(target=run_queue)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    successes = [result for result in results if not isinstance(result, Exception)]
    collisions = [result for result in results if isinstance(result, RenderOutputCollisionError)]
    assert len(successes) == 1
    assert len(collisions) == 1
    assert counting_resolve.queue_calls == 1
    check_db = Database(db_path).connect()
    jobs = check_db.list_render_jobs_for_episode("RLC-E025")
    assert len(jobs) == 1
    assert jobs[0].status == RenderJobStatus.QUEUED
    assert jobs[0].output_path == str(tmp_path / "_episodes" / "RLC-E025" / "exports" / "RLC-E025_MASTER.mov")
    check_db.close()
