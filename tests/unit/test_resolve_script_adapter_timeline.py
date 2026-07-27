import pytest

from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.exceptions import ProjectNotFoundError, ResolveConnectionError, TimelineOperationError


class FalseyTimeline:
    def __bool__(self):
        return False


class FakeTimeline:
    def __init__(self, name: str | None, add_results=None, get_name_error: Exception | None = None):
        self.name = name
        self.add_results = list(add_results) if add_results is not None else []
        self.get_name_error = get_name_error
        self.marker_calls = []

    def GetName(self):
        if self.get_name_error is not None:
            raise self.get_name_error
        return self.name

    def AddMarker(self, frame, color, name, note, duration, custom_data):
        self.marker_calls.append((frame, color, name, note, duration, custom_data))
        if self.add_results:
            result = self.add_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return True


class FakeMediaPool:
    def __init__(self, create_result=None):
        self.create_result = create_result
        self.create_calls = []

    def CreateEmptyTimeline(self, timeline_name: str):
        self.create_calls.append(timeline_name)
        return self.create_result


class FakeProject:
    def __init__(self, timelines=None, media_pool=None, timeline_count=None):
        self.timelines = list(timelines or [])
        self.media_pool = media_pool
        self.timeline_count = timeline_count
        self.timeline_indexes = []

    def GetTimelineCount(self):
        if self.timeline_count is not None:
            return self.timeline_count
        return len(self.timelines)

    def GetTimelineByIndex(self, index: int):
        self.timeline_indexes.append(index)
        if 1 <= index <= len(self.timelines):
            return self.timelines[index - 1]
        return None

    def GetMediaPool(self):
        return self.media_pool


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
    project_manager = FakeProjectManager(project)
    adapter._project_manager = project_manager
    adapter._resolve = FakeResolve()
    return adapter, project_manager


def test_build_timeline_disconnected_raises_resolve_connection_error():
    adapter = ResolveScriptAdapter()

    with pytest.raises(ResolveConnectionError):
        adapter.build_timeline("project", "timeline")


def test_build_timeline_blank_name_raises_before_project_loading():
    adapter, project_manager = connected_adapter(FakeProject())

    with pytest.raises(TimelineOperationError, match="non-empty"):
        adapter.build_timeline("project", "  ")

    assert project_manager.load_calls == []


def test_build_timeline_missing_project_raises_project_not_found():
    adapter, _project_manager = connected_adapter(project=False)

    with pytest.raises(ProjectNotFoundError):
        adapter.build_timeline("missing", "timeline")


def test_build_timeline_reuses_existing_timeline():
    existing = FakeTimeline("timeline")
    media_pool = FakeMediaPool(create_result=FakeTimeline("timeline"))
    project = FakeProject(timelines=[existing], media_pool=media_pool)
    adapter, _project_manager = connected_adapter(project)

    assert adapter.build_timeline("project", "timeline") == "timeline"


def test_build_timeline_reuse_does_not_create_duplicate():
    existing = FakeTimeline("timeline")
    media_pool = FakeMediaPool(create_result=FakeTimeline("timeline"))
    project = FakeProject(timelines=[existing], media_pool=media_pool)
    adapter, _project_manager = connected_adapter(project)

    adapter.build_timeline("project", "timeline")

    assert media_pool.create_calls == []


def test_build_timeline_missing_media_pool_raises_timeline_operation_error():
    project = FakeProject(media_pool=None)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="media pool"):
        adapter.build_timeline("project", "timeline")


def test_build_timeline_create_returning_none_raises_timeline_operation_error():
    project = FakeProject(media_pool=FakeMediaPool(create_result=None))
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="failed to create"):
        adapter.build_timeline("project", "timeline")


def test_build_timeline_created_timeline_empty_name_raises_timeline_operation_error():
    project = FakeProject(media_pool=FakeMediaPool(create_result=FakeTimeline("")))
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="without a usable name"):
        adapter.build_timeline("project", "timeline")


def test_build_timeline_auto_renamed_timeline_raises_timeline_operation_error():
    project = FakeProject(media_pool=FakeMediaPool(create_result=FakeTimeline("timeline 1")))
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="different name"):
        adapter.build_timeline("project", "timeline")


def test_build_timeline_success_returns_exact_requested_name():
    project = FakeProject(media_pool=FakeMediaPool(create_result=FakeTimeline("timeline")))
    adapter, _project_manager = connected_adapter(project)

    assert adapter.build_timeline("project", "timeline") == "timeline"


def test_find_timeline_uses_one_based_indexes():
    target = FakeTimeline("target")
    project = FakeProject(timelines=[FakeTimeline("first"), target])
    adapter, _project_manager = connected_adapter(project)

    assert adapter._find_timeline(project, "target") is target
    assert project.timeline_indexes == [1, 2]


def test_find_timeline_skips_falsey_handles_safely():
    target = FakeTimeline("target")
    project = FakeProject(timelines=[FalseyTimeline(), target])
    adapter, _project_manager = connected_adapter(project)

    assert adapter._find_timeline(project, "target") is target


def test_find_timeline_count_none_is_treated_as_zero():
    project = FakeProject(timelines=[FakeTimeline("target")], timeline_count=None)
    project.GetTimelineCount = lambda: None
    adapter, _project_manager = connected_adapter(project)

    assert adapter._find_timeline(project, "target") is None
    assert project.timeline_indexes == []


@pytest.mark.parametrize("timeline_count", [True, "2", -1])
def test_find_timeline_invalid_count_raises_timeline_operation_error(timeline_count):
    project = FakeProject(timeline_count=timeline_count)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="invalid timeline count"):
        adapter._find_timeline(project, "target")


def test_find_timeline_count_exception_preserves_original_cause():
    original = RuntimeError("count failed")
    project = FakeProject()
    project.GetTimelineCount = lambda: (_ for _ in ()).throw(original)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter._find_timeline(project, "target")

    assert exc_info.value.__cause__ is original


def test_find_timeline_get_name_exception_preserves_original_cause():
    original = RuntimeError("name failed")
    project = FakeProject(timelines=[FakeTimeline("target", get_name_error=original)])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter._find_timeline(project, "target")

    assert exc_info.value.__cause__ is original


def test_build_timeline_create_returning_false_raises_timeline_operation_error():
    project = FakeProject(media_pool=FakeMediaPool(create_result=False))
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="failed to create"):
        adapter.build_timeline("project", "timeline")


def test_add_markers_disconnected_raises_resolve_connection_error():
    adapter = ResolveScriptAdapter()

    with pytest.raises(ResolveConnectionError):
        adapter.add_markers("project", "timeline", [{"frame": 0, "color": "Blue"}])


def test_add_markers_empty_returns_without_project_loading():
    adapter, project_manager = connected_adapter(FakeProject())

    assert adapter.add_markers("project", "timeline", []) is None
    assert project_manager.load_calls == []


@pytest.mark.parametrize(
    "marker, expected",
    [
        ("not a dict", "dictionary"),
        ({"color": "Blue"}, "missing frame"),
        ({"frame": 0}, "missing color"),
        ({"frame": True, "color": "Blue"}, "frame must be an integer"),
        ({"frame": -1, "color": "Blue"}, "frame must be >= 0"),
        ({"frame": 0, "color": "  "}, "color must be a non-empty string"),
        ({"frame": 0, "color": "Blue", "name": 1}, "name must be a string"),
        ({"frame": 0, "color": "Blue", "note": 1}, "note must be a string"),
        ({"frame": 0, "color": "Blue", "duration": False}, "duration must be an integer"),
        ({"frame": 0, "color": "Blue", "duration": 0}, "duration must be >= 1"),
        ({"frame": 0, "color": "Blue", "custom_data": 1}, "custom_data must be a string"),
    ],
)
def test_add_markers_invalid_marker_is_rejected(marker, expected):
    adapter, _project_manager = connected_adapter(FakeProject())

    with pytest.raises(TimelineOperationError, match=expected):
        adapter.add_markers("project", "timeline", [marker])


def test_add_markers_multiple_invalid_markers_are_reported_together():
    adapter, _project_manager = connected_adapter(FakeProject())

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter.add_markers(
            "project",
            "timeline",
            [{"color": "Blue"}, {"frame": -1, "color": ""}],
        )

    message = str(exc_info.value)
    assert "marker index 0" in message
    assert "missing frame" in message
    assert "marker index 1" in message
    assert "frame must be >= 0" in message
    assert "color must be a non-empty string" in message


def test_add_markers_invalid_input_performs_no_resolve_calls():
    timeline = FakeTimeline("timeline")
    project = FakeProject(timelines=[timeline])
    adapter, project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError):
        adapter.add_markers("project", "timeline", [{"frame": -1, "color": "Blue"}])

    assert project_manager.load_calls == []
    assert timeline.marker_calls == []


def test_add_markers_missing_project_raises_project_not_found():
    adapter, _project_manager = connected_adapter(project=False)

    with pytest.raises(ProjectNotFoundError):
        adapter.add_markers("missing", "timeline", [{"frame": 0, "color": "Blue"}])


def test_add_markers_missing_timeline_raises_timeline_operation_error():
    project = FakeProject(timelines=[FakeTimeline("other")])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="not found"):
        adapter.add_markers("project", "timeline", [{"frame": 0, "color": "Blue"}])


def test_add_markers_default_optional_values_are_passed_correctly():
    timeline = FakeTimeline("timeline")
    project = FakeProject(timelines=[timeline])
    adapter, _project_manager = connected_adapter(project)

    adapter.add_markers("project", "timeline", [{"frame": 0, "color": "Blue"}])

    assert timeline.marker_calls == [(0, "Blue", "", "", 1, "")]


def test_add_markers_complete_values_are_passed_correctly():
    timeline = FakeTimeline("timeline")
    project = FakeProject(timelines=[timeline])
    adapter, _project_manager = connected_adapter(project)

    adapter.add_markers(
        "project",
        "timeline",
        [
            {
                "frame": 12,
                "color": "Red",
                "name": "Beat",
                "note": "A note",
                "duration": 5,
                "custom_data": "custom",
            }
        ],
    )

    assert timeline.marker_calls == [(12, "Red", "Beat", "A note", 5, "custom")]


def test_add_markers_legacy_custom_data_is_accepted():
    timeline = FakeTimeline("timeline")
    project = FakeProject(timelines=[timeline])
    adapter, _project_manager = connected_adapter(project)

    adapter.add_markers(
        "project",
        "timeline",
        [{"frame": 12, "color": "Red", "customData": "legacy"}],
    )

    assert timeline.marker_calls == [(12, "Red", "", "", 1, "legacy")]


def test_add_markers_duplicate_custom_data_fields_are_rejected():
    adapter, project_manager = connected_adapter(FakeProject())

    with pytest.raises(TimelineOperationError, match="provide only one"):
        adapter.add_markers(
            "project",
            "timeline",
            [{"frame": 12, "color": "Red", "custom_data": "new", "customData": "legacy"}],
        )

    assert project_manager.load_calls == []


def test_add_markers_false_return_raises_timeline_operation_error():
    timeline = FakeTimeline("timeline", add_results=[False])
    project = FakeProject(timelines=[timeline])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="marker index 0"):
        adapter.add_markers("project", "timeline", [{"frame": 0, "color": "Blue"}])


def test_add_markers_none_return_raises_timeline_operation_error():
    timeline = FakeTimeline("timeline", add_results=[None])
    project = FakeProject(timelines=[timeline])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="marker index 0"):
        adapter.add_markers("project", "timeline", [{"frame": 0, "color": "Blue"}])


def test_add_markers_exception_preserves_cause():
    original = RuntimeError("resolve said no")
    timeline = FakeTimeline("timeline", add_results=[original])
    project = FakeProject(timelines=[timeline])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter.add_markers("project", "timeline", [{"frame": 0, "color": "Blue"}])

    assert exc_info.value.__cause__ is original


def test_add_markers_partial_failure_reports_failed_marker_index():
    timeline = FakeTimeline("timeline", add_results=[True, False])
    project = FakeProject(timelines=[timeline])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="marker index 1"):
        adapter.add_markers(
            "project",
            "timeline",
            [{"frame": 0, "color": "Blue"}, {"frame": 10, "color": "Red"}],
        )

    assert len(timeline.marker_calls) == 2


def test_add_markers_partial_failure_logs_added_count(caplog):
    timeline = FakeTimeline("timeline", add_results=[True, False])
    project = FakeProject(timelines=[timeline])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError):
        adapter.add_markers(
            "project",
            "timeline",
            [{"frame": 0, "color": "Blue"}, {"frame": 10, "color": "Red"}],
        )

    assert "requested_count=2" in caplog.text
    assert "added_count=1" in caplog.text
    assert "failed_index=1" in caplog.text


def test_add_markers_success_calls_add_marker_once_per_marker():
    timeline = FakeTimeline("timeline")
    project = FakeProject(timelines=[timeline])
    adapter, _project_manager = connected_adapter(project)

    adapter.add_markers(
        "project",
        "timeline",
        [{"frame": 0, "color": "Blue"}, {"frame": 10, "color": "Red"}],
    )

    assert timeline.marker_calls == [
        (0, "Blue", "", "", 1, ""),
        (10, "Red", "", "", 1, ""),
    ]
