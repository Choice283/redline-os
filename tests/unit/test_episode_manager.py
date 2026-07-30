"""Tests for EpisodeManager, built entirely against MockResolveAdapter + a
temp SQLite DB + temp folders — no real Resolve or Studio license needed."""
from pathlib import Path

import pytest

from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    MarkerDefinition,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.db.database import AssemblyClaimReleaseError, Database
from redline_core.db.models import EpisodeStatus
from redline_core.episode.exceptions import EpisodeAlreadyExistsError, EpisodeBuildError, EpisodeNotFoundError
from redline_core.episode.manager import EpisodeManager
from redline_core.episode.models import EpisodeBuildDefinition, EpisodeBuildResult
from redline_core.media.manager import MediaManager
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.timeline.builder import TimelineBuilder, TimelineBuildResult


class FakeMediaManager:
    def __init__(self, calls=None, result=None, error=None):
        self.calls = calls if calls is not None else []
        self.result = result if result is not None else ["clip-1"]
        self.error = error

    def import_media(self, project_name: str, media_paths: list[str], bin_name: str) -> list[str]:
        self.calls.append(("import_media", project_name, list(media_paths), bin_name))
        if self.error is not None:
            raise self.error
        return self.result


class FakeTimelineBuilder:
    def __init__(self, calls=None, build_error=None, place_error=None, place_result=None):
        self.calls = calls if calls is not None else []
        self.build_error = build_error
        self.place_error = place_error
        self.place_result = place_result if place_result is not None else ["item-1"]

    def timeline_name_for_episode(self, episode_id: str) -> str:
        return f"{episode_id}_TIMELINE"

    def build_timeline_for_episode(self, project_name: str, episode_id: str, markers=None) -> TimelineBuildResult:
        self.calls.append(("build_timeline", project_name, episode_id, list(markers or [])))
        if self.build_error is not None:
            raise self.build_error
        return TimelineBuildResult(
            timeline_id=f"{episode_id}_TIMELINE",
            timeline_name=f"{episode_id}_TIMELINE",
            markers_applied=len(markers or []),
        )

    def place_clips(self, project_name: str, timeline_name: str, clip_ids: list[str]) -> list[str]:
        self.calls.append(("place_clips", project_name, timeline_name, list(clip_ids)))
        if self.place_error is not None:
            raise self.place_error
        return self.place_result


def make_manager(
    tmp_path: Path,
    media_manager=None,
    timeline_builder=None,
) -> EpisodeManager:
    config = RedlineConfig(
        naming=NamingConfig(
            episode_id_pattern="RLC-E{episode_number:03d}",
            project_name_pattern="{episode_id}_MASTER",
        ),
        folder_structure=FolderStructureConfig(
            root_path=str(tmp_path / "_episodes"),
            subfolders=["footage", "graphics", "audio", "exports", "project"],
        ),
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
    resolve = MockResolveAdapter()
    resolve.connect()
    return EpisodeManager(
        config=config,
        db=db,
        resolve=resolve,
        media_manager=media_manager,
        timeline_builder=timeline_builder,
    )


def test_create_episode_success(tmp_path):
    manager = make_manager(tmp_path)
    episode = manager.create_episode(25)

    assert episode.episode_id == "RLC-E025"
    assert episode.project_name == "RLC-E025_MASTER"
    assert episode.status == EpisodeStatus.CREATED
    assert episode.folder_path is not None
    assert episode.project_path is not None

    folder = Path(episode.folder_path)
    assert folder.is_dir()
    for sub in ["footage", "graphics", "audio", "exports", "project"]:
        assert (folder / sub).is_dir()

    # And it actually exists in the mock Resolve backend.
    assert episode.project_name in manager.resolve.projects


def test_create_episode_twice_raises(tmp_path):
    manager = make_manager(tmp_path)
    manager.create_episode(25)
    with pytest.raises(EpisodeAlreadyExistsError):
        manager.create_episode(25)


def test_get_episode_status_not_found(tmp_path):
    manager = make_manager(tmp_path)
    with pytest.raises(EpisodeNotFoundError):
        manager.get_episode_status(999)


def test_get_episode_status_found(tmp_path):
    manager = make_manager(tmp_path)
    manager.create_episode(25)
    episode = manager.get_episode_status(25)
    assert episode.episode_number == 25


def test_list_episodes_ordered(tmp_path):
    manager = make_manager(tmp_path)
    manager.create_episode(2)
    manager.create_episode(1)
    episodes = manager.list_episodes()
    assert [e.episode_number for e in episodes] == [1, 2]


def build_definition(**overrides) -> EpisodeBuildDefinition:
    values = {
        "episode_id": "RLC-E025",
        "media_paths": ["/media/a.wav"],
        "markers": [MarkerDefinition(frame=0, color="Blue", name="Start")],
        "bin_name": "footage",
    }
    values.update(overrides)
    return EpisodeBuildDefinition(**values)


def created_manager(tmp_path: Path, media_manager=None, timeline_builder=None) -> EpisodeManager:
    manager = make_manager(tmp_path, media_manager=media_manager, timeline_builder=timeline_builder)
    manager.create_episode(25)
    return manager


def test_episode_manager_accepts_assembly_dependencies(tmp_path):
    media = FakeMediaManager()
    timeline = FakeTimelineBuilder()
    manager = make_manager(tmp_path, media_manager=media, timeline_builder=timeline)

    assert manager.media_manager is media
    assert manager.timeline_builder is timeline


def test_build_episode_rejects_invalid_definition_type_before_manager_calls(tmp_path):
    calls = []
    manager = make_manager(tmp_path, media_manager=FakeMediaManager(calls), timeline_builder=FakeTimelineBuilder(calls))

    with pytest.raises(EpisodeBuildError) as exc_info:
        manager.build_episode({"episode_id": "RLC-E025"})

    assert exc_info.value.stage == "validation"
    assert calls == []


@pytest.mark.parametrize(
    "definition, message",
    [
        (build_definition(episode_id=" "), "episode_id"),
        (build_definition(media_paths=None), "media_paths"),
        (build_definition(media_paths="/media/a.wav"), "media_paths"),
        (build_definition(media_paths=("/media/a.wav",)), "media_paths"),
        (build_definition(media_paths=[]), "at least one"),
        (build_definition(media_paths=[123]), "media path index 0"),
        (build_definition(media_paths=["  "]), "media path index 0"),
        (build_definition(markers=None), "markers"),
        (build_definition(markers=(MarkerDefinition(frame=0, color="Blue", name="Start"),)), "markers"),
        (build_definition(markers=[{"frame": 0}]), "marker index 0"),
        (build_definition(bin_name=" "), "bin_name"),
    ],
)
def test_build_episode_input_validation_rejects_bad_values_before_manager_calls(tmp_path, definition, message):
    calls = []
    manager = make_manager(tmp_path, media_manager=FakeMediaManager(calls), timeline_builder=FakeTimelineBuilder(calls))

    with pytest.raises(EpisodeBuildError, match=message) as exc_info:
        manager.build_episode(definition)

    assert exc_info.value.stage == "validation"
    assert calls == []


def test_build_episode_rejects_duplicate_normalized_media_paths_before_manager_calls(tmp_path):
    calls = []
    media_path = tmp_path / "media" / "clip.wav"
    duplicate = tmp_path / "media" / ".." / "media" / "clip.wav"
    manager = make_manager(tmp_path, media_manager=FakeMediaManager(calls), timeline_builder=FakeTimelineBuilder(calls))

    with pytest.raises(EpisodeBuildError, match="duplicate media path") as exc_info:
        manager.build_episode(build_definition(media_paths=[str(media_path), str(duplicate)]))

    assert exc_info.value.stage == "validation"
    assert calls == []


def test_build_episode_nonexistent_episode_fails_before_manager_calls(tmp_path):
    calls = []
    manager = make_manager(tmp_path, media_manager=FakeMediaManager(calls), timeline_builder=FakeTimelineBuilder(calls))

    with pytest.raises(EpisodeBuildError, match="No existing episode") as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "episode_lookup"
    assert calls == []


def test_build_episode_happy_path_delegates_in_order_and_preserves_result_order(tmp_path):
    calls = []
    media = FakeMediaManager(calls, result=["clip-a", "clip-b"])
    timeline = FakeTimelineBuilder(calls, place_result=["item-a", "item-b"])
    manager = created_manager(tmp_path, media, timeline)
    markers = [MarkerDefinition(frame=0, color="Blue", name="Start")]
    definition = build_definition(media_paths=["/media/a.wav", "/media/b.png"], markers=markers, bin_name="source")

    result = manager.build_episode(definition)

    assert calls == [
        ("import_media", "RLC-E025_MASTER", ["/media/a.wav", "/media/b.png"], "source"),
        ("build_timeline", "RLC-E025_MASTER", "RLC-E025", markers),
        ("place_clips", "RLC-E025_MASTER", "RLC-E025_TIMELINE", ["clip-a", "clip-b"]),
    ]
    assert result == EpisodeBuildResult(
        episode_id="RLC-E025",
        project_name="RLC-E025_MASTER",
        timeline_id="RLC-E025_TIMELINE",
        timeline_name="RLC-E025_TIMELINE",
        media_paths=["/media/a.wav", "/media/b.png"],
        media_ids=["clip-a", "clip-b"],
        markers_applied=1,
        timeline_item_ids=["item-a", "item-b"],
    )
    assert manager.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.ASSEMBLED


def test_build_episode_empty_markers_are_allowed_and_placement_still_occurs(tmp_path):
    calls = []
    media = FakeMediaManager(calls, result=["clip-1"])
    timeline = FakeTimelineBuilder(calls, place_result=["item-1"])
    manager = created_manager(tmp_path, media, timeline)

    result = manager.build_episode(build_definition(markers=[]))

    assert ("build_timeline", "RLC-E025_MASTER", "RLC-E025", []) in calls
    assert calls[-1][0] == "place_clips"
    assert result.markers_applied == 0


def test_build_episode_media_import_failure_prevents_later_stages_and_preserves_cause(tmp_path, caplog):
    calls = []
    cause = RuntimeError("import failed")
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, error=cause),
        FakeTimelineBuilder(calls),
    )
    caplog.set_level("ERROR")

    with pytest.raises(EpisodeBuildError) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "media_import"
    assert exc_info.value.completed_stages == ()
    assert exc_info.value.__cause__ is cause
    assert calls == [("import_media", "RLC-E025_MASTER", ["/media/a.wav"], "footage")]
    assert "Persistent partial Resolve state may remain" in caplog.text
    assert manager.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.FAILED


@pytest.mark.parametrize(
    "media_ids, message",
    [
        ([], "Expected 1 media ID"),
        ([""], "media ID index 0"),
        (["clip-1", "clip-1"], "Expected 1 media ID"),
    ],
)
def test_build_episode_invalid_media_result_prevents_timeline_build(tmp_path, media_ids, message):
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=media_ids),
        FakeTimelineBuilder(calls),
    )

    with pytest.raises(EpisodeBuildError, match=message) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "media_result_validation"
    assert exc_info.value.completed_stages == ("media_import",)
    assert [call[0] for call in calls] == ["import_media"]


def test_build_episode_duplicate_media_ids_are_rejected(tmp_path):
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1", "clip-1"]),
        FakeTimelineBuilder(calls),
    )

    with pytest.raises(EpisodeBuildError, match="Duplicate media ID") as exc_info:
        manager.build_episode(build_definition(media_paths=["/media/a.wav", "/media/b.wav"]))

    assert exc_info.value.stage == "media_result_validation"
    assert [call[0] for call in calls] == ["import_media"]


def test_build_episode_timeline_failure_occurs_after_import_and_prevents_placement(tmp_path):
    calls = []
    cause = RuntimeError("timeline failed")
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, build_error=cause),
    )

    with pytest.raises(EpisodeBuildError) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "timeline_build"
    assert exc_info.value.completed_stages == ("media_import",)
    assert exc_info.value.imported_count == 1
    assert exc_info.value.__cause__ is cause
    assert [call[0] for call in calls] == ["import_media", "build_timeline"]


def test_build_episode_placement_failure_occurs_after_timeline_and_preserves_context(tmp_path):
    calls = []
    cause = RuntimeError("placement failed")
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_error=cause),
    )

    with pytest.raises(EpisodeBuildError) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "clip_placement"
    assert exc_info.value.completed_stages == ("media_import", "timeline_build")
    assert exc_info.value.timeline_name == "RLC-E025_TIMELINE"
    assert exc_info.value.markers_applied == 1
    assert exc_info.value.__cause__ is cause
    assert [call[0] for call in calls] == ["import_media", "build_timeline", "place_clips"]


@pytest.mark.parametrize(
    "timeline_item_ids, message",
    [
        ([], "Expected 1 TimelineItem ID"),
        ([""], "TimelineItem ID index 0"),
    ],
)
def test_build_episode_invalid_timeline_item_result_fails_after_placement(tmp_path, timeline_item_ids, message):
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=timeline_item_ids),
    )

    with pytest.raises(EpisodeBuildError, match=message) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "result_validation"
    assert exc_info.value.completed_stages == ("media_import", "timeline_build", "clip_placement")
    assert [call[0] for call in calls] == ["import_media", "build_timeline", "place_clips"]


def test_build_episode_duplicate_timeline_item_ids_are_rejected(tmp_path):
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-a", "clip-b"]),
        FakeTimelineBuilder(calls, place_result=["item-1", "item-1"]),
    )

    with pytest.raises(EpisodeBuildError, match="Duplicate TimelineItem ID") as exc_info:
        manager.build_episode(build_definition(media_paths=["/media/a.wav", "/media/b.wav"]))

    assert exc_info.value.stage == "result_validation"
    assert exc_info.value.placed_count == 2


def test_build_episode_already_assembled_episode_is_rejected_before_media_import(tmp_path):
    calls = []
    manager = created_manager(tmp_path, FakeMediaManager(calls), FakeTimelineBuilder(calls))
    manager.db.update_episode_status("RLC-E025", EpisodeStatus.ASSEMBLED)

    with pytest.raises(EpisodeBuildError, match="already assembled") as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "episode_lookup"
    assert calls == []


def test_build_episode_failed_episode_is_rejected_before_media_import(tmp_path):
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=["item-1"]),
    )
    manager.db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)

    with pytest.raises(EpisodeBuildError, match="marked failed") as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "episode_lookup"
    assert calls == []


@pytest.mark.parametrize(
    "status", [EpisodeStatus.RENDER_QUEUED, EpisodeStatus.RENDERED, EpisodeStatus.ARCHIVED]
)
def test_build_episode_downstream_status_rejected_even_with_force(tmp_path, status):
    calls = []
    manager = created_manager(tmp_path, FakeMediaManager(calls), FakeTimelineBuilder(calls))
    manager.db.update_episode_status("RLC-E025", status)

    with pytest.raises(EpisodeBuildError, match="assembly is not permitted for downstream episodes") as exc_info:
        manager.build_episode(build_definition(), allow_unsafe_retry=True)

    assert exc_info.value.stage == "episode_lookup"
    assert calls == []


def test_build_episode_already_assembled_is_rejected_even_with_force(tmp_path):
    calls = []
    manager = created_manager(tmp_path, FakeMediaManager(calls), FakeTimelineBuilder(calls))
    manager.db.update_episode_status("RLC-E025", EpisodeStatus.ASSEMBLED)

    with pytest.raises(EpisodeBuildError, match="already assembled") as exc_info:
        manager.build_episode(build_definition(), allow_unsafe_retry=True)

    assert exc_info.value.stage == "episode_lookup"
    assert calls == []


def test_build_episode_forced_retry_succeeds_after_failed_status(tmp_path):
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=["item-1"]),
    )
    manager.db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)

    result = manager.build_episode(build_definition(), allow_unsafe_retry=True)

    assert result.timeline_item_ids == ["item-1"]
    assert manager.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.ASSEMBLED


def test_build_episode_dangling_claim_blocks_ordinary_retry(tmp_path):
    """Simulates a claim left behind by a crashed/interrupted prior attempt
    (never released): assembly_claim_token is set, but status is untouched.
    An ordinary retry must be blocked (ADR-0001 invariant: a stale/uncertain
    claim blocks ordinary retry)."""
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=["item-1"]),
    )
    assert manager.db.claim_episode_for_assembly("RLC-E025", "dangling-token") is True

    with pytest.raises(EpisodeBuildError, match="active or unresolved assembly claim") as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "episode_lookup"
    assert calls == []


def test_build_episode_dangling_claim_can_be_overridden_with_force(tmp_path):
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=["item-1"]),
    )
    assert manager.db.claim_episode_for_assembly("RLC-E025", "dangling-token") is True

    result = manager.build_episode(build_definition(), allow_unsafe_retry=True)

    assert result.timeline_item_ids == ["item-1"]
    assert manager.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.ASSEMBLED


def test_build_episode_final_release_token_mismatch_prevents_success_result(tmp_path):
    """A failed final release must convert into EpisodeBuildError -- never
    silently return EpisodeBuildResult while the episode was never actually
    marked ASSEMBLED and the claim was never actually cleared.

    Unlike the stage-aware/immediate-rerun tests above (which monkeypatch
    release_assembly_claim itself), this exercises the REAL, unmodified
    release_assembly_claim() end to end: a fake TimelineBuilder simulates a
    concurrent actor superseding this attempt's claim (e.g. an operator's
    forced retry racing in) between clip placement and the manager's own
    final release call, so the real release_assembly_claim() genuinely
    raises AssemblyClaimReleaseError on a real token mismatch -- not a
    simulated one.
    """
    calls = []
    manager_holder: dict = {}

    class HijackingTimelineBuilder(FakeTimelineBuilder):
        def place_clips(self, project_name, timeline_name, clip_ids):
            result = super().place_clips(project_name, timeline_name, clip_ids)
            manager = manager_holder["manager"]
            manager.db.conn.execute(
                "UPDATE episodes SET assembly_claim_token = ? WHERE episode_id = ?",
                ("someone-elses-token", "RLC-E025"),
            )
            manager.db.conn.commit()
            return result

    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        HijackingTimelineBuilder(calls, place_result=["item-1"]),
    )
    manager_holder["manager"] = manager

    with pytest.raises(EpisodeBuildError) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "status_update"
    assert isinstance(exc_info.value.__cause__, AssemblyClaimReleaseError)

    # The row must NOT show ASSEMBLED, and the hijacker's token must still
    # be in place -- proving release_assembly_claim() genuinely refused to
    # overwrite a claim it no longer owned, rather than the test merely
    # asserting on a mocked return value.
    episode = manager.db.get_episode_by_episode_id("RLC-E025")
    assert episode.status != EpisodeStatus.ASSEMBLED
    assert episode.assembly_claim_token == "someone-elses-token"


def test_claim_commits_before_first_resolve_facing_call(tmp_path):
    """The claim must be durably committed before build_episode() calls
    anything Resolve-facing (MediaManager.import_media() is the first
    stage). Checked via a second, independent Database connection to the
    SAME on-disk file, opened and read from inside import_media() itself --
    this proves the claim is visible cross-connection (i.e. actually
    committed, not merely pending in this process's own connection) before
    any Resolve mutation begins, per ADR-0001's claim-commits-before-
    mutation invariant."""
    observed = {}
    manager_holder: dict = {}

    class ObservingMediaManager(FakeMediaManager):
        def import_media(self, project_name, media_paths, bin_name):
            manager = manager_holder["manager"]
            other_conn = Database(manager.db.db_path).connect()
            episode = other_conn.get_episode_by_episode_id("RLC-E025")
            observed["claim_token"] = episode.assembly_claim_token
            other_conn.close()
            return super().import_media(project_name, media_paths, bin_name)

    calls = []
    manager = created_manager(
        tmp_path,
        ObservingMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=["item-1"]),
    )
    manager_holder["manager"] = manager

    manager.build_episode(build_definition())

    assert observed["claim_token"] is not None


def test_build_episode_safe_retry_after_validation_failure(tmp_path):
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=["item-1"]),
    )

    with pytest.raises(EpisodeBuildError):
        manager.build_episode(build_definition(media_paths=[]))

    result = manager.build_episode(build_definition())

    assert result.timeline_item_ids == ["item-1"]
    assert manager.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.ASSEMBLED


def test_build_episode_original_failure_is_preserved_when_failed_status_update_fails(tmp_path, monkeypatch, caplog):
    calls = []
    original = RuntimeError("resolve import failed")
    status_error = RuntimeError("db unavailable")
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, error=original),
        FakeTimelineBuilder(calls),
    )

    def fail_release(episode_id, claim_token, status):
        raise status_error

    monkeypatch.setattr(manager.db, "release_assembly_claim", fail_release)
    caplog.set_level("WARNING")

    with pytest.raises(EpisodeBuildError) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "media_import"
    assert exc_info.value.__cause__ is original
    assert "preserving original failure" in caplog.text


def test_build_episode_timeline_failure_preserved_when_failed_status_update_fails(tmp_path, monkeypatch, caplog):
    calls = []
    original = RuntimeError("timeline failed")
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, build_error=original),
    )

    def fail_release(episode_id, claim_token, status):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(manager.db, "release_assembly_claim", fail_release)
    caplog.set_level("WARNING")

    with pytest.raises(EpisodeBuildError) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "timeline_build"
    assert exc_info.value.completed_stages == ("media_import",)
    assert exc_info.value.imported_count == 1
    assert exc_info.value.__cause__ is original
    assert [call[0] for call in calls] == ["import_media", "build_timeline"]
    assert "preserving original failure" in caplog.text


def test_build_episode_clip_placement_failure_preserved_when_failed_status_update_fails(
    tmp_path, monkeypatch, caplog
):
    calls = []
    original = RuntimeError("placement failed")
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_error=original),
    )

    def fail_release(episode_id, claim_token, status):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(manager.db, "release_assembly_claim", fail_release)
    caplog.set_level("WARNING")

    with pytest.raises(EpisodeBuildError) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "clip_placement"
    assert exc_info.value.completed_stages == ("media_import", "timeline_build")
    assert exc_info.value.imported_count == 1
    assert exc_info.value.markers_applied == 1
    assert exc_info.value.placed_count == 0
    assert exc_info.value.__cause__ is original
    assert [call[0] for call in calls] == ["import_media", "build_timeline", "place_clips"]
    assert "preserving original failure" in caplog.text


def test_build_episode_assembled_status_update_failure_is_stage_aware(tmp_path, monkeypatch, caplog):
    calls = []
    status_error = RuntimeError("db unavailable")
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=["item-1"]),
    )

    def fail_assembled_release(episode_id, claim_token, status):
        # Only the final success-path release (to ASSEMBLED) happens in this
        # scenario -- _build_error never calls release_assembly_claim for the
        # status_update stage itself (that's the whole point: the claim must
        # stay set as the persisted "uncertain outcome" signal).
        assert status == EpisodeStatus.ASSEMBLED
        raise status_error

    monkeypatch.setattr(manager.db, "release_assembly_claim", fail_assembled_release)
    caplog.set_level("ERROR")

    with pytest.raises(EpisodeBuildError) as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "status_update"
    assert exc_info.value.completed_stages == ("media_import", "timeline_build", "clip_placement")
    assert exc_info.value.imported_count == 1
    assert exc_info.value.markers_applied == 1
    assert exc_info.value.placed_count == 1
    assert exc_info.value.__cause__ is status_error
    assert "Resolve assembly already completed" in caplog.text
    assert "Database status is stale" in caplog.text


def test_build_episode_status_update_failure_blocks_immediate_rerun(tmp_path, monkeypatch):
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=["item-1"]),
    )

    def fail_assembled_release(episode_id, claim_token, status):
        assert status == EpisodeStatus.ASSEMBLED
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(manager.db, "release_assembly_claim", fail_assembled_release)
    with pytest.raises(EpisodeBuildError):
        manager.build_episode(build_definition())

    calls.clear()
    # The claim from the first attempt was never released (the release call
    # itself failed), so it's still active/unresolved -- an ordinary retry
    # without allow_unsafe_retry must be blocked (ADR-0001).
    with pytest.raises(EpisodeBuildError, match="active or unresolved assembly claim") as exc_info:
        manager.build_episode(build_definition())

    assert exc_info.value.stage == "episode_lookup"
    assert calls == []


def test_build_episode_status_update_failure_allows_forced_rerun(tmp_path, monkeypatch):
    """Companion to the immediate-rerun-blocked test above: with
    allow_unsafe_retry=True, the same dangling claim must be overridable."""
    calls = []
    manager = created_manager(
        tmp_path,
        FakeMediaManager(calls, result=["clip-1"]),
        FakeTimelineBuilder(calls, place_result=["item-1"]),
    )

    def fail_assembled_release(episode_id, claim_token, status):
        assert status == EpisodeStatus.ASSEMBLED
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(manager.db, "release_assembly_claim", fail_assembled_release)
    with pytest.raises(EpisodeBuildError):
        manager.build_episode(build_definition())

    calls.clear()
    monkeypatch.undo()  # restore the real release_assembly_claim for the retry
    result = manager.build_episode(build_definition(), allow_unsafe_retry=True)

    assert result.timeline_item_ids == ["item-1"]
    assert manager.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.ASSEMBLED


def test_episode_manager_rejects_media_manager_with_different_resolve_adapter(tmp_path):
    manager = make_manager(tmp_path)
    other_resolve = MockResolveAdapter()
    other_resolve.connect()
    media_manager = MediaManager(manager.config, other_resolve)

    with pytest.raises(ValueError, match="media_manager"):
        EpisodeManager(manager.config, manager.db, manager.resolve, media_manager, manager.timeline_builder)


def test_episode_manager_rejects_timeline_builder_with_different_resolve_adapter(tmp_path):
    manager = make_manager(tmp_path)
    other_resolve = MockResolveAdapter()
    other_resolve.connect()
    timeline_builder = TimelineBuilder(manager.config, other_resolve)

    with pytest.raises(ValueError, match="timeline_builder"):
        EpisodeManager(manager.config, manager.db, manager.resolve, manager.media_manager, timeline_builder)
