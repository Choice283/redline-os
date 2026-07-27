"""Tests for MockResolveAdapter — proves the ResolveAdapter interface is usable
end-to-end without a real Resolve installation. Every real ResolveScriptAdapter
method (Phase 1+) must satisfy the same interface these tests exercise.
"""
import pytest

from redline_core.resolve.exceptions import ProjectAlreadyExistsError, ProjectNotFoundError, RenderJobError
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
