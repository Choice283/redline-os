"""Installed-package smoke tests for first-run database initialization."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_installed_package_initializes_database_outside_repo(tmp_path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir()
    venv_dir = tmp_path / "venv"
    database_path = tmp_path / "redline.db"
    repo_build_dir = REPO_ROOT / "build"
    repo_build_existed = repo_build_dir.exists()

    try:
        _build_wheel(wheelhouse=wheelhouse, cwd=outside_cwd)
        wheel_path = _single_wheel(wheelhouse)

        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(venv_dir)
        python = _venv_python(venv_dir)
        _run([str(python), "-m", "pip", "install", "--no-deps", str(wheel_path)], cwd=outside_cwd)

        bootstrap_probe = (
            "import sqlite3\n"
            "import sys\n"
            "from pathlib import Path\n"
            "from redline_core.db.database import Database\n"
            "db_path = Path(sys.argv[1])\n"
            "db = Database(db_path).connect()\n"
            "try:\n"
            "    db.init_schema()\n"
            "finally:\n"
            "    db.close()\n"
            "with sqlite3.connect(db_path) as connection:\n"
            "    tables = {\n"
            "        row[0]\n"
            "        for row in connection.execute(\n"
            "            \"SELECT name FROM sqlite_master WHERE type = 'table'\"\n"
            "        ).fetchall()\n"
            "    }\n"
            "assert {'episodes', 'render_jobs', 'archives'}.issubset(tables)\n"
            "print('|'.join(sorted(tables)))\n"
        )
        result = _run([str(python), "-c", bootstrap_probe, str(database_path)], cwd=outside_cwd, env=_isolated_env())

        assert database_path.exists()
        assert "episodes" in result.stdout
        assert "render_jobs" in result.stdout
        assert "archives" in result.stdout
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


def _isolated_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    return env
