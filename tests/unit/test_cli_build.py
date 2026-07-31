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
    PreparedBuildRequest,
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


def _yaml_path(path: Path) -> str:
    return path.resolve().as_posix()


def write_isolated_config(config_dir: Path, root: Path) -> None:
    ingest = root / "_ingest"
    assets = root / "_assets"
    archive = root / "_archive"
    episodes = root / "_episodes"
    for path in (ingest, assets, archive, episodes):
        path.mkdir(parents=True, exist_ok=True)

    (config_dir / "naming.yaml").write_text(
        "episode_id_pattern: 'RLC-E{episode_number:03d}'\n"
        "project_name_pattern: '{episode_id}_MASTER'\n",
        encoding="utf-8",
    )
    (config_dir / "folder_structure.yaml").write_text(
        f"root_path: '{_yaml_path(episodes)}'\n",
        encoding="utf-8",
    )
    (config_dir / "render_presets.yaml").write_text("presets: []\n", encoding="utf-8")
    (config_dir / "paths.yaml").write_text(
        f"ingest_path: '{_yaml_path(ingest)}'\n"
        f"archive_path: '{_yaml_path(archive)}'\n"
        f"assets_path: '{_yaml_path(assets)}'\n"
        "master_project_template: RLC_MASTER_TEMPLATE\n",
        encoding="utf-8",
    )
    (config_dir / "assets.yaml").write_text("assets: []\nrequired_for_episode: []\n", encoding="utf-8")
    (config_dir / "timeline_template.yaml").write_text(
        "timeline_name_pattern: '{episode_id}_TIMELINE'\nmarkers: []\n",
        encoding="utf-8",
    )


def write_valid_manifest(path: Path, media_path: Path, *, episode_id: str = "RLC-E001") -> None:
    path.write_text(
        "schema_version: 1\n"
        "episode:\n"
        f"  id: {episode_id}\n"
        "assembly:\n"
        "  media:\n"
        f"    - path: {_yaml_path(media_path)}\n",
        encoding="utf-8",
    )


class FakeOrchestrator:
    def __init__(self, result_or_error):
        self.result_or_error = result_or_error
        self.calls: list[dict] = []
        self.prepared_calls: list[dict] = []

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

    def build_prepared(self, prepared_request: PreparedBuildRequest, *, allow_unsafe_retry: bool):
        self.prepared_calls.append(
            {
                "prepared_request": prepared_request,
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
    logging_calls: list[dict] = []
    events: list[str] = []

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    write_isolated_config(config_dir, tmp_path)
    media_file = tmp_path / "_ingest" / "clip.wav"
    media_file.write_bytes(b"x")
    write_valid_manifest(tmp_path / "Episode_0001.yaml", media_file)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "redline.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    def fake_configure_logging(*, log_dir, level):
        events.append("logging")
        logging_calls.append({"log_dir": log_dir, "level": level})

    def fake_services(*, resolve_adapter=None, config=None):
        events.append("application_services")
        service_calls.append({"resolve_adapter": resolve_adapter, "config": config})
        return services

    original_build_prepared = fake.build_prepared

    def record_build_prepared(prepared_request, *, allow_unsafe_retry):
        events.append("build_prepared")
        return original_build_prepared(prepared_request, allow_unsafe_retry=allow_unsafe_retry)

    monkeypatch.setattr(fake, "build_prepared", record_build_prepared)

    monkeypatch.setattr(cli_main, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(cli_main, "build_application_services", fake_services)
    monkeypatch.setattr(build_commands, "BuildOrchestrator", lambda *, config, episode_manager: fake)
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["build", "Episode_0001"])

    assert exit_code == 0
    assert events == ["logging", "application_services", "build_prepared"]
    assert logging_calls == [{"log_dir": str(tmp_path / "logs"), "level": "INFO"}]
    assert service_calls == [{"resolve_adapter": None, "config": service_calls[0]["config"]}]
    assert service_calls[0]["config"].naming.episode_id_pattern == "RLC-E{episode_number:03d}"
    assert fake.calls == []
    assert len(fake.prepared_calls) == 1
    prepared_request = fake.prepared_calls[0]["prepared_request"]
    assert prepared_request.target.original_target == "Episode_0001"
    assert prepared_request.manifest_resolution.path == (tmp_path / "Episode_0001.yaml").resolve()
    assert prepared_request.plan.episode_id == "RLC-E001"
    assert fake.prepared_calls == [
        {
            "allow_unsafe_retry": False,
            "prepared_request": prepared_request,
        }
    ]
    assert "Build complete" in capsys.readouterr().out


def test_main_non_build_commands_still_configure_logging_before_dispatch(tmp_path, monkeypatch, capsys):
    events: list[str] = []
    services = SimpleNamespace(
        asset_manager=SimpleNamespace(list_available_assets=lambda: []),
    )

    def fake_configure_logging(*, log_dir, level):
        events.append("logging")

    def fake_core_services():
        events.append("core_services")
        return services

    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(cli_main, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(cli_main, "build_core_services", fake_core_services)

    exit_code = cli_main.main(["asset", "list"])

    assert exit_code == 0
    assert events == ["logging", "core_services"]
    assert "No assets found." in capsys.readouterr().out


def _prepare_cli_preflight_failure(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    write_isolated_config(config_dir, tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "redline.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    def fail_if_composed(*args, **kwargs):
        raise AssertionError("full application services must not be composed before build preflight succeeds")

    monkeypatch.setattr(cli_main, "build_application_services", fail_if_composed)


def _assert_no_preflight_artifacts(tmp_path: Path) -> None:
    assert not (tmp_path / "redline.db").exists()
    assert not (tmp_path / "logs").exists()


def test_main_build_missing_default_manifest_does_not_create_database_or_connect_resolve(
    tmp_path, monkeypatch, capsys
):
    _prepare_cli_preflight_failure(tmp_path, monkeypatch)

    exit_code = cli_main.main(["build", "Episode_9001"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Build failed (manifest resolution failed):" in captured.err
    assert "default manifest not found" in captured.err
    _assert_no_preflight_artifacts(tmp_path)


def test_main_build_missing_explicit_manifest_does_not_create_database_or_connect_resolve(
    tmp_path, monkeypatch, capsys
):
    _prepare_cli_preflight_failure(tmp_path, monkeypatch)

    exit_code = cli_main.main(["build", "Episode_9001", "--manifest", "missing.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Build failed (manifest resolution failed):" in captured.err
    assert "explicit manifest does not exist" in captured.err
    _assert_no_preflight_artifacts(tmp_path)


def test_main_build_invalid_yaml_does_not_create_database_or_connect_resolve(tmp_path, monkeypatch, capsys):
    _prepare_cli_preflight_failure(tmp_path, monkeypatch)
    (tmp_path / "Episode_9001.yaml").write_text("schema_version: [\n", encoding="utf-8")

    exit_code = cli_main.main(["build", "Episode_9001"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Build failed (manifest failed):" in captured.err
    assert "manifest YAML parse failed" in captured.err
    _assert_no_preflight_artifacts(tmp_path)


def test_main_build_schema_invalid_manifest_does_not_create_database_or_connect_resolve(
    tmp_path, monkeypatch, capsys
):
    _prepare_cli_preflight_failure(tmp_path, monkeypatch)
    (tmp_path / "Episode_9001.yaml").write_text(
        "schema_version: 1\n"
        "episode:\n"
        "  id: RLC-E9001\n"
        "assembly:\n"
        "  media: []\n",
        encoding="utf-8",
    )

    exit_code = cli_main.main(["build", "Episode_9001"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Build failed (manifest failed):" in captured.err
    assert "assembly.media" in captured.err
    _assert_no_preflight_artifacts(tmp_path)


def test_main_build_invalid_media_path_does_not_create_database_or_connect_resolve(
    tmp_path, monkeypatch, capsys
):
    _prepare_cli_preflight_failure(tmp_path, monkeypatch)
    missing_media = tmp_path / "_ingest" / "missing.wav"
    write_valid_manifest(tmp_path / "Episode_9001.yaml", missing_media, episode_id="RLC-E9001")

    exit_code = cli_main.main(["build", "Episode_9001"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Build failed (manifest failed):" in captured.err
    assert "cannot be resolved" in captured.err
    _assert_no_preflight_artifacts(tmp_path)


def test_main_build_manifest_identity_mismatch_does_not_create_database_or_connect_resolve(
    tmp_path, monkeypatch, capsys
):
    _prepare_cli_preflight_failure(tmp_path, monkeypatch)
    media_file = tmp_path / "_ingest" / "clip.wav"
    media_file.write_bytes(b"x")
    write_valid_manifest(tmp_path / "Episode_9001.yaml", media_file, episode_id="RLC-E000")

    exit_code = cli_main.main(["build", "Episode_9001"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Build failed (manifest identity mismatch):" in captured.err
    assert "target episode_id=RLC-E9001" in captured.err
    _assert_no_preflight_artifacts(tmp_path)
