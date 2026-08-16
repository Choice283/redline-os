"""Focused tests for Control Room V0 Mission 9: Closed-State Currency.

Answers one question -- has the repository moved beyond the latest
formally closed Control Room state? -- via a fixed source-of-truth chain:
PROJECT_STATE.yaml's `latest_checkpoint.document` -> two-layer closure-
path validation -> a read-only Git-resolved introduction commit -> a
comparison against live HEAD. Covers GitReader's two new read-only
methods in isolation, the two-layer path-validation helpers in
project_status_service.py in isolation, full service/API composition for
all four locked states (CURRENT/AHEAD/NOT_ANCESTOR/UNAVAILABLE), the
no-attention / no-new-route / no-Git-in-MissionHistoryReader invariants,
and a real-repository proof against the actual Redline OS repository this
suite lives in. Matches the conventions in test_git_reader.py and
test_checkpoint_change_set.py.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from control_room.app import create_app
from control_room.git_reader import GitReader
from control_room.models import ClosedStateCurrencyStatus
from control_room.project_registry import ProjectRegistry
from control_room.project_status_service import (
    ProjectStatusService,
    _closure_path_is_proven,
    _validate_canonical_closure_path,
)
from control_room.state_reader import StateReader

_GIT_ENV_ARGS = ["-c", "user.name=Test User", "-c", "user.email=test@example.com"]


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *_GIT_ENV_ARGS, *args], cwd=cwd, capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "initial commit")
    return path


# =============================================================================
# GitReader.read_path_introduction_commit()
# =============================================================================


def test_read_path_introduction_commit_exactly_one_addition(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "docs").mkdir()
    (repo / "docs" / "CLOSURE.md").write_text("closure\n", encoding="utf-8")
    _git(repo, "add", "docs/CLOSURE.md")
    _git(repo, "commit", "-q", "-m", "add closure doc")
    expected_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    (repo / "README.md").write_text("changed again\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "unrelated later commit")

    commit, error = GitReader(repo).read_path_introduction_commit("docs/CLOSURE.md")
    assert error is None
    assert commit == expected_sha


def test_read_path_introduction_commit_zero_additions_is_unavailable(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    commit, error = GitReader(repo).read_path_introduction_commit("docs/never_existed.md")
    assert commit is None
    assert error
    assert "no commit" in error.lower()


def test_read_path_introduction_commit_two_additions_is_ambiguous(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "docs").mkdir()
    doc = repo / "docs" / "CLOSURE.md"

    doc.write_text("first\n", encoding="utf-8")
    _git(repo, "add", "docs/CLOSURE.md")
    _git(repo, "commit", "-q", "-m", "first add")

    _git(repo, "rm", "-q", "docs/CLOSURE.md")
    _git(repo, "commit", "-q", "-m", "delete")

    (repo / "docs").mkdir(exist_ok=True)
    doc.write_text("second\n", encoding="utf-8")
    _git(repo, "add", "docs/CLOSURE.md")
    _git(repo, "commit", "-q", "-m", "second add")

    commit, error = GitReader(repo).read_path_introduction_commit("docs/CLOSURE.md")
    assert commit is None
    assert error
    assert "more than one" in error.lower()


def test_read_path_introduction_commit_malformed_git_output_is_unavailable(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    reader = GitReader(repo)

    def fake_run(self, args):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="not-a-sha\n", stderr="")

    monkeypatch.setattr(GitReader, "_run", fake_run)
    commit, error = reader.read_path_introduction_commit("docs/CLOSURE.md")
    assert commit is None
    assert error


def test_read_path_introduction_commit_invocation_shape(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    reader = GitReader(repo)
    captured = {}

    def fake_run(self, args):
        captured["args"] = args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(GitReader, "_run", fake_run)
    reader.read_path_introduction_commit("docs/CLOSURE.md")

    args = captured["args"]
    assert args[0] == "--literal-pathspecs"
    assert args[1] == "log"
    assert "--no-renames" in args
    assert "--diff-filter=A" in args
    assert "HEAD" in args
    assert "--" in args
    assert args[args.index("--") + 1] == "docs/CLOSURE.md"
    assert "-1" not in args


# =============================================================================
# GitReader.read_closed_state_currency()
# =============================================================================


def test_read_closed_state_currency_ancestor_zero_commits_beyond(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    is_ancestor, count, error = GitReader(repo).read_closed_state_currency(head, head)
    assert is_ancestor is True
    assert count == 0
    assert error is None


def test_read_closed_state_currency_ancestor_with_commits_beyond(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    closed_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    for i in range(3):
        (repo / f"file_{i}.txt").write_text("x\n", encoding="utf-8")
        _git(repo, "add", f"file_{i}.txt")
        _git(repo, "commit", "-q", "-m", f"commit {i}")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    is_ancestor, count, error = GitReader(repo).read_closed_state_currency(closed_sha, head)
    assert is_ancestor is True
    assert count == 3
    assert error is None


def test_read_closed_state_currency_not_ancestor_skips_count(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    first_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # A second, unrelated root commit via an orphan branch -- not an
    # ancestor of `first_sha`, and vice versa.
    _git(repo, "checkout", "-q", "--orphan", "other")
    _git(repo, "rm", "-q", "-rf", ".")
    (repo / "other.txt").write_text("other\n", encoding="utf-8")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "-q", "-m", "unrelated root commit")
    other_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    reader = GitReader(repo)
    calls = []
    real_run = GitReader._run

    def spying_run(self, args):
        calls.append(args)
        return real_run(self, args)

    monkeypatch.setattr(GitReader, "_run", spying_run)

    is_ancestor, count, error = reader.read_closed_state_currency(first_sha, other_sha)
    assert is_ancestor is False
    assert count is None
    assert error is None
    assert not any(args[0] == "rev-list" for args in calls)


def test_read_closed_state_currency_merge_base_hard_failure_is_unavailable(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    real_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    fake_sha = "a" * 40  # well-formed hex, but never committed -- merge-base fails hard

    is_ancestor, count, error = GitReader(repo).read_closed_state_currency(fake_sha, real_sha)
    assert is_ancestor is None
    assert count is None
    assert error


def test_read_closed_state_currency_rejects_non_sha_revisions(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    is_ancestor, count, error = GitReader(repo).read_closed_state_currency("main", "HEAD")
    assert is_ancestor is None
    assert count is None
    assert error


@pytest.mark.parametrize(
    "stdout,expected_count",
    [
        ("0\n", 0),
        ("5\n", 5),
    ],
)
def test_read_closed_state_currency_count_parsing_valid(tmp_path, monkeypatch, stdout, expected_count):
    repo = _init_repo(tmp_path / "repo")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    reader = GitReader(repo)
    real_run = GitReader._run

    def fake_run(self, args):
        if args[0] == "rev-list":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")
        return real_run(self, args)

    monkeypatch.setattr(GitReader, "_run", fake_run)
    is_ancestor, count, error = reader.read_closed_state_currency(head, head)
    assert is_ancestor is True
    assert count == expected_count
    assert error is None


@pytest.mark.parametrize(
    "stdout",
    [
        "-1\n",
        "3 4\n",
        "abc\n",
        "\n",
        "",
        "3.5\n",
        # Independent-review regression (confirmed MEDIUM finding): Python's
        # `str.isdigit()` accepts non-ASCII Unicode digit characters that
        # `int()` then rejects with an uncaught `ValueError` -- e.g. U+00B2
        # SUPERSCRIPT TWO ("²".isdigit() is True, but int("²")
        # raises. Before the fix this crashed `read_closed_state_currency()`
        # instead of degrading; this case proves it no longer does.
        "²\n",
        "²",
    ],
)
def test_read_closed_state_currency_count_parsing_malformed(tmp_path, monkeypatch, stdout):
    repo = _init_repo(tmp_path / "repo")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    reader = GitReader(repo)
    real_run = GitReader._run

    def fake_run(self, args):
        if args[0] == "rev-list":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")
        return real_run(self, args)

    monkeypatch.setattr(GitReader, "_run", fake_run)
    is_ancestor, count, error = reader.read_closed_state_currency(head, head)
    assert is_ancestor is True  # ancestry was still proven
    assert count is None
    assert error


def test_read_closed_state_currency_subprocess_failure_is_unavailable(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    reader = GitReader(repo)

    def fake_run(self, args):
        return None  # mirrors GitReader._run()'s own timeout/missing-git/OSError sentinel

    monkeypatch.setattr(GitReader, "_run", fake_run)
    is_ancestor, count, error = reader.read_closed_state_currency(head, head)
    assert is_ancestor is None
    assert count is None
    assert error


# =============================================================================
# Layer 1: strict canonical closure-path syntax validation
# =============================================================================


@pytest.mark.parametrize(
    "path",
    [
        "",
        "docs/control_room/\x00evil.md",
        "C:\\Users\\pj198\\evil.md",
        "/etc/passwd",
        "//server/share/evil.md",
        "C:evil.md",
        "\\\\server\\share\\evil.md",
        "docs/../../../etc/passwd",
        "docs/./control_room/CLOSURE.md",
        "docs\\control_room\\CLOSURE.md",
        "docs//control_room/CLOSURE.md",
        "docs/control_room/CLOSURE.md/",
        "-docs/control_room/CLOSURE.md",
        ":(icase)docs/control_room/CLOSURE.md",
        ":docs/control_room/CLOSURE.md",
        "docs/control_room//CLOSURE.md",
    ],
)
def test_canonical_path_validation_rejects_malformed_forms(path):
    assert _validate_canonical_closure_path(path) is not None


@pytest.mark.parametrize(
    "path",
    [
        "docs/control_room/MISSION_8_CLOSURE_2026-08-16.md",
        "CLOSURE.md",
        "a/b/c.md",
    ],
)
def test_canonical_path_validation_accepts_canonical_forms(path):
    assert _validate_canonical_closure_path(path) is None


# =============================================================================
# Layer 2: independently discovered, provably repository-relative membership
# =============================================================================


def _make_history_entry(closure_document: str):
    from control_room.models import MissionHistoryEntry

    return MissionHistoryEntry(mission_number=1, closure_document=closure_document, status="closed")


def test_layer_two_accepts_path_matching_discovered_real_file(tmp_path):
    repo = tmp_path / "repo"
    history_dir = repo / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text("x", encoding="utf-8")

    candidate = "docs/control_room/MISSION_1_CLOSURE_2026-08-01.md"
    entries = [_make_history_entry(candidate)]

    assert _closure_path_is_proven(candidate, repo, history_dir, entries) is True


def test_layer_two_rejects_syntactically_valid_path_not_in_discovered_set(tmp_path):
    repo = tmp_path / "repo"
    history_dir = repo / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text("x", encoding="utf-8")

    candidate = "docs/control_room/MISSION_9_CLOSURE_2026-08-16.md"  # never discovered
    entries = [_make_history_entry("docs/control_room/MISSION_1_CLOSURE_2026-08-01.md")]

    assert _closure_path_is_proven(candidate, repo, history_dir, entries) is False


def test_layer_two_rejects_fallback_bare_filename_even_if_string_matches(tmp_path):
    """Simulates MissionHistoryReader's own defensive fallback: an entry
    whose `closure_document` is a bare filename (no directory component)
    because the file could not be proven to live under `repository_path`.
    Even though the candidate string matches that entry exactly, Layer 2
    must not accept it as a Git path, because independently resolving
    `repository_path / candidate` does not land inside `history_dir`."""
    repo = tmp_path / "repo"
    history_dir = repo / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    # No file exists at repo/MISSION_1_CLOSURE_2026-08-01.md (repo root) --
    # only the bare-filename *string* was ever recorded by the fallback.
    entries = [_make_history_entry("MISSION_1_CLOSURE_2026-08-01.md")]

    candidate = "MISSION_1_CLOSURE_2026-08-01.md"
    assert _closure_path_is_proven(candidate, repo, history_dir, entries) is False


def test_layer_two_rejects_path_outside_history_dir_even_if_real_file(tmp_path):
    repo = tmp_path / "repo"
    history_dir = repo / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    other_dir = repo / "elsewhere"
    other_dir.mkdir()
    (other_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text("x", encoding="utf-8")

    candidate = "elsewhere/MISSION_1_CLOSURE_2026-08-01.md"
    entries = [_make_history_entry(candidate)]  # hypothetically matches, but wrong directory

    assert _closure_path_is_proven(candidate, repo, history_dir, entries) is False


def test_layer_two_rejects_path_that_does_not_exist_on_disk(tmp_path):
    repo = tmp_path / "repo"
    history_dir = repo / "docs" / "control_room"
    history_dir.mkdir(parents=True)

    candidate = "docs/control_room/MISSION_1_CLOSURE_2026-08-01.md"
    entries = [_make_history_entry(candidate)]  # matches string, but file was never written

    assert _closure_path_is_proven(candidate, repo, history_dir, entries) is False


# =============================================================================
# Full service/API composition -- all four locked states
# =============================================================================

_STATE_TEMPLATE = {
    "project_id": "example-project",
    "summary": "Example project for tests.",
    "current_mission": {"id": "m1", "title": "Mission 1", "phase": "complete"},
    "latest_checkpoint": {"label": "Checkpoint 1", "commit": "placeholder", "document": "placeholder"},
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

## Closure

Control Room V0 Mission {number} is formally closed.
"""


def _write_registry(tmp_path: Path) -> ProjectRegistry:
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
    return ProjectRegistry(registry_path, base_dir=tmp_path)


def _build_client(tmp_path: Path, closure_document_commits_ahead: int = 0):
    """Fixture repo whose mission closure document and PROJECT_STATE.yaml
    are committed together in one commit (so that commit is both the
    closure document's Git-resolved introduction commit *and* the
    recorded closed state), optionally followed by further commits to
    exercise AHEAD. `closure_document_commits_ahead == 0` exercises
    CURRENT."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")
    initial_commit_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    state_dir = repo / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    closure_document = "docs/control_room/MISSION_1_CLOSURE_2026-08-01.md"
    (state_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        _CLOSURE_TEMPLATE.format(number=1, sha="0" * 40), encoding="utf-8"
    )
    state = dict(_STATE_TEMPLATE)
    state["latest_checkpoint"] = {
        # A real, always-resolvable commit unrelated to Mission 9's own
        # document-path chain -- so `_checkpoint_valid()` (pre-existing,
        # Mission-8-and-earlier behavior) never contributes an unrelated
        # attention reason that would contaminate these Mission 9 tests.
        "label": "Checkpoint 1",
        "commit": initial_commit_sha,
        "document": closure_document,
    }
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")
    _git(repo, "add", "docs/control_room")
    _git(repo, "commit", "-q", "-m", "add closure document and project state")
    closed_state_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    for i in range(closure_document_commits_ahead):
        (repo / f"file_{i}.txt").write_text("x\n", encoding="utf-8")
        _git(repo, "add", f"file_{i}.txt")
        _git(repo, "commit", "-q", "-m", f"commit {i}")

    registry = _write_registry(tmp_path)
    service = ProjectStatusService(registry, state_reader=StateReader())
    app = create_app(service=service)
    return TestClient(app), closed_state_sha


def _build_not_ancestor_client(tmp_path: Path, monkeypatch):
    """Because the closed-state commit is resolved via `git log HEAD --
    <path>`, it is only ever found among commits reachable from
    *that same, freshly-read* HEAD -- so it can never organically be a
    non-ancestor of a HEAD read moments earlier in the same request,
    barring an external, out-of-band repository mutation between the two
    independent Git reads (e.g. another process switching branches or
    resetting HEAD mid-request). This fixture simulates exactly that
    narrow race deterministically: it builds a real repository, resolves
    a real closed-state commit and a real, genuinely unrelated commit,
    then patches `GitReader.read_status()` to report the unrelated
    commit as `head_sha` -- so the rest of the composition (including the
    actual `git merge-base --is-ancestor` call) runs unmodified and for
    real."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")
    initial_commit_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    state_dir = repo / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    closure_document = "docs/control_room/MISSION_1_CLOSURE_2026-08-01.md"
    (state_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        _CLOSURE_TEMPLATE.format(number=1, sha="0" * 40), encoding="utf-8"
    )
    state = dict(_STATE_TEMPLATE)
    state["latest_checkpoint"] = {
        "label": "Checkpoint 1",
        "commit": initial_commit_sha,
        "document": closure_document,
    }
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")
    _git(repo, "add", "docs/control_room")
    _git(repo, "commit", "-q", "-m", "add closure document and project state")
    closed_state_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _git(repo, "checkout", "-q", "--orphan", "unrelated")
    _git(repo, "rm", "-q", "-rf", ".")
    (repo / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    _git(repo, "add", "unrelated.txt")
    _git(repo, "commit", "-q", "-m", "unrelated root commit, never a descendant of closed_state_sha")
    unrelated_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", "main")

    real_read_status = GitReader.read_status

    def patched_read_status(self):
        status = real_read_status(self)
        return status.model_copy(update={"head_sha": unrelated_sha})

    monkeypatch.setattr(GitReader, "read_status", patched_read_status)

    registry = _write_registry(tmp_path)
    service = ProjectStatusService(registry, state_reader=StateReader())
    app = create_app(service=service)
    return TestClient(app), closed_state_sha


def test_current_state_zero_commits_beyond(tmp_path):
    client, closed_state_sha = _build_client(tmp_path, closure_document_commits_ahead=0)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    currency = response.json()["closed_state_currency"]

    assert currency["status"] == "CURRENT"
    assert currency["closed_state_commit"] == closed_state_sha
    assert currency["commits_since_closed_state"] == 0


def test_ahead_state_exact_count(tmp_path):
    client, closed_state_sha = _build_client(tmp_path, closure_document_commits_ahead=4)
    response = client.get("/api/projects/example-project")
    currency = response.json()["closed_state_currency"]

    assert currency["status"] == "AHEAD"
    assert currency["closed_state_commit"] == closed_state_sha
    assert currency["commits_since_closed_state"] == 4


def test_not_ancestor_state_has_no_count(tmp_path, monkeypatch):
    client, closed_state_sha = _build_not_ancestor_client(tmp_path, monkeypatch)
    response = client.get("/api/projects/example-project")
    currency = response.json()["closed_state_currency"]

    assert currency["status"] == "NOT_ANCESTOR"
    assert currency["closed_state_commit"] == closed_state_sha
    assert currency["commits_since_closed_state"] is None
    assert currency["detail"]


def test_unavailable_state_when_configured_document_path_is_malformed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")

    state_dir = repo / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    state = dict(_STATE_TEMPLATE)
    state["latest_checkpoint"] = {
        "label": "Checkpoint 1",
        "commit": _git(repo, "rev-parse", "HEAD").stdout.strip(),
        "document": "../outside/CLOSURE.md",
    }
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")
    _git(repo, "add", "docs/control_room/PROJECT_STATE.yaml")
    _git(repo, "commit", "-q", "-m", "record project state")

    registry = _write_registry(tmp_path)
    service = ProjectStatusService(registry, state_reader=StateReader())
    app = create_app(service=service)
    client = TestClient(app)

    response = client.get("/api/projects/example-project")
    currency = response.json()["closed_state_currency"]
    assert currency["status"] == "UNAVAILABLE"
    assert currency["closed_state_commit"] is None
    assert currency["detail"]


def test_unavailable_state_when_configured_document_is_not_a_discovered_entry(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")

    state_dir = repo / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    # No MISSION_*_CLOSURE_*.md file exists at all -- MissionHistoryReader
    # will discover zero entries, so nothing can match.
    state = dict(_STATE_TEMPLATE)
    state["latest_checkpoint"] = {
        "label": "Checkpoint 1",
        "commit": _git(repo, "rev-parse", "HEAD").stdout.strip(),
        "document": "docs/control_room/MISSION_1_CLOSURE_2026-08-01.md",
    }
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")
    _git(repo, "add", "docs/control_room/PROJECT_STATE.yaml")
    _git(repo, "commit", "-q", "-m", "record project state")

    registry = _write_registry(tmp_path)
    service = ProjectStatusService(registry, state_reader=StateReader())
    app = create_app(service=service)
    client = TestClient(app)

    response = client.get("/api/projects/example-project")
    currency = response.json()["closed_state_currency"]
    assert currency["status"] == "UNAVAILABLE"
    assert "discovered" in currency["detail"].lower()


# =============================================================================
# Composition invariants: attention untouched, no new route, rides existing
# ProjectSnapshot, no Git inside MissionHistoryReader
# =============================================================================


def test_ahead_state_does_not_trigger_founder_attention(tmp_path):
    client, _ = _build_client(tmp_path, closure_document_commits_ahead=5)
    response = client.get("/api/projects/example-project")
    body = response.json()
    assert body["closed_state_currency"]["status"] == "AHEAD"
    assert body["attention"]["required"] is False


def test_not_ancestor_state_does_not_trigger_founder_attention(tmp_path, monkeypatch):
    client, _ = _build_not_ancestor_client(tmp_path, monkeypatch)
    response = client.get("/api/projects/example-project")
    body = response.json()
    assert body["closed_state_currency"]["status"] == "NOT_ANCESTOR"
    assert body["attention"]["required"] is False


def test_closed_state_currency_rides_existing_project_list_route(tmp_path):
    client, _ = _build_client(tmp_path, closure_document_commits_ahead=0)
    response = client.get("/api/projects")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["closed_state_currency"]["status"] == "CURRENT"


def test_mission_history_reader_module_never_imports_subprocess():
    import control_room.mission_history_reader as module

    assert "subprocess" not in module.__dict__
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "git_reader" not in source.lower().replace("mission_history_reader", "")


# =============================================================================
# Real-repository proof (Section 15): the actual Redline OS repository
# =============================================================================


def test_real_redline_os_repository_closed_state_currency(tmp_path):
    """Cross-checks the full composition against the actual Redline OS
    repository this test suite lives in, using an *independently issued*
    Git subprocess call (never a hardcoded SHA) as the expected value --
    so this test keeps proving the architecture as the repository's HEAD
    moves forward with future missions, rather than going stale the
    moment a new commit lands after this one."""
    repo_root = Path(__file__).resolve().parents[3]
    assert (repo_root / ".git").exists()

    state_path = repo_root / "docs" / "control_room" / "PROJECT_STATE.yaml"
    state_data = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    document = state_data["latest_checkpoint"]["document"]

    intro = subprocess.run(
        [
            "git", "--literal-pathspecs", "log", "--no-renames", "--format=%H",
            "--diff-filter=A", "HEAD", "--", document,
        ],
        cwd=repo_root, capture_output=True, text=True, check=True,
    )
    intro_lines = [line for line in intro.stdout.splitlines() if line]
    assert len(intro_lines) == 1, "real repo's closure document must have exactly one introduction commit"
    expected_commit = intro_lines[0]

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", expected_commit, head], cwd=repo_root
    )

    registry_path = repo_root / "config" / "control_room" / "projects.yaml"
    registry = ProjectRegistry(registry_path, base_dir=repo_root)
    service = ProjectStatusService(registry, state_reader=StateReader())
    snapshot = service.get_snapshot("redline-os")
    currency = snapshot.closed_state_currency

    assert currency.closed_state_commit == expected_commit

    if ancestor.returncode == 0:
        count = subprocess.run(
            ["git", "rev-list", "--count", f"{expected_commit}..{head}"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        expected_status = (
            ClosedStateCurrencyStatus.CURRENT if count == "0" else ClosedStateCurrencyStatus.AHEAD
        )
        assert currency.status == expected_status
        assert currency.commits_since_closed_state == int(count)
    elif ancestor.returncode == 1:
        assert currency.status == ClosedStateCurrencyStatus.NOT_ANCESTOR
        assert currency.commits_since_closed_state is None
    else:
        pytest.fail(f"git merge-base --is-ancestor failed unexpectedly: {ancestor.returncode}")
