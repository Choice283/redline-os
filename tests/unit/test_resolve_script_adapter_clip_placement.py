import logging

import pytest

from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.exceptions import ProjectNotFoundError, ResolveConnectionError, TimelineOperationError


class FalseyTimelineItem:
    def __bool__(self):
        return False


class FakeTimeline:
    def __init__(self, name: str):
        self.name = name

    def GetName(self):
        return self.name


class FakeTimelineItem:
    def __init__(self, unique_id=None, error: Exception | None = None):
        self.unique_id = unique_id
        self.error = error
        self.unique_id_calls = 0

    def GetUniqueId(self):
        self.unique_id_calls += 1
        if self.error is not None:
            raise self.error
        return self.unique_id


class FakeMediaPoolItem:
    def __init__(
        self,
        media_id=None,
        unique_id=None,
        media_error: Exception | None = None,
        unique_error: Exception | None = None,
    ):
        self.media_id = media_id
        self.unique_id = unique_id
        self.media_error = media_error
        self.unique_error = unique_error

    def GetMediaId(self):
        if self.media_error is not None:
            raise self.media_error
        return self.media_id

    def GetUniqueId(self):
        if self.unique_error is not None:
            raise self.unique_error
        return self.unique_id


class FakeFolder:
    def __init__(self, clips=None, subfolders=None, clip_error: Exception | None = None, folder_error: Exception | None = None):
        self.clips = clips
        self.subfolders = subfolders
        self.clip_error = clip_error
        self.folder_error = folder_error

    def GetClipList(self):
        if self.clip_error is not None:
            raise self.clip_error
        return self.clips

    def GetSubFolderList(self):
        if self.folder_error is not None:
            raise self.folder_error
        return self.subfolders


class FakeMediaPool:
    def __init__(self, root_folder=None, append_result=None, append_error: Exception | None = None):
        self.root_folder = root_folder
        self.append_result = append_result
        self.append_error = append_error
        self.append_calls = []
        self.delete_calls = []

    def GetRootFolder(self):
        return self.root_folder

    def AppendToTimeline(self, media_pool_items):
        self.append_calls.append(media_pool_items)
        if self.append_error is not None:
            raise self.append_error
        return self.append_result

    def DeleteClips(self, timeline_items):
        self.delete_calls.append(timeline_items)
        return True


class FakeProject:
    def __init__(
        self,
        timelines=None,
        media_pool=None,
        set_current_result=True,
        set_current_error: Exception | None = None,
    ):
        self.timelines = list(timelines or [])
        self.media_pool = media_pool
        self.set_current_result = set_current_result
        self.set_current_error = set_current_error
        self.current_timeline = None

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, index: int):
        if 1 <= index <= len(self.timelines):
            return self.timelines[index - 1]
        return None

    def SetCurrentTimeline(self, timeline):
        if self.set_current_error is not None:
            raise self.set_current_error
        self.current_timeline = timeline
        return self.set_current_result

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


def media_item(media_id: str, unique_id: str | None = None):
    return FakeMediaPoolItem(media_id=media_id, unique_id=unique_id)


def timeline_item(unique_id: str):
    return FakeTimelineItem(unique_id)


DEFAULT_APPEND_RESULT = object()


def project_with_media(clips, append_result=DEFAULT_APPEND_RESULT, timelines=None, root_folder=None, **project_kwargs):
    timeline = FakeTimeline("timeline")
    if timelines is None:
        timelines = [timeline]
    if root_folder is None:
        root_folder = FakeFolder(clips=clips, subfolders=[])
    if append_result is DEFAULT_APPEND_RESULT:
        append_result = [timeline_item("item-1")]
    media_pool = FakeMediaPool(root_folder=root_folder, append_result=append_result)
    project = FakeProject(timelines=timelines, media_pool=media_pool, **project_kwargs)
    return project, media_pool, timeline


def test_place_clips_disconnected_adapter_raises_resolve_connection_error():
    adapter = ResolveScriptAdapter()

    with pytest.raises(ResolveConnectionError):
        adapter.place_clips("project", "timeline", ["clip-1"])


def test_place_clips_empty_input_returns_without_project_loading():
    adapter, project_manager = connected_adapter(FakeProject())

    assert adapter.place_clips("project", "timeline", []) == []
    assert project_manager.load_calls == []


@pytest.mark.parametrize(
    "clip_ids",
    [
        None,
        "clip-id",
        ("clip-id",),
        (clip_id for clip_id in ["clip-id"]),
        {"clip-id"},
        {"clip_id": "clip-id"},
        iter(["clip-id"]),
    ],
)
def test_place_clips_invalid_clip_id_container_is_rejected_before_project_loading(clip_ids):
    adapter, project_manager = connected_adapter(FakeProject())

    with pytest.raises(TimelineOperationError, match="clip_ids must be a list of strings"):
        adapter.place_clips("project", "timeline", clip_ids)

    assert project_manager.load_calls == []


@pytest.mark.parametrize("clip_id", [None, 123, True, "", "   "])
def test_place_clips_invalid_clip_id_is_rejected(clip_id):
    adapter, project_manager = connected_adapter(FakeProject())

    with pytest.raises(TimelineOperationError, match="Invalid clip ID"):
        adapter.place_clips("project", "timeline", [clip_id])

    assert project_manager.load_calls == []


def test_place_clips_multiple_invalid_indexes_are_reported_together():
    adapter, _project_manager = connected_adapter(FakeProject())

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter.place_clips("project", "timeline", ["", 3, "ok"])

    message = str(exc_info.value)
    assert "index 0" in message
    assert "index 1" in message


def test_place_clips_duplicate_requested_clip_ids_are_rejected():
    adapter, project_manager = connected_adapter(FakeProject())

    with pytest.raises(TimelineOperationError, match="Duplicate clip ID"):
        adapter.place_clips("project", "timeline", ["clip-1", "clip-1"])

    assert project_manager.load_calls == []


def test_place_clips_invalid_input_performs_no_resolve_api_calls():
    root = FakeFolder(clips=[media_item("clip-1")], subfolders=[])
    media_pool = FakeMediaPool(root_folder=root, append_result=[timeline_item("item-1")])
    project = FakeProject(timelines=[FakeTimeline("timeline")], media_pool=media_pool)
    adapter, project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError):
        adapter.place_clips("project", "timeline", [" "])

    assert project_manager.load_calls == []
    assert media_pool.append_calls == []


def test_place_clips_missing_project_raises_project_not_found():
    adapter, _project_manager = connected_adapter(project=False)

    with pytest.raises(ProjectNotFoundError):
        adapter.place_clips("missing", "timeline", ["clip-1"])


def test_place_clips_missing_timeline_raises_timeline_operation_error():
    project, media_pool, _timeline = project_with_media([media_item("clip-1")], timelines=[FakeTimeline("other")])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="not found"):
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls == []


@pytest.mark.parametrize("set_current_result", [False, None])
def test_place_clips_set_current_timeline_falsey_result_raises_timeline_operation_error(set_current_result):
    project, _media_pool, _timeline = project_with_media(
        [media_item("clip-1")], set_current_result=set_current_result
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="set timeline"):
        adapter.place_clips("project", "timeline", ["clip-1"])


def test_place_clips_set_current_timeline_exception_preserves_original_cause():
    original = RuntimeError("set current failed")
    project, _media_pool, _timeline = project_with_media([media_item("clip-1")], set_current_error=original)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert exc_info.value.__cause__ is original


def test_place_clips_missing_media_pool_raises_timeline_operation_error():
    project = FakeProject(timelines=[FakeTimeline("timeline")], media_pool=None)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="media pool"):
        adapter.place_clips("project", "timeline", ["clip-1"])


def test_place_clips_missing_root_folder_raises_timeline_operation_error():
    project = FakeProject(timelines=[FakeTimeline("timeline")], media_pool=FakeMediaPool(root_folder=None))
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="root folder"):
        adapter.place_clips("project", "timeline", ["clip-1"])


def test_place_clips_finds_clip_in_root_folder():
    project, media_pool, _timeline = project_with_media([media_item("clip-1")])
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls[0] == [project.media_pool.root_folder.clips[0]]


def test_place_clips_finds_clip_in_nested_folder():
    nested_clip = media_item("clip-1")
    root = FakeFolder(clips=[], subfolders=[FakeFolder(clips=[nested_clip], subfolders=[])])
    project, media_pool, _timeline = project_with_media([], root_folder=root)
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls[0] == [nested_clip]


def test_place_clips_deeply_nested_folder_lookup_works():
    target = media_item("clip-1")
    root = FakeFolder(
        clips=[],
        subfolders=[FakeFolder(clips=[], subfolders=[FakeFolder(clips=[], subfolders=[FakeFolder(clips=[target])])])],
    )
    project, media_pool, _timeline = project_with_media([], root_folder=root)
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls[0] == [target]


def test_place_clips_self_referencing_folder_does_not_recurse_forever():
    target = media_item("clip-1")
    root = FakeFolder(clips=[target], subfolders=[])
    root.subfolders = [root]
    project, media_pool, _timeline = project_with_media([], root_folder=root)
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls[0] == [target]


def test_place_clips_root_child_cycle_completes_without_recursion_error():
    target = media_item("clip-1")
    root = FakeFolder(clips=[], subfolders=[])
    child = FakeFolder(clips=[target], subfolders=[root])
    root.subfolders = [child]
    project, media_pool, _timeline = project_with_media([], root_folder=root)
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls[0] == [target]


def test_place_clips_repeated_folder_references_do_not_create_duplicate_matches():
    target = media_item("clip-1")
    shared_child = FakeFolder(clips=[target], subfolders=[])
    root = FakeFolder(clips=[], subfolders=[shared_child, shared_child])
    project, media_pool, _timeline = project_with_media([], root_folder=root)
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls[0] == [target]


def test_place_clips_two_parent_folders_referencing_same_child_do_not_duplicate_matches():
    target = media_item("clip-1")
    shared_child = FakeFolder(clips=[target], subfolders=[])
    root = FakeFolder(
        clips=[],
        subfolders=[
            FakeFolder(clips=[], subfolders=[shared_child]),
            FakeFolder(clips=[], subfolders=[shared_child]),
        ],
    )
    project, media_pool, _timeline = project_with_media([], root_folder=root)
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls[0] == [target]


def test_place_clips_requested_order_is_preserved_despite_scan_order():
    first_scan = media_item("clip-b")
    second_scan = media_item("clip-a")
    project, media_pool, _timeline = project_with_media(
        [first_scan, second_scan], append_result=[timeline_item("item-a"), timeline_item("item-b")]
    )
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-a", "clip-b"])

    assert media_pool.append_calls[0] == [second_scan, first_scan]


def test_place_clips_get_media_id_is_preferred():
    clip = FakeMediaPoolItem(media_id="media-id", unique_id="unique-id")
    project, media_pool, _timeline = project_with_media([clip])
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["media-id"])

    assert media_pool.append_calls[0] == [clip]


def test_place_clips_get_unique_id_is_used_as_fallback():
    clip = FakeMediaPoolItem(media_id="", unique_id="unique-id")
    project, media_pool, _timeline = project_with_media([clip])
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["unique-id"])

    assert media_pool.append_calls[0] == [clip]


def test_place_clips_get_media_id_raising_uses_get_unique_id_fallback():
    clip = FakeMediaPoolItem(media_id=None, unique_id="unique-id", media_error=RuntimeError("media id failed"))
    project, media_pool, _timeline = project_with_media([clip])
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["unique-id"])

    assert media_pool.append_calls[0] == [clip]


@pytest.mark.parametrize("media_id", ["", "   ", 123, False])
def test_place_clips_unusable_get_media_id_uses_get_unique_id_fallback(media_id):
    clip = FakeMediaPoolItem(media_id=media_id, unique_id="unique-id")
    project, media_pool, _timeline = project_with_media([clip])
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["unique-id"])

    assert media_pool.append_calls[0] == [clip]


def test_place_clips_both_identifiers_unusable_treats_item_as_unmatched():
    clip = FakeMediaPoolItem(media_id="", unique_id=" ")
    project, media_pool, _timeline = project_with_media([clip])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="not found"):
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls == []


def test_place_clips_get_unique_id_raising_after_unusable_media_id_preserves_original_cause():
    original = RuntimeError("unique id failed")
    clip = FakeMediaPoolItem(media_id="", unique_error=original)
    project, _media_pool, _timeline = project_with_media([clip])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert exc_info.value.__cause__ is original


def test_place_clips_import_fallback_style_id_can_be_found():
    clip = FakeMediaPoolItem(media_id=None, unique_id="fallback-import-id")
    project, media_pool, _timeline = project_with_media([clip])
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["fallback-import-id"])

    assert media_pool.append_calls[0] == [clip]


def test_place_clips_missing_clip_id_raises_before_append_to_timeline():
    project, media_pool, _timeline = project_with_media([media_item("other")])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="not found"):
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls == []


def test_place_clips_duplicate_media_pool_matches_raise_before_append_to_timeline():
    project, media_pool, _timeline = project_with_media([media_item("clip-1"), media_item("clip-1")])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="Multiple"):
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls == []


def test_place_clips_falsey_get_clip_list_is_treated_as_empty():
    target = media_item("clip-1")
    root = FakeFolder(clips=False, subfolders=[FakeFolder(clips=[target], subfolders=[])])
    project, media_pool, _timeline = project_with_media([], root_folder=root)
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls[0] == [target]


def test_place_clips_falsey_get_subfolder_list_is_treated_as_empty():
    target = media_item("clip-1")
    root = FakeFolder(clips=[target], subfolders=False)
    project, media_pool, _timeline = project_with_media([], root_folder=root)
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.append_calls[0] == [target]


def test_place_clips_folder_traversal_exception_preserves_original_cause():
    original = RuntimeError("folder failed")
    root = FakeFolder(clips=[], subfolders=[], folder_error=original)
    project, _media_pool, _timeline = project_with_media([], root_folder=root)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert exc_info.value.__cause__ is original


def test_place_clips_get_unique_id_exception_is_normalized_after_media_id_failure():
    original = RuntimeError("id failed")
    project, _media_pool, _timeline = project_with_media(
        [FakeMediaPoolItem(media_error=RuntimeError("media id failed"), unique_error=original)]
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert exc_info.value.__cause__ is original


def test_place_clips_append_to_timeline_receives_one_ordered_list():
    clip_a = media_item("clip-a")
    clip_b = media_item("clip-b")
    project, media_pool, _timeline = project_with_media(
        [clip_a, clip_b], append_result=[timeline_item("item-a"), timeline_item("item-b")]
    )
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-a", "clip-b"])

    assert media_pool.append_calls == [[clip_a, clip_b]]


@pytest.mark.parametrize("append_result", [None, False, []])
def test_place_clips_falsey_append_to_timeline_result_raises(append_result):
    project, _media_pool, _timeline = project_with_media([media_item("clip-1")], append_result=append_result)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError):
        adapter.place_clips("project", "timeline", ["clip-1"])


def test_place_clips_append_to_timeline_returning_non_sequence_raises():
    project, _media_pool, _timeline = project_with_media([media_item("clip-1")], append_result="bad-result")
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="invalid placement result"):
        adapter.place_clips("project", "timeline", ["clip-1"])


def test_place_clips_returned_count_mismatch_raises():
    project, _media_pool, _timeline = project_with_media(
        [media_item("clip-a"), media_item("clip-b")], append_result=[timeline_item("item-a")]
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="1 item"):
        adapter.place_clips("project", "timeline", ["clip-a", "clip-b"])


def test_place_clips_append_to_timeline_exception_preserves_cause_and_skips_id_extraction(caplog):
    caplog.set_level(logging.ERROR)
    original = RuntimeError("append failed")
    clip_a = media_item("clip-a")
    clip_b = media_item("clip-b")
    returned_item = timeline_item("item-a")
    project, media_pool, _timeline = project_with_media(
        [clip_a, clip_b],
        append_result=[returned_item],
    )
    media_pool.append_error = original
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter.place_clips("project", "timeline", ["clip-a", "clip-b"])

    assert exc_info.value.__cause__ is original
    assert media_pool.append_calls == [[clip_a, clip_b]]
    assert returned_item.unique_id_calls == 0
    assert "Partial Resolve state may remain" in caplog.text


def test_place_clips_success_returns_timeline_item_ids_in_order():
    project, _media_pool, _timeline = project_with_media(
        [media_item("clip-a"), media_item("clip-b")], append_result=[timeline_item("item-a"), timeline_item("item-b")]
    )
    adapter, _project_manager = connected_adapter(project)

    assert adapter.place_clips("project", "timeline", ["clip-a", "clip-b"]) == ["item-a", "item-b"]


def test_place_clips_falsey_timeline_item_handle_raises():
    project, _media_pool, _timeline = project_with_media(
        [media_item("clip-1")], append_result=[FalseyTimelineItem()]
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="falsey"):
        adapter.place_clips("project", "timeline", ["clip-1"])


def test_place_clips_timeline_item_empty_unique_id_raises():
    project, _media_pool, _timeline = project_with_media([media_item("clip-1")], append_result=[timeline_item("")])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="usable ID"):
        adapter.place_clips("project", "timeline", ["clip-1"])


def test_place_clips_duplicate_timeline_item_ids_raise_timeline_operation_error():
    project, _media_pool, _timeline = project_with_media(
        [media_item("clip-a"), media_item("clip-b")],
        append_result=[timeline_item("item-a"), timeline_item("item-a")],
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError, match="duplicate TimelineItem ID"):
        adapter.place_clips("project", "timeline", ["clip-a", "clip-b"])


def test_place_clips_does_not_attempt_rollback_after_id_validation_failure():
    bad_item = timeline_item("")
    project, media_pool, _timeline = project_with_media([media_item("clip-1")], append_result=[bad_item])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError):
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert media_pool.delete_calls == []


def test_place_clips_timeline_item_unique_id_exception_preserves_original_cause():
    original = RuntimeError("unique failed")
    project, _media_pool, _timeline = project_with_media(
        [media_item("clip-1")], append_result=[FakeTimelineItem(error=original)]
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError) as exc_info:
        adapter.place_clips("project", "timeline", ["clip-1"])

    assert exc_info.value.__cause__ is original


def test_place_clips_partial_invalid_returned_items_report_extracted_count(caplog):
    caplog.set_level(logging.ERROR)
    project, _media_pool, _timeline = project_with_media(
        [media_item("clip-a"), media_item("clip-b")], append_result=[timeline_item("item-a"), timeline_item("")]
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(TimelineOperationError):
        adapter.place_clips("project", "timeline", ["clip-a", "clip-b"])

    assert "extracted_count=1" in caplog.text
    assert "failed_index=1" in caplog.text
    assert "Partial Resolve state may remain" in caplog.text


def test_place_clips_logging_includes_requested_resolved_and_placed_counts(caplog):
    caplog.set_level(logging.INFO)
    project, _media_pool, _timeline = project_with_media(
        [media_item("clip-a"), media_item("clip-b")], append_result=[timeline_item("item-a"), timeline_item("item-b")]
    )
    adapter, _project_manager = connected_adapter(project)

    adapter.place_clips("project", "timeline", ["clip-a", "clip-b"])

    assert "requested_count=2" in caplog.text
    assert "resolved_count=2" in caplog.text
    assert "placed_count=2" in caplog.text
