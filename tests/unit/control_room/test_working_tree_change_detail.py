"""Focused tests for Control Room V0 Mission 8: Current Working Tree
Change Detail, reachable from the live GitStatus block on the Project
Detail screen. Covers GitReader's single consolidated
`git --no-optional-locks status --porcelain=v2 -z --untracked-files=all
--renames` read (record decoding for ordinary/rename/copy/unmerged/
untracked shapes, the staged-and-further-modified single-record case,
the real-Git rename-detection boundary, the two-tier failure design
where a subprocess-level failure still fails the whole GitStatus but a
record-decode failure only degrades the detail), service composition
(no enrichment code needed -- the field rides straight through from
GitReader.read_status()), served frontend wiring, the read-only/
no-new-routes invariant, and compatibility with this repository's own
real, live working tree. Matches the conventions in test_git_reader.py
and test_checkpoint_change_set.py.

Independent-review correction rounds (static adversarial Codex review):
round 1 -- an empty path/original_path in any recognized record shape,
and a rename/copy score field validated only by its first character,
must each degrade the entire detail list exactly like any other
malformed record -- covered by the empty-path and malformed-score tests
below, alongside a direct structural test of copy-kind derivation.
Round 2 (non-blocking finding, corrected anyway) -- status-letter
validation is per-record-type, not the general documented union, since
Git never emits 'U' for an ordinary or rename/copy record (only for its
own unmerged "u" record type)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from control_room.app import build_service, create_app
from control_room.git_reader import GitReader
from control_room.models import WorkingTreeChangeKind, WorkingTreeStatus
from control_room.project_registry import ProjectRegistry
from control_room.project_status_service import ProjectStatusService
from control_room.state_reader import StateReader

_GIT_ENV_ARGS = ["-c", "user.name=Test User", "-c", "user.email=test@example.com"]
_REAL_SUBPROCESS_RUN = subprocess.run


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *_GIT_ENV_ARGS, *args], cwd=cwd, capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "initial commit")
    return path


# -- clean tree ---------------------------------------------------------------


def test_clean_repository_has_empty_working_tree_changes(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    status = GitReader(repo).read_status()

    assert status.working_tree == WorkingTreeStatus.CLEAN
    assert status.working_tree_changes == []
    assert status.working_tree_changes_error is None


# -- ordinary tracked changes ---------------------------------------------------


def test_unstaged_modification_reports_tracked_change(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    status = GitReader(repo).read_status()
    assert status.working_tree == WorkingTreeStatus.DIRTY
    assert status.working_tree_changes_error is None
    changes = {c.path: c for c in status.working_tree_changes}
    assert changes["README.md"].kind == WorkingTreeChangeKind.TRACKED
    assert changes["README.md"].index_status is None
    assert changes["README.md"].worktree_status == "M"


def test_staged_and_further_modified_file_is_one_record_with_both_statuses(tmp_path):
    """A file staged, then modified again in the working tree, must
    appear as ONE WorkingTreeChange with both index_status and
    worktree_status set -- never two disconnected entries for the same
    path (the exact defect the four-flat-list design would have had)."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("staged change\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    (repo / "README.md").write_text("staged change\nplus more\n", encoding="utf-8")

    status = GitReader(repo).read_status()
    matching = [c for c in status.working_tree_changes if c.path == "README.md"]
    assert len(matching) == 1
    change = matching[0]
    assert change.index_status == "M"
    assert change.worktree_status == "M"
    assert change.kind == WorkingTreeChangeKind.TRACKED


# -- untracked, including a path with a space and a nested directory --------


def test_untracked_files_including_space_and_nested_directory(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "untracked with space.txt").write_text("new\n", encoding="utf-8")
    nested = repo / "new_dir" / "nested"
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("new\n", encoding="utf-8")

    status = GitReader(repo).read_status()
    paths = {c.path for c in status.working_tree_changes if c.kind == WorkingTreeChangeKind.UNTRACKED}
    # --untracked-files=all expands the directory into the individual
    # file path, never a single directory-summary entry.
    assert paths == {"untracked with space.txt", "new_dir/nested/deep.txt"}
    for change in status.working_tree_changes:
        assert change.index_status is None
        assert change.worktree_status is None
        assert change.original_path is None


# -- rename detection: real Git behavior, not an assumption -----------------


def test_staged_rename_reports_original_and_new_path(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "mv", "README.md", "README_RENAMED.md")

    status = GitReader(repo).read_status()
    matching = [c for c in status.working_tree_changes if c.kind == WorkingTreeChangeKind.RENAMED]
    assert len(matching) == 1
    change = matching[0]
    assert change.path == "README_RENAMED.md"
    assert change.original_path == "README.md"


def test_unstaged_rename_is_reported_as_delete_plus_untracked_not_renamed(tmp_path):
    """Verified against real `git status` output: rename detection with
    `--renames` only applies to a *staged* rename (index vs HEAD). A
    rename made in the working tree without staging it (plain filesystem
    move, no `git add`) is reported as a plain delete of the old path
    plus a plain untracked add of the new path -- this module must not
    try to infer a rename Git itself did not detect."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").rename(repo / "README_MOVED.md")

    status = GitReader(repo).read_status()
    kinds_by_path = {c.path: c.kind for c in status.working_tree_changes}
    assert kinds_by_path.get("README.md") == WorkingTreeChangeKind.TRACKED
    deleted = next(c for c in status.working_tree_changes if c.path == "README.md")
    assert deleted.worktree_status == "D"
    assert kinds_by_path.get("README_MOVED.md") == WorkingTreeChangeKind.UNTRACKED
    assert not any(c.kind == WorkingTreeChangeKind.RENAMED for c in status.working_tree_changes)


# -- merge conflict -----------------------------------------------------------


def test_merge_conflict_reports_conflicted_kind(tmp_path):
    repo = _init_repo(tmp_path / "repo")

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "conflict.txt").write_text("from feature\n", encoding="utf-8")
    _git(repo, "add", "conflict.txt")
    _git(repo, "commit", "-q", "-m", "feature change")

    _git(repo, "checkout", "-q", "main")
    (repo / "conflict.txt").write_text("from main\n", encoding="utf-8")
    _git(repo, "add", "conflict.txt")
    _git(repo, "commit", "-q", "-m", "main change")

    subprocess.run(
        ["git", *_GIT_ENV_ARGS, "merge", "-q", "-m", "merge attempt", "feature"],
        cwd=repo, capture_output=True, text=True,
    )

    status = GitReader(repo).read_status()
    matching = [c for c in status.working_tree_changes if c.path == "conflict.txt"]
    assert len(matching) == 1
    assert matching[0].kind == WorkingTreeChangeKind.CONFLICTED


# -- malformed/unrecognized output: whole-DETAIL degradation, narrow blast --
# -- radius (does not fail branch/HEAD/tracking, unlike a subprocess-level --
# -- git status failure, which still fails the whole snapshot as before) ----


def test_unexpected_ignored_record_degrades_detail_only(tmp_path):
    """The fixed command never passes --ignored, so a `!` record can
    never legitimately appear. If it somehow did, it must degrade the
    entire detail list explicitly -- never be silently skipped -- while
    leaving the rest of GitStatus (branch, HEAD, tracking) intact, since
    the coarse CLEAN/DIRTY signal and the rest of read_status() do not
    depend on successfully decoding every record."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    def _fake_run(args, **kwargs):
        if args[0] == "git" and "status" in args and "--porcelain=v2" in args:
            return subprocess.CompletedProcess(args, returncode=0, stdout="! ignored.txt\0", stderr="")
        return _REAL_SUBPROCESS_RUN(args, **kwargs)

    import control_room.git_reader as git_reader_module

    original = git_reader_module.subprocess.run
    git_reader_module.subprocess.run = _fake_run
    try:
        status = GitReader(repo).read_status()
    finally:
        git_reader_module.subprocess.run = original

    assert status.repository_valid is True
    assert status.branch == "main"
    assert status.head_sha is not None
    assert status.working_tree == WorkingTreeStatus.DIRTY
    assert status.working_tree_changes is None
    assert status.working_tree_changes_error is not None
    assert "ignored.txt" in status.working_tree_changes_error


def test_malformed_ordinary_record_degrades_detail_only(tmp_path):
    repo = _init_repo(tmp_path / "repo")

    def _fake_run(args, **kwargs):
        if args[0] == "git" and "status" in args and "--porcelain=v2" in args:
            return subprocess.CompletedProcess(args, returncode=0, stdout="1 not-enough-fields\0", stderr="")
        return _REAL_SUBPROCESS_RUN(args, **kwargs)

    import control_room.git_reader as git_reader_module

    original = git_reader_module.subprocess.run
    git_reader_module.subprocess.run = _fake_run
    try:
        status = GitReader(repo).read_status()
    finally:
        git_reader_module.subprocess.run = original

    assert status.repository_valid is True
    assert status.working_tree_changes is None
    assert status.working_tree_changes_error is not None


def _read_status_with_fake_porcelain_output(repo: Path, stdout: str):
    """Shared helper for the malformed-record hardening tests below:
    monkeypatch only the `git status --porcelain=v2` call to return
    crafted output, passing every other git invocation through to the
    real subprocess so the rest of read_status() still runs normally
    against the real fixture repo."""

    def _fake_run(args, **kwargs):
        if args[0] == "git" and "status" in args and "--porcelain=v2" in args:
            return subprocess.CompletedProcess(args, returncode=0, stdout=stdout, stderr="")
        return _REAL_SUBPROCESS_RUN(args, **kwargs)

    import control_room.git_reader as git_reader_module

    original = git_reader_module.subprocess.run
    git_reader_module.subprocess.run = _fake_run
    try:
        return GitReader(repo).read_status()
    finally:
        git_reader_module.subprocess.run = original


# -- independent-review correction round: empty-path and malformed-score  --
# -- hardening (Codex finding: a bare successful subprocess result is not --
# -- trustworthy at face value -- an empty path, or a rename/copy score   --
# -- field validated only by its first character, must degrade the whole  --
# -- list exactly like any other malformed record, never survive into a   --
# -- structured WorkingTreeChange). ------------------------------------------


def test_ordinary_record_with_empty_path_degrades_detail_only(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    status = _read_status_with_fake_porcelain_output(
        repo, "1 .M N... 100644 100644 100644 " + "0" * 40 + " " + "0" * 40 + " \0"
    )
    assert status.repository_valid is True
    assert status.working_tree_changes is None
    assert status.working_tree_changes_error is not None


def test_untracked_record_with_empty_path_degrades_detail_only(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    status = _read_status_with_fake_porcelain_output(repo, "? \0")
    assert status.repository_valid is True
    assert status.working_tree_changes is None
    assert status.working_tree_changes_error is not None


def test_unmerged_record_with_empty_path_degrades_detail_only(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    status = _read_status_with_fake_porcelain_output(
        repo,
        "u AA N... 000000 100644 100644 100644 "
        + "0" * 40 + " " + "0" * 40 + " " + "0" * 40 + " \0",
    )
    assert status.repository_valid is True
    assert status.working_tree_changes is None
    assert status.working_tree_changes_error is not None


def test_rename_record_with_empty_new_path_degrades_detail_only(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = (
        "2 R. N... 100644 100644 100644 " + "0" * 40 + " " + "0" * 40 + " R100 \0"
    )
    status = _read_status_with_fake_porcelain_output(repo, record + "original.txt\0")
    assert status.repository_valid is True
    assert status.working_tree_changes is None
    assert status.working_tree_changes_error is not None


def test_rename_record_with_empty_original_path_degrades_detail_only(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = (
        "2 R. N... 100644 100644 100644 " + "0" * 40 + " " + "0" * 40 + " R100 new.txt\0"
    )
    status = _read_status_with_fake_porcelain_output(repo, record + "\0")
    assert status.repository_valid is True
    assert status.working_tree_changes is None
    assert status.working_tree_changes_error is not None


def test_rename_record_with_malformed_score_field_degrades_detail_only(tmp_path):
    """Independent review finding: validating only the first character of
    the score field (`score[0] in ("R", "C")`) would silently accept "R"
    alone, "Rabc", or "C-1" as a legitimate record. The full field must
    match `^[RC][0-9]+$`."""
    repo = _init_repo(tmp_path / "repo")
    for malformed_score in ("R", "Rabc", "C-1", "X100"):
        record = (
            "2 R. N... 100644 100644 100644 " + "0" * 40 + " " + "0" * 40
            + f" {malformed_score} new.txt\0"
        )
        status = _read_status_with_fake_porcelain_output(repo, record + "original.txt\0")
        assert status.working_tree_changes is None, f"score {malformed_score!r} should have degraded"
        assert status.working_tree_changes_error is not None


def test_copied_kind_is_derived_from_c_score_prefix(tmp_path):
    """Real `git status` rarely emits a copy record without an explicit
    copy-detection flag this fixed command does not pass, so this is a
    direct structural test of the "C" branch of score-prefix kind
    derivation, complementing the real, empirically-verified staged-
    rename coverage above."""
    repo = _init_repo(tmp_path / "repo")
    record = (
        "2 C. N... 100644 100644 100644 " + "0" * 40 + " " + "0" * 40 + " C100 copy_target.txt\0"
    )
    status = _read_status_with_fake_porcelain_output(repo, record + "copy_source.txt\0")
    assert status.working_tree_changes_error is None
    matching = [c for c in status.working_tree_changes if c.kind == WorkingTreeChangeKind.COPIED]
    assert len(matching) == 1
    assert matching[0].path == "copy_target.txt"
    assert matching[0].original_path == "copy_source.txt"


def test_ordinary_record_with_illegal_u_status_degrades_detail_only(tmp_path):
    """Real Git never emits 'U' in a type "1" ordinary record -- an
    unmerged path is always its own type "u" record. Validating ordinary
    records against the full general status-letter union (rather than a
    per-record-type set) would silently accept this impossible shape as
    a legitimate TRACKED change (round-2 independent review finding)."""
    repo = _init_repo(tmp_path / "repo")
    record = "1 U. N... 100644 100644 100644 " + "0" * 40 + " " + "0" * 40 + " impossible.txt\0"
    status = _read_status_with_fake_porcelain_output(repo, record)
    assert status.working_tree_changes is None
    assert status.working_tree_changes_error is not None


def test_rename_record_with_illegal_u_status_degrades_detail_only(tmp_path):
    """Same principle for a type "2" rename/copy record: the worktree
    (Y) column must be an ordinary letter, never 'U' -- an unmerged path
    cannot simultaneously be a rename/copy record."""
    repo = _init_repo(tmp_path / "repo")
    record = "2 RU N... 100644 100644 100644 " + "0" * 40 + " " + "0" * 40 + " R100 new.txt\0"
    status = _read_status_with_fake_porcelain_output(repo, record + "original.txt\0")
    assert status.working_tree_changes is None
    assert status.working_tree_changes_error is not None


def test_status_subprocess_failure_fails_whole_snapshot(tmp_path):
    """Distinct from the record-decode failures above: if the
    `git status` subprocess itself fails (non-zero exit), this is the
    same failure class `_read_working_tree()` always had -- it must
    still fail the whole GitStatus via `_error_status()`, exactly as
    before Mission 8."""
    repo = _init_repo(tmp_path / "repo")

    def _fake_run(args, **kwargs):
        if args[0] == "git" and "status" in args and "--porcelain=v2" in args:
            return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="fatal: simulated failure")
        return _REAL_SUBPROCESS_RUN(args, **kwargs)

    import control_room.git_reader as git_reader_module

    original = git_reader_module.subprocess.run
    git_reader_module.subprocess.run = _fake_run
    try:
        status = GitReader(repo).read_status()
    finally:
        git_reader_module.subprocess.run = original

    assert status.repository_valid is False
    assert status.working_tree == WorkingTreeStatus.ERROR
    assert status.branch is None
    assert status.head_sha is None
    assert status.error


# -- service composition: no enrichment code needed --------------------------


_STATE = {
    "project_id": "example-project",
    "summary": "Example project for tests.",
    "current_mission": {"id": "m1", "title": "Mission 1", "phase": "complete"},
    "latest_checkpoint": {"label": "Checkpoint 1", "commit": "placeholder", "document": "docs/CHECKPOINT.md"},
    "validation": {"status": "pass", "summary": "All checks passed."},
    "attention": {"required": False, "reason": None},
}


def _build_client(tmp_path: Path, make_dirty: bool = False):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial commit")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    state = dict(_STATE)
    state["latest_checkpoint"] = dict(_STATE["latest_checkpoint"])
    state["latest_checkpoint"]["commit"] = head_sha
    state_dir = repo / "docs" / "control_room"
    state_dir.mkdir(parents=True)
    (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")
    _git(repo, "add", "docs/control_room")
    _git(repo, "commit", "-q", "-m", "add project state")

    if make_dirty:
        (repo / "README.md").write_text("dirty change\n", encoding="utf-8")

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


def test_project_snapshot_carries_working_tree_changes_through_git_status(tmp_path):
    client = _build_client(tmp_path, make_dirty=True)
    response = client.get("/api/projects/example-project")
    assert response.status_code == 200
    git = response.json()["git"]

    assert git["working_tree"] == "DIRTY"
    assert git["working_tree_changes_error"] is None
    paths = {c["path"] for c in git["working_tree_changes"]}
    assert "README.md" in paths


def test_project_snapshot_clean_tree_reports_empty_list(tmp_path):
    client = _build_client(tmp_path, make_dirty=False)
    response = client.get("/api/projects/example-project")
    git = response.json()["git"]

    assert git["working_tree"] == "CLEAN"
    assert git["working_tree_changes"] == []
    assert git["working_tree_changes_error"] is None


# -- served frontend wiring ----------------------------------------------------


def test_app_js_renders_working_tree_change_detail_drill_down(tmp_path):
    client = _build_client(tmp_path)
    response = client.get("/static/app.js")
    assert response.status_code == 200
    script = response.text
    assert "working_tree_changes" in script
    assert "working_tree_changes_error" in script
    assert "Current Working Tree Change Detail" in script
    assert "escapeHtml(change.path)" in script


# -- read-only behavior / zero new mutation routes ----------------------------


def test_working_tree_change_detail_feature_introduced_no_new_routes(tmp_path):
    client = _build_client(tmp_path)
    app = client.app

    api_paths = {route.path for route in app.routes if getattr(route, "path", "").startswith("/api/")}
    assert api_paths == {"/api/projects", "/api/projects/{project_id}"}

    for route in app.routes:
        methods = getattr(route, "methods", None)
        if methods:
            assert methods <= {"GET", "HEAD", "OPTIONS"}, f"mutating verb allowed on {route.path}: {methods}"


def test_project_state_yaml_still_not_the_working_tree_source(tmp_path):
    client = _build_client(tmp_path, make_dirty=True)
    response = client.get("/api/projects/example-project")
    state = response.json()["state"]
    assert "working_tree_changes" not in state
    assert set(state.keys()) == {
        "project_id",
        "summary",
        "current_mission",
        "latest_checkpoint",
        "validation",
        "attention",
    }


# -- real repository compatibility (internal consistency, not a fixed value) -


def test_real_repository_working_tree_changes_is_internally_consistent():
    """This repository's own live checkout, whatever its current state
    happens to be: repository_valid must be True, the read must never
    fail outright, and working_tree_changes must be exactly consistent
    with the coarse CLEAN/DIRTY classification derived from the same
    read -- CLEAN implies an empty list, DIRTY implies a non-empty one.
    Deliberately does not assert a fixed clean/dirty value, since that
    is not durable across a real checkout's lifetime."""
    service = build_service()
    snapshot = service.get_snapshot("redline-os")
    git = snapshot.git

    assert git.repository_valid is True
    assert git.working_tree_changes_error is None
    assert git.working_tree_changes is not None

    if git.working_tree == WorkingTreeStatus.CLEAN:
        assert git.working_tree_changes == []
    elif git.working_tree == WorkingTreeStatus.DIRTY:
        assert len(git.working_tree_changes) > 0
