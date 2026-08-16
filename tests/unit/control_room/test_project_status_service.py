"""Tests for control_room.project_status_service.ProjectStatusService --
composition of ProjectDefinition + live GitStatus + ProjectState into
ProjectSnapshot, and the derived `attention` signal."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from control_room.models import (
    AttentionState,
    CheckpointState,
    ClosedStateCurrency,
    ClosedStateCurrencyStatus,
    GitStatus,
    MissionState,
    ProjectState,
    TrackingStatus,
    ValidationState,
    WorkingTreeStatus,
)
from control_room.project_registry import ProjectRegistry
from control_room.project_status_service import ProjectNotFoundError, ProjectStatusService
from control_room.state_reader import StateReader

_GIT_ENV_ARGS = ["-c", "user.name=Test User", "-c", "user.email=test@example.com"]

_CLOSURE_DOCUMENT_RELATIVE = "docs/control_room/MISSION_1_CLOSURE_2026-01-01.md"

_VALID_STATE = {
    "project_id": "example-project",
    "summary": "Example project for tests.",
    "current_mission": {"id": "m1", "title": "Mission 1", "phase": "implementation"},
    "latest_checkpoint": {"label": "Checkpoint 1", "commit": None, "document": _CLOSURE_DOCUMENT_RELATIVE},
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
        # A real closure document at the configured `latest_checkpoint.document`
        # path, added in the same commit as PROJECT_STATE.yaml, so this
        # baseline fixture's Closed-State Currency resolves deterministically
        # to CURRENT (0 commits since closed state) rather than UNAVAILABLE --
        # matching realistic PROJECT_STATE.yaml usage and keeping the
        # "no attention" tests below a clean baseline for the *other*
        # triggers they actually exercise (Mission 10).
        (state_dir / "MISSION_1_CLOSURE_2026-01-01.md").write_text(
            "# Mission 1 Closure\n\nMission 1 is formally closed.\n", encoding="utf-8"
        )
        (state_dir / "PROJECT_STATE.yaml").write_text(yaml.safe_dump(state_data), encoding="utf-8")
        _git(repo_path, "add", "docs/control_room/MISSION_1_CLOSURE_2026-01-01.md", "docs/control_room/PROJECT_STATE.yaml")
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


# =============================================================================
# Closed-State Currency Attention Integration (Mission 10)
#
# Deterministic, fixture-based coverage of ProjectStatusService._derive_attention()
# against synthetic GitStatus/ProjectState/ClosedStateCurrency objects -- no Git
# repository, no filesystem, no subprocess. This proves the four-state policy
# (CURRENT/AHEAD never trigger attention by themselves; NOT_ANCESTOR/UNAVAILABLE
# do) and reason composition independently of any real repository's lifecycle
# state, per the locked Mission 10 policy. Real end-to-end proofs against a
# genuine repository and the actual API response shape live in
# test_closed_state_currency.py.
# =============================================================================


def _clean_git_status(**overrides) -> GitStatus:
    fields = dict(
        repository_valid=True,
        branch="main",
        head_sha="a" * 40,
        head_sha_short="aaaaaaa",
        working_tree=WorkingTreeStatus.CLEAN,
        tracking=TrackingStatus.SYNCHRONIZED,
        upstream="origin/main",
        ahead=0,
        behind=0,
    )
    fields.update(overrides)
    return GitStatus(**fields)


def _clean_project_state(**overrides) -> ProjectState:
    fields = dict(
        project_id="example-project",
        summary="Example project for tests.",
        current_mission=MissionState(id="m1", title="Mission 1", phase="complete"),
        latest_checkpoint=CheckpointState(
            label="Checkpoint 1", commit="a" * 40, document=_CLOSURE_DOCUMENT_RELATIVE
        ),
        validation=ValidationState(status="pass", summary="All checks passed."),
        attention=AttentionState(required=False, reason=None),
    )
    fields.update(overrides)
    return ProjectState(**fields)


def _currency(status: ClosedStateCurrencyStatus, **overrides) -> ClosedStateCurrency:
    fields: dict = {"status": status}
    fields.update(overrides)
    return ClosedStateCurrency(**fields)


_PRESCRIPTIVE_PHRASES = ("should", "must ", "please", "recommend", "commit these", "run git", "push", "reset")


def _assert_reason_is_factual(reason: str) -> None:
    lowered = reason.lower()
    for phrase in _PRESCRIPTIVE_PHRASES:
        assert phrase not in lowered, f"reason must be factual, not prescriptive: found {phrase!r} in {reason!r}"


def test_derive_attention_current_currency_alone_does_not_require_attention():
    result = ProjectStatusService._derive_attention(
        _clean_git_status(),
        _clean_project_state(),
        None,
        True,
        _currency(ClosedStateCurrencyStatus.CURRENT, closed_state_commit="a" * 40, commits_since_closed_state=0),
    )
    assert result.required is False
    assert result.reason is None


def test_derive_attention_ahead_currency_alone_does_not_require_attention():
    """AHEAD deliberately mirrors the existing TrackingStatus.AHEAD precedent:
    HEAD having moved past the last recorded closed state is normal,
    expected post-closure development, not an anomaly."""
    result = ProjectStatusService._derive_attention(
        _clean_git_status(),
        _clean_project_state(),
        None,
        True,
        _currency(ClosedStateCurrencyStatus.AHEAD, closed_state_commit="a" * 40, commits_since_closed_state=7),
    )
    assert result.required is False
    assert result.reason is None


def test_derive_attention_not_ancestor_currency_alone_requires_attention():
    result = ProjectStatusService._derive_attention(
        _clean_git_status(),
        _clean_project_state(),
        None,
        True,
        _currency(
            ClosedStateCurrencyStatus.NOT_ANCESTOR,
            closed_state_commit="a" * 40,
            detail="The recorded closed state is not an ancestor of current HEAD.",
        ),
    )
    assert result.required is True
    assert "ancestor" in result.reason.lower()
    _assert_reason_is_factual(result.reason)


def test_derive_attention_unavailable_currency_alone_requires_attention():
    result = ProjectStatusService._derive_attention(
        _clean_git_status(),
        _clean_project_state(),
        None,
        True,
        _currency(
            ClosedStateCurrencyStatus.UNAVAILABLE,
            detail="configured closure document path is invalid: path is empty",
        ),
    )
    assert result.required is True
    assert "closure document" in result.reason.lower()
    _assert_reason_is_factual(result.reason)


def test_derive_attention_not_ancestor_reason_falls_back_when_detail_missing():
    result = ProjectStatusService._derive_attention(
        _clean_git_status(),
        _clean_project_state(),
        None,
        True,
        _currency(ClosedStateCurrencyStatus.NOT_ANCESTOR, detail=None),
    )
    assert result.required is True
    assert result.reason
    _assert_reason_is_factual(result.reason)


def test_derive_attention_unavailable_reason_falls_back_when_detail_missing():
    result = ProjectStatusService._derive_attention(
        _clean_git_status(),
        _clean_project_state(),
        None,
        True,
        _currency(ClosedStateCurrencyStatus.UNAVAILABLE, detail=None),
    )
    assert result.required is True
    assert result.reason
    _assert_reason_is_factual(result.reason)


def test_derive_attention_dirty_tree_and_unavailable_currency_preserve_both_reasons():
    git_status = _clean_git_status(working_tree=WorkingTreeStatus.DIRTY)
    result = ProjectStatusService._derive_attention(
        git_status,
        _clean_project_state(),
        None,
        True,
        _currency(ClosedStateCurrencyStatus.UNAVAILABLE, detail="live Git HEAD is unavailable"),
    )
    assert result.required is True
    reason = result.reason.lower()
    assert "dirty" in reason
    assert "live git head is unavailable" in reason


def test_derive_attention_existing_checkpoint_trigger_and_not_ancestor_preserve_both_reasons():
    result = ProjectStatusService._derive_attention(
        _clean_git_status(),
        _clean_project_state(),
        None,
        False,  # checkpoint_valid is False -- a pre-Mission-10 trigger
        _currency(ClosedStateCurrencyStatus.NOT_ANCESTOR, detail="not an ancestor of current HEAD"),
    )
    assert result.required is True
    reason = result.reason.lower()
    assert "checkpoint" in reason
    assert "not an ancestor" in reason


def test_derive_attention_pre_mission_10_dirty_tree_trigger_unaffected_by_current_currency():
    """CURRENT currency contributes nothing -- the pre-Mission-10 dirty-tree
    trigger's reason text is unchanged, byte for byte."""
    git_status = _clean_git_status(working_tree=WorkingTreeStatus.DIRTY)
    result = ProjectStatusService._derive_attention(
        git_status,
        _clean_project_state(),
        None,
        True,
        _currency(ClosedStateCurrencyStatus.CURRENT, commits_since_closed_state=0),
    )
    assert result.required is True
    assert result.reason == "Working tree is dirty (uncommitted changes present)."


def test_derive_attention_pre_mission_10_diverged_tracking_trigger_unaffected_by_ahead_currency():
    """AHEAD currency contributes nothing -- the pre-Mission-10 diverged-
    tracking trigger's reason text is unchanged, byte for byte."""
    git_status = _clean_git_status(tracking=TrackingStatus.DIVERGED)
    result = ProjectStatusService._derive_attention(
        git_status,
        _clean_project_state(),
        None,
        True,
        _currency(ClosedStateCurrencyStatus.AHEAD, commits_since_closed_state=3),
    )
    assert result.required is True
    assert result.reason == "Local branch has diverged from its upstream tracking branch."


def test_derive_attention_makes_no_git_subprocess_call(monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("attention derivation must not invoke a Git subprocess")

    monkeypatch.setattr(subprocess, "run", _fail_if_called)

    currency = _currency(ClosedStateCurrencyStatus.NOT_ANCESTOR, detail="not an ancestor")
    result = ProjectStatusService._derive_attention(
        _clean_git_status(), _clean_project_state(), None, True, currency
    )
    assert result.required is True


def test_derive_attention_does_not_mutate_closed_state_currency_value():
    currency = _currency(ClosedStateCurrencyStatus.UNAVAILABLE, detail="live Git HEAD is unavailable")
    currency_before = currency.model_copy(deep=True)

    ProjectStatusService._derive_attention(_clean_git_status(), _clean_project_state(), None, True, currency)

    assert currency == currency_before
