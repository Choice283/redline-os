import pytest

from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.exceptions import RenderJobError, ResolveConnectionError


class FakeProject:
    def __init__(self, status_result: object, status_error: Exception | None = None) -> None:
        self.status_result = status_result
        self.status_error = status_error
        self.status_calls: list[str] = []

    def GetRenderJobStatus(self, job_id: str) -> object:
        self.status_calls.append(job_id)
        if self.status_error is not None:
            raise self.status_error
        return self.status_result


class FakeProjectManager:
    def __init__(self, project: object = None) -> None:
        self.project = project
        self.current_project_calls = 0

    def GetCurrentProject(self) -> object:
        self.current_project_calls += 1
        return self.project


class FakeResolve:
    def __init__(self, project_manager: object = None) -> None:
        self.project_manager = project_manager
        self.project_manager_calls = 0

    def GetProjectManager(self) -> object:
        self.project_manager_calls += 1
        return self.project_manager


_DEFAULT_PROJECT_MANAGER = object()


def connected_adapter(project: object = None, project_manager: object = _DEFAULT_PROJECT_MANAGER):
    adapter = ResolveScriptAdapter()
    if project_manager is _DEFAULT_PROJECT_MANAGER:
        project_manager = FakeProjectManager(project)
    adapter._project_manager = project_manager
    adapter._resolve = FakeResolve(project_manager)
    return adapter, project_manager


def test_get_render_status_requires_connection():
    adapter = ResolveScriptAdapter()

    with pytest.raises(ResolveConnectionError):
        adapter.get_render_status("job-1")


def test_get_render_status_rejects_empty_job_id():
    project = FakeProject({"JobStatus": "Ready"})
    adapter, project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-empty"):
        adapter.get_render_status("")

    assert project_manager.current_project_calls == 0
    assert project.status_calls == []


def test_get_render_status_rejects_whitespace_job_id():
    project = FakeProject({"JobStatus": "Ready"})
    adapter, project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-empty"):
        adapter.get_render_status("   ")

    assert project_manager.current_project_calls == 0
    assert project.status_calls == []


def test_get_render_status_rejects_non_string_job_id():
    project = FakeProject({"JobStatus": "Ready"})
    adapter, project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-empty"):
        adapter.get_render_status(42)

    assert project_manager.current_project_calls == 0
    assert project.status_calls == []


def test_get_render_status_fails_when_project_manager_is_unavailable():
    adapter = ResolveScriptAdapter()
    adapter._project_manager = object()
    adapter._resolve = FakeResolve(None)

    with pytest.raises(RenderJobError, match="project manager"):
        adapter.get_render_status("job-1")


def test_get_render_status_fails_when_no_project_is_loaded():
    adapter, project_manager = connected_adapter(project=None)

    with pytest.raises(RenderJobError, match="no Resolve project"):
        adapter.get_render_status("job-1")

    assert project_manager.current_project_calls == 1


def test_get_render_status_returns_unknown_for_missing_job():
    project = FakeProject(None)
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "unknown"
    assert project.status_calls == ["job-1"]


@pytest.mark.parametrize(
    ("resolve_status", "redline_status"),
    [
        ("Ready", "queued"),
        ("Rendering", "rendering"),
        ("Complete", "complete"),
        ("Failed", "failed"),
        ("Cancelled", "cancelled"),
        ("Canceled", "cancelled"),
    ],
)
def test_get_render_status_maps_known_statuses(resolve_status, redline_status):
    project = FakeProject({"JobStatus": resolve_status, "CompletionPercentage": 0})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == redline_status


def test_get_render_status_maps_ready_to_queued():
    project = FakeProject({"JobStatus": "Ready"})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "queued"


def test_get_render_status_maps_rendering():
    project = FakeProject({"JobStatus": "Rendering"})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "rendering"


def test_get_render_status_maps_complete():
    project = FakeProject({"JobStatus": "Complete"})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "complete"


def test_get_render_status_maps_failed():
    project = FakeProject({"JobStatus": "Failed"})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "failed"


def test_get_render_status_maps_cancelled():
    project = FakeProject({"JobStatus": "Cancelled"})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "cancelled"


def test_get_render_status_maps_us_canceled_spelling():
    project = FakeProject({"JobStatus": "Canceled"})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "cancelled"


def test_get_render_status_is_case_insensitive():
    project = FakeProject({"JobStatus": "rEaDy"})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "queued"


def test_get_render_status_trims_status_whitespace():
    project = FakeProject({"JobStatus": "  Ready  "})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "queued"


def test_get_render_status_trims_job_id_before_querying_resolve():
    project = FakeProject({"JobStatus": "Ready"})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("  job-1  ") == "queued"
    assert project.status_calls == ["job-1"]


def test_get_render_status_returns_unknown_for_unrecognized_status():
    project = FakeProject({"JobStatus": "Waiting"})
    adapter, _project_manager = connected_adapter(project)

    assert adapter.get_render_status("job-1") == "unknown"


def test_get_render_status_rejects_non_dict_response():
    project = FakeProject(["not", "a", "dict"])
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="invalid render-job status"):
        adapter.get_render_status("job-1")


def test_get_render_status_rejects_missing_job_status():
    project = FakeProject({"CompletionPercentage": 0})
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="JobStatus"):
        adapter.get_render_status("job-1")


def test_get_render_status_rejects_empty_job_status():
    project = FakeProject({"JobStatus": "   "})
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="JobStatus"):
        adapter.get_render_status("job-1")


def test_get_render_status_rejects_non_string_job_status():
    project = FakeProject({"JobStatus": 1})
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="JobStatus"):
        adapter.get_render_status("job-1")


def test_get_render_status_wraps_resolve_api_exception():
    original = RuntimeError("Resolve API changed")
    project = FakeProject({"JobStatus": "Ready"}, status_error=original)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError) as exc_info:
        adapter.get_render_status("job-1")

    assert exc_info.value.__cause__ is original
