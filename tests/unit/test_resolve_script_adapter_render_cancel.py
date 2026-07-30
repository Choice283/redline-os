from unittest.mock import Mock

import pytest

from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.exceptions import RenderJobError, ResolveConnectionError


class FakeProject:
    def __init__(
        self,
        *,
        statuses: dict[str, object] | None = None,
        render_jobs: list[dict] | None = None,
        rendering_in_progress: object = False,
        delete_result: object = True,
        stop_error: Exception | None = None,
        status_error: Exception | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self.statuses = dict(statuses or {})
        self.render_jobs = list(render_jobs or [])
        self.status_error = status_error
        self.list_error = list_error
        self.stop_returns: list[object] = []
        self.GetRenderJobStatus = Mock(side_effect=self._get_render_job_status)
        self.DeleteRenderJob = Mock(side_effect=self._delete_render_job)
        self.StopRendering = Mock(side_effect=self._stop_rendering)
        self.IsRenderingInProgress = Mock(side_effect=self._is_rendering_in_progress)
        self.rendering_in_progress_values = self._as_sequence(rendering_in_progress)
        self.delete_result = delete_result
        self.stop_error = stop_error

    def _as_sequence(self, value: object) -> list[object]:
        if isinstance(value, list):
            return list(value)
        return [value]

    def _get_render_job_status(self, job_id: str) -> object:
        if self.status_error is not None:
            raise self.status_error
        return self.statuses.get(job_id)

    def _delete_render_job(self, job_id: str) -> object:
        result = self.delete_result
        if result is True:
            self.statuses.pop(job_id, None)
            self.render_jobs = [job for job in self.render_jobs if job.get("JobId") != job_id]
        return result

    def _stop_rendering(self) -> object:
        if self.stop_error is not None:
            raise self.stop_error
        for job_id, status in list(self.statuses.items()):
            if isinstance(status, dict) and status.get("JobStatus") == "Rendering":
                self.statuses[job_id] = {"JobStatus": "Cancelled", "CompletionPercentage": 14}
        self.stop_returns.append(None)
        return None

    def _is_rendering_in_progress(self) -> object:
        if len(self.rendering_in_progress_values) > 1:
            return self.rendering_in_progress_values.pop(0)
        return self.rendering_in_progress_values[0]

    def GetRenderJobList(self) -> list[dict]:
        if self.list_error is not None:
            raise self.list_error
        return self.render_jobs


class FakeProjectManager:
    def __init__(self, project: object = None) -> None:
        self.project = project

    def GetCurrentProject(self) -> object:
        return self.project


class FakeResolve:
    def __init__(self, project_manager: object = None) -> None:
        self.project_manager = project_manager

    def GetProjectManager(self) -> object:
        return self.project_manager


_DEFAULT_PROJECT_MANAGER = object()


def connected_adapter(project: object = None, project_manager: object = _DEFAULT_PROJECT_MANAGER):
    adapter = ResolveScriptAdapter()
    if project_manager is _DEFAULT_PROJECT_MANAGER:
        project_manager = FakeProjectManager(project)
    adapter._project_manager = project_manager
    adapter._resolve = FakeResolve(project_manager)
    return adapter


def test_cancel_render_requires_connection():
    adapter = ResolveScriptAdapter()

    with pytest.raises(ResolveConnectionError):
        adapter.cancel_render("job-1")


def test_cancel_render_rejects_empty_job_id():
    project = FakeProject(statuses={"job-1": {"JobStatus": "Ready"}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-empty"):
        adapter.cancel_render("")

    project.GetRenderJobStatus.assert_not_called()


def test_cancel_render_rejects_whitespace_job_id():
    project = FakeProject(statuses={"job-1": {"JobStatus": "Ready"}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-empty"):
        adapter.cancel_render("   ")

    project.GetRenderJobStatus.assert_not_called()


def test_cancel_render_rejects_non_string_job_id():
    project = FakeProject(statuses={"job-1": {"JobStatus": "Ready"}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-empty"):
        adapter.cancel_render(42)

    project.GetRenderJobStatus.assert_not_called()


def test_cancel_render_fails_when_project_manager_is_unavailable():
    adapter = ResolveScriptAdapter()
    adapter._project_manager = object()
    adapter._resolve = FakeResolve(None)

    with pytest.raises(RenderJobError, match="project manager"):
        adapter.cancel_render("job-1")


def test_cancel_render_fails_when_no_project_is_loaded():
    adapter = connected_adapter(project=None)

    with pytest.raises(RenderJobError, match="no Resolve project"):
        adapter.cancel_render("job-1")


def test_cancel_render_rejects_unknown_job():
    project = FakeProject(statuses={})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="not found"):
        adapter.cancel_render("job-1")


def test_cancel_render_rejects_malformed_status_response():
    project = FakeProject(statuses={"job-1": ["not", "a", "dict"]})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="invalid render-job status"):
        adapter.cancel_render("job-1")


def test_cancel_render_rejects_missing_job_status():
    project = FakeProject(statuses={"job-1": {"CompletionPercentage": 0}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="JobStatus"):
        adapter.cancel_render("job-1")


def test_cancel_render_rejects_non_string_job_status():
    project = FakeProject(statuses={"job-1": {"JobStatus": 1}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="JobStatus"):
        adapter.cancel_render("job-1")


def test_cancel_render_ready_deletes_normalized_job_id():
    project = FakeProject(
        statuses={"job-1": {"JobStatus": "Ready"}},
        render_jobs=[{"JobId": "job-1"}],
    )
    adapter = connected_adapter(project)

    adapter.cancel_render("  job-1  ")

    project.DeleteRenderJob.assert_called_once_with("job-1")
    assert project.GetRenderJobStatus("job-1") is None


def test_cancel_render_ready_requires_delete_true():
    project = FakeProject(statuses={"job-1": {"JobStatus": "Ready"}}, delete_result=False)
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="failed to delete"):
        adapter.cancel_render("job-1")


def test_cancel_render_ready_requires_deleted_job_to_be_absent():
    project = FakeProject(statuses={"job-1": {"JobStatus": "Ready"}}, delete_result="ok")
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="failed to delete"):
        adapter.cancel_render("job-1")


def test_cancel_render_ready_rejects_job_still_present_after_deletion():
    project = FakeProject(statuses={"job-1": {"JobStatus": "Ready"}}, delete_result=True)
    project.DeleteRenderJob.side_effect = lambda job_id: True
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="remained available"):
        adapter.cancel_render("job-1")


def test_cancel_render_rendering_requires_render_in_progress():
    project = FakeProject(
        statuses={"job-1": {"JobStatus": "Rendering"}},
        render_jobs=[{"JobId": "job-1"}],
        rendering_in_progress=False,
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="no render is currently active"):
        adapter.cancel_render("job-1")

    project.StopRendering.assert_not_called()


def test_cancel_render_rendering_verifies_requested_id_is_active():
    project = FakeProject(
        statuses={"job-1": {"JobStatus": "Rendering"}},
        render_jobs=[{"JobId": "job-1"}],
        rendering_in_progress=[True, False],
    )
    adapter = connected_adapter(project)

    adapter.cancel_render("job-1")

    project.StopRendering.assert_called_once_with()
    project.DeleteRenderJob.assert_not_called()
    assert project.statuses["job-1"]["JobStatus"] == "Cancelled"


def test_cancel_render_rendering_accepts_stop_rendering_none_return():
    project = FakeProject(
        statuses={"job-1": {"JobStatus": "Rendering"}},
        render_jobs=[{"JobId": "job-1"}],
        rendering_in_progress=[True, False],
    )
    adapter = connected_adapter(project)

    adapter.cancel_render("job-1")

    assert project.stop_returns == [None]


def test_cancel_render_rendering_rejects_wrong_active_job():
    project = FakeProject(
        statuses={
            "job-1": {"JobStatus": "Rendering"},
            "job-2": {"JobStatus": "Rendering"},
        },
        render_jobs=[{"JobId": "job-2"}],
        rendering_in_progress=True,
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="could not be identified safely"):
        adapter.cancel_render("job-1")

    project.StopRendering.assert_not_called()


def test_cancel_render_rendering_rejects_multiple_active_jobs():
    project = FakeProject(
        statuses={
            "job-1": {"JobStatus": "Rendering"},
            "job-2": {"JobStatus": "Rendering"},
        },
        render_jobs=[{"JobId": "job-1"}, {"JobId": "job-2"}],
        rendering_in_progress=True,
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="could not be identified safely"):
        adapter.cancel_render("job-1")

    project.StopRendering.assert_not_called()


def test_cancel_render_rendering_rejects_invalid_render_job_list():
    project = FakeProject(statuses={"job-1": {"JobStatus": "Rendering"}}, rendering_in_progress=True)
    project.GetRenderJobList = Mock(return_value=False)
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="invalid render job list"):
        adapter.cancel_render("job-1")


def test_cancel_render_rendering_wraps_render_job_list_exception():
    original = RuntimeError("list failed")
    project = FakeProject(
        statuses={"job-1": {"JobStatus": "Rendering"}},
        rendering_in_progress=True,
        list_error=original,
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError) as exc_info:
        adapter.cancel_render("job-1")

    assert exc_info.value.__cause__ is original


def test_cancel_render_rendering_requires_stopped_postcondition():
    project = FakeProject(
        statuses={"job-1": {"JobStatus": "Rendering"}},
        render_jobs=[{"JobId": "job-1"}],
        rendering_in_progress=True,
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="did not stop"):
        adapter.cancel_render("job-1")


def test_cancel_render_rendering_requires_cancelled_status_postcondition():
    project = FakeProject(
        statuses={"job-1": {"JobStatus": "Rendering"}},
        render_jobs=[{"JobId": "job-1"}],
        rendering_in_progress=[True, False],
    )
    project.StopRendering.side_effect = lambda: None
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="did not transition"):
        adapter.cancel_render("job-1")


@pytest.mark.parametrize("terminal_status", ["Complete", "Failed", "Cancelled", "Canceled"])
def test_cancel_render_rejects_terminal_statuses(terminal_status):
    project = FakeProject(statuses={"job-1": {"JobStatus": terminal_status}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="terminal status"):
        adapter.cancel_render("job-1")

    project.DeleteRenderJob.assert_not_called()
    project.StopRendering.assert_not_called()


def test_cancel_render_rejects_unknown_valid_status():
    project = FakeProject(statuses={"job-1": {"JobStatus": "Waiting"}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="unsupported status"):
        adapter.cancel_render("job-1")


def test_cancel_render_wraps_unexpected_resolve_api_exception():
    original = RuntimeError("Resolve API changed")
    project = FakeProject(statuses={"job-1": {"JobStatus": "Ready"}}, status_error=original)
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError) as exc_info:
        adapter.cancel_render("job-1")

    assert exc_info.value.__cause__ is original
