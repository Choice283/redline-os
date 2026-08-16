"""Focused tests for Control Room V0 Mission 7: Checkpoint Change Set
Detail, reachable from the Mission & Checkpoint History section on the
Project Detail screen. Covers service composition -- GET
/api/projects/{project_id} embedding the repository-relative file paths
Git reports for each historical mission's published checkpoint commit --
the served frontend wiring, degraded (unavailable/empty) behavior, non-
contamination of closure `parse_error`, preservation of existing
Mission 5/6 drill-downs, the read-only/no-new-routes invariant, and
compatibility with the real Missions 1-6 checkpoints already published in
this repository. Matches the conventions in test_mission_scope_outcome.py
and test_git_reader.py."""
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from control_room.app import build_service, create_app
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

_CLOSURE_TEMPLATE = """# Control Room V0 Mission {number} Closure

## Purpose

Test mission {number}.

## Published Checkpoint

SHA:
`{sha}`

## Delivered Capability

- Delivered a thing.

## Deferred Work

- Deferred a thing.

## Validation

- Tests passed.

## Independent Review

PASS.

## Closure

Control Room V0 Mission {number} is formally closed.
"""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *_GIT_ENV_ARGS, *args], cwd=cwd, capture_output=True, text=True, check=True)


def _build_client(tmp_path: Path):
    """Fixture repo with three missions: Mission 1's checkpoint changes a
    real tracked file (normal case), Mission 2's checkpoint is an empty
    commit (legitimately empty change set), Mission 3's checkpoint SHA
    was never committed anywhere (unavailable/unresolved case)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")
    mission_1_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _git(repo, "commit", "-q", "--allow-empty", "-m", "empty commit for mission 2")
    mission_2_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    mission_3_sha_unresolvable = "f" * 40

    state = dict(_STATE)
    state["latest_checkpoint"] = dict(_STATE["latest_checkpoint"])
    state["latest_checkpoint"]["commit"] = mission_1_sha
    state_dir = repo / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")

    (state_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        _CLOSURE_TEMPLATE.format(number=1, sha=mission_1_sha), encoding="utf-8"
    )
    (state_dir / "MISSION_2_CLOSURE_2026-08-10.md").write_text(
        _CLOSURE_TEMPLATE.format(number=2, sha=mission_2_sha), encoding="utf-8"
    )
    (state_dir / "MISSION_3_CLOSURE_2026-08-15.md").write_text(
        _CLOSURE_TEMPLATE.format(number=3, sha=mission_3_sha_unresolvable), encoding="utf-8"
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


# -- correct service composition / normal change set ------------------------


def test_project_snapshot_embeds_checkpoint_change_set_for_normal_commit(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}

    mission_1 = history[1]
    assert mission_1["checkpoint_changed_files"] == ["README.md"]
    assert mission_1["checkpoint_changes_error"] is None


# -- explicit empty state -----------------------------------------------------


def test_legitimately_empty_change_set_is_explicit_not_an_error(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}

    mission_2 = history[2]
    assert mission_2["checkpoint_changed_files"] == []
    assert mission_2["checkpoint_changes_error"] is None


# -- explicit unavailable state ----------------------------------------------


def test_unresolved_checkpoint_yields_unavailable_change_set(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}

    mission_3 = history[3]
    assert mission_3["checkpoint_resolved"] is False
    assert mission_3["checkpoint_changed_files"] is None
    assert mission_3["checkpoint_changes_error"]


# -- merge checkpoint degrades explicitly, without breaking other detail ----
# -- sections or other history entries (correction round regression) -------


def _build_client_with_merge_checkpoint(tmp_path: Path):
    """Mission 1: normal one-parent checkpoint. Mission 2: a real,
    non-trivial merge checkpoint (two diverged branches, --no-ff) that
    genuinely introduces a file. Proves a merge checkpoint degrades in
    isolation -- it must not affect Mission 1's rendering, and Mission 2's
    own Mission Scope & Outcome / Validation & Evidence sections must
    still render normally despite its change set being unavailable."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")
    mission_1_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "feature_file.txt").write_text("from feature\n", encoding="utf-8")
    _git(repo, "add", "feature_file.txt")
    _git(repo, "commit", "-q", "-m", "feature commit")

    _git(repo, "checkout", "-q", "main")
    (repo / "main_file.txt").write_text("from main\n", encoding="utf-8")
    _git(repo, "add", "main_file.txt")
    _git(repo, "commit", "-q", "-m", "main-only commit")

    _git(repo, "merge", "-q", "--no-ff", "-m", "merge feature into main", "feature")
    mission_2_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    state = dict(_STATE)
    state["latest_checkpoint"] = dict(_STATE["latest_checkpoint"])
    state["latest_checkpoint"]["commit"] = mission_1_sha
    state_dir = repo / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")

    (state_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        _CLOSURE_TEMPLATE.format(number=1, sha=mission_1_sha), encoding="utf-8"
    )
    (state_dir / "MISSION_2_CLOSURE_2026-08-10.md").write_text(
        _CLOSURE_TEMPLATE.format(number=2, sha=mission_2_sha), encoding="utf-8"
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
    return TestClient(app), mission_2_sha


def test_merge_checkpoint_degrades_without_breaking_other_entries_or_sections(tmp_path):
    client, merge_sha = _build_client_with_merge_checkpoint(tmp_path)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}

    # The merge checkpoint itself: unavailable, explicit, never [].
    mission_2 = history[2]
    assert mission_2["checkpoint_commit"] == merge_sha
    assert mission_2["checkpoint_resolved"] is True
    assert mission_2["checkpoint_changed_files"] is None
    assert mission_2["checkpoint_changes_error"]
    assert "merge" in mission_2["checkpoint_changes_error"].lower()
    assert mission_2["parse_error"] is None  # not a closure-parsing problem

    # Mission 2's other detail sections are unaffected by the merge
    # change-set outcome.
    assert "Test mission 2" in mission_2["purpose_section"]
    assert "Delivered a thing" in mission_2["delivered_capability_section"]
    assert "Tests passed" in mission_2["validation_section"]

    # Mission 1 (an unrelated, normal, one-parent checkpoint) is completely
    # unaffected by Mission 2's merge commit.
    mission_1 = history[1]
    assert mission_1["checkpoint_changed_files"] == ["README.md"]
    assert mission_1["checkpoint_changes_error"] is None
    assert mission_1["parse_error"] is None


# -- no contamination of closure parse_error ---------------------------------


def test_change_set_outcomes_never_set_closure_parse_error(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}

    for mission_number in (1, 2, 3):
        assert history[mission_number]["parse_error"] is None, (
            f"mission {mission_number}: change-set outcome must not set parse_error"
        )


# -- existing Mission 5/6 drill-downs remain unchanged -----------------------


def test_mission_scope_outcome_and_validation_evidence_unchanged(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    history = {entry["mission_number"]: entry for entry in response.json()["mission_history"]}

    mission_1 = history[1]
    assert "Test mission 1" in mission_1["purpose_section"]
    assert "Delivered a thing" in mission_1["delivered_capability_section"]
    assert "Deferred a thing" in mission_1["deferred_work_section"]
    assert "Tests passed" in mission_1["validation_section"]
    assert "PASS" in mission_1["independent_review_section"]


# -- Project Detail rendering: served JS wires up the change-set drill-down -


def test_app_js_renders_checkpoint_change_set_drill_down(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/static/app.js")
    assert response.status_code == 200
    script = response.text
    assert "checkpoint_changed_files" in script
    assert "checkpoint_changes_error" in script
    assert "Checkpoint Change Set Detail" in script
    # All three drill-downs must coexist.
    assert "Mission Scope &amp; Outcome Detail" in script
    assert "Validation &amp; Evidence Detail" in script
    assert script.count("<details") >= 3
    # Safe rendering: paths are escaped, not interpolated raw.
    assert "escapeHtml(path)" in script


# -- read-only behavior / zero new mutation routes (Mission 7 added none) --


def test_checkpoint_change_set_feature_introduced_no_new_routes(tmp_path):
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


def test_project_state_yaml_still_not_the_change_set_source(tmp_path):
    """PROJECT_STATE.yaml has no change-set fields in its schema --
    Checkpoint Change Set Detail must come only from live Git."""
    client = _build_client(tmp_path)
    response = client.get("/api/projects/example-project")
    state = response.json()["state"]
    assert "checkpoint_changed_files" not in state
    assert set(state.keys()) == {
        "project_id",
        "summary",
        "current_mission",
        "latest_checkpoint",
        "validation",
        "attention",
    }


# -- real Missions 1-6 historical checkpoint compatibility ------------------


def test_real_mission_1_through_6_checkpoints_have_a_determined_change_set():
    """Every real, published Missions 1-6 checkpoint is a real commit in
    this repository -- each must yield either a non-empty or a
    legitimately empty change set, never an unavailable one, and never
    contaminate parse_error."""
    service = build_service()
    snapshot = service.get_snapshot("redline-os")
    by_number = {entry.mission_number: entry for entry in snapshot.mission_history}

    for mission_number in (1, 2, 3, 4, 5, 6):
        assert mission_number in by_number, f"Mission {mission_number} not found in history"
        entry = by_number[mission_number]
        assert entry.parse_error is None, f"Mission {mission_number}: {entry.parse_error}"
        assert entry.checkpoint_resolved is True, f"Mission {mission_number}: checkpoint did not resolve"
        assert entry.checkpoint_changes_error is None, (
            f"Mission {mission_number}: {entry.checkpoint_changes_error}"
        )
        assert entry.checkpoint_changed_files is not None, f"Mission {mission_number}: change set unavailable"
        assert len(entry.checkpoint_changed_files) > 0, (
            f"Mission {mission_number}: expected a non-empty change set for a real feature/docs commit"
        )
