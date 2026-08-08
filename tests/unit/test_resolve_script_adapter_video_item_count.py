"""Tests for ResolveScriptAdapter.get_video_timeline_item_count().

Uses the same fake-object pattern as
test_resolve_script_adapter_render_queue.py: no real DaVinciResolveScript
import, no live Resolve. `_resolve`/`_project_manager` are set directly to
lightweight fakes.
"""
import pytest

from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.exceptions import (
    ProjectNotFoundError,
    ResolveConnectionError,
    TimelineOperationError,
)


class FakeTimeline:
    def __init__(self, name: str = "timeline", track_counts=None, items_by_track=None, track_count_error=None,
                 item_list_error=None, missing_methods=False):
        self.name = name
        self.track_counts = track_counts or {}
        self.items_by_track = items_by_track or {}
        self.track_count_error = track_count_error
        self.item_list_error = item_list_error
        if missing_methods:
            self.GetTrackCount = None
            self.GetItemListInTrack = None

    def GetName(self):
        return self.name

    def GetTrackCount(self, track_type: str):
        if self.track_count_error is not None:
            raise self.track_count_error
        return self.track_counts.get(track_type, 0)

    def GetItemListInTrack(self, track_type: str, index: int):
        if self.item_list_error is not None:
            raise self.item_list_error
        return self.items_by_track.get((track_type, index), [])


class FakeProject:
    def __init__(self, timeline=None, timeline_count=1):
        self.timeline = timeline or FakeTimeline()
        self._timeline_count = timeline_count

    def GetTimelineCount(self):
        return self._timeline_count

    def GetTimelineByIndex(self, index: int):
        return self.timeline if index == 1 else None


class FakeProjectManager:
    def __init__(self, project=None):
        self.project = project
        self.load_calls = []

    def LoadProject(self, project_name: str):
        self.load_calls.append(project_name)
        return self.project


class FakeResolve:
    pass


def connected_adapter(project=None):
    adapter = ResolveScriptAdapter()
    adapter._project_manager = FakeProjectManager(project)
    adapter._resolve = FakeResolve()
    return adapter


def test_requires_connection():
    adapter = ResolveScriptAdapter()
    with pytest.raises(ResolveConnectionError):
        adapter.get_video_timeline_item_count("project", "timeline")


def test_rejects_unknown_project():
    adapter = connected_adapter(project=False)
    with pytest.raises(ProjectNotFoundError):
        adapter.get_video_timeline_item_count("missing", "timeline")


def test_rejects_unknown_timeline():
    project = FakeProject(timeline=FakeTimeline(name="other"))
    adapter = connected_adapter(project)
    with pytest.raises(TimelineOperationError, match="not found"):
        adapter.get_video_timeline_item_count("project", "timeline")


def test_zero_video_tracks_returns_zero():
    timeline = FakeTimeline(track_counts={"video": 0})
    project = FakeProject(timeline)
    adapter = connected_adapter(project)

    assert adapter.get_video_timeline_item_count("project", "timeline") == 0


def test_counts_items_across_multiple_video_tracks():
    timeline = FakeTimeline(
        track_counts={"video": 2},
        items_by_track={
            ("video", 1): [object()],
            ("video", 2): [object(), object()],
        },
    )
    project = FakeProject(timeline)
    adapter = connected_adapter(project)

    assert adapter.get_video_timeline_item_count("project", "timeline") == 3


def test_falsey_item_list_treated_as_empty():
    timeline = FakeTimeline(track_counts={"video": 1}, items_by_track={("video", 1): False})
    project = FakeProject(timeline)
    adapter = connected_adapter(project)

    assert adapter.get_video_timeline_item_count("project", "timeline") == 0


def test_missing_inspection_methods_fails_closed():
    timeline = FakeTimeline(missing_methods=True)
    project = FakeProject(timeline)
    adapter = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="cannot report"):
        adapter.get_video_timeline_item_count("project", "timeline")


def test_invalid_track_count_fails_closed():
    timeline = FakeTimeline()
    timeline.GetTrackCount = lambda track_type: -1
    project = FakeProject(timeline)
    adapter = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="invalid video track count"):
        adapter.get_video_timeline_item_count("project", "timeline")


def test_track_count_exception_fails_closed():
    timeline = FakeTimeline(track_count_error=RuntimeError("Resolve bridge error"))
    project = FakeProject(timeline)
    adapter = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="failed to report"):
        adapter.get_video_timeline_item_count("project", "timeline")


def test_item_list_exception_fails_closed():
    timeline = FakeTimeline(track_counts={"video": 1}, item_list_error=RuntimeError("Resolve bridge error"))
    project = FakeProject(timeline)
    adapter = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="failed to list items"):
        adapter.get_video_timeline_item_count("project", "timeline")


def test_non_list_item_list_fails_closed():
    timeline = FakeTimeline()
    timeline.GetTrackCount = lambda track_type: 1
    timeline.GetItemListInTrack = lambda track_type, index: "not-a-list"
    project = FakeProject(timeline)
    adapter = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="invalid item list"):
        adapter.get_video_timeline_item_count("project", "timeline")
