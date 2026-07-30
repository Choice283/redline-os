import pytest

from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.exceptions import ProjectNotFoundError, RenderJobError, ResolveConnectionError


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
    ):
        self.render_job_lists = list(render_job_lists or [[]])
        self.load_preset_result = load_preset_result
        self.load_preset_error = load_preset_error
        self.set_settings_result = set_settings_result
        self.set_settings_error = set_settings_error
        self.add_render_job_result = add_render_job_result
        self.add_render_job_error = add_render_job_error
        self.load_preset_calls = []
        self.set_settings_calls = []
        self.add_render_job_calls = 0
        self.render_job_list_calls = 0

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
        adapter.queue_render("project", "preset", "exports")


def test_queue_render_rejects_unknown_project():
    adapter, _project_manager = connected_adapter(project=False)

    with pytest.raises(ProjectNotFoundError):
        adapter.queue_render("missing", "preset", "exports")


def test_queue_render_rejects_empty_preset_name():
    project = FakeProject()
    adapter, project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-empty"):
        adapter.queue_render("project", "  ", "exports")

    assert project_manager.load_calls == []
    assert project.load_preset_calls == []


def test_queue_render_fails_when_preset_cannot_be_loaded():
    project = FakeProject(load_preset_result=False)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="load render preset"):
        adapter.queue_render("project", "missing-preset", "exports")

    assert project.load_preset_calls == ["missing-preset"]
    assert project.set_settings_calls == []
    assert project.add_render_job_calls == 0


def test_queue_render_fails_when_output_settings_cannot_be_applied():
    project = FakeProject(set_settings_result=False)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="output settings"):
        adapter.queue_render("project", "preset", "exports")

    assert project.set_settings_calls == [{"TargetDir": "exports"}]
    assert project.add_render_job_calls == 0


def test_queue_render_fails_when_add_render_job_fails():
    project = FakeProject(add_render_job_result=False)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="failed to add"):
        adapter.queue_render("project", "preset", "exports")

    assert project.add_render_job_calls == 1
    assert project.render_job_list_calls == 1


def test_queue_render_returns_direct_job_id():
    project = FakeProject(add_render_job_result="resolve-job-1")
    adapter, _project_manager = connected_adapter(project)

    job_id = adapter.queue_render("project", "preset", "exports")

    assert job_id == "resolve-job-1"
    assert project.load_preset_calls == ["preset"]
    assert project.set_settings_calls == [{"TargetDir": "exports"}]
    assert project.add_render_job_calls == 1
    assert project.render_job_list_calls == 1


def test_queue_render_returns_direct_integer_job_id():
    project = FakeProject(add_render_job_result=42)
    adapter, _project_manager = connected_adapter(project)

    assert adapter.queue_render("project", "preset", "exports") == "42"


def test_queue_render_derives_job_id_from_job_list():
    project = FakeProject(
        render_job_lists=[
            [{"JobId": "old-job"}],
            [{"JobId": "old-job"}, {"JobId": "new-job"}],
        ],
        add_render_job_result=True,
    )
    adapter, _project_manager = connected_adapter(project)

    assert adapter.queue_render("project", "preset", "exports") == "new-job"
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

    assert adapter.queue_render("project", "preset", "exports") == "new-job"


def test_queue_render_fails_when_job_id_is_missing():
    project = FakeProject(
        render_job_lists=[
            [],
            [{"RenderJobName": "unnamed"}],
        ],
        add_render_job_result=True,
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="no usable job ID"):
        adapter.queue_render("project", "preset", "exports")


def test_queue_render_fails_when_no_new_job_id_can_be_reconciled():
    project = FakeProject(
        render_job_lists=[
            [{"JobId": "old-job"}],
            [{"JobId": "old-job"}],
        ],
        add_render_job_result=True,
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="returned no usable job ID"):
        adapter.queue_render("project", "preset", "exports")


def test_queue_render_fails_when_job_id_is_ambiguous():
    project = FakeProject(
        render_job_lists=[
            [{"JobId": "old-job"}],
            [{"JobId": "old-job"}, {"JobId": "new-a"}, {"JobId": "new-b"}],
        ],
        add_render_job_result=True,
    )
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError, match="2 possible"):
        adapter.queue_render("project", "preset", "exports")


def test_queue_render_wraps_unexpected_resolve_errors():
    original = RuntimeError("Resolve API changed")
    project = FakeProject(load_preset_error=original)
    adapter, _project_manager = connected_adapter(project)

    with pytest.raises(RenderJobError) as exc_info:
        adapter.queue_render("project", "preset", "exports")

    assert exc_info.value.__cause__ is original


def test_queue_render_wraps_project_load_errors():
    original = RuntimeError("load failed")
    adapter, _project_manager = connected_adapter(load_error=original)

    with pytest.raises(RenderJobError) as exc_info:
        adapter.queue_render("project", "preset", "exports")

    assert exc_info.value.__cause__ is original
