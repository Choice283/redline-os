"""Installed-wheel smoke tests for Redline OS packaging."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_installed_wheel_imports_resources_and_redline_entrypoint_outside_repo(tmp_path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir()
    venv_dir = tmp_path / "venv"
    repo_build_dir = REPO_ROOT / "build"
    repo_build_existed = repo_build_dir.exists()

    try:
        _build_wheel(wheelhouse=wheelhouse, cwd=outside_cwd)

        wheel_path = _single_wheel(wheelhouse)
        with zipfile.ZipFile(wheel_path) as wheel:
            names = set(wheel.namelist())
        assert "redline_core/db/schema.sql" in names
        assert "redline_core/asset/schema.sql" in names

        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(venv_dir)
        python = _venv_python(venv_dir)
        redline = _venv_script(venv_dir, "redline")

        _run([str(python), "-m", "pip", "install", "--no-deps", str(wheel_path)], cwd=outside_cwd)

        env = _isolated_env()
        resource_probe = (
            "from importlib.resources import files\n"
            "import redline_core\n"
            "db_schema = files('redline_core.db').joinpath('schema.sql').read_text(encoding='utf-8')\n"
            "asset_schema = files('redline_core.asset').joinpath('schema.sql').read_text(encoding='utf-8')\n"
            "assert 'CREATE TABLE IF NOT EXISTS episodes' in db_schema\n"
            "assert 'CREATE TABLE IF NOT EXISTS render_jobs' in db_schema\n"
            "assert 'CREATE TABLE' in asset_schema\n"
            "print(redline_core.__name__)\n"
        )
        import_result = _run([str(python), "-c", resource_probe], cwd=outside_cwd, env=env)
        assert import_result.stdout.strip() == "redline_core"

        assert redline.exists()
        help_result = _run([str(redline), "--help"], cwd=outside_cwd, env=env)
        assert "Redline OS command-line interface" in help_result.stdout
        assert "episode" in help_result.stdout
        assert "asset" in help_result.stdout
        assert "archive" in help_result.stdout
    finally:
        if repo_build_dir.exists() and not repo_build_existed:
            shutil.rmtree(repo_build_dir)


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


def _isolated_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["REDLINE_LOG_DIR"] = str(Path(os.environ.get("TMP", os.environ.get("TEMP", "."))) / "redline-os-smoke-logs")
    return env
