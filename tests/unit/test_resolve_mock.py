"""Tests for MockResolveAdapter — proves the ResolveAdapter interface is usable
end-to-end without a real Resolve installation. Every real ResolveScriptAdapter
method (Phase 1+) must satisfy the same interface these tests exercise.
"""
import pytest

from redline_core.resolve.exceptions import (
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    RenderJobError,
    TimelineOperationError,
)
from redline_core.resolve.mock import MockResolveAdapter


def test_connect_required_before_use():
    adapter = MockResolveAdapter()
    with pytest.raises(RuntimeError):
        adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")


def test_duplicate_project():
    adapter = MockResolveAdapter()
    adapter.connect()
    handle = adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    assert handle.name == "RLC-E025_MASTER"
    assert handle.path is not None


def test_duplicate_project_twice_raises():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    with pytest.raises(ProjectAlreadyExistsError):
        adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")


def test_import_media_requires_existing_project():
    adapter = MockResolveAdapter()
    adapter.connect()
    with pytest.raises(ProjectNotFoundError):
        adapter.import_media("does-not-exist", ["/x/a.mov"], "footage")


def test_full_episode_flow_against_mock():
    adapter = MockResolveAdapter()
    adapter.connect()

    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    clip_ids = adapter.import_media("RLC-E025_MASTER", ["/x/a.mov", "/x/b.mov"], "footage")
    assert len(clip_ids) == 2

    timeline_id = adapter.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    assert timeline_id == "RLC-E025_TIMELINE"

    adapter.add_markers(
        "RLC-E025_MASTER", "RLC-E025_TIMELINE", [{"frame": 0, "color": "Blue", "name": "Cold open"}]
    )
    assert adapter.markers["RLC-E025_MASTER:RLC-E025_TIMELINE"][0]["name"] == "Cold open"

    job_id = adapter.queue_render("RLC-E025_MASTER", "broadcast_master", "/x/exports/ep025.mov")
    assert adapter.get_render_status(job_id) == "queued"

    adapter.simulate_render_complete(job_id)
    assert adapter.get_render_status(job_id) == "complete"


def test_cancel_render():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    job_id = adapter.queue_render("RLC-E025_MASTER", "broadcast_master", "/x/exports/ep025.mov")

    adapter.cancel_render(job_id)
    assert adapter.get_render_status(job_id) == "cancelled"


def test_cancel_render_unknown_job_raises():
    adapter = MockResolveAdapter()
    adapter.connect()
    with pytest.raises(RenderJobError):
        adapter.cancel_render("does-not-exist")


def test_cancel_render_already_complete_raises():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    job_id = adapter.queue_render("RLC-E025_MASTER", "broadcast_master", "/x/exports/ep025.mov")
    adapter.simulate_render_complete(job_id)

    with pytest.raises(RenderJobError):
        adapter.cancel_render(job_id)


def test_mock_place_clips_places_multiple_clips_sequentially():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    clip_ids = adapter.import_media("RLC-E025_MASTER", ["/x/a.mov", "/x/b.mov"], "footage")
    adapter.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")

    timeline_item_ids = adapter.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", clip_ids)

    assert len(timeline_item_ids) == 2
    assert timeline_item_ids[0] != timeline_item_ids[1]


def test_mock_place_clips_preserves_order():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    clip_ids = adapter.import_media("RLC-E025_MASTER", ["/x/a.mov", "/x/b.mov"], "footage")
    adapter.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")

    adapter.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", [clip_ids[1], clip_ids[0]])

    records = adapter.timeline_items["RLC-E025_MASTER:RLC-E025_TIMELINE"]
    assert [record["clip_id"] for record in records] == [clip_ids[1], clip_ids[0]]
    assert [record["order"] for record in records] == [0, 1]


def test_mock_place_clips_stores_timeline_item_records():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    clip_ids = adapter.import_media("RLC-E025_MASTER", ["/x/a.mov"], "footage")
    adapter.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")

    timeline_item_ids = adapter.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", clip_ids)

    records = adapter.timeline_items["RLC-E025_MASTER:RLC-E025_TIMELINE"]
    assert records == [{"timeline_item_id": timeline_item_ids[0], "clip_id": clip_ids[0], "order": 0}]


def test_mock_place_clips_rejects_missing_clip_ids():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    adapter.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")

    with pytest.raises(TimelineOperationError, match="not found"):
        adapter.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", ["missing"])


def test_mock_place_clips_rejects_duplicate_requested_ids():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    clip_ids = adapter.import_media("RLC-E025_MASTER", ["/x/a.mov"], "footage")
    adapter.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")

    with pytest.raises(TimelineOperationError, match="Duplicate"):
        adapter.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", [clip_ids[0], clip_ids[0]])


def test_mock_place_clips_requires_timeline_to_exist():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    clip_ids = adapter.import_media("RLC-E025_MASTER", ["/x/a.mov"], "footage")

    with pytest.raises(TimelineOperationError, match="Timeline"):
        adapter.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", clip_ids)


def test_mock_place_clips_empty_input_returns_empty():
    adapter = MockResolveAdapter()
    adapter.connect()

    assert adapter.place_clips("project", "timeline", []) == []


@pytest.mark.parametrize("clip_ids", [None, "clip-id", ("clip-id",), (clip_id for clip_id in ["clip-id"])])
def test_mock_place_clips_rejects_invalid_clip_id_containers(clip_ids):
    adapter = MockResolveAdapter()
    adapter.connect()

    with pytest.raises(TimelineOperationError, match="clip_ids must be a list of strings"):
        adapter.place_clips("project", "timeline", clip_ids)


def test_mock_build_timeline_supports_two_distinct_timelines_in_one_project():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")

    adapter.build_timeline("RLC-E025_MASTER", "timeline-a")
    adapter.build_timeline("RLC-E025_MASTER", "timeline-b")

    assert adapter.timelines["RLC-E025_MASTER"] == ["timeline-a", "timeline-b"]


def test_mock_build_timeline_reuses_existing_exact_name_without_duplicate():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")

    adapter.build_timeline("RLC-E025_MASTER", "timeline-a")
    adapter.build_timeline("RLC-E025_MASTER", "timeline-a")

    assert adapter.timelines["RLC-E025_MASTER"] == ["timeline-a"]


def test_mock_place_clips_into_two_timelines_keeps_records_separated():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    clip_ids = adapter.import_media("RLC-E025_MASTER", ["/x/a.mov", "/x/b.mov"], "footage")
    adapter.build_timeline("RLC-E025_MASTER", "timeline-a")
    adapter.build_timeline("RLC-E025_MASTER", "timeline-b")

    first_ids = adapter.place_clips("RLC-E025_MASTER", "timeline-a", [clip_ids[0]])
    second_ids = adapter.place_clips("RLC-E025_MASTER", "timeline-b", [clip_ids[1]])

    assert adapter.timeline_items["RLC-E025_MASTER:timeline-a"] == [
        {"timeline_item_id": first_ids[0], "clip_id": clip_ids[0], "order": 0}
    ]
    assert adapter.timeline_items["RLC-E025_MASTER:timeline-b"] == [
        {"timeline_item_id": second_ids[0], "clip_id": clip_ids[1], "order": 0}
    ]


def test_mock_markers_for_two_timelines_remain_separated():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    adapter.build_timeline("RLC-E025_MASTER", "timeline-a")
    adapter.build_timeline("RLC-E025_MASTER", "timeline-b")

    adapter.add_markers("RLC-E025_MASTER", "timeline-a", [{"frame": 0, "color": "Blue", "name": "A"}])
    adapter.add_markers("RLC-E025_MASTER", "timeline-b", [{"frame": 0, "color": "Red", "name": "B"}])

    assert adapter.markers["RLC-E025_MASTER:timeline-a"][0]["name"] == "A"
    assert adapter.markers["RLC-E025_MASTER:timeline-b"][0]["name"] == "B"


def test_mock_add_markers_requires_existing_timeline():
    adapter = MockResolveAdapter()
    adapter.connect()
    adapter.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")

    with pytest.raises(TimelineOperationError, match="Timeline"):
        adapter.add_markers("RLC-E025_MASTER", "missing", [{"frame": 0, "color": "Blue"}])
