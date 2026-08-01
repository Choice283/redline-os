import logging

import pytest
from unittest.mock import Mock

from redline_core.logging.setup import configure_logging
from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.exceptions import (
    ProjectNotFoundError,
    RenderJobError,
    RenderQueueAcceptanceNotObservedError,
    RenderQueueIdentityUnresolvedError,
    ResolveConnectionError,
)


class FakeTimeline:
    def __init__(self, name: str = "timeline"):
        self.name = name

    def GetName(self):
        return self.name


class FakeProject:
    def __init__(
        self,
        *,
        render_job_lists=None,
        load_preset_result=True,
        load_preset_error: Exception | None = None,
        set_settings_result=True,
        set_settings_error: Exception | None = None,
        add_render_job_result="job-1",
        add_render_job_error: Exception | None = None,
        timeline_name: str = "timeline",
        set_current_timeline_result=True,
        has_set_current_timeline=True,
        current_timeline_name: str = "timeline",
        preserve_current_timeline: bool = False,
    ):
        self.render_job_lists = list(render_job_lists or [[]])
        self.load_preset_result = load_preset_result
        self.load_preset_error = load_preset_error
        self.set_settings_result = set_settings_result
        self.set_settings_error = set_settings_error
        self.add_render_job_result = add_render_job_result
        self.add_render_job_error = add_render_job_error
        self.timeline = FakeTimeline(timeline_name)
        self.current_timeline = FakeTimeline(current_timeline_name)
        self.preserve_current_timeline = preserve_current_timeline
        self.set_current_timeline_result = set_current_timeline_result
        self.load_preset_calls = []
        self.set_settings_calls = []
        self.add_render_job_calls = 0
        self.render_job_list_calls = 0
        self.set_current_timeline_calls = []
        self.StartRendering = Mock()
        if not has_set_current_timeline:
            self.SetCurrentTimeline = None

    def LoadRenderPreset(self, preset_name: str):
        self.load_preset_calls.append(preset_name)
        if self.load_preset_error is not None:
            raise self.load_preset_error
        return self.load_preset_result

    def SetRenderSettings(self, settings: dict[str, object]):
        self.set_settings_calls.append(settings)
        if self.set_settings_error is not None:
            raise self.set_settings_error
        return self.set_settings_result

    def AddRenderJob(self):
        self.add_render_job_calls += 1
        if self.add_render_job_error is not None:
            raise self.add_render_job_error
        return self.add_render_job_result

    def GetRenderJobList(self):
        self.render_job_list_calls += 1
        index = min(self.render_job_list_calls - 1, len(self.render_job_lists) - 1)
        return self.render_job_lists[index]

    def GetTimelineCount(self):
        return 1

    def GetTimelineByIndex(self, index: int):
        return self.timeline if index == 1 else None

    def SetCurrentTimeline(self, timeline):
        self.set_current_timeline_calls.append(timeline)
        if self.set_current_timeline_result is True and not self.preserve_current_timeline:
            self.current_timeline = timeline
        return self.set_current_timeline_result

    def GetCurrentTimeline(self):
        return self.current_timeline


def queue(adapter: ResolveScriptAdapter):
    return adapter.queue_render_job(
        project_name="project",
        timeline_name="timeline",
        resolve_preset_name="preset",
        target_directory="exports",
        custom_name="RLC-E025",
    )


class FakeProjectManager:
    def __init__(self, project=None, load_error: Exception | None = None):
        self.project = project
        self.load_error = load_error
        self.load_calls = []

    def LoadProject(self, project_name: str):
        self.load_calls.append(project_name)
        if self.load_error is not None:
            raise self.load_error
        return self.project


class FakeResolve:
    pass


def connected_adapter(project=None, load_error: Exception | None = None):
    adapter = ResolveScriptAdapter()
    project_manager = FakeProjectManager(project, load_error=load_error)
    adapter._project_manager = project_manager
    adapter._resolve = FakeResolve()
    return adapter, project_manager


def test_queue_render_requires_connection():
    adapter = ResolveScriptAdapter()

    with pytest.raises(ResolveConnectionError):
        queue(adapter)


def test_queue_render_rejects_unknown_project():
    adapter, _project_manager = connected_adapter(project=False)

    with pytest.raises(ProjectNotFoundError):
        adapter.queue_render_job(
            project_name="missing",
            timeline_name="timeline",
            resolve_preset_name="preset",
            target_directory="exports",
            custom_name="RLC-E025",
        )


def test_queue_render_rejects_empty_project_name():
    project = FakeProject()
    adapter, project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="Project name"):
        adapter.queue_render_job(
            project_name="  ",
            timeline_name="timeline",
            resolve_preset_name="preset",
            target_directory="exports",
            custom_name="RLC-E025",
        )

    assert project_manager.load_calls == []
    assert project.add_render_job_calls == 0


def test_queue_render_rejects_empty_preset_name():
    project = FakeProject()
    adapter, project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-empty"):
        adapter.queue_render_job(
            project_name="project",
            timeline_name="timeline",
            resolve_preset_name="  ",
            target_directory="exports",
            custom_name="RLC-E025",
        )

    assert project_manager.load_calls == []
    assert project.load_preset_calls == []


def test_queue_render_fails_when_preset_cannot_be_loaded():
    project = FakeProject(load_preset_result=False)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="load render preset"):
        adapter.queue_render_job(
            project_name="project",
            timeline_name="timeline",
            resolve_preset_name="missing-preset",
            target_directory="exports",
            custom_name="RLC-E025",
        )

    assert project.load_preset_calls == ["missing-preset"]
    assert project.set_settings_calls == []
    assert project.add_render_job_calls == 0
    project.StartRendering.assert_not_called()


def test_queue_render_fails_when_timeline_is_missing():
    project = FakeProject(timeline_name="other-timeline")
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="Timeline 'timeline' not found"):
        queue(adapter)

    assert project.load_preset_calls == []
    assert project.set_settings_calls == []
    assert project.add_render_job_calls == 0
    project.StartRendering.assert_not_called()


def test_queue_render_fails_when_timeline_cannot_be_selected():
    project = FakeProject(set_current_timeline_result=False)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="set timeline"):
        queue(adapter)

    assert project.load_preset_calls == []
    assert project.set_settings_calls == []
    assert project.add_render_job_calls == 0
    project.StartRendering.assert_not_called()


def test_queue_render_fails_when_timeline_selection_returns_none():
    project = FakeProject(set_current_timeline_result=None)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="could not set timeline"):
        queue(adapter)

    assert project.load_preset_calls == []
    assert project.set_settings_calls == []
    assert project.add_render_job_calls == 0
    project.StartRendering.assert_not_called()


def test_queue_render_fails_when_timeline_selection_api_is_missing():
    project = FakeProject(has_set_current_timeline=False)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="cannot select timeline"):
        queue(adapter)

    assert project.load_preset_calls == []
    assert project.set_settings_calls == []
    assert project.add_render_job_calls == 0
    project.StartRendering.assert_not_called()


def test_queue_render_fails_when_selected_timeline_mismatch_is_reported():
    project = FakeProject(current_timeline_name="other-timeline", preserve_current_timeline=True)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="selected timeline"):
        queue(adapter)

    assert project.load_preset_calls == []
    assert project.set_settings_calls == []
    assert project.add_render_job_calls == 0
    project.StartRendering.assert_not_called()


def test_queue_render_fails_when_output_settings_cannot_be_applied():
    project = FakeProject(set_settings_result=False)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="output settings"):
        queue(adapter)

    assert project.set_settings_calls == [{"TargetDir": "exports", "CustomName": "RLC-E025"}]
    assert project.add_render_job_calls == 0


def test_queue_render_fails_when_add_render_job_fails():
    project = FakeProject(add_render_job_result=False)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="failed to add"):
        queue(adapter)

    assert project.add_render_job_calls == 1
    assert project.render_job_list_calls == 1


def test_queue_render_returns_direct_job_id():
    project = FakeProject(add_render_job_result="resolve-job-1")
    adapter, _project_manager = connected_adapter(project)

    job_id = queue(adapter)

    assert job_id == "resolve-job-1"
    assert project.load_preset_calls == ["preset"]
    assert project.set_settings_calls == [{"TargetDir": "exports", "CustomName": "RLC-E025"}]
    assert project.add_render_job_calls == 1
    assert project.render_job_list_calls == 1
    project.StartRendering.assert_not_called()


def test_queue_render_returns_direct_integer_job_id():
    project = FakeProject(add_render_job_result=42)
    adapter, _project_manager = connected_adapter(project)

    assert queue(adapter) == "42"


def test_queue_render_derives_job_id_from_job_list():
    project = FakeProject(
        render_job_lists=[
            [{"JobId": "old-job"}],
            [{"JobId": "old-job"}, {"JobId": "new-job"}],
        ],
        add_render_job_result=True,
    )
    adapter, _project_manager = connected_adapter(project)

    assert queue(adapter) == "new-job"
    assert project.render_job_list_calls == 2


def test_queue_render_derives_job_id_from_common_id_key_variants():
    project = FakeProject(
        render_job_lists=[
            [{"job_id": "old-job"}],
            [{"job_id": "old-job"}, {"ID": "new-job"}],
        ],
        add_render_job_result=None,
    )
    adapter, _project_manager = connected_adapter(project)

    assert queue(adapter) == "new-job"


def test_queue_render_fails_when_job_id_is_missing():
    project = FakeProject(
        render_job_lists=[
            [],
            [{"RenderJobName": "unnamed"}],
        ],
        add_render_job_result=True,
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError, match="no usable job ID"):
        queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()


def test_queue_render_fails_when_no_new_job_id_can_be_reconciled():
    project = FakeProject(
        render_job_lists=[
            [{"JobId": "old-job"}],
            [{"JobId": "old-job"}],
        ],
        add_render_job_result=True,
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError, match="returned no usable job ID"):
        queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()


def test_queue_render_fails_when_job_id_is_ambiguous():
    project = FakeProject(
        render_job_lists=[
            [{"JobId": "old-job"}],
            [{"JobId": "old-job"}, {"JobId": "new-a"}, {"JobId": "new-b"}],
        ],
        add_render_job_result=True,
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError, match="2 possible"):
        queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()


def test_queue_render_before_phase_failure_stays_plain_render_job_error():
    """A pre-existing, already-queued item that Redline can't read is a
    before-phase failure — AddRenderJob() is never reached, so this is not
    an uncertain post-mutation state and must not be reclassified."""
    project = FakeProject(render_job_lists=[[{"RenderJobName": "unnamed"}]])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError) as exc_info:
        queue(adapter)

    assert not isinstance(exc_info.value, RenderQueueIdentityUnresolvedError)
    assert project.add_render_job_calls == 0


class GetRenderJobListRaisesAfterAdd(FakeProject):
    def AddRenderJob(self):
        result = super().AddRenderJob()
        self._raise_on_list = True
        return result

    def GetRenderJobList(self):
        if getattr(self, "_raise_on_list", False):
            self.render_job_list_calls += 1
            raise RuntimeError("Resolve API changed")
        return super().GetRenderJobList()


def test_queue_render_identity_unresolved_when_after_list_raises():
    project = GetRenderJobListRaisesAfterAdd(render_job_lists=[[]], add_render_job_result=True)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError):
        queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()


class GetRenderJobListRemovedAfterAdd(FakeProject):
    def AddRenderJob(self):
        result = super().AddRenderJob()
        self.GetRenderJobList = None  # shadows the bound method -> not callable
        return result


def test_queue_render_identity_unresolved_when_after_list_unavailable():
    project = GetRenderJobListRemovedAfterAdd(render_job_lists=[[]], add_render_job_result=True)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError):
        queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()


class GetRenderJobListNonListAfterAdd(FakeProject):
    def AddRenderJob(self):
        result = super().AddRenderJob()
        self._return_non_list = True
        return result

    def GetRenderJobList(self):
        if getattr(self, "_return_non_list", False):
            self.render_job_list_calls += 1
            return "not-a-list"
        return super().GetRenderJobList()


def test_queue_render_identity_unresolved_logs_error_for_non_list_after_response(caplog):
    project = GetRenderJobListNonListAfterAdd(render_job_lists=[[]], add_render_job_result=True)
    adapter, _project_manager = connected_adapter(project)

    with caplog.at_level(logging.ERROR, logger="redline_os.resolve.adapter"):
        with pytest.raises(RenderQueueIdentityUnresolvedError):
            queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()
    message = caplog.records[-1].getMessage()
    assert "after_job_ids='unavailable'" in message
    assert "reconciliation_error_type=RenderJobError" in message
    assert "invalid render job list" in message
    assert ": str" in message


class RaisingLookupDict(dict):
    def __contains__(self, key):
        raise RuntimeError("unexpected dict failure")


def test_queue_render_identity_unresolved_when_unexpected_error_during_extraction(caplog):
    project = FakeProject(
        render_job_lists=[[], [RaisingLookupDict({"JobId": "x"})]],
        add_render_job_result=True,
    )
    adapter, _project_manager = connected_adapter(project)

    with caplog.at_level(logging.ERROR, logger="redline_os.resolve.adapter"):
        with pytest.raises(RenderQueueIdentityUnresolvedError):
            queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()
    message = caplog.records[-1].getMessage()
    assert "reconciliation_error_type=RuntimeError" in message
    assert "RaisingLookupDict" in message
    assert "after_job_ids='unavailable'" in message


def test_queue_render_identity_unresolved_logs_true_add_result_diagnostics(caplog):
    project = FakeProject(render_job_lists=[[], []], add_render_job_result=True)
    adapter, _project_manager = connected_adapter(project)

    with caplog.at_level(logging.ERROR, logger="redline_os.resolve.adapter"):
        with pytest.raises(RenderQueueIdentityUnresolvedError):
            queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()
    message = caplog.records[-1].getMessage()
    assert "add_result_type=bool" in message
    assert "add_result_repr=True" in message
    assert "reconciliation_outcome=identity_unresolved" in message


def test_queue_render_identity_unresolved_logs_none_add_result_diagnostics(caplog):
    project = FakeProject(render_job_lists=[[], []], add_render_job_result=None)
    adapter, _project_manager = connected_adapter(project)

    with caplog.at_level(logging.ERROR, logger="redline_os.resolve.adapter"):
        with pytest.raises(RenderQueueIdentityUnresolvedError):
            queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()
    message = caplog.records[-1].getMessage()
    assert "add_result_type=NoneType" in message
    assert "add_result_repr=None" in message


class UnrepresentableAddResult:
    def __repr__(self):
        raise RuntimeError("cannot repr")


def test_queue_render_identity_unresolved_survives_unrepresentable_add_result(caplog):
    project = FakeProject(render_job_lists=[[], []], add_render_job_result=UnrepresentableAddResult())
    adapter, _project_manager = connected_adapter(project)

    with caplog.at_level(logging.ERROR, logger="redline_os.resolve.adapter"):
        with pytest.raises(RenderQueueIdentityUnresolvedError):
            queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()
    message = caplog.records[-1].getMessage()
    assert "<unrepresentable UnrepresentableAddResult>" in message


def test_queue_render_identity_unresolved_is_not_masked_when_logger_raises(monkeypatch):
    project = FakeProject(render_job_lists=[[], []], add_render_job_result=True)
    adapter, _project_manager = connected_adapter(project)

    def raise_logging_error(*args, **kwargs):
        raise RuntimeError("logging failed")

    monkeypatch.setattr("redline_core.resolve.adapter._render_queue_identity_logger.error", raise_logging_error)

    with pytest.raises(RenderQueueIdentityUnresolvedError):
        queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()


@pytest.fixture
def isolated_redline_application_logging():
    """Isolates both the "redline_os" root and "redline_os.resolve.adapter"
    child logger around a test that calls the real configure_logging().

    Removes any pre-existing handlers from both loggers up front, *without*
    closing them, so configure_logging() never sees the root logger's
    existing handlers and therefore never closes them itself
    (configure_logging() closes any handler already tagged as Redline-owned
    that it finds attached), and so the test can't depend on or emit into
    ambient child-logger handlers. Teardown then closes only
    handlers that were not part of the saved pre-test state -- i.e. only the
    ones this test's configure_logging() call actually created -- and
    restores both loggers' original handlers, level, propagate, and
    disabled state exactly.
    """
    redline_os_logger = logging.getLogger("redline_os")
    child_logger = logging.getLogger("redline_os.resolve.adapter")

    saved_root_handlers = list(redline_os_logger.handlers)
    saved_root_level = redline_os_logger.level
    saved_root_propagate = redline_os_logger.propagate
    saved_root_disabled = redline_os_logger.disabled

    saved_child_handlers = list(child_logger.handlers)
    saved_child_level = child_logger.level
    saved_child_propagate = child_logger.propagate
    saved_child_disabled = child_logger.disabled

    for handler in list(redline_os_logger.handlers):
        redline_os_logger.removeHandler(handler)

    for handler in list(child_logger.handlers):
        child_logger.removeHandler(handler)

    child_logger.setLevel(logging.NOTSET)
    child_logger.propagate = True
    child_logger.disabled = False

    try:
        yield
    finally:
        for handler in list(redline_os_logger.handlers):
            redline_os_logger.removeHandler(handler)
            if handler not in saved_root_handlers:
                handler.close()
        for handler in saved_root_handlers:
            redline_os_logger.addHandler(handler)
        redline_os_logger.setLevel(saved_root_level)
        redline_os_logger.propagate = saved_root_propagate
        redline_os_logger.disabled = saved_root_disabled

        for handler in list(child_logger.handlers):
            child_logger.removeHandler(handler)
            if handler not in saved_child_handlers:
                handler.close()
        for handler in saved_child_handlers:
            child_logger.addHandler(handler)
        child_logger.setLevel(saved_child_level)
        child_logger.propagate = saved_child_propagate
        child_logger.disabled = saved_child_disabled


def test_queue_render_identity_unresolved_writes_to_configured_application_log(
    tmp_path, isolated_redline_application_logging
):
    """Proves the diagnostic actually lands in logs/redline_os.log via the
    real configured logger tree, not just via caplog."""
    configure_logging(log_dir=tmp_path, level="INFO")

    project = FakeProject(render_job_lists=[[], []], add_render_job_result=True)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError):
        queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()

    redline_os_logger = logging.getLogger("redline_os")
    for handler in redline_os_logger.handlers:
        if getattr(handler, "_redline_os_owned_handler", False):
            handler.flush()

    log_file = tmp_path / "redline_os.log"
    assert log_file.exists()
    contents = log_file.read_text(encoding="utf-8")
    assert "add_result_type=bool" in contents
    assert "add_result_repr=True" in contents
    assert "candidate_job_ids=[]" in contents
    assert "reconciliation_error_type=RenderJobError" in contents
    assert "redline_os.resolve.adapter" in contents


def test_queue_render_acceptance_not_observed_when_empty_string_and_unchanged_empty_queue():
    project = FakeProject(render_job_lists=[[], []], add_render_job_result="")
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueAcceptanceNotObservedError) as exc_info:
        queue(adapter)

    assert not isinstance(exc_info.value, RenderQueueIdentityUnresolvedError)
    assert "Manual render-queue reconciliation" not in str(exc_info.value)
    assert "Resolve added a render job" not in str(exc_info.value)
    assert "the same render-job ID multiset with no unidentified items" in str(exc_info.value)
    assert project.add_render_job_calls == 1
    assert project.render_job_list_calls == 2
    project.StartRendering.assert_not_called()


def test_queue_render_acceptance_not_observed_when_empty_string_and_identical_nonempty_multisets():
    project = FakeProject(
        render_job_lists=[
            [{"JobId": "existing"}],
            [{"JobId": "existing"}],
        ],
        add_render_job_result="",
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueAcceptanceNotObservedError):
        queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()


def test_queue_render_derives_job_id_when_add_result_is_empty_string():
    project = FakeProject(
        render_job_lists=[
            [],
            [{"JobId": "new-job"}],
        ],
        add_render_job_result="",
    )
    adapter, _project_manager = connected_adapter(project)

    assert queue(adapter) == "new-job"


def test_queue_render_identity_unresolved_when_empty_string_and_multiple_candidates():
    project = FakeProject(
        render_job_lists=[
            [],
            [{"JobId": "a"}, {"JobId": "b"}],
        ],
        add_render_job_result="",
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError) as exc_info:
        queue(adapter)

    assert not isinstance(exc_info.value, RenderQueueAcceptanceNotObservedError)


def test_queue_render_identity_unresolved_when_empty_string_and_unidentified_item():
    project = FakeProject(
        render_job_lists=[
            [],
            [{"RenderJobName": "unnamed"}],
        ],
        add_render_job_result="",
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError) as exc_info:
        queue(adapter)

    assert not isinstance(exc_info.value, RenderQueueAcceptanceNotObservedError)


def test_queue_render_identity_unresolved_when_empty_string_and_after_snapshot_fails():
    project = GetRenderJobListRaisesAfterAdd(render_job_lists=[[]], add_render_job_result="")
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError) as exc_info:
        queue(adapter)

    assert not isinstance(exc_info.value, RenderQueueAcceptanceNotObservedError)


def test_queue_render_identity_unresolved_when_empty_string_and_existing_job_disappears():
    """A job vanishing between snapshots is more suspicious, not less --
    candidate_job_ids stays empty (nothing NEW appeared, since the diff only
    tracks additions), so multiset *equality* -- not just "zero candidates"
    -- is what correctly keeps this on the cautious identity-unresolved
    path instead of the more confident acceptance-not-observed one."""
    project = FakeProject(
        render_job_lists=[
            [{"JobId": "existing"}],
            [],
        ],
        add_render_job_result="",
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueIdentityUnresolvedError) as exc_info:
        queue(adapter)

    assert not isinstance(exc_info.value, RenderQueueAcceptanceNotObservedError)


def test_queue_render_succeeds_when_empty_string_and_job_disappears_alongside_one_new_id():
    """Documents an intentional boundary: this classification only runs when
    _derive_new_render_job_id() does NOT already return a single successful
    candidate. If an existing job disappears but exactly one new candidate
    also appears, that pre-existing single-candidate-success path (from
    before this classification existed) fires first and returns success
    directly -- the disappearance is never inspected by this method. Only a
    disappearance that leaves zero new candidates is caught by the
    multiset-equality guard in the identity-unresolved branch."""
    project = FakeProject(
        render_job_lists=[
            [{"JobId": "old"}],
            [{"JobId": "new"}],
        ],
        add_render_job_result="",
    )
    adapter, _project_manager = connected_adapter(project)

    assert queue(adapter) == "new"


class RaisingAttributeLookupProject(FakeProject):
    """Simulates a bridged Resolve object whose attribute lookup itself
    raises -- proving getattr(obj, name, default) alone is not a safe
    guard, since it only suppresses AttributeError, not an arbitrary
    exception a bridged __getattr__ might raise."""

    def __getattr__(self, name):
        if name == "GetCurrentRenderFormatAndCodec":
            raise RuntimeError("attribute lookup failed")
        raise AttributeError(name)


def test_queue_render_acceptance_not_observed_survives_attribute_lookup_failure(caplog):
    project = RaisingAttributeLookupProject(render_job_lists=[[], []], add_render_job_result="")
    adapter, _project_manager = connected_adapter(project)

    with caplog.at_level(logging.ERROR, logger="redline_os.resolve.adapter"):
        with pytest.raises(RenderQueueAcceptanceNotObservedError):
            queue(adapter)

    assert project.add_render_job_calls == 1
    message = caplog.records[-1].getMessage()
    assert "render_format='unavailable'" in message
    assert "render_codec='unavailable'" in message


class RaisingFormatCodecProject(FakeProject):
    def GetCurrentRenderFormatAndCodec(self):
        raise RuntimeError("format/codec query failed")


def test_queue_render_acceptance_not_observed_survives_format_codec_call_failure(caplog):
    project = RaisingFormatCodecProject(render_job_lists=[[], []], add_render_job_result="")
    adapter, _project_manager = connected_adapter(project)

    with caplog.at_level(logging.ERROR, logger="redline_os.resolve.adapter"):
        with pytest.raises(RenderQueueAcceptanceNotObservedError):
            queue(adapter)

    assert project.add_render_job_calls == 1
    message = caplog.records[-1].getMessage()
    assert "render_format='unavailable'" in message
    assert "render_codec='unavailable'" in message


class ReportingFormatCodecProject(FakeProject):
    def GetCurrentRenderFormatAndCodec(self):
        return {"format": "QuickTime", "codec": "ProRes"}


def test_queue_render_acceptance_not_observed_logs_successful_format_codec_capture(
    tmp_path, isolated_redline_application_logging
):
    configure_logging(log_dir=tmp_path, level="INFO")

    project = ReportingFormatCodecProject(render_job_lists=[[], []], add_render_job_result="")
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueAcceptanceNotObservedError):
        queue(adapter)

    assert project.add_render_job_calls == 1
    assert project.render_job_list_calls == 2
    project.StartRendering.assert_not_called()

    redline_os_logger = logging.getLogger("redline_os")
    for handler in redline_os_logger.handlers:
        if getattr(handler, "_redline_os_owned_handler", False):
            handler.flush()

    log_file = tmp_path / "redline_os.log"
    contents = log_file.read_text(encoding="utf-8")
    assert "render_format='QuickTime'" in contents
    assert "render_codec='ProRes'" in contents


def test_queue_render_acceptance_not_observed_is_not_masked_when_logger_raises(monkeypatch):
    project = FakeProject(render_job_lists=[[], []], add_render_job_result="")
    adapter, _project_manager = connected_adapter(project)

    def raise_logging_error(*args, **kwargs):
        raise RuntimeError("logging failed")

    monkeypatch.setattr("redline_core.resolve.adapter._render_queue_identity_logger.error", raise_logging_error)

    with pytest.raises(RenderQueueAcceptanceNotObservedError):
        queue(adapter)

    assert project.add_render_job_calls == 1
    project.StartRendering.assert_not_called()


def test_queue_render_acceptance_not_observed_writes_to_configured_application_log(
    tmp_path, isolated_redline_application_logging
):
    """Proves the diagnostic lands in logs/redline_os.log with the exact
    known pre-add values and a machine-searchable reconciliation_outcome
    field, not just via caplog."""
    configure_logging(log_dir=tmp_path, level="INFO")

    project = FakeProject(render_job_lists=[[], []], add_render_job_result="")
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderQueueAcceptanceNotObservedError):
        queue(adapter)

    assert project.add_render_job_calls == 1
    assert project.render_job_list_calls == 2
    project.StartRendering.assert_not_called()

    redline_os_logger = logging.getLogger("redline_os")
    for handler in redline_os_logger.handlers:
        if getattr(handler, "_redline_os_owned_handler", False):
            handler.flush()

    log_file = tmp_path / "redline_os.log"
    assert log_file.exists()
    contents = log_file.read_text(encoding="utf-8")
    assert "reconciliation_outcome=acceptance_not_observed" in contents
    assert "timeline_name='timeline'" in contents
    assert "target_dir='exports'" in contents
    assert "custom_name='RLC-E025'" in contents
    assert "render_format='unavailable'" in contents
    assert "render_codec='unavailable'" in contents
    assert "render_mode='unavailable'" in contents
    assert "redline_os.resolve.adapter" in contents


def test_queue_render_wraps_unexpected_resolve_errors():
    original = RuntimeError("Resolve API changed")
    project = FakeProject(load_preset_error=original)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError) as exc_info:
        queue(adapter)

    assert exc_info.value.__cause__ is original


def test_queue_render_wraps_project_load_errors():
    original = RuntimeError("load failed")
    adapter, _project_manager = connected_adapter(load_error=original)

    with pytest.raises(RenderJobError) as exc_info:
        queue(adapter)

    assert exc_info.value.__cause__ is original


def test_list_render_jobs_returns_project_queue_metadata():
    project = FakeProject(render_job_lists=[[{"JobId": "job-1", "TargetDir": "exports", "CustomName": "RLC-E025"}]])
    adapter, _project_manager = connected_adapter(project)

    assert adapter.list_render_jobs("project") == [{"JobId": "job-1", "TargetDir": "exports", "CustomName": "RLC-E025"}]


def test_delete_render_job_uses_resolve_delete_api():
    project = FakeProject()
    project.DeleteRenderJob = Mock(return_value=True)
    adapter, _project_manager = connected_adapter(project)

    adapter.delete_render_job("project", "job-1")

    project.DeleteRenderJob.assert_called_once_with("job-1")
