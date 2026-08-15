"""Packaging verification for Control Room (Codex review Finding 1):
proves control_room/static/*.{html,js,css} survive into a built wheel,
not just that they exist in the source tree.

Deliberately lighter than tests/unit/test_installed_wheel_smoke.py's full
build-into-venv-and-import flow: building the wheel and inspecting its
member list is the smallest mechanism that actually proves package-data
inclusion, without a second venv-install-and-import round trip duplicating
that existing test's job for redline_core's own resources.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_REQUIRED_STATIC_MEMBERS = {
    "control_room/static/index.html",
    "control_room/static/app.js",
    "control_room/static/styles.css",
}


def test_built_wheel_includes_control_room_static_assets(tmp_path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir()

    wheel_path = _build_wheel(wheelhouse=wheelhouse, cwd=outside_cwd)

    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    missing = _REQUIRED_STATIC_MEMBERS - names
    assert not missing, f"wheel is missing Control Room static assets: {sorted(missing)}"


def _build_wheel(*, wheelhouse: Path, cwd: Path) -> Path:
    base_args = [sys.executable, "-m", "pip", "wheel", str(REPO_ROOT), "--no-deps", "-w", str(wheelhouse)]

    # --no-build-isolation requires setuptools already present as a
    # *runtime* package in the current environment; a genuinely fresh
    # venv (setuptools listed only under [build-system].requires, which
    # only isolated builds consult, not installed as a runtime dep of
    # `dev`) won't have it, and fails in more than one way depending on
    # exactly what's missing/outdated (e.g. "invalid command 'bdist_wheel'"
    # vs "Cannot import 'setuptools.build_meta'"). Rather than special-case
    # exact error text, fall back to a normal build-isolation build (which
    # downloads the pinned build requirements itself) on any failure.
    isolated_result = subprocess.run([*base_args, "--no-build-isolation"], cwd=cwd, capture_output=True, text=True)
    if isolated_result.returncode != 0:
        result = subprocess.run(base_args, cwd=cwd, capture_output=True, text=True)
        assert result.returncode == 0, f"Wheel build failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    wheels = sorted(wheelhouse.glob("redline_os-*.whl"))
    assert len(wheels) == 1, f"expected exactly one built wheel, found: {wheels}"
    return wheels[0]
