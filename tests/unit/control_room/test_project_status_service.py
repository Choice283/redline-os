"""Tests for control_room.project_status_service.ProjectStatusService --
composition of ProjectDefinition + live GitStatus + ProjectState into
ProjectSnapshot, and the derived `attention` signal."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from control_room.models import TrackingStatus, WorkingTreeStatus
from control_room.project_registry import ProjectRegistry
from control_room.project_status_service import ProjectNotFoundError, ProjectStatusService
from control_room.state_reader import StateReader

_GIT_ENV_ARGS = ["-c", "user.name=Test User", "-c", "user.email=test@example.com"]

_VALID_STATE = {
    "project_id": "example-project",
    "summary": "Example project for tests.",
    "current_mission": {"id": "m1", "title": "Mission 1", "phase": "implementation"},
    "latest_checkpoint": {"label": "Checkpoint 1", "commit": None, "document": "docs/CHECKPOINT.md"},
    "validation": {"status": "pass_with_exception", "summary": "Independent audit passed; CI red (documented)."},
    "attention": {"required": False, "reason": None},
}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *_GIT_ENV_ARGS, *args], cwd=cwd, capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "initial commit")
    return _git(path, "rev-parse", "HEAD").stdout.strip()


def _build_fixture(tmp_path: Path, state_overrides: dict | None = None, write_state: bool = True) -> ProjectStatusService:
    repo_path = tmp_path / "repo"
    checkpoint_sha = _init_repo(repo_path)

    state_data = dict(_VALID_STATE)
    state_data["latest_checkpoint"] = dict(_VALID_STATE["latest_checkpoint"])
    state_data["latest_checkpoint"]["commit"] = checkpoint_sha
    if state_overrides:
        for key, value in state_overrides.items():
            state_data[key] = value

    if write_state:
        # Committed (not left untracked) so the working tree stays CLEAN
        # after fixture setup -- state_file lives inside the repo, just
        # like docs/control_room/PROJECT_STATE.yaml does for real. This
        # also means the checkpoint commit legitimately precedes current
        # HEAD, matching the real V1-checkpoint-vs-post-V1-HEAD situation
        # this service must not treat as an attention trigger by itself.
        state_dir = repo_path / "docs" / "control_room"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state_data), encoding="utf-8")
        _git(repo_path, "add", "docs/control_room/PROJECT_STATE.yaml")
        _git(repo_path, "commit", "-q", "-m", "add project state")

    registry_dir = tmp_path / "config" / "control_room"
    registry_dir.mkdir(parents=True, exist_ok=True)
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
    return ProjectStatusService(registry, state_reader=StateReader())


def test_successful_snapshot_composition(tmp_path):
    service = _build_fixture(tmp_path)
    snapshot = service.get_snapshot("example-project")

    assert snapshot.project_id == "example-project"
    assert snapshot.name == "Example Project"
    assert snapshot.state is not None
    assert snapshot.state_error is None
    assert snapshot.attention.required is False


def test_semantic_state_and_live_git_are_both_present_and_independent(tmp_path):
    service = _build_fixture(tmp_path)
    snapshot = service.get_snapshot("example-project")

    # Git facts come from GitReader, not from the YAML.
    assert snapshot.git.repository_valid is True
    assert snapshot.git.branch == "main"
    assert snapshot.git.working_tree == WorkingTreeStatus.CLEAN
    assert snapshot.git.head_sha is not None

    # Semantic facts come from PROJECT_STATE.yaml, not from Git.
    assert snapshot.state.current_mission.title == "Mission 1"
    assert snapshot.state.summary == "Example project for tests."


def test_attention_caused_by_dirty_working_tree(tmp_path):
    service = _build_fixture(tmp_path)
    (tmp_path / "repo" / "README.md").write_text("modified\n", encoding="utf-8")

    snapshot = service.get_snapshot("example-project")

    assert snapshot.git.working_tree == WorkingTreeStatus.DIRTY
    assert snapshot.attention.required is True
    assert "dirty" in snapshot.attention.reason.lower()


def test_attention_caused_by_missing_state_file(tmp_path):
    service = _build_fixture(tmp_path, write_state=False)

    snapshot = service.get_snapshot("example-project")

    assert snapshot.state is None
    assert snapshot.state_error is not None
    assert snapshot.attention.required is True


def test_attention_caused_by_invalid_checkpoint_commit(tmp_path):
    service = _build_fixture(tmp_path, state_overrides={
        "latest_checkpoint": {"label": "Bad checkpoint", "commit": "0" * 40, "document": "docs/CHECKPOINT.md"}
    })

    snapshot = service.get_snapshot("example-project")

    assert snapshot.attention.required is True
    assert "checkpoint" in snapshot.attention.reason.lower()


def test_preserves_pass_with_exception_validation_state_without_forcing_attention(tmp_path):
    service = _build_fixture(tmp_path)
    snapshot = service.get_snapshot("example-project")

    assert snapshot.state.validation.status == "pass_with_exception"
    assert "CI" in snapshot.state.validation.summary
    # A documented pass_with_exception + clean/synchronized Git does not,
    # by itself, force overall attention.
    assert snapshot.attention.required is False


def test_unknown_project_id_raises(tmp_path):
    service = _build_fixture(tmp_path)
    with pytest.raises(ProjectNotFoundError):
        service.get_snapshot("does-not-exist")


def test_list_snapshots_returns_all_registered_projects(tmp_path):
    service = _build_fixture(tmp_path)
    snapshots = service.list_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0].project_id == "example-project"
