"""Tests for the CLI's `redline render` command family.

Mission 35 keeps this as transport coverage only: argument parsing,
RenderManager invocation, output formatting, known failure mapping, and build
independence. Render-domain policy remains covered by RenderManager and
Resolve adapter tests.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from redline_core.build import BuildResult, BuildStage, BuildTarget
from redline_core.db.models import EpisodeStatus, RenderJob, RenderJobStatus
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.render.exceptions import RenderJobNotFoundError, RenderPresetNotFoundError
from redline_core.resolve.exceptions import RenderJobError

from cli import build_commands, render_commands
from cli import main as cli_main
from cli.main import _build_parser


def _yaml_path(path: Path) -> str:
    return path.resolve().as_posix()


def write_build_preflight_fixture(root: Path, episode_id: str = "RLC-E001") -> Path:
    config_dir = root / "config"
    ingest = root / "_ingest"
    for path in (config_dir, ingest, root / "_assets", root / "_archive", root / "_episodes"):
        path.mkdir(parents=True, exist_ok=True)

    (config_dir / "naming.yaml").write_text(
        "episode_id_pattern: 'RLC-E{episode_number:03d}'\n"
        "project_name_pattern: '{episode_id}_MASTER'\n",
        encoding="utf-8",
    )
    (config_dir / "folder_structure.yaml").write_text(
        f"root_path: '{_yaml_path(root / '_episodes')}'\n",
        encoding="utf-8",
    )
    (config_dir / "render_presets.yaml").write_text("presets: []\n", encoding="utf-8")
    (config_dir / "paths.yaml").write_text(
        f"ingest_path: '{_yaml_path(ingest)}'\n"
        f"archive_path: '{_yaml_path(root / '_archive')}'\n"
        f"assets_path: '{_yaml_path(root / '_assets')}'\n"
        "master_project_template: RLC_MASTER_TEMPLATE\n",
        encoding="utf-8",
    )
    (config_dir / "assets.yaml").write_text("assets: []\nrequired_for_episode: []\n", encoding="utf-8")
    (config_dir / "timeline_template.yaml").write_text(
        "timeline_name_pattern: '{episode_id}_TIMELINE'\nmarkers: []\n",
        encoding="utf-8",
    )

    media_file = ingest / "clip.wav"
    media_file.write_bytes(b"x")
    (root / "Episode_0001.yaml").write_text(
        "schema_version: 1\n"
        "episode:\n"
        f"  id: {episode_id}\n"
        "assembly:\n"
        "  media:\n"
        f"    - path: {_yaml_path(media_file)}\n",
        encoding="utf-8",
    )
    return config_dir


def render_job(
    *,
    job_id: int = 7,
    episode_id: str = "RLC-E001",
    preset_name: str = "broadcast_master",
    resolve_job_id: str | None = "resolve-job-7",
    status: RenderJobStatus = RenderJobStatus.QUEUED,
    output_path: str | None = "C:/work/RLC-E001/exports",
) -> RenderJob:
    return RenderJob(
        id=job_id,
        episode_id=episode_id,
        preset_name=preset_name,
        resolve_job_id=resolve_job_id,
        status=status,
        output_path=output_path,
        created_at="2026-07-30 10:00:00",
        updated_at="2026-07-30 10:01:00",
    )


class FakeRenderManager:
    def __init__(self):
        self.queue_result = render_job()
        self.status_result = render_job(status=RenderJobStatus.RENDERING)
        self.list_result = [render_job(job_id=2), render_job(job_id=3, status=RenderJobStatus.COMPLETE)]
        self.cancel_result = render_job(status=RenderJobStatus.CANCELLED)
        self.calls: list[dict] = []

    def queue_render(self, episode_id: str, preset_name: str) -> RenderJob:
        self.calls.append({"method": "queue_render", "episode_id": episode_id, "preset_name": preset_name})
        if isinstance(self.queue_result, Exception):
            raise self.queue_result
        return self.queue_result

    def get_render_status(self, job_id: int) -> RenderJob:
        self.calls.append({"method": "get_render_status", "job_id": job_id})
        if isinstance(self.status_result, Exception):
            raise self.status_result
        return self.status_result

    def list_render_jobs_for_episode(self, episode_id: str) -> list[RenderJob]:
        self.calls.append({"method": "list_render_jobs_for_episode", "episode_id": episode_id})
        return self.list_result

    def cancel_render(self, job_id: int) -> RenderJob:
        self.calls.append({"method": "cancel_render", "job_id": job_id})
        if isinstance(self.cancel_result, Exception):
            raise self.cancel_result
        return self.cancel_result


def services_with(manager: FakeRenderManager):
    return SimpleNamespace(render_manager=manager)


def test_parser_registers_render_resource_and_subcommands():
    parser = _build_parser()

    assert parser.parse_args(["render", "queue", "RLC-E001", "broadcast_master"]).action == "queue"
    assert parser.parse_args(["render", "status", "7"]).action == "status"
    assert parser.parse_args(["render", "list", "RLC-E001"]).action == "list"
    assert parser.parse_args(["render", "cancel", "7"]).action == "cancel"


def test_parser_render_status_and_cancel_require_integer_job_ids():
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["render", "status", "not-an-int"])
    with pytest.raises(SystemExit):
        parser.parse_args(["render", "cancel", "not-an-int"])


def test_render_queue_invokes_manager_once_with_unchanged_inputs():
    manager = FakeRenderManager()

    result = render_commands._run_render_queue(services_with(manager), "RLC-E001", "broadcast_master")

    assert result["success"] is True
    assert manager.calls == [
        {"method": "queue_render", "episode_id": "RLC-E001", "preset_name": "broadcast_master"}
    ]


def test_render_queue_output_is_queued_not_complete_and_excludes_build_archive(capsys):
    result = {"success": True, "job": render_commands._job_to_dict(render_job())}

    render_commands._print_render_queue_result(result)

    out = capsys.readouterr().out
    assert "Render queued" in out
    assert "Render complete" not in out
    assert "Job ID: 7" in out
    assert "Episode ID: RLC-E001" in out
    assert "Preset: broadcast_master" in out
    assert "Resolve Job ID: resolve-job-7" in out
    assert "Status: queued" in out
    assert "Output path: C:/work/RLC-E001/exports" in out
    assert "Created: 2026-07-30 10:00:00" in out
    assert "Last updated: 2026-07-30 10:01:00" in out
    assert "Build was not performed." in out
    assert "Archive was not performed." in out


def test_render_status_invokes_manager_once_without_poll_loop():
    manager = FakeRenderManager()

    result = render_commands._run_render_status(services_with(manager), 7)

    assert result["success"] is True
    assert manager.calls == [{"method": "get_render_status", "job_id": 7}]


def test_render_status_output_uses_returned_fields_only(capsys):
    result = {"success": True, "job": render_commands._job_to_dict(render_job(status=RenderJobStatus.RENDERING))}

    render_commands._print_render_status_result(result)

    out = capsys.readouterr().out
    assert "Render Status" in out
    assert "Job ID: 7" in out
    assert "Status: rendering" in out
    assert "Progress:" not in out


def test_render_list_invokes_manager_once_and_preserves_order():
    manager = FakeRenderManager()

    result = render_commands._run_render_list(services_with(manager), "RLC-E001")

    assert result["success"] is True
    assert [job["id"] for job in result["jobs"]] == [2, 3]
    assert manager.calls == [{"method": "list_render_jobs_for_episode", "episode_id": "RLC-E001"}]


def test_render_list_output_is_stable_for_zero_jobs(capsys):
    render_commands._print_render_list_result({"success": True, "episode_id": "RLC-E001", "jobs": []})

    out = capsys.readouterr().out
    assert "Episode ID: RLC-E001" in out
    assert "No render jobs found." in out


def test_render_list_output_preserves_returned_order(capsys):
    result = {
        "success": True,
        "episode_id": "RLC-E001",
        "jobs": [
            render_commands._job_to_dict(render_job(job_id=9)),
            render_commands._job_to_dict(render_job(job_id=4, status=RenderJobStatus.COMPLETE)),
        ],
    }

    render_commands._print_render_list_result(result)

    out = capsys.readouterr().out
    assert out.index("Job ID: 9") < out.index("Job ID: 4")
    assert "2 render job(s)." in out


def test_render_cancel_invokes_manager_once_with_job_id_only():
    manager = FakeRenderManager()

    result = render_commands._run_render_cancel(services_with(manager), 7)

    assert result["success"] is True
    assert manager.calls == [{"method": "cancel_render", "job_id": 7}]


def test_render_cancel_output_does_not_claim_cleanup_or_archive(capsys):
    result = {"success": True, "job": render_commands._job_to_dict(render_job(status=RenderJobStatus.CANCELLED))}

    render_commands._print_render_cancel_result(result)

    out = capsys.readouterr().out
    assert "Render cancelled" in out
    assert "Status: cancelled" in out
    assert "Build was not performed." in out
    assert "Archive was not performed." in out
    assert "deleted" not in out.casefold()
    assert "rollback" not in out.casefold()


@pytest.mark.parametrize(
    ("method_name", "result_attr", "error", "category"),
    [
        ("_run_render_queue", "queue_result", EpisodeNotFoundError("missing episode"), "episode not found"),
        ("_run_render_queue", "queue_result", RenderPresetNotFoundError("missing preset"), "render preset not found"),
        ("_run_render_queue", "queue_result", RenderJobError("Resolve failed"), "render queue failed"),
        ("_run_render_status", "status_result", RenderJobNotFoundError("missing job"), "render job not found"),
        ("_run_render_status", "status_result", RenderJobError("Resolve failed"), "render status failed"),
        ("_run_render_cancel", "cancel_result", RenderJobNotFoundError("missing job"), "render job not found"),
        ("_run_render_cancel", "cancel_result", RenderJobError("Resolve failed"), "render cancel failed"),
    ],
)
def test_render_known_failures_map_to_exit_one_without_retry(method_name, result_attr, error, category):
    manager = FakeRenderManager()
    setattr(manager, result_attr, error)
    method = getattr(render_commands, method_name)

    if method_name == "_run_render_queue":
        result = method(services_with(manager), "RLC-E001", "broadcast_master")
    else:
        result = method(services_with(manager), 7)

    assert result["success"] is False
    assert result["category"] == category
    assert result["exit_code"] == 1
    assert len(manager.calls) == 1


def test_render_failure_output_uses_error_stream(capsys):
    render_commands._print_render_status_result(
        {
            "success": False,
            "category": "render job not found",
            "error": "missing job",
            "exit_code": 1,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Render status failed (render job not found): missing job" in captured.err


def test_render_run_dispatches_each_action():
    manager = FakeRenderManager()
    parser = _build_parser()

    assert render_commands.run(parser.parse_args(["render", "queue", "RLC-E001", "broadcast_master"]), services_with(manager)) == 0
    assert render_commands.run(parser.parse_args(["render", "status", "7"]), services_with(manager)) == 0
    assert render_commands.run(parser.parse_args(["render", "list", "RLC-E001"]), services_with(manager)) == 0
    assert render_commands.run(parser.parse_args(["render", "cancel", "7"]), services_with(manager)) == 0

    assert [call["method"] for call in manager.calls] == [
        "queue_render",
        "get_render_status",
        "list_render_jobs_for_episode",
        "cancel_render",
    ]


def test_render_run_ignores_other_resources():
    args = SimpleNamespace(resource="asset", action="list")

    assert render_commands.run(args, services_with(FakeRenderManager())) is None


def test_main_render_dispatches_application_services_once(monkeypatch, capsys):
    manager = FakeRenderManager()
    service_calls: list[object] = []

    def fake_services(*, resolve_adapter=None):
        service_calls.append(resolve_adapter)
        return services_with(manager)

    monkeypatch.setattr(cli_main, "build_application_services", fake_services)

    exit_code = cli_main.main(["render", "queue", "RLC-E001", "broadcast_master"])

    assert exit_code == 0
    assert service_calls == [None]
    assert manager.calls == [
        {"method": "queue_render", "episode_id": "RLC-E001", "preset_name": "broadcast_master"}
    ]
    assert "Render queued" in capsys.readouterr().out


def test_main_render_with_mock_resolve_passes_mock_adapter(monkeypatch):
    manager = FakeRenderManager()
    service_calls: list[object] = []

    def fake_services(*, resolve_adapter=None):
        service_calls.append(resolve_adapter)
        return services_with(manager)

    monkeypatch.setattr(cli_main, "build_application_services", fake_services)

    assert cli_main.main(["--mock-resolve", "render", "status", "7"]) == 0

    assert len(service_calls) == 1
    assert service_calls[0] is not None


def test_main_render_unexpected_failure_uses_existing_generic_guard(monkeypatch, capsys):
    manager = FakeRenderManager()
    manager.queue_result = RuntimeError("boom")
    monkeypatch.setattr(cli_main, "build_application_services", lambda *, resolve_adapter=None: services_with(manager))

    exit_code = cli_main.main(["render", "queue", "RLC-E001", "broadcast_master"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Error: boom" in captured.err


def test_main_build_remains_render_free(monkeypatch, tmp_path, capsys):
    fake_render = FakeRenderManager()
    services = SimpleNamespace(config=object(), episode_manager=object(), render_manager=fake_render)
    build_calls: list[dict] = []
    config_dir = write_build_preflight_fixture(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "redline.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    class FakeBuildOrchestrator:
        def __init__(self, *, config, episode_manager):
            self.config = config
            self.episode_manager = episode_manager

        def build_prepared(self, prepared_request, *, allow_unsafe_retry):
            build_calls.append(
                {
                    "target": prepared_request.target.original_target,
                    "manifest_path": prepared_request.manifest_resolution.path,
                    "allow_unsafe_retry": allow_unsafe_retry,
                }
            )
            return BuildResult(
                target=BuildTarget(
                    original_target="Episode_0001",
                    episode_number=1,
                    episode_id="RLC-E001",
                ),
                manifest_path=tmp_path / "Episode_0001.yaml",
                completed_stages=(BuildStage.EPISODE_ASSEMBLED,),
                final_state=EpisodeStatus.ASSEMBLED,
                project_name="RLC-E001_MASTER",
                timeline_name="RLC-E001_TIMELINE",
                media_count=1,
                markers_applied=1,
                clips_placed=1,
                warnings=(),
                episode_created=False,
            )

    monkeypatch.setattr(cli_main, "build_application_services", lambda *, resolve_adapter=None, config=None: services)
    monkeypatch.setattr(build_commands, "BuildOrchestrator", FakeBuildOrchestrator)
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["build", "Episode_0001"])

    assert exit_code == 0
    assert build_calls == [
        {
            "target": "Episode_0001",
            "manifest_path": (tmp_path / "Episode_0001.yaml").resolve(),
            "allow_unsafe_retry": False,
        }
    ]
    assert fake_render.calls == []
    assert "Render queued: no" in capsys.readouterr().out
