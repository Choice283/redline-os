"""Focused tests for the Control Room V0 Mission 3 Project Detail screen.

The Detail screen is pure client-side view selection (hash routing) inside
the existing single-page shell -- no new backend route was added. These
tests therefore cover: the served shell supports both screens, the served
JS wires up card selection/navigation, `GET /api/projects/{project_id}`
(the endpoint the detail screen calls) returns every field the detail view
renders, that same endpoint surfaces degraded/not-found states rather than
inventing data, and that no mutation-capable route exists anywhere in the
app -- Mission 3 added zero new routes."""
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

_STATE = {
    "project_id": "example-project",
    "summary": "Example project for tests.",
    "current_mission": {"id": "m1", "title": "Mission 1", "phase": "implementation"},
    "latest_checkpoint": {"label": "Checkpoint 1", "commit": "placeholder", "document": "docs/CHECKPOINT.md"},
    "validation": {"status": "pass_with_exception", "summary": "Independent audit passed; CI red (documented)."},
    "attention": {"required": False, "reason": None},
}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *_GIT_ENV_ARGS, *args], cwd=cwd, capture_output=True, text=True, check=True)


def _build_client(tmp_path: Path, write_state: bool = True) -> TestClient:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")
    checkpoint_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    if write_state:
        state = dict(_STATE)
        state["latest_checkpoint"] = dict(_STATE["latest_checkpoint"])
        state["latest_checkpoint"]["commit"] = checkpoint_sha
        state_dir = repo / "docs" / "control_room"
        state_dir.mkdir(parents=True)
        (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")
        _git(repo, "add", "docs/control_room/PROJECT_STATE.yaml")
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


# -- detail-page route: the served shell supports both screens -------------


def test_index_html_includes_detail_container(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="detail"' in response.text
    assert 'id="projects"' in response.text


# -- project selection/navigation: served JS wires up card links + router --


def test_app_js_wires_up_card_navigation_and_hash_routing(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/static/app.js")
    assert response.status_code == 200
    script = response.text
    assert "#/projects/" in script
    assert "hashchange" in script
    assert 'href="#/"' in script


# -- rendering of existing snapshot data: detail endpoint returns every ----
# -- field the detail view renders ------------------------------------------


def test_get_single_project_returns_full_snapshot_for_detail_rendering(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    body = response.json()

    assert body["name"] == "Example Project"
    assert body["state"]["summary"] == "Example project for tests."
    assert body["attention"]["required"] is False

    git = body["git"]
    assert git["branch"] == "main"
    assert git["head_sha_short"]
    assert git["working_tree"] == "CLEAN"
    assert git["tracking"] in ("NO_UPSTREAM", "UNKNOWN")

    state = body["state"]
    assert state["current_mission"] == {"id": "m1", "title": "Mission 1", "phase": "implementation"}
    assert state["latest_checkpoint"]["label"] == "Checkpoint 1"
    assert state["validation"]["status"] == "pass_with_exception"
    assert "CI" in state["validation"]["summary"]


# -- degraded/error states: same endpoint the detail screen calls must -----
# -- surface them explicitly, never invent data ------------------------------


def test_get_single_project_surfaces_missing_state_as_degraded(tmp_path):
    client = _build_client(tmp_path, write_state=False)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    body = response.json()

    assert body["state"] is None
    assert body["state_error"]
    assert body["attention"]["required"] is True


def test_get_unknown_project_returns_404_not_a_synthetic_snapshot(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/does-not-exist")
    assert response.status_code == 404
    assert "state" not in response.json() or response.json().get("project_id") is None


# -- read-only behavior: Mission 3 introduced zero new backend routes ------


def test_detail_feature_introduced_no_new_routes(tmp_path):
    client = _build_client(tmp_path)
    app = client.app

    api_paths = {route.path for route in app.routes if getattr(route, "path", "").startswith("/api/")}
    assert api_paths == {"/api/projects", "/api/projects/{project_id}"}

    for route in app.routes:
        methods = getattr(route, "methods", None)
        if methods:
            assert methods <= {"GET", "HEAD", "OPTIONS"}, f"mutating verb allowed on {route.path}: {methods}"

    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/projects/example-project")
        assert response.status_code in (404, 405)
