"""Tests for the transport-neutral build-to-render workflow."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from redline_core.build import BuildResult, BuildStage, BuildTarget, BuildTargetError
from redline_core.db.models import EpisodeStatus, RenderJob, RenderJobStatus
from redline_core.render.exceptions import RenderPresetNotFoundError
from redline_core.workflows import BuildRenderResult, BuildRenderWorkflow


def build_result(*, episode_id: str = "RLC-E001") -> BuildResult:
    return BuildResult(
        target=BuildTarget(
            original_target="Episode_0001",
            episode_number=1,
            episode_id=episode_id,
        ),
        manifest_path=Path("C:/work/Episode_0001.yaml"),
        completed_stages=(BuildStage.EPISODE_ASSEMBLED,),
        final_state=EpisodeStatus.ASSEMBLED,
        project_name="RLC-E001_MASTER",
        timeline_name="RLC-E001_TIMELINE",
        media_count=2,
        markers_applied=3,
        clips_placed=2,
        warnings=(),
        episode_created=True,
    )


def render_job() -> RenderJob:
    return RenderJob(
        id=7,
        episode_id="RLC-E001",
        preset_name="broadcast_master",
        resolve_job_id="resolve-job-7",
        status=RenderJobStatus.QUEUED,
        output_path="C:/work/RLC-E001/exports",
    )


class FakeBuildOrchestrator:
    def __init__(self, calls: list[str], result_or_error):
        self.calls = calls
        self.result_or_error = result_or_error
        self.build_calls: list[dict] = []

    def build(
        self,
        target: str,
        *,
        working_directory: Path | str,
        manifest_path: Path | str | None = None,
        allow_unsafe_retry: bool = False,
    ) -> BuildResult:
        self.calls.append("build")
        self.build_calls.append(
            {
                "target": target,
                "working_directory": working_directory,
                "manifest_path": manifest_path,
                "allow_unsafe_retry": allow_unsafe_retry,
            }
        )
        if isinstance(self.result_or_error, Exception):
            raise self.result_or_error
        return self.result_or_error


class FakeRenderManager:
    def __init__(self, calls: list[str], result_or_error):
        self.calls = calls
        self.result_or_error = result_or_error
        self.queue_calls: list[dict] = []
        self.status_calls: list[object] = []
        self.list_calls: list[object] = []
        self.cancel_calls: list[object] = []

    def queue_render(self, episode_id: str, preset_name: str) -> RenderJob:
        self.calls.append("queue_render")
        self.queue_calls.append({"episode_id": episode_id, "preset_name": preset_name})
        if isinstance(self.result_or_error, Exception):
            raise self.result_or_error
        return self.result_or_error

    def get_render_status(self, job_id: int):  # pragma: no cover - should never be called
        self.status_calls.append(job_id)
        raise AssertionError("BuildRenderWorkflow must not poll render status.")

    def list_render_jobs_for_episode(self, episode_id: str):  # pragma: no cover - should never be called
        self.list_calls.append(episode_id)
        raise AssertionError("BuildRenderWorkflow must not list render jobs.")

    def cancel_render(self, job_id: int):  # pragma: no cover - should never be called
        self.cancel_calls.append(job_id)
        raise AssertionError("BuildRenderWorkflow must not cancel render jobs.")


def make_workflow(*, build_result_or_error=None, render_result_or_error=None):
    calls: list[str] = []
    build = FakeBuildOrchestrator(calls, build_result_or_error if build_result_or_error is not None else build_result())
    render = FakeRenderManager(calls, render_result_or_error if render_result_or_error is not None else render_job())
    workflow = BuildRenderWorkflow(build_orchestrator=build, render_manager=render)
    return workflow, build, render, calls


def test_successful_composition_calls_build_then_render_once():
    workflow, build, render, calls = make_workflow()
    manifest_path = Path("manifests/custom.yaml")

    result = workflow.run(
        "Episode_0001",
        working_directory=Path("C:/work"),
        manifest_path=manifest_path,
        preset_name="broadcast_master",
        allow_unsafe_retry=True,
    )

    assert calls == ["build", "queue_render"]
    assert build.build_calls == [
        {
            "target": "Episode_0001",
            "working_directory": Path("C:/work"),
            "manifest_path": manifest_path,
            "allow_unsafe_retry": True,
        }
    ]
    assert render.queue_calls == [{"episode_id": "RLC-E001", "preset_name": "broadcast_master"}]
    assert result == BuildRenderResult(build=build.result_or_error, render=render.result_or_error)


def test_render_episode_id_comes_from_build_result_not_target():
    workflow, _, render, _ = make_workflow(build_result_or_error=build_result(episode_id="RLC-E777"))

    workflow.run("Episode_0001", working_directory=Path("C:/work"), preset_name="broadcast_master")

    assert render.queue_calls == [{"episode_id": "RLC-E777", "preset_name": "broadcast_master"}]


def test_preset_name_is_passed_through_unchanged():
    workflow, _, render, _ = make_workflow()

    workflow.run("Episode_0001", working_directory=Path("C:/work"), preset_name="delivery_master")

    assert render.queue_calls[0]["preset_name"] == "delivery_master"


def test_build_failure_prevents_render_and_preserves_exception():
    failure = BuildTargetError("bad target")
    workflow, build, render, calls = make_workflow(build_result_or_error=failure)

    with pytest.raises(BuildTargetError, match="bad target"):
        workflow.run("bad", working_directory=Path("C:/work"), preset_name="broadcast_master")

    assert calls == ["build"]
    assert len(build.build_calls) == 1
    assert render.queue_calls == []
    assert render.status_calls == []
    assert render.list_calls == []
    assert render.cancel_calls == []


def test_render_failure_does_not_retry_or_repair_successful_build():
    failure = RenderPresetNotFoundError("missing preset")
    workflow, build, render, calls = make_workflow(render_result_or_error=failure)

    with pytest.raises(RenderPresetNotFoundError, match="missing preset"):
        workflow.run("Episode_0001", working_directory=Path("C:/work"), preset_name="missing")

    assert calls == ["build", "queue_render"]
    assert len(build.build_calls) == 1
    assert render.queue_calls == [{"episode_id": "RLC-E001", "preset_name": "missing"}]
    assert render.status_calls == []
    assert render.list_calls == []
    assert render.cancel_calls == []


def test_combined_result_is_immutable():
    workflow, _, _, _ = make_workflow()

    result = workflow.run("Episode_0001", working_directory=Path("C:/work"), preset_name="broadcast_master")

    with pytest.raises(FrozenInstanceError):
        result.render = render_job()
