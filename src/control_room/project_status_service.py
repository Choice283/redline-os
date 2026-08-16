"""Combines ProjectDefinition + live GitStatus + ProjectState into a
single ProjectSnapshot -- the only boundary the web layer talks to.

Neither the HTML/JS frontend nor app.py's routes touch GitReader,
StateReader, or ProjectRegistry directly; they call this service and
render whatever ProjectSnapshot it returns, including degraded/unknown
states.

Closed-State Currency (Mission 9) -- whether the repository has moved
beyond `state.latest_checkpoint.document`, the closure document recorded
in PROJECT_STATE.yaml -- is composed here, not in MissionHistoryReader
(which stays Git-free) or GitReader (which owns only the narrow Git
reads it's asked for). This module owns the two-layer closure-path
validation (`_validate_canonical_closure_path` for strict canonical
syntax, `_closure_path_is_proven` for independently discovered,
provably repository-relative membership against MissionHistoryReader's
own discovery) and the composition that turns a validated path into a
`ClosedStateCurrency` via `GitReader.read_path_introduction_commit()`
and `GitReader.read_closed_state_currency()`. Observation only: this
value is never fed into `_derive_attention()`.
"""
from __future__ import annotations

import logging
import posixpath
from pathlib import Path

from control_room.git_reader import GitReader
from control_room.mission_history_reader import MissionHistoryReader
from control_room.models import (
    AttentionState,
    ClosedStateCurrency,
    ClosedStateCurrencyStatus,
    GitStatus,
    MissionHistoryEntry,
    ProjectDefinition,
    ProjectSnapshot,
    ProjectState,
    TrackingStatus,
    WorkingTreeStatus,
)
from control_room.project_registry import ProjectRegistry
from control_room.state_reader import StateReader, StateReadError

logger = logging.getLogger("redline_os.control_room.project_status_service")

# Closed-State Currency (Mission 9), Layer 1: strict canonical-syntax
# validation of `state.latest_checkpoint.document` before it is ever
# treated as Git input. This rejects rather than normalizes -- a path
# that is not already canonical is refused outright, never silently
# corrected (e.g. backslashes are never converted to forward slashes).
_NUL_CHARACTER = "\x00"
_DRIVE_LETTER_PATTERN_SOURCE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _validate_canonical_closure_path(path: str) -> str | None:
    """Return an error message if `path` is not already a canonical,
    repository-relative POSIX-style closure-document path, or `None` if
    it is acceptable. Fails closed: any ambiguity is a rejection, never a
    best-effort normalization."""
    if not path:
        return "path is empty"
    if _NUL_CHARACTER in path:
        return "path contains an embedded NUL character"
    if "\\" in path:
        return "path contains a backslash"
    if path.startswith(":"):
        return "path begins with a bare leading colon (possible Git pathspec magic)"
    if path.startswith("-"):
        return "path begins with a leading dash"
    if path.startswith("/"):
        return "path is an absolute POSIX path (or UNC-style path)"
    if len(path) >= 2 and path[1] == ":" and path[0] in _DRIVE_LETTER_PATTERN_SOURCE:
        return "path is drive-qualified"
    if path.endswith("/"):
        return "path has a trailing slash"
    if "//" in path:
        return "path contains a double slash"
    segments = path.split("/")
    if any(segment == "" for segment in segments):
        return "path contains an empty segment"
    if any(segment == "." for segment in segments):
        return "path contains a '.' segment"
    if any(segment == ".." for segment in segments):
        return "path contains a '..' segment"
    if posixpath.normpath(path) != path:
        return "path requires normalization before it would be canonical"
    return None


def _closure_path_is_proven(
    candidate: str, repository_path: Path, history_dir: Path, raw_entries: list[MissionHistoryEntry]
) -> bool:
    """Closed-State Currency (Mission 9), Layer 2: independently
    discovered membership. `candidate` (already Layer-1 validated) must
    exactly match a `closure_document` MissionHistoryReader itself
    already discovered by scanning `history_dir` -- no second closure-file
    discovery mechanism is introduced here.

    That string-equality match alone is not trusted, though:
    `MissionHistoryReader._relative_document_path()` has a defensive
    fallback that can return a bare filename (no directory component) if
    its history directory were ever unexpectedly outside the repository.
    A bare filename could coincidentally pass Layer 1 (it contains no
    illegal characters) and, in a pathological case, coincidentally
    string-match a discovered entry, so this function additionally
    resolves `repository_path / candidate` *independently* of whatever
    MissionHistoryReader itself did internally and proves, from that
    fresh resolution alone: it stays inside `repository_path` (no
    traversal/escape), its parent directory is exactly `history_dir` (the
    real directory that was scanned), and it names a real file on disk.
    Only when all of these hold is `candidate` treated as a genuine
    repository-relative Git path."""
    if not any(entry.closure_document == candidate for entry in raw_entries):
        return False

    resolved_repository = repository_path.resolve()
    resolved_history_dir = history_dir.resolve()
    candidate_full = (repository_path / candidate).resolve()

    try:
        candidate_full.relative_to(resolved_repository)
    except ValueError:
        return False

    if candidate_full.parent != resolved_history_dir:
        return False

    return candidate_full.is_file()


class ProjectNotFoundError(Exception):
    """Raised when a requested project id is not present in the registry."""


class ProjectStatusService:
    def __init__(
        self,
        registry: ProjectRegistry,
        state_reader: StateReader | None = None,
        mission_history_reader: MissionHistoryReader | None = None,
    ):
        self._registry = registry
        self._state_reader = state_reader or StateReader()
        self._mission_history_reader = mission_history_reader or MissionHistoryReader()

    def list_snapshots(self) -> list[ProjectSnapshot]:
        return [self._build_snapshot(definition) for definition in self._registry.load()]

    def get_snapshot(self, project_id: str) -> ProjectSnapshot:
        definition = self._registry.get(project_id)
        if definition is None:
            raise ProjectNotFoundError(f"unknown project id: {project_id}")
        return self._build_snapshot(definition)

    # -- internals ------------------------------------------------------

    def _build_snapshot(self, definition: ProjectDefinition) -> ProjectSnapshot:
        repository_path = self._registry.resolve_repository_path(definition)
        state_file_path = self._registry.resolve_state_file_path(definition)

        git_status = GitReader(repository_path).read_status()

        state = None
        state_error = None
        try:
            state = self._state_reader.read(state_file_path)
        except StateReadError as exc:
            state_error = str(exc)
            logger.error(
                "control room snapshot for project '%s': project state unavailable: %s",
                definition.id,
                state_error,
            )

        checkpoint_valid = self._checkpoint_valid(repository_path, git_status, state)

        attention = self._derive_attention(git_status, state, state_error, checkpoint_valid)

        # docs/control_room/ -- the same directory the registry's already-
        # configured state_file lives in, not a second hardcoded location.
        # Read once here and reuse for both Mission & Checkpoint History
        # and Closed-State Currency below, rather than a second
        # MissionHistoryReader.read() call / discovery pass.
        history_dir = state_file_path.parent
        raw_entries = self._mission_history_reader.read(history_dir, repository_path)

        mission_history = self._enrich_mission_history(repository_path, raw_entries, git_status)
        closed_state_currency = self._compute_closed_state_currency(
            repository_path, history_dir, raw_entries, state, git_status
        )

        return ProjectSnapshot(
            project_id=definition.id,
            name=definition.name,
            git=git_status,
            state=state,
            state_error=state_error,
            attention=attention,
            mission_history=mission_history,
            closed_state_currency=closed_state_currency,
        )

    def _enrich_mission_history(
        self, repository_path, entries: list[MissionHistoryEntry], git_status: GitStatus
    ) -> list[MissionHistoryEntry]:
        if not git_status.repository_valid:
            return entries

        # MissionHistoryReader never runs Git -- it only parses closure
        # documents. Enrichment against live Git machine truth (checkpoint
        # resolution, and now the checkpoint's own file-path change set)
        # happens here, after parsing, exactly like `_checkpoint_valid()`
        # already does for the *current* checkpoint.
        git_reader = GitReader(repository_path)
        resolved_entries = []
        for entry in entries:
            checkpoint_resolved = git_reader.commit_exists(entry.checkpoint_commit) if entry.checkpoint_commit else None
            changed_files, changes_error = self._read_checkpoint_change_set(
                git_reader, entry.checkpoint_commit, checkpoint_resolved
            )
            resolved_entries.append(entry.model_copy(update={
                "checkpoint_resolved": checkpoint_resolved,
                "checkpoint_changed_files": changed_files,
                "checkpoint_changes_error": changes_error,
            }))
        return resolved_entries

    @staticmethod
    def _read_checkpoint_change_set(
        git_reader: GitReader, checkpoint_commit: str | None, checkpoint_resolved: bool | None
    ) -> tuple[list[str] | None, str | None]:
        """Only ever query Git for a commit already resolved as real
        (`checkpoint_resolved is True`) -- there is no reason to spawn a
        `diff-tree` for a SHA that couldn't even be verified to exist, and
        `GitReader.read_commit_changed_files()` itself refuses anything
        that isn't a plain hex SHA regardless."""
        if checkpoint_commit is None:
            return None, "no checkpoint commit was recorded for this mission"
        if checkpoint_resolved is not True:
            reason = (
                "checkpoint commit does not resolve in the repository"
                if checkpoint_resolved is False
                else "checkpoint resolution could not be determined"
            )
            return None, reason
        return git_reader.read_commit_changed_files(checkpoint_commit)

    @staticmethod
    def _checkpoint_valid(repository_path, git_status, state) -> bool | None:
        if state is None or not git_status.repository_valid:
            return None
        return GitReader(repository_path).commit_exists(state.latest_checkpoint.commit)

    @staticmethod
    def _compute_closed_state_currency(
        repository_path: Path,
        history_dir: Path,
        raw_entries: list[MissionHistoryEntry],
        state: ProjectState | None,
        git_status: GitStatus,
    ) -> ClosedStateCurrency:
        """Closed-State Currency (Mission 9): has the repository moved
        beyond the latest formally closed Control Room state? Observation
        only -- this never feeds `_derive_attention()`, is never cached,
        and is recomputed fresh on every snapshot from the approved
        source-of-truth chain: `state.latest_checkpoint.document` ->
        Layer 1/Layer 2 path validation -> Git-resolved introduction
        commit -> comparison against live `git_status.head_sha`."""
        if state is None:
            return ClosedStateCurrency(
                status=ClosedStateCurrencyStatus.UNAVAILABLE,
                detail="project state unavailable; no closure document is recorded to anchor the closed state",
            )
        if not git_status.repository_valid or not git_status.head_sha:
            return ClosedStateCurrency(
                status=ClosedStateCurrencyStatus.UNAVAILABLE,
                detail="live Git HEAD is unavailable",
            )

        candidate = state.latest_checkpoint.document

        validation_error = _validate_canonical_closure_path(candidate)
        if validation_error is not None:
            return ClosedStateCurrency(
                status=ClosedStateCurrencyStatus.UNAVAILABLE,
                detail=f"configured closure document path is invalid: {validation_error}",
            )

        if not _closure_path_is_proven(candidate, repository_path, history_dir, raw_entries):
            return ClosedStateCurrency(
                status=ClosedStateCurrencyStatus.UNAVAILABLE,
                detail=(
                    "configured closure document could not be proven to be an independently "
                    "discovered, genuinely repository-relative mission history entry"
                ),
            )

        git_reader = GitReader(repository_path)
        closed_state_commit, introduction_error = git_reader.read_path_introduction_commit(candidate)
        if closed_state_commit is None:
            return ClosedStateCurrency(status=ClosedStateCurrencyStatus.UNAVAILABLE, detail=introduction_error)

        is_ancestor, commits_since, currency_error = git_reader.read_closed_state_currency(
            closed_state_commit, git_status.head_sha
        )
        if is_ancestor is None:
            return ClosedStateCurrency(
                status=ClosedStateCurrencyStatus.UNAVAILABLE,
                closed_state_commit=closed_state_commit,
                detail=currency_error,
            )
        if is_ancestor is False:
            return ClosedStateCurrency(
                status=ClosedStateCurrencyStatus.NOT_ANCESTOR,
                closed_state_commit=closed_state_commit,
                detail=(
                    "The recorded closed state is not an ancestor of current HEAD. "
                    "A linear commits-beyond count is unavailable."
                ),
            )
        if commits_since is None:
            return ClosedStateCurrency(
                status=ClosedStateCurrencyStatus.UNAVAILABLE,
                closed_state_commit=closed_state_commit,
                detail=currency_error,
            )
        if commits_since == 0:
            return ClosedStateCurrency(
                status=ClosedStateCurrencyStatus.CURRENT,
                closed_state_commit=closed_state_commit,
                commits_since_closed_state=0,
            )
        return ClosedStateCurrency(
            status=ClosedStateCurrencyStatus.AHEAD,
            closed_state_commit=closed_state_commit,
            commits_since_closed_state=commits_since,
        )

    @staticmethod
    def _derive_attention(git_status, state, state_error, checkpoint_valid) -> AttentionState:
        reasons: list[str] = []

        if not git_status.repository_valid:
            reasons.append(f"Git repository unavailable: {git_status.error or 'unknown error'}")
        elif git_status.working_tree == WorkingTreeStatus.ERROR:
            reasons.append(f"Git read failure: {git_status.error or 'unknown error'}")
        else:
            if git_status.working_tree == WorkingTreeStatus.DIRTY:
                reasons.append("Working tree is dirty (uncommitted changes present).")
            if git_status.tracking == TrackingStatus.DIVERGED:
                reasons.append("Local branch has diverged from its upstream tracking branch.")
            elif git_status.tracking == TrackingStatus.ERROR:
                reasons.append(f"Git tracking read failure: {git_status.error or 'unknown error'}")

        if state is None:
            reasons.append(state_error or "Project state unavailable.")
        else:
            if checkpoint_valid is False:
                reasons.append(
                    f"Latest checkpoint commit '{state.latest_checkpoint.commit}' "
                    "could not be resolved in the repository."
                )
            if state.attention.required:
                reasons.append(state.attention.reason or "Semantic attention flag set in project state.")

        if reasons:
            return AttentionState(required=True, reason="; ".join(reasons))
        return AttentionState(required=False, reason=None)
