"""Installed MCP startup smoke tests for Redline OS packaging."""
from __future__ import annotations

import email
import os
import shutil
import subprocess
import sys
import venv
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_MCP_WHEEL = "mcp-1.0.0-py3-none-any.whl"


def test_installed_mcp_server_starts_with_mock_resolve_outside_repo(tmp_path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir()
    venv_dir = tmp_path / "venv"
    config_dir = _write_isolated_config_dir(tmp_path)
    database_path = tmp_path / "redline.db"
    log_dir = tmp_path / "logs"
    repo_build_dir = REPO_ROOT / "build"
    repo_build_existed = repo_build_dir.exists()

    try:
        _build_wheel(wheelhouse=wheelhouse, cwd=outside_cwd)
        wheel_path = _single_wheel(wheelhouse)
        _assert_declares_mcp_extra(wheel_path)
        fake_mcp_wheel = _write_fake_mcp_wheel(wheelhouse)

        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(venv_dir)
        python = _venv_python(venv_dir)
        redline_mcp = _venv_script(venv_dir, "redline-mcp")
        _run([str(python), "-m", "pip", "install", "--no-deps", str(fake_mcp_wheel)], cwd=outside_cwd)
        _run([str(python), "-m", "pip", "install", "--no-deps", str(wheel_path)], cwd=outside_cwd)

        startup_probe = (
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "import mcp\n"
            "from mcp_server.server import create_server\n"
            "from redline_core.logging.setup import configure_logging\n"
            "venv_dir = Path(sys.argv[1])\n"
            "log_dir = Path(sys.argv[2])\n"
            "configure_logging(log_dir=log_dir)\n"
            "server = create_server(use_mock_resolve=True)\n"
            "tools = sorted(server.tools)\n"
            "assert Path(mcp.__file__).is_relative_to(venv_dir)\n"
            "assert server.name == 'redline-mcp'\n"
            "assert len(tools) == 18\n"
            "expected = {\n"
            "    'create_episode', 'get_episode_status', 'list_episodes',\n"
            "    'validate_manifest', 'assemble_episode',\n"
            "    'list_available_assets', 'verify_assets_for_episode',\n"
            "    'scan_ingest_for_episode', 'organize_bins',\n"
            "    'build_timeline', 'add_markers', 'place_clips',\n"
            "    'queue_render', 'get_render_status', 'cancel_render',\n"
            "    'list_render_jobs_for_episode', 'archive_episode', 'list_archives',\n"
            "}\n"
            "assert set(tools) == expected\n"
            "print(json.dumps({'name': server.name, 'tools': tools}, sort_keys=True))\n"
        )
        result = _run(
            [str(python), "-c", startup_probe, str(venv_dir), str(log_dir)],
            cwd=outside_cwd,
            env=_isolated_env(config_dir=config_dir, database_path=database_path, log_dir=log_dir),
        )

        assert redline_mcp.exists()
        assert "redline-mcp" in result.stdout
        assert "create_episode" in result.stdout
        assert "assemble_episode" in result.stdout
        assert "cancel_render" in result.stdout
        assert database_path.exists()
        assert (log_dir / "redline_os.log").exists()
    finally:
        if repo_build_dir.exists() and not repo_build_existed:
            shutil.rmtree(repo_build_dir)


def _assert_declares_mcp_extra(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as wheel:
        metadata_name = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_string(wheel.read(metadata_name).decode("utf-8"))

    extras = set(metadata.get_all("Provides-Extra", []))
    requirements = metadata.get_all("Requires-Dist", [])
    assert "mcp" in extras
    assert any(requirement.startswith("mcp") and "extra == \"mcp\"" in requirement for requirement in requirements)


def _write_fake_mcp_wheel(wheelhouse: Path) -> Path:
    wheel_path = wheelhouse / FAKE_MCP_WHEEL
    files = {
        "mcp/__init__.py": "__version__ = '1.0.0'\n",
        "mcp/server/__init__.py": "",
        "mcp/server/fastmcp.py": (
            "class FastMCP:\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
            "        self.tools = {}\n"
            "\n"
            "    def tool(self):\n"
            "        def decorate(func):\n"
            "            self.tools[func.__name__] = func\n"
            "            return func\n"
            "        return decorate\n"
            "\n"
            "    def run(self):\n"
            "        raise AssertionError('Mission 25 smoke must not call mcp.run()')\n"
        ),
        "mcp-1.0.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: mcp\nVersion: 1.0.0\n",
        "mcp-1.0.0.dist-info/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: redline-os-test\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ),
        "mcp-1.0.0.dist-info/RECORD": "",
    }
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for name, contents in files.items():
            wheel.writestr(name, contents)
    return wheel_path


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
    (config_dir / "render_presets.yaml").write_text(
        "presets:\n"
        '  - name: "broadcast_master"\n'
        '    resolve_preset_name: "Redline Broadcast Master"\n'
        '    output_subfolder: "exports"\n'
        '    filename_template: "{episode_id}"\n'
        '    file_extension: ".mov"\n'
        '    collision_policy: "reject"\n',
        encoding="utf-8",
    )
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


def _isolated_env(*, config_dir: Path, database_path: Path, log_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["REDLINE_CONFIG_DIR"] = str(config_dir)
    env["REDLINE_DB_PATH"] = str(database_path)
    env["REDLINE_LOG_DIR"] = str(log_dir)
    return env
