"""Tests for the CLI's top-level `redline build` command.

Mission 34 keeps this as transport coverage only: argument parsing,
BuildOrchestrator invocation, output formatting, and known failure mapping.
Build-domain policy remains covered by the Phase 13 parser, resolver, and
orchestrator tests.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from redline_core.build import (
    BuildResult,
    BuildStage,
    BuildTarget,
    BuildTargetError,
    ManifestIdentityMismatchError,
    ManifestResolutionError,
)
from redline_core.db.models import EpisodeStatus
from redline_core.episode.exceptions import EpisodeBuildError
from redline_core.manifest import ManifestLoadError, ManifestValidationError
from redline_core.resolve.exceptions import ResolveConnectionError

from cli import build_commands
from cli import main as cli_main
from cli.main import _build_parser


def build_result(*, warnings: tuple[str, ...] = (), episode_created: bool = True) -> BuildResult:
    return BuildResult(
        target=BuildTarget(original_target="Episode_0001", episode_number=1, episode_id="RLC-E001"),
        manifest_path=Path("C:/work/Episode_0001.yaml"),
        completed_stages=(
            BuildStage.TARGET_PARSED,
            BuildStage.MANIFEST_RESOLVED,
            BuildStage.MANIFEST_LOADED,
            BuildStage.MANIFEST_VALIDATED,
            BuildStage.IDENTITY_CONFIRMED,
            BuildStage.EPISODE_RESOLVED,
            BuildStage.EPISODE_CREATED,
            BuildStage.EPISODE_ASSEMBLED,
        ),
        final_state=EpisodeStatus.ASSEMBLED,
        project_name="RLC-E001_MASTER",
        timeline_name="RLC-E001_TIMELINE",
        media_count=2,
        markers_applied=3,
        clips_placed=2,
        warnings=warnings,
        episode_created=episode_created,
    )


class FakeOrchestrator:
    def __init__(self, result_or_error):
        self.result_or_error = result_or_error
        self.calls: list[dict] = []

    def build(self, target: str, *, working_directory: Path, manifest_path, allow_unsafe_retry: bool):
        self.calls.append(
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


def test_parser_registers_build_command():
    parser = _build_parser()

    args = parser.parse_args(["build", "Episode_0001"])

    assert args.resource == "build"
    assert args.target == "Episode_0001"
    assert args.manifest_path is None
    assert args.force is False


def test_parser_build_accepts_manifest_and_force():
    parser = _build_parser()

    args = parser.parse_args(["build", "Episode_0001", "--manifest", "manifests/custom.yaml", "--force"])

    assert args.target == "Episode_0001"
    assert args.manifest_path == "manifests/custom.yaml"
    assert args.force is True


def test_parser_build_requires_target():
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["build"])


def test_run_build_invokes_orchestrator_once_with_transport_inputs(tmp_path):
    orchestrator = FakeOrchestrator(build_result())

    result = build_commands._run_build(
        orchestrator,
        "Episode_0001",
        working_directory=tmp_path,
        manifest_path=None,
        force=False,
    )

    assert result["success"] is True
    assert orchestrator.calls == [
        {
            "target": "Episode_0001",
            "working_directory": tmp_path,
            "manifest_path": None,
            "allow_unsafe_retry": False,
        }
    ]


def test_run_build_passes_explicit_manifest_without_cli_resolution(tmp_path):
    orchestrator = FakeOrchestrator(build_result())

    build_commands._run_build(
        orchestrator,
        "Episode_0001",
        working_directory=tmp_path,
        manifest_path="manifests/custom.yaml",
        force=False,
    )

    assert orchestrator.calls[0]["manifest_path"] == "manifests/custom.yaml"


def test_run_build_passes_force_only_as_unsafe_retry(tmp_path):
    orchestrator = FakeOrchestrator(build_result())

    build_commands._run_build(
        orchestrator,
        "Episode_0001",
        working_directory=tmp_path,
        manifest_path=None,
        force=True,
    )

    assert orchestrator.calls[0]["allow_unsafe_retry"] is True
    assert len(orchestrator.calls) == 1


def test_print_build_success_includes_result_fields_and_exclusions(capsys):
    build_commands._print_build_result({"success": True, "result": build_result()})

    out = capsys.readouterr().out
    assert "Build complete" in out
    assert "Target: Episode_0001" in out
    assert "Episode number: 1" in out
    assert "Episode ID: RLC-E001" in out
    assert "Manifest: C:\\work\\Episode_0001.yaml" in out
    assert "Episode: created" in out
    assert "Final state: assembled" in out
    assert "Project: RLC-E001_MASTER" in out
    assert "Timeline: RLC-E001_TIMELINE" in out
    assert "Media count: 2" in out
    assert "Markers applied: 3" in out
    assert "Clips placed: 2" in out
    assert "Warnings: none" in out
    assert "Build completed through assembly." in out
    assert "Render queued: no" in out
    assert "Archive performed: no" in out


def test_print_build_success_reports_reused_episode(capsys):
    build_commands._print_build_result({"success": True, "result": build_result(episode_created=False)})

    out = capsys.readouterr().out
    assert "Episode: reused" in out


def test_print_build_success_prints_warnings_in_result_order(capsys):
    build_commands._print_build_result(
        {"success": True, "result": build_result(warnings=("first warning", "second warning"))}
    )

    out = capsys.readouterr().out
    assert "Warnings:" in out
    assert out.index("first warning") < out.index("second warning")


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (BuildTargetError("bad target"), "invalid target"),
        (ManifestResolutionError("missing manifest"), "manifest resolution failed"),
        (ManifestLoadError("cannot read"), "manifest failed"),
        (ManifestValidationError("invalid manifest"), "manifest failed"),
        (
            ManifestIdentityMismatchError(
                target_episode_id="RLC-E001",
                manifest_episode_id="RLC-E002",
            ),
            "manifest identity mismatch",
        ),
        (
            EpisodeBuildError("already assembled", stage="episode_lookup", episode_id="RLC-E001"),
            "episode assembly failed",
        ),
        (ResolveConnectionError("Resolve unavailable"), "episode assembly failed"),
    ],
)
def test_run_build_maps_known_failures_without_retry(tmp_path, error, category):
    orchestrator = FakeOrchestrator(error)

    result = build_commands._run_build(
        orchestrator,
        "Episode_0001",
        working_directory=tmp_path,
        manifest_path=None,
        force=False,
    )

    assert result["success"] is False
    assert result["category"] == category
    assert result["exit_code"] == 1
    assert len(orchestrator.calls) == 1


def test_print_build_failure_uses_error_stream(capsys):
    build_commands._print_build_result(
        {
            "success": False,
            "category": "manifest failed",
            "error": "missing file",
            "exit_code": 1,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Build failed (manifest failed): missing file" in captured.err


def test_run_dispatch_constructs_orchestrator_from_application_services(tmp_path, monkeypatch, capsys):
    fake = FakeOrchestrator(build_result())
    constructed: dict[str, object] = {}
    services = SimpleNamespace(config=object(), episode_manager=object())
    args = _build_parser().parse_args(["build", "Episode_0001"])

    def fake_factory(*, config, episode_manager):
        constructed["config"] = config
        constructed["episode_manager"] = episode_manager
        return fake

    monkeypatch.setattr(build_commands, "BuildOrchestrator", fake_factory)

    exit_code = build_commands.run(args, services, working_directory=tmp_path)

    assert exit_code == 0
    assert constructed == {"config": services.config, "episode_manager": services.episode_manager}
    assert fake.calls[0]["working_directory"] == tmp_path
    assert "Build complete" in capsys.readouterr().out


def test_main_build_dispatches_application_services_once(tmp_path, monkeypatch, capsys):
    fake = FakeOrchestrator(build_result())
    services = SimpleNamespace(config=object(), episode_manager=object())
    service_calls: list[object] = []

    def fake_services(*, resolve_adapter=None):
        service_calls.append(resolve_adapter)
        return services

    monkeypatch.setattr(cli_main, "build_application_services", fake_services)
    monkeypatch.setattr(build_commands, "BuildOrchestrator", lambda *, config, episode_manager: fake)
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["build", "Episode_0001"])

    assert exit_code == 0
    assert service_calls == [None]
    assert fake.calls == [
        {
            "target": "Episode_0001",
            "working_directory": tmp_path,
            "manifest_path": None,
            "allow_unsafe_retry": False,
        }
    ]
    assert "Build complete" in capsys.readouterr().out
