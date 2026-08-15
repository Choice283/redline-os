"""Focused tests for Control Room V0 Mission 4: the Mission & Checkpoint
History section on the Project Detail screen. Covers the full path a
real request takes -- GET /api/projects/{project_id} composing live Git
checkpoint resolution with MissionHistoryReader output -- plus the served
frontend wiring and the read-only/no-new-routes invariant, matching the
conventions established in test_detail_view.py and
test_mission_history_reader.py."""
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
    "current_mission": {"id": "m2", "title": "Mission 2", "phase": "complete"},
    "latest_checkpoint": {"label": "Checkpoint 2", "commit": "placeholder", "document": "docs/CHECKPOINT.md"},
    "validation": {"status": "pass", "summary": "All checks passed."},
    "attention": {"required": False, "reason": None},
}

_CLOSURE_TEMPLATE = """# Control Room V0 Mission {number} Closure

## Published Checkpoint

SHA:
`{sha}`

## Closure

Control Room V0 Mission {number} is formally closed.
"""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *_GIT_ENV_ARGS, *args], cwd=cwd, capture_output=True, text=True, check=True)


def _build_client(tmp_path: Path, write_history: bool = True) -> tuple[TestClient, str, str]:
    """Returns (client, mission_1_checkpoint_sha, mission_2_checkpoint_sha).
    Mission 1's closure doc cites a real commit in the fixture repo
    (resolvable); Mission 2's cites a SHA that was never committed
    (unresolvable) -- exercising both checkpoint_resolved outcomes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")
    mission_1_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    mission_2_sha_unresolvable = "f" * 40

    state = dict(_STATE)
    state["latest_checkpoint"] = dict(_STATE["latest_checkpoint"])
    state["latest_checkpoint"]["commit"] = mission_1_sha
    state_dir = repo / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")

    if write_history:
        (state_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
            _CLOSURE_TEMPLATE.format(number=1, sha=mission_1_sha), encoding="utf-8"
        )
        (state_dir / "MISSION_2_CLOSURE_2026-08-10.md").write_text(
            _CLOSURE_TEMPLATE.format(number=2, sha=mission_2_sha_unresolvable), encoding="utf-8"
        )

    _git(repo, "add", "docs/control_room")
    _git(repo, "commit", "-q", "-m", "add project state and mission history")

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
    return TestClient(app), mission_1_sha, mission_2_sha_unresolvable


# -- discovery/parsing + checkpoint/reference rendering, end-to-end --------


def test_project_snapshot_includes_mission_history_in_deterministic_order(tmp_path):
    client, mission_1_sha, mission_2_sha = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    history = response.json()["mission_history"]

    assert [entry["mission_number"] for entry in history] == [1, 2]
    assert history[0]["closure_document"] == "docs/control_room/MISSION_1_CLOSURE_2026-08-01.md"
    assert history[0]["checkpoint_commit"] == mission_1_sha
    assert history[0]["status"] == "closed"
    assert history[1]["checkpoint_commit"] == mission_2_sha


def test_mission_history_checkpoint_resolution_reflects_live_git(tmp_path):
    client, mission_1_sha, mission_2_sha = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}

    # Mission 1's checkpoint is a real commit in the fixture repo.
    assert history[1]["checkpoint_resolved"] is True
    # Mission 2's checkpoint was never committed anywhere.
    assert history[2]["checkpoint_resolved"] is False


# -- degraded/missing history does not crash the snapshot ------------------


def test_no_history_documents_yields_empty_history_not_an_error(tmp_path):
    client, _, _ = _build_client(tmp_path, write_history=False)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    assert response.json()["mission_history"] == []


# -- Project Detail history rendering: served JS wires up the history ------
# -- section ------------------------------------------------------------------


def test_app_js_renders_mission_history_section(tmp_path):
    client, _, _ = _build_client(tmp_path)
    response = client.get("/static/app.js")
    assert response.status_code == 200
    script = response.text
    assert "mission_history" in script
    assert "Mission &amp; Checkpoint History" in script or "Mission & Checkpoint History" in script


# -- read-only behavior / zero new mutation routes (Mission 4 added none) --


def test_mission_history_feature_introduced_no_new_routes(tmp_path):
    client, _, _ = _build_client(tmp_path)
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


def test_project_state_yaml_is_not_the_history_source(tmp_path):
    """PROJECT_STATE.yaml has no mission-history field in its schema --
    history must come only from closure documents, never from the current
    semantic-state file."""
    client, _, _ = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    state = response.json()["state"]
    assert "mission_history" not in state
    assert set(state.keys()) == {
        "project_id",
        "summary",
        "current_mission",
        "latest_checkpoint",
        "validation",
        "attention",
    }
