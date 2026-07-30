"""Transport-neutral build-to-render composition workflow."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from redline_core.build import BuildOrchestrator, BuildResult
from redline_core.db.models import RenderJob
from redline_core.render.manager import RenderManager


@dataclass(frozen=True, slots=True)
class BuildRenderResult:
    """Successful build result paired with the render job queued from it."""

    build: BuildResult
    render: RenderJob


class BuildRenderWorkflow:
    """Sequence a successful build into a render queue request without owning policy."""

    def __init__(
        self,
        *,
        build_orchestrator: BuildOrchestrator,
        render_manager: RenderManager,
    ) -> None:
        self.build_orchestrator = build_orchestrator
        self.render_manager = render_manager

    def run(
        self,
        target: str,
        *,
        working_directory: Path | str,
        preset_name: str,
        manifest_path: Path | str | None = None,
        allow_unsafe_retry: bool = False,
    ) -> BuildRenderResult:
        """Build through assembly, then queue one render for the built episode."""
        build_result = self.build_orchestrator.build(
            target,
            working_directory=working_directory,
            manifest_path=manifest_path,
            allow_unsafe_retry=allow_unsafe_retry,
        )

        render_job = self.render_manager.queue_render(
            build_result.target.episode_id,
            preset_name,
        )

        return BuildRenderResult(build=build_result, render=render_job)
