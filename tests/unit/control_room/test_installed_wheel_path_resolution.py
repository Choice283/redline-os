"""Proves Control Room's installed-wheel path-resolution behavior (Codex
review "Prove the path design under an installed wheel").

Determined, not assumed: a real wheel (not an editable install) launched
from a directory unrelated to the Redline OS repository has its
`_PACKAGE_ROOT` resolve into the installing venv's site-packages tree,
which has no `config/control_room/projects.yaml` -- confirming Control
Room V0 requires an existing Redline OS repository checkout (Option A). It
is not, and cannot be, a self-contained installed package: its whole
purpose is reading a real checkout's live Git state, which is never
bundled into a wheel. This test proves both halves of that design:
launching without a valid root fails fast and clearly (before binding a
socket), and REDLINE_CONTROL_ROOM_ROOT correctly points an installed wheel
at an explicit checkout regardless of CWD.

Heavier than the other Control Room tests (builds a real wheel, installs
it with real runtime dependencies into a fresh venv) -- intentionally, per
the review's explicit instruction not to assume editable-install behavior
generalizes to a real wheel install.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_GIT_ENV_ARGS = ["-c", "user.name=Test User", "-c", "user.email=test@example.com"]


def test_installed_wheel_path_resolution_from_unrelated_cwd(tmp_path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    build_cwd = tmp_path / "build_cwd"
    build_cwd.mkdir()
    wheel_path = _build_wheel(wheelhouse=wheelhouse, cwd=build_cwd)

    venv_dir = tmp_path / "venv"
    # Real runtime deps resolved from PyPI (not --no-deps): the probe
    # script imports control_room.app, which needs pydantic/PyYAML
    # actually functional, not just present as file paths.
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = _venv_python(venv_dir)
    _run([str(python), "-m", "pip", "install", str(wheel_path)], cwd=build_cwd)

    unrelated_cwd = tmp_path / "unrelated_cwd"
    unrelated_cwd.mkdir()
    checkout_root = tmp_path / "synthetic_checkout"
    _build_synthetic_checkout(checkout_root)

    env = _isolated_env()

    # Without an explicit root, an installed wheel launched from a
    # directory with no relation to any Redline OS checkout must fail --
    # never silently reinterpret that directory as the project.
    without_root = _run(
        [str(python), "-c", _PROBE_SCRIPT], cwd=unrelated_cwd, env=env, check=False
    )
    assert without_root.returncode != 0
    assert "RegistryError" in without_root.stderr
    assert without_root.stdout.strip() == ""  # the probe never reached its print -- no snapshot leaked

    # With REDLINE_CONTROL_ROOM_ROOT pointed at a real checkout, the same
    # installed wheel, from the same unrelated CWD, resolves it correctly.
    with_root_env = dict(env, REDLINE_CONTROL_ROOM_ROOT=str(checkout_root))
    with_root = _run([str(python), "-c", _PROBE_SCRIPT], cwd=unrelated_cwd, env=with_root_env)
    assert with_root.stdout.strip() == "synthetic-checkout:main"


_PROBE_SCRIPT = (
    "from control_room.app import build_service\n"
    "service = build_service()\n"
    "snapshots = service.list_snapshots()\n"
    "print(';'.join(f'{s.project_id}:{s.git.branch}' for s in snapshots))\n"
)


def _build_synthetic_checkout(root: Path) -> None:
    """A minimal, self-contained fake Redline OS checkout -- a real repo
    with its own registry + state file, entirely separate from the actual
    Redline OS repository -- proving REDLINE_CONTROL_ROOM_ROOT genuinely
    drives resolution rather than something coincidentally still pointing
    at the real repo."""
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "initial")
    checkpoint_sha = _git(root, "rev-parse", "HEAD").stdout.strip()

    state_dir = root / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    (state_dir / "PROJECT_STATE.yaml").write_text(
        "project_id: synthetic-checkout\n"
        "summary: Synthetic checkout for installed-wheel path resolution proof.\n"
        "current_mission:\n  id: m1\n  title: Test Mission\n  phase: implementation\n"
        f"latest_checkpoint:\n  label: checkpoint\n  commit: {checkpoint_sha}\n  document: docs/CHECKPOINT.md\n"
        "validation:\n  status: pass_with_exception\n  summary: test\n"
        "attention:\n  required: false\n  reason: null\n",
        encoding="utf-8",
    )
    _git(root, "add", "docs/control_room/PROJECT_STATE.yaml")
    _git(root, "commit", "-q", "-m", "add state")

    registry_dir = root / "config" / "control_room"
    registry_dir.mkdir(parents=True)
    (registry_dir / "projects.yaml").write_text(
        "projects:\n"
        "  - id: synthetic-checkout\n"
        "    name: Synthetic Checkout\n"
        "    repository: .\n"
        "    state_file: docs/control_room/PROJECT_STATE.yaml\n",
        encoding="utf-8",
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *_GIT_ENV_ARGS, *args], cwd=cwd, capture_output=True, text=True, check=True)


def _run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if check:
        assert result.returncode == 0, f"Command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return result


def _build_wheel(*, wheelhouse: Path, cwd: Path) -> Path:
    base_args = [sys.executable, "-m", "pip", "wheel", str(REPO_ROOT), "--no-deps", "-w", str(wheelhouse)]
    isolated_result = subprocess.run([*base_args, "--no-build-isolation"], cwd=cwd, capture_output=True, text=True)
    if isolated_result.returncode != 0:
        result = subprocess.run(base_args, cwd=cwd, capture_output=True, text=True)
        assert result.returncode == 0, f"Wheel build failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    wheels = sorted(wheelhouse.glob("redline_os-*.whl"))
    assert len(wheels) == 1, f"expected exactly one built wheel, found: {wheels}"
    return wheels[0]


def _venv_python(venv_dir: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return venv_dir / scripts_dir / executable


def _isolated_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("REDLINE_CONTROL_ROOM_ROOT", None)
    env.pop("REDLINE_CONTROL_ROOM_REGISTRY", None)
    env["PYTHONNOUSERSITE"] = "1"
    return env
