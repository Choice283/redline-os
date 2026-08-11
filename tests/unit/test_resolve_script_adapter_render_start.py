from pathlib import Path
from unittest.mock import Mock

import pytest

from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.exceptions import (
    RenderJobError,
    RenderStartReconciliationRequiredError,
    ResolveConnectionError,
)

PROJECT_NAME = "RLC-E001_MASTER"
TIMELINE_NAME = "RLC-E001_TIMELINE"
JOB_ID = "job-1"
OUTPUT_PATH = r"C:\work\RLC-E001\exports\RLC-E001.mov"
EXPECTED_TARGET_DIR = str(Path(OUTPUT_PATH).parent)
# Rev4: Resolve's real GetRenderJobList() reports OutputFilename as the
# complete filename (extension included), not the extensionless stem --
# confirmed against live getter-only evidence captured from a real,
# running Resolve Studio 21.0.3.7 instance
# (RLC-E9901_render_queue_snapshot_rev3_20260810T233837Z.json, SHA-256
# f2afab5c4e2fb04821c928511341801e3ae6c232ed9fbbe70151c369710c8975:
# observed `"OutputFilename": "RLC-E9901_MASTER.mov"`, not
# `"RLC-E9901_MASTER"`). The fixtures below use the same shape.
EXPECTED_OUTPUT_FILENAME = Path(OUTPUT_PATH).name


def _default_render_job_list() -> list[dict]:
    return [
        {
            "JobId": JOB_ID,
            "ProjectName": PROJECT_NAME,
            "TimelineName": TIMELINE_NAME,
            "TargetDir": EXPECTED_TARGET_DIR,
            "OutputFilename": EXPECTED_OUTPUT_FILENAME,
        }
    ]


class FakeProject:
    """Fake for tests that only exercise the precondition path (rejected
    before StartRendering() is ever called), so GetRenderJobStatus() only
    ever needs to serve one fixed value per job ID. Tests that also need to
    exercise the postcondition-wait polling loop use
    `make_project_with_postcondition` instead, which installs its own
    sequenced GetRenderJobStatus() in place of this class's fixed one.
    """

    def __init__(
        self,
        *,
        project_name: object = PROJECT_NAME,
        get_name_error: Exception | None = None,
        render_job_list: object = "__default__",
        render_job_list_error: Exception | None = None,
        statuses: dict[str, object] | None = None,
        rendering_in_progress: object = False,
        start_result: object = True,
        start_error: Exception | None = None,
        status_error: Exception | None = None,
    ) -> None:
        self._project_name = project_name
        self._get_name_error = get_name_error
        self.GetName = Mock(side_effect=self._get_name)

        self._render_job_list = _default_render_job_list() if render_job_list == "__default__" else render_job_list
        self._render_job_list_error = render_job_list_error
        self.GetRenderJobList = Mock(side_effect=self._get_render_job_list)

        self.statuses = dict(statuses if statuses is not None else {JOB_ID: {"JobStatus": "Ready"}})
        self.status_error = status_error
        self.status_calls: list[str] = []
        self.GetRenderJobStatus = Mock(side_effect=self._get_render_job_status)

        self._rendering_in_progress = rendering_in_progress
        self.IsRenderingInProgress = Mock(side_effect=self._is_rendering_in_progress)

        self.start_result = start_result
        self.start_error = start_error
        self.StartRendering = Mock(side_effect=self._start_rendering)

        self.AddRenderJob = Mock(side_effect=AssertionError("AddRenderJob must never be called"))
        self.DeleteRenderJob = Mock(side_effect=AssertionError("DeleteRenderJob must never be called"))
        self.DeleteAllRenderJobs = Mock(side_effect=AssertionError("DeleteAllRenderJobs must never be called"))
        self.StopRendering = Mock(side_effect=AssertionError("StopRendering must never be called"))
        self.SetRenderSettings = Mock(side_effect=AssertionError("SetRenderSettings must never be called"))
        self.LoadRenderPreset = Mock(side_effect=AssertionError("LoadRenderPreset must never be called"))
        self.LoadProject = Mock(side_effect=AssertionError("LoadProject must never be called"))
        self.SetCurrentTimeline = Mock(side_effect=AssertionError("SetCurrentTimeline must never be called"))

    def _get_name(self) -> object:
        if self._get_name_error is not None:
            raise self._get_name_error
        return self._project_name

    def _get_render_job_list(self) -> object:
        if self._render_job_list_error is not None:
            raise self._render_job_list_error
        return self._render_job_list

    def _get_render_job_status(self, job_id: str) -> object:
        if self.status_error is not None:
            raise self.status_error
        self.status_calls.append(job_id)
        return self.statuses.get(job_id)

    def _is_rendering_in_progress(self) -> object:
        return self._rendering_in_progress

    def _start_rendering(self, job_ids, isInteractiveMode=False) -> object:
        if self.start_error is not None:
            raise self.start_error
        return self.start_result


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


def start(
    adapter,
    *,
    project_name=PROJECT_NAME,
    timeline_name=TIMELINE_NAME,
    resolve_job_id=JOB_ID,
    output_path=OUTPUT_PATH,
):
    return adapter.start_render(
        project_name=project_name,
        timeline_name=timeline_name,
        resolve_job_id=resolve_job_id,
        output_path=output_path,
    )


def make_project_with_postcondition(
    *,
    precondition_status: dict,
    postcondition_statuses: list[object],
    rendering_in_progress: object = False,
    start_result: object = True,
    start_error: Exception | None = None,
    render_job_list: object = "__default__",
    status_error_after_start: Exception | None = None,
) -> FakeProject:
    """Builds a FakeProject whose GetRenderJobStatus() returns
    `precondition_status` for every call up to and including the one made
    right before StartRendering(), then walks through
    `postcondition_statuses` in order (repeating the last entry) for every
    call made afterward -- modeling the postcondition-wait polling loop
    precisely. `status_error_after_start`, if set, is raised by every
    postcondition-phase call instead (models a getter exception during the
    poll, which _poll_for_rendering must tolerate as "not yet confirmed")."""

    project = FakeProject(
        statuses={JOB_ID: precondition_status},
        rendering_in_progress=rendering_in_progress,
        start_result=start_result,
        start_error=start_error,
        render_job_list=render_job_list,
    )
    remaining = list(postcondition_statuses)

    def _get_status(job_id: str) -> object:
        if project.status_error is not None:
            raise project.status_error
        if project.StartRendering.call_count > 0 and status_error_after_start is not None:
            project.status_calls.append(job_id)
            raise status_error_after_start
        project.status_calls.append(job_id)
        if project.StartRendering.call_count == 0:
            return precondition_status
        if remaining:
            return remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return precondition_status

    project.GetRenderJobStatus = Mock(side_effect=_get_status)
    return project


# --- connection / basic input validation ------------------------------------


def test_start_render_requires_connection():
    adapter = ResolveScriptAdapter()

    with pytest.raises(ResolveConnectionError):
        start(adapter)


@pytest.mark.parametrize("bad_value", ["", "   ", 42, None])
def test_start_render_rejects_invalid_project_name(bad_value):
    project = FakeProject()
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="Project name"):
        start(adapter, project_name=bad_value)

    project.GetName.assert_not_called()
    project.StartRendering.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   ", 42, None])
def test_start_render_rejects_invalid_timeline_name(bad_value):
    project = FakeProject()
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="Timeline name"):
        start(adapter, timeline_name=bad_value)

    project.GetName.assert_not_called()
    project.StartRendering.assert_not_called()


@pytest.mark.parametrize("bad_job_id", ["", "   ", 42])
def test_start_render_rejects_invalid_job_id(bad_job_id):
    project = FakeProject()
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-empty"):
        start(adapter, resolve_job_id=bad_job_id)

    project.GetName.assert_not_called()
    project.StartRendering.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   ", 42, None])
def test_start_render_rejects_invalid_output_path(bad_value):
    project = FakeProject()
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="Output path"):
        start(adapter, output_path=bad_value)

    project.GetName.assert_not_called()
    project.StartRendering.assert_not_called()


def test_start_render_fails_when_project_manager_is_unavailable():
    adapter = ResolveScriptAdapter()
    adapter._project_manager = object()
    adapter._resolve = FakeResolve(None)

    with pytest.raises(RenderJobError, match="project manager"):
        start(adapter)


def test_start_render_fails_when_no_project_is_loaded():
    adapter = connected_adapter(project=None)

    with pytest.raises(RenderJobError, match="no Resolve project"):
        start(adapter)


# --- Finding 1 (Rev2): current-project identity binding ----------------------


def test_start_render_rejects_wrong_current_project():
    project = FakeProject(project_name="SOME_OTHER_PROJECT")
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="current project is 'SOME_OTHER_PROJECT'"):
        start(adapter)

    project.GetRenderJobList.assert_not_called()
    project.GetRenderJobStatus.assert_not_called()
    project.StartRendering.assert_not_called()


@pytest.mark.parametrize("missing_name", [None, "", "   "])
def test_start_render_rejects_missing_current_project_name(missing_name):
    project = FakeProject(project_name=missing_name)
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="no usable name"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_rejects_malformed_current_project_name():
    project = FakeProject(project_name=12345)
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="no usable name"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_wraps_get_name_exception():
    original = RuntimeError("bridge error")
    project = FakeProject(get_name_error=original)
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError) as exc_info:
        start(adapter)

    assert exc_info.value.__cause__ is original
    project.StartRendering.assert_not_called()


def test_start_render_never_calls_load_project():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
    )
    adapter = connected_adapter(project)

    start(adapter)

    project.LoadProject.assert_not_called()


# --- Finding 1 (Rev3): strict Job-ID alias resolution -------------------------


def test_start_render_sole_canonical_job_id_passes():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "TargetDir": EXPECTED_TARGET_DIR,
                "OutputFilename": EXPECTED_OUTPUT_FILENAME,
            }
        ],
    )
    adapter = connected_adapter(project)

    start(adapter)  # must not raise

    project.StartRendering.assert_called_once()


def test_start_render_two_agreeing_job_id_aliases_pass():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
        render_job_list=[
            {
                "JobId": JOB_ID,
                "job_id": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "TargetDir": EXPECTED_TARGET_DIR,
                "OutputFilename": EXPECTED_OUTPUT_FILENAME,
            }
        ],
    )
    adapter = connected_adapter(project)

    start(adapter)  # must not raise

    project.StartRendering.assert_called_once()


def test_start_render_conflicting_job_id_aliases_fail_before_start_rendering():
    project = FakeProject(
        render_job_list=[
            {
                "JobId": JOB_ID,
                "job_id": "other-job",
                "TimelineName": TIMELINE_NAME,
                "TargetDir": EXPECTED_TARGET_DIR,
                "OutputFilename": EXPECTED_OUTPUT_FILENAME,
            }
        ]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="conflicting or malformed job-ID"):
        start(adapter)

    project.StartRendering.assert_not_called()


@pytest.mark.parametrize("malformed_id", [123, True, {"nested": "object"}, ["a", "list"]])
def test_start_render_malformed_job_id_alias_type_fails_before_start_rendering(malformed_id):
    project = FakeProject(render_job_list=[{"JobId": malformed_id, "TimelineName": TIMELINE_NAME}])
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="conflicting or malformed job-ID"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_duplicate_queue_entries_for_expected_id_fail():
    entry = {
        "JobId": JOB_ID,
        "TimelineName": TIMELINE_NAME,
        "TargetDir": EXPECTED_TARGET_DIR,
        "OutputFilename": EXPECTED_OUTPUT_FILENAME,
    }
    project = FakeProject(render_job_list=[dict(entry), dict(entry)])
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="2 entries matching job ID"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_unrelated_malformed_entry_elsewhere_in_queue_fails_closed():
    """A malformed entry that has no alias overlap with the requested job
    ID at all must still fail the whole lookup closed -- its true identity
    cannot be ruled out, so it can't be silently skipped while resolving a
    different, otherwise-clean entry."""
    project = FakeProject(
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "TargetDir": EXPECTED_TARGET_DIR,
                "OutputFilename": EXPECTED_OUTPUT_FILENAME,
            },
            {"JobId": "unrelated-job", "job_id": "totally-different"},
        ]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="conflicting or malformed job-ID"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_rejects_job_absent_from_current_project_queue():
    project = FakeProject(render_job_list=[])
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="not found in the current project's render queue"):
        start(adapter)

    project.GetRenderJobStatus.assert_not_called()
    project.StartRendering.assert_not_called()


def test_start_render_rejects_invalid_render_job_list_type():
    project = FakeProject(render_job_list="not-a-list")
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="invalid render job list"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_rejects_non_dict_queue_entry():
    project = FakeProject(render_job_list=["not-a-dict"])
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="non-record entry"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_wraps_get_render_job_list_exception():
    original = RuntimeError("bridge error")
    project = FakeProject(render_job_list_error=original)
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError) as exc_info:
        start(adapter)

    assert exc_info.value.__cause__ is original
    project.StartRendering.assert_not_called()


def test_start_render_never_calls_set_current_timeline():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
    )
    adapter = connected_adapter(project)

    start(adapter)

    project.SetCurrentTimeline.assert_not_called()


# --- Finding 2: strict timeline alias resolution ------------------------------


def test_start_render_two_agreeing_timeline_aliases_pass():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "timeline_name": TIMELINE_NAME,
                "TargetDir": EXPECTED_TARGET_DIR,
                "OutputFilename": EXPECTED_OUTPUT_FILENAME,
            }
        ],
    )
    adapter = connected_adapter(project)

    start(adapter)  # must not raise

    project.StartRendering.assert_called_once()


def test_start_render_conflicting_timeline_aliases_fail():
    project = FakeProject(
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "timeline_name": "SOME_OTHER_TIMELINE",
                "TargetDir": EXPECTED_TARGET_DIR,
                "OutputFilename": EXPECTED_OUTPUT_FILENAME,
            }
        ]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="conflicting or malformed timeline"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_rejects_missing_timeline_name_in_queue_entry():
    project = FakeProject(render_job_list=[{"JobId": JOB_ID}])
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="no usable timeline name"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_rejects_malformed_timeline_alias_type():
    project = FakeProject(render_job_list=[{"JobId": JOB_ID, "TimelineName": 999}])
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="conflicting or malformed timeline"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_rejects_wrong_timeline_name_in_queue_entry():
    project = FakeProject(render_job_list=[{"JobId": JOB_ID, "TimelineName": "SOME_OTHER_TIMELINE"}])
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="targets timeline 'SOME_OTHER_TIMELINE'"):
        start(adapter)

    project.StartRendering.assert_not_called()


# --- preserved precondition behavior: job status -----------------------------


def test_start_render_rejects_unknown_job():
    """The job is present in the queue-identity list (so identity binding
    passes) but GetRenderJobStatus() itself reports it unknown."""
    project = FakeProject(statuses={})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="not found"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_rejects_malformed_status_response():
    project = FakeProject(statuses={JOB_ID: ["not", "a", "dict"]})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="invalid render-job status"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_rejects_already_rendering_requested_job():
    project = FakeProject(statuses={JOB_ID: {"JobStatus": "Rendering"}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="already rendering"):
        start(adapter)

    project.StartRendering.assert_not_called()


@pytest.mark.parametrize("terminal_status", ["Complete", "Failed", "Cancelled", "Canceled"])
def test_start_render_rejects_terminal_statuses(terminal_status):
    project = FakeProject(statuses={JOB_ID: {"JobStatus": terminal_status}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="terminal status"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_rejects_unsupported_status():
    project = FakeProject(statuses={JOB_ID: {"JobStatus": "Waiting"}})
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="unsupported status"):
        start(adapter)

    project.StartRendering.assert_not_called()


# --- Finding 3: queued output-destination binding -----------------------------


def test_start_render_exact_queued_destination_passes():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
    )
    adapter = connected_adapter(project)

    start(adapter)  # must not raise

    project.StartRendering.assert_called_once()


def test_start_render_extension_bearing_output_filename_matches_and_starts():
    """Rev4 required regression: the real Resolve queue reports
    OutputFilename as the complete filename, extension included (live
    getter-only evidence: RLC-E9901_render_queue_snapshot_rev3_20260810T233837Z.json,
    SHA-256 f2afab5c4e2fb04821c928511341801e3ae6c232ed9fbbe70151c369710c8975,
    observed `"OutputFilename": "RLC-E9901_MASTER.mov"`). A queue entry
    using that exact shape against an expected `.mov` output path must
    pass identity verification and start exactly once."""
    expected_output_path = r"C:\work\RLC-E025\exports\RLC-E025_MASTER.mov"
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "TargetDir": str(Path(expected_output_path).parent),
                "OutputFilename": "RLC-E025_MASTER.mov",
            }
        ],
    )
    adapter = connected_adapter(project)

    start(adapter, output_path=expected_output_path)  # must not raise

    project.StartRendering.assert_called_once()


def test_start_render_extensionless_output_filename_fails_closed():
    """The inverse of the regression above: an extensionless (stem-only)
    OutputFilename -- what Rev3 incorrectly expected -- must fail closed
    against a `.mov` expected path, with zero StartRendering() calls."""
    expected_output_path = r"C:\work\RLC-E025\exports\RLC-E025_MASTER.mov"
    project = FakeProject(
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "TargetDir": str(Path(expected_output_path).parent),
                "OutputFilename": "RLC-E025_MASTER",
            }
        ]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="targets output filename"):
        start(adapter, output_path=expected_output_path)

    assert project.StartRendering.call_count == 0


def test_start_render_wrong_target_dir_fails():
    project = FakeProject(
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "TargetDir": r"C:\somewhere\else",
                "OutputFilename": EXPECTED_OUTPUT_FILENAME,
            }
        ]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="targets output directory"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_wrong_output_filename_fails():
    project = FakeProject(
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "TargetDir": EXPECTED_TARGET_DIR,
                "OutputFilename": "SOME_OTHER_NAME",
            }
        ]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="targets output filename"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_missing_target_dir_fails():
    project = FakeProject(
        render_job_list=[{"JobId": JOB_ID, "TimelineName": TIMELINE_NAME, "OutputFilename": EXPECTED_OUTPUT_FILENAME}]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="no usable TargetDir"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_missing_output_filename_fails():
    project = FakeProject(
        render_job_list=[{"JobId": JOB_ID, "TimelineName": TIMELINE_NAME, "TargetDir": EXPECTED_TARGET_DIR}]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="no usable OutputFilename"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_conflicting_output_aliases_fail():
    project = FakeProject(
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "TargetDir": EXPECTED_TARGET_DIR,
                "targetDir": r"C:\somewhere\else",
                "OutputFilename": EXPECTED_OUTPUT_FILENAME,
            }
        ]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="conflicting or malformed TargetDir"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_never_calls_set_render_settings_or_load_render_preset_on_output_mismatch():
    project = FakeProject(
        render_job_list=[
            {
                "JobId": JOB_ID,
                "TimelineName": TIMELINE_NAME,
                "TargetDir": r"C:\wrong",
                "OutputFilename": EXPECTED_OUTPUT_FILENAME,
            }
        ]
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError):
        start(adapter)

    project.SetRenderSettings.assert_not_called()
    project.LoadRenderPreset.assert_not_called()


# --- Finding 3 (Rev3): exact-False IsRenderingInProgress guard ---------------


@pytest.mark.parametrize("observed", [True, None, 0, 1, "False", "false", [], {}, object()])
def test_start_render_rejects_non_exact_false_rendering_in_progress(observed):
    project = FakeProject(rendering_in_progress=observed)
    adapter = connected_adapter(project)

    with pytest.raises(RenderJobError, match="exact rendering-in-progress state of False"):
        start(adapter)

    project.StartRendering.assert_not_called()


def test_start_render_proceeds_when_rendering_in_progress_is_exact_false():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
        rendering_in_progress=False,
    )
    adapter = connected_adapter(project)

    start(adapter)

    project.StartRendering.assert_called_once()


# --- success path -------------------------------------------------------------


def test_start_render_queued_job_starts_successfully():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
        rendering_in_progress=False,
    )
    adapter = connected_adapter(project)

    start(adapter, resolve_job_id="  job-1  ")

    project.StartRendering.assert_called_once_with(["job-1"], isInteractiveMode=False)


def test_start_render_passes_exact_requested_job_id():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
    )
    adapter = connected_adapter(project)

    start(adapter)

    called_args, called_kwargs = project.StartRendering.call_args
    assert called_args == ([JOB_ID],)
    assert called_kwargs == {"isInteractiveMode": False}


def test_start_render_calls_start_rendering_exactly_once():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
    )
    adapter = connected_adapter(project)

    start(adapter)

    assert project.StartRendering.call_count == 1


def test_start_render_never_calls_prohibited_mutation_methods():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
    )
    adapter = connected_adapter(project)

    start(adapter)

    project.AddRenderJob.assert_not_called()
    project.DeleteRenderJob.assert_not_called()
    project.DeleteAllRenderJobs.assert_not_called()
    project.StopRendering.assert_not_called()
    project.SetRenderSettings.assert_not_called()
    project.LoadRenderPreset.assert_not_called()
    project.LoadProject.assert_not_called()
    project.SetCurrentTimeline.assert_not_called()


def test_start_render_only_targets_the_requested_job_id_not_a_list_of_all_jobs():
    """Proves the job-ID-targeted StartRendering([job_id]) form is used --
    not the zero-argument 'start everything queued' form -- by asserting
    the exact single-element list passed."""
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
    )
    adapter = connected_adapter(project)

    start(adapter)

    args, kwargs = project.StartRendering.call_args
    assert len(args[0]) == 1
    assert args[0][0] == JOB_ID


def test_start_render_postcondition_tolerates_one_lagging_poll():
    """The first postcondition poll still shows 'Ready' (Resolve hasn't
    transitioned the status yet); the second shows 'Rendering'. No second
    StartRendering() call is made while waiting."""
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Ready"}, {"JobStatus": "Rendering"}],
    )
    adapter = connected_adapter(project)

    start(adapter)

    assert project.StartRendering.call_count == 1


# --- Finding 4 (Rev3): unified StartRendering() outcome reconciliation -------
# The documented contract is only `StartRendering(...) --> Bool`; no return
# value -- including an exact False -- is treated as sufficient proof by
# itself that no mutation occurred. True/False/exception/non-boolean are all
# resolved identically via the same getter-only reconciliation poll.


def test_start_render_false_result_confirmed_by_poll_succeeds():
    """Rev3 Finding 4's required adversarial regression: StartRendering()
    returns False, but GetRenderJobStatus() independently proves the job is
    Rendering -- the operation must succeed, not raise, and StartRendering
    must have been called exactly once."""
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
        rendering_in_progress=False,
        start_result=False,
    )
    adapter = connected_adapter(project)

    start(adapter)  # must not raise

    assert project.StartRendering.call_count == 1


def test_start_render_false_result_not_confirmed_raises_reconciliation_required():
    """Rev3 Finding 4's other required adversarial regression: StartRendering()
    returns False and Rendering can never be established -- this must raise
    RenderStartReconciliationRequiredError (never a plain, retry-implying
    RenderJobError), with exactly one StartRendering() call and no second
    attempt."""
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Ready"}],
        rendering_in_progress=False,
        start_result=False,
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderStartReconciliationRequiredError):
        start(adapter)

    assert project.StartRendering.call_count == 1


def test_start_render_true_result_never_confirmed_raises_reconciliation_required():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Ready"}],
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderStartReconciliationRequiredError):
        start(adapter)

    assert project.StartRendering.call_count == 1


def test_start_render_postcondition_none_response_raises_reconciliation_required():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[None],
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderStartReconciliationRequiredError):
        start(adapter)

    assert project.StartRendering.call_count == 1


def test_start_render_postcondition_getter_exception_raises_reconciliation_required():
    """A GetRenderJobStatus() exception during the postcondition poll must
    be tolerated as 'not yet confirmed' for that attempt, and an
    unconfirmed poll must still surface as reconciliation-required rather
    than propagating the raw getter exception."""
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Ready"}],
        status_error_after_start=RuntimeError("bridge error"),
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderStartReconciliationRequiredError):
        start(adapter)

    assert project.StartRendering.call_count == 1


def test_start_render_exception_confirmed_by_reconciliation_succeeds():
    """StartRendering() raising does not by itself prove no mutation
    occurred -- if the getter-only reconciliation poll independently
    confirms Rendering, start_render() must succeed rather than raise."""
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
        start_error=RuntimeError("Resolve API changed"),
    )
    adapter = connected_adapter(project)

    start(adapter)  # must not raise

    assert project.StartRendering.call_count == 1


def test_start_render_exception_not_confirmed_raises_reconciliation_required():
    original = RuntimeError("Resolve API changed")
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Ready"}],
        start_error=original,
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderStartReconciliationRequiredError) as exc_info:
        start(adapter)

    assert exc_info.value.__cause__ is original
    assert project.StartRendering.call_count == 1


def test_start_render_non_boolean_start_result_confirmed_by_poll_succeeds():
    """A Bool-contract-violating return value (neither True nor False) is
    ambiguous, not an automatic failure -- if the getter-only poll confirms
    Rendering, start_render() succeeds."""
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Rendering"}],
        start_result="yes",
    )
    adapter = connected_adapter(project)

    start(adapter)  # must not raise

    assert project.StartRendering.call_count == 1


def test_start_render_non_boolean_start_result_not_confirmed_raises_reconciliation_required():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Ready"}],
        start_result=None,
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderStartReconciliationRequiredError):
        start(adapter)

    assert project.StartRendering.call_count == 1


def test_start_render_never_retries_start_rendering_after_reconciliation_required():
    project = make_project_with_postcondition(
        precondition_status={"JobStatus": "Ready"},
        postcondition_statuses=[{"JobStatus": "Ready"}] * 10,
    )
    adapter = connected_adapter(project)

    with pytest.raises(RenderStartReconciliationRequiredError):
        start(adapter)

    assert project.StartRendering.call_count == 1
