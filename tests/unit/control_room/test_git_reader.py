"""Tests for control_room.git_reader.GitReader against real temporary Git
repositories (not the live Redline OS repository)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from control_room.git_reader import GitReader
from control_room.models import TrackingStatus, WorkingTreeStatus

_GIT_ENV_ARGS = ["-c", "user.name=Test User", "-c", "user.email=test@example.com"]


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *_GIT_ENV_ARGS, *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "initial commit")
    return path


# -- basic classification ----------------------------------------------------


def test_missing_repository_path_is_not_a_repository(tmp_path):
    status = GitReader(tmp_path / "does-not-exist").read_status()
    assert status.repository_valid is False
    assert status.working_tree == WorkingTreeStatus.NOT_A_REPOSITORY
    assert status.tracking == TrackingStatus.NOT_A_REPOSITORY
    assert status.error


def test_directory_that_is_not_a_git_repository(tmp_path):
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    status = GitReader(plain_dir).read_status()
    assert status.repository_valid is False
    assert status.working_tree == WorkingTreeStatus.NOT_A_REPOSITORY
    assert status.tracking == TrackingStatus.NOT_A_REPOSITORY


def test_clean_repository_with_no_upstream(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    status = GitReader(repo).read_status()

    assert status.repository_valid is True
    assert status.branch == "main"
    assert status.detached_head is False
    assert status.working_tree == WorkingTreeStatus.CLEAN
    assert status.tracking == TrackingStatus.NO_UPSTREAM
    assert status.upstream is None
    assert status.ahead is None
    assert status.behind is None
    assert status.head_sha is not None
    assert status.head_sha_short == status.head_sha[:8]


def test_dirty_repository_from_modified_tracked_file(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    status = GitReader(repo).read_status()
    assert status.working_tree == WorkingTreeStatus.DIRTY


def test_dirty_repository_from_untracked_file(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")
    status = GitReader(repo).read_status()
    assert status.working_tree == WorkingTreeStatus.DIRTY


def test_detached_head(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", head_sha)

    status = GitReader(repo).read_status()
    assert status.detached_head is True
    assert status.branch is None
    assert status.tracking == TrackingStatus.DETACHED_HEAD


# -- tracking: ahead / behind / diverged (local-only, no network) ------------


def _init_tracking_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Bare 'origin' repo + a clone that tracks it -- entirely local files,
    no network access, matching the "no git fetch in production code"
    constraint (fetch here is test *setup*, not something GitReader runs)."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _git(bare, "init", "-q", "--bare", "-b", "main")

    seed = _init_repo(tmp_path / "seed")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-q", "origin", "main")

    clone_path = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(bare), str(clone_path))
    _git(clone_path, "checkout", "-q", "main")
    return bare, clone_path


def test_ahead_of_upstream(tmp_path):
    _, clone = _init_tracking_pair(tmp_path)
    (clone / "new_file.txt").write_text("local only\n", encoding="utf-8")
    _git(clone, "add", "new_file.txt")
    _git(clone, "commit", "-q", "-m", "local commit not yet pushed")

    status = GitReader(clone).read_status()
    assert status.tracking == TrackingStatus.AHEAD
    assert status.ahead == 1
    assert status.behind == 0
    assert status.upstream is not None


def test_behind_upstream(tmp_path):
    bare, clone = _init_tracking_pair(tmp_path)

    other_clone = tmp_path / "other_clone"
    _git(tmp_path, "clone", "-q", str(bare), str(other_clone))
    (other_clone / "remote_file.txt").write_text("pushed by someone else\n", encoding="utf-8")
    _git(other_clone, "add", "remote_file.txt")
    _git(other_clone, "commit", "-q", "-m", "remote-only commit")
    _git(other_clone, "push", "-q", "origin", "main")

    _git(clone, "fetch", "-q", "origin")  # test setup only, not GitReader's job

    status = GitReader(clone).read_status()
    assert status.tracking == TrackingStatus.BEHIND
    assert status.ahead == 0
    assert status.behind == 1


def test_diverged_from_upstream(tmp_path):
    bare, clone = _init_tracking_pair(tmp_path)

    other_clone = tmp_path / "other_clone"
    _git(tmp_path, "clone", "-q", str(bare), str(other_clone))
    (other_clone / "remote_file.txt").write_text("pushed by someone else\n", encoding="utf-8")
    _git(other_clone, "add", "remote_file.txt")
    _git(other_clone, "commit", "-q", "-m", "remote-only commit")
    _git(other_clone, "push", "-q", "origin", "main")

    (clone / "local_file.txt").write_text("local only\n", encoding="utf-8")
    _git(clone, "add", "local_file.txt")
    _git(clone, "commit", "-q", "-m", "local-only commit")
    _git(clone, "fetch", "-q", "origin")  # test setup only, not GitReader's job

    status = GitReader(clone).read_status()
    assert status.tracking == TrackingStatus.DIVERGED
    assert status.ahead == 1
    assert status.behind == 1


def test_synchronized_with_upstream(tmp_path):
    _, clone = _init_tracking_pair(tmp_path)
    status = GitReader(clone).read_status()
    assert status.tracking == TrackingStatus.SYNCHRONIZED
    assert status.ahead == 0
    assert status.behind == 0


# -- commit_exists ------------------------------------------------------------


def test_commit_exists_true_for_head(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert GitReader(repo).commit_exists(head_sha) is True


def test_commit_exists_false_for_unknown_sha(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    assert GitReader(repo).commit_exists("0" * 40) is False


# -- Git unavailable / failure modes ------------------------------------------


def test_git_executable_not_found(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")

    def _raise_not_found(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", _raise_not_found)
    status = GitReader(repo).read_status()
    assert status.repository_valid is False
    assert status.working_tree == WorkingTreeStatus.ERROR
    assert status.tracking == TrackingStatus.ERROR
    assert status.error


def test_git_command_timeout(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5.0)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    status = GitReader(repo).read_status()
    assert status.working_tree == WorkingTreeStatus.ERROR
    assert status.tracking == TrackingStatus.ERROR
