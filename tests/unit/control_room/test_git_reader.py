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


# -- read_commit_changed_files (Mission 7) ------------------------------------


def test_changed_files_for_root_commit(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    paths, error = GitReader(repo).read_commit_changed_files(head_sha)

    assert error is None
    assert paths == ["README.md"]


def test_changed_files_for_commit_with_multiple_files(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "a.txt", "b.txt")
    _git(repo, "commit", "-q", "-m", "add two files")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    paths, error = GitReader(repo).read_commit_changed_files(head_sha)

    assert error is None
    assert sorted(paths) == ["a.txt", "b.txt"]


def test_changed_files_are_repository_relative_paths(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    nested = repo / "sub" / "dir"
    nested.mkdir(parents=True)
    (nested / "nested.txt").write_text("nested\n", encoding="utf-8")
    _git(repo, "add", "sub/dir/nested.txt")
    _git(repo, "commit", "-q", "-m", "add nested file")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    paths, error = GitReader(repo).read_commit_changed_files(head_sha)

    assert error is None
    assert paths == ["sub/dir/nested.txt"]


def test_changed_files_with_spaces_in_filename_are_not_split(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "a file with spaces.txt").write_text("content\n", encoding="utf-8")
    _git(repo, "add", "a file with spaces.txt")
    _git(repo, "commit", "-q", "-m", "add file with spaces")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    paths, error = GitReader(repo).read_commit_changed_files(head_sha)

    assert error is None
    assert paths == ["a file with spaces.txt"]


def test_changed_files_empty_change_set_is_not_an_error(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "empty commit")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    paths, error = GitReader(repo).read_commit_changed_files(head_sha)

    assert error is None
    assert paths == []


def test_changed_files_unknown_commit_returns_unavailable(tmp_path):
    repo = _init_repo(tmp_path / "repo")

    paths, error = GitReader(repo).read_commit_changed_files("0" * 40)

    assert paths is None
    assert error


def test_changed_files_rejects_non_sha_revision_without_invoking_git(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("git must not be invoked for a non-SHA revision")

    monkeypatch.setattr(subprocess, "run", _fail_if_called)

    for revision in ("main", "HEAD", "HEAD~1", "--upload-pack=/bin/sh", "not a sha", ""):
        paths, error = GitReader(repo).read_commit_changed_files(revision)
        assert paths is None
        assert error


def test_changed_files_git_command_failure_degrades_without_raising(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5.0)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    paths, error = GitReader(repo).read_commit_changed_files(head_sha)

    assert paths is None
    assert error


def test_merge_commit_change_set_is_unavailable_not_empty(tmp_path):
    """Correction round (Codex finding): `git diff-tree` without an
    explicit merge diff strategy can under-report or omit files a merge
    actually introduced -- that must never collapse into "legitimate
    empty commit". A non-trivial three-way merge (both branches diverged,
    not a fast-forward) must degrade as unavailable, never as []."""
    repo = _init_repo(tmp_path / "repo")

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "feature_file.txt").write_text("from feature branch\n", encoding="utf-8")
    _git(repo, "add", "feature_file.txt")
    _git(repo, "commit", "-q", "-m", "feature commit")
    feature_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _git(repo, "checkout", "-q", "main")
    (repo / "main_file.txt").write_text("from main branch\n", encoding="utf-8")
    _git(repo, "add", "main_file.txt")
    _git(repo, "commit", "-q", "-m", "main-only commit")

    _git(repo, "merge", "-q", "--no-ff", "-m", "merge feature into main", "feature")
    merge_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # Sanity: this really is a non-trivial two-parent merge that
    # introduces feature_file.txt into main.
    parents = _git(repo, "rev-list", "--parents", "-n", "1", merge_sha).stdout.split()
    assert len(parents) - 1 == 2
    assert (repo / "feature_file.txt").is_file()
    reader = GitReader(repo)
    assert reader.commit_exists(merge_sha) is True
    assert reader.commit_exists(feature_sha) is True

    paths, error = reader.read_commit_changed_files(merge_sha)

    assert paths is None
    assert error is not None
    assert "merge" in error.lower()

    # A normal, non-merge commit is unaffected by the merge-detection path.
    normal_paths, normal_error = reader.read_commit_changed_files(feature_sha)
    assert normal_error is None
    assert normal_paths == ["feature_file.txt"]


def test_malformed_rev_list_output_is_unavailable_not_diff_tree(tmp_path, monkeypatch):
    """Correction round (Codex finding): a successful (exit 0) `git
    rev-list --parents -n 1` is not trusted at face value -- its output
    must be validated as whitespace-separated full 40-hex-char SHA tokens
    before being interpreted as a parent count. Malformed output (e.g. a
    `rev-list` that somehow prints "not-a-sha") must degrade explicitly,
    never be guessed at as root/normal/merge, and must never fall through
    to `diff-tree`."""
    repo = _init_repo(tmp_path / "repo")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    def _fake_run(args, **kwargs):
        if "rev-list" in args:
            return subprocess.CompletedProcess(args, returncode=0, stdout="not-a-sha\n", stderr="")
        if "diff-tree" in args:
            raise AssertionError("diff-tree must not be invoked when rev-list output is malformed")
        raise AssertionError(f"unexpected git invocation in this test: {args}")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    paths, error = GitReader(repo).read_commit_changed_files(head_sha)

    assert paths is None
    assert paths != []
    assert error is not None
