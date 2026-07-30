"""Installed CLI smoke tests for non-help operator startup."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_installed_redline_asset_list_runs_outside_repo_without_db_or_resolve(tmp_path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir()
    venv_dir = tmp_path / "venv"
    config_dir = _write_isolated_config_dir(tmp_path)
    log_dir = tmp_path / "logs"
    database_path = outside_cwd / "redline.db"
    repo_build_dir = REPO_ROOT / "build"
    repo_build_existed = repo_build_dir.exists()

    try:
        _build_wheel(wheelhouse=wheelhouse, cwd=outside_cwd)
        wheel_path = _single_wheel(wheelhouse)

        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(venv_dir)
        python = _venv_python(venv_dir)
        redline = _venv_script(venv_dir, "redline")
        _run([str(python), "-m", "pip", "install", "--no-deps", str(wheel_path)], cwd=outside_cwd)

        result = _run(
            [str(redline), "asset", "list"],
            cwd=outside_cwd,
            env=_isolated_env(config_dir=config_dir, log_dir=log_dir),
        )

        assert "REDLINE OS" in result.stdout
        assert "Assets" in result.stdout
        assert "RLG-001" in result.stdout
        assert "Lower third" in result.stdout
        assert "lower_third.png" in result.stdout
        assert "1 asset(s)." in result.stdout
        assert (log_dir / "redline_os.log").exists()
        assert not database_path.exists()
    finally:
        if repo_build_dir.exists() and not repo_build_existed:
            shutil.rmtree(repo_build_dir)


def _write_isolated_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()

    (config_dir / "naming.yaml").write_text(
        'episode_id_pattern: "RLC-E{episode_number:03d}"\n'
        'project_name_pattern: "{episode_id}_MASTER"\n',
        encoding="utf-8",
    )
    (config_dir / "folder_structure.yaml").write_text(
        f'root_path: "{_yaml_path(tmp_path / "_episodes")}"\n',
        encoding="utf-8",
    )
    (config_dir / "render_presets.yaml").write_text("presets: []\n", encoding="utf-8")
    (config_dir / "paths.yaml").write_text(
        f'ingest_path: "{_yaml_path(tmp_path / "_ingest")}"\n'
        f'archive_path: "{_yaml_path(tmp_path / "_archive")}"\n'
        f'assets_path: "{_yaml_path(assets_path)}"\n'
        'master_project_template: "RLC_MASTER_TEMPLATE"\n',
        encoding="utf-8",
    )
    (config_dir / "assets.yaml").write_text(
        "assets:\n"
        '  - asset_id: "RLG-001"\n'
        '    description: "Lower third"\n'
        '    filename: "lower_third.png"\n'
        "required_for_episode: []\n",
        encoding="utf-8",
    )
    (config_dir / "timeline_template.yaml").write_text(
        'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n',
        encoding="utf-8",
    )
    return config_dir


def _yaml_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"Command failed with exit code {completed.returncode}: {args}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    return completed


def _build_wheel(*, wheelhouse: Path, cwd: Path) -> None:
    base_args = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        str(REPO_ROOT),
        "--no-deps",
        "-w",
        str(wheelhouse),
    ]
    isolated_result = subprocess.run(
        [*base_args, "--no-build-isolation"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if isolated_result.returncode == 0:
        return

    if "invalid command 'bdist_wheel'" not in isolated_result.stderr:
        assert False, (
            "Wheel build without build isolation failed unexpectedly.\n"
            f"stdout:\n{isolated_result.stdout}\n"
            f"stderr:\n{isolated_result.stderr}"
        )

    _run(base_args, cwd=cwd)


def _single_wheel(wheelhouse: Path) -> Path:
    wheels = sorted(wheelhouse.glob("redline_os-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def _venv_python(venv_dir: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return venv_dir / scripts_dir / executable


def _venv_script(venv_dir: Path, name: str) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = f"{name}.exe" if os.name == "nt" else name
    return venv_dir / scripts_dir / executable


def _isolated_env(*, config_dir: Path, log_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("REDLINE_DB_PATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["REDLINE_CONFIG_DIR"] = str(config_dir)
    env["REDLINE_LOG_DIR"] = str(log_dir)
    return env
