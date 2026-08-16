"""Lightweight tests for the control_room.app FastAPI boundary: routes call
only ProjectStatusService, translate ProjectNotFoundError to 404, and
never expose a mutation route."""
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from control_room.app import create_app
from control_room.project_registry import ProjectRegistry
from control_room.project_status_service import ProjectStatusService
from control_room.state_reader import StateReader

_GIT_ENV_ARGS = ["-c", "user.name=Test User", "-c", "user.email=test@example.com"]

_CLOSURE_DOCUMENT_RELATIVE = "docs/control_room/MISSION_1_CLOSURE_2026-01-01.md"

_STATE = {
    "project_id": "example-project",
    "summary": "Example project for tests.",
    "current_mission": {"id": "m1", "title": "Mission 1", "phase": "implementation"},
    "latest_checkpoint": {"label": "Checkpoint 1", "commit": "placeholder", "document": _CLOSURE_DOCUMENT_RELATIVE},
    "validation": {"status": "pass_with_exception", "summary": "Independent audit passed; CI red (documented)."},
    "attention": {"required": False, "reason": None},
}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *_GIT_ENV_ARGS, *args], cwd=cwd, capture_output=True, text=True, check=True)


def _build_client(tmp_path: Path) -> TestClient:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")
    checkpoint_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    state = dict(_STATE)
    state["latest_checkpoint"] = dict(_STATE["latest_checkpoint"])
    state["latest_checkpoint"]["commit"] = checkpoint_sha
    state_dir = repo / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    # A real closure document at the configured document path (Mission 10)
    # so Closed-State Currency resolves to CURRENT rather than UNAVAILABLE,
    # keeping this "no attention" fixture a clean baseline.
    (state_dir / "MISSION_1_CLOSURE_2026-01-01.md").write_text(
        "# Mission 1 Closure\n\nMission 1 is formally closed.\n", encoding="utf-8"
    )
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")
    _git(repo, "add", "docs/control_room/MISSION_1_CLOSURE_2026-01-01.md", "docs/control_room/PROJECT_STATE.yaml")
    _git(repo, "commit", "-q", "-m", "add project state")

    registry_dir = tmp_path / "config" / "control_room"
    registry_dir.mkdir(parents=True)
    registry_path = registry_dir / "projects.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {
                        "id": "example-project",
                        "name": "Example Project",
                        "repository": "repo",
                        "state_file": "repo/docs/control_room/PROJECT_STATE.yaml",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    registry = ProjectRegistry(registry_path, base_dir=tmp_path)
    service = ProjectStatusService(registry, state_reader=StateReader())
    app = create_app(service=service)
    return TestClient(app)


def test_index_serves_html(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "Control Room" in response.text


def test_list_projects(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["project_id"] == "example-project"
    assert body[0]["attention"]["required"] is False


def test_get_single_project(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    assert response.json()["name"] == "Example Project"


def test_get_unknown_project_returns_404(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/does-not-exist")
    assert response.status_code == 404


def test_no_mutation_routes_exist(tmp_path):
    client = _build_client(tmp_path)
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/projects/example-project")
        assert response.status_code in (404, 405)
