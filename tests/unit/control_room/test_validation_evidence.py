"""Focused tests for Control Room V0 Mission 5: Validation & Evidence
Detail, reachable from the Mission & Checkpoint History section on the
Project Detail screen. Covers the request path -- GET
/api/projects/{project_id} embedding verbatim Validation/Independent
Review/CI section text per historical mission -- the served frontend
wiring, degraded (missing-section) behavior, and the read-only/no-new-
routes invariant, matching the conventions in test_detail_view.py,
test_project_detail_history.py, and test_mission_history_reader.py."""
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
    "current_mission": {"id": "m1", "title": "Mission 1", "phase": "complete"},
    "latest_checkpoint": {"label": "Checkpoint 1", "commit": "placeholder", "document": "docs/CHECKPOINT.md"},
    "validation": {"status": "pass", "summary": "All checks passed."},
    "attention": {"required": False, "reason": None},
}

_CLOSURE_WITH_EVIDENCE = """# Control Room V0 Mission 1 Closure

## Published Checkpoint

SHA:
`{sha}`

## Validation

- **Focused suite**: 10 passed.
- **Broad regression**: 100 passed, 2 skipped.

## Independent Review

Final verdict: **PASS**.

## Closure

Control Room V0 Mission 1 is formally closed.
"""

_CLOSURE_WITHOUT_EVIDENCE = """# Control Room V0 Mission 2 Closure

## Published Checkpoint

SHA:
`{sha}`

## Closure

Control Room V0 Mission 2 is formally closed.
"""


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
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")

    (state_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        _CLOSURE_WITH_EVIDENCE.format(sha=checkpoint_sha), encoding="utf-8"
    )
    (state_dir / "MISSION_2_CLOSURE_2026-08-10.md").write_text(
        _CLOSURE_WITHOUT_EVIDENCE.format(sha=checkpoint_sha), encoding="utf-8"
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
    return TestClient(app)


# -- durable validation info renders accurately -----------------------------


def test_project_snapshot_embeds_validation_evidence_per_mission(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}

    mission_1 = history[1]
    assert "Focused suite" in mission_1["validation_section"]
    assert "10 passed" in mission_1["validation_section"]
    assert "PASS" in mission_1["independent_review_section"]
    assert mission_1["ci_section"] is None  # this closure doc has no ## CI section


# -- missing evidence is explicit rather than inferred ----------------------


def test_missing_evidence_sections_are_none_not_invented(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}

    mission_2 = history[2]
    assert mission_2["validation_section"] is None
    assert mission_2["independent_review_section"] is None
    assert mission_2["ci_section"] is None
    # A closure doc with no evidence detail is not itself a malformed
    # record -- title/checkpoint/closure-statement still parsed fine.
    assert mission_2["parse_error"] is None


# -- checkpoint identity stays tied to the correct mission -------------------


def test_evidence_does_not_alter_or_duplicate_checkpoint_identity(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}
    checkpoint_sha = history[1]["checkpoint_commit"]

    assert checkpoint_sha == history[2]["checkpoint_commit"]  # both cite the same real commit in this fixture
    assert checkpoint_sha not in (history[1]["validation_section"] or "")


# -- Project Detail rendering: served JS wires up the evidence drill-down --


def test_app_js_renders_validation_evidence_drill_down(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/static/app.js")
    assert response.status_code == 200
    script = response.text
    assert "validation_section" in script
    assert "independent_review_section" in script
    assert "Validation &amp; Evidence Detail" in script
    assert "<details" in script


# -- read-only behavior / zero new mutation routes (Mission 5 added none) --


def test_validation_evidence_feature_introduced_no_new_routes(tmp_path):
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


def test_project_state_yaml_still_not_the_evidence_source(tmp_path):
    """PROJECT_STATE.yaml has no validation-evidence fields in its schema
    -- evidence must come only from closure documents."""
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    state = response.json()["state"]
    assert "validation_section" not in state
    assert set(state.keys()) == {
        "project_id",
        "summary",
        "current_mission",
        "latest_checkpoint",
        "validation",
        "attention",
    }
