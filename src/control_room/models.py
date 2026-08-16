"""Typed data model for Control Room V0.

Three sources compose into one `ProjectSnapshot`:

  ProjectDefinition  -- which projects to display (config/control_room/projects.yaml)
  GitStatus          -- live local Git truth, read fresh on every request
  ProjectState       -- durable semantic state (docs/control_room/PROJECT_STATE.yaml)

Git facts (branch, HEAD, dirty/clean, tracking) are never stored in
ProjectState and never duplicated into it -- they are read live by
GitReader on every snapshot. See docs/CONTROL_ROOM_V0_ARCHITECTURE.md.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ProjectDefinition(BaseModel):
    """A single entry from the project registry: which project to show and
    where its repository and semantic state file live."""

    id: str
    name: str
    repository: str
    state_file: str


# -- live Git state --------------------------------------------------------


class WorkingTreeStatus(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    NOT_A_REPOSITORY = "NOT_A_REPOSITORY"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class WorkingTreeChangeKind(str, Enum):
    TRACKED = "TRACKED"
    RENAMED = "RENAMED"
    COPIED = "COPIED"
    UNTRACKED = "UNTRACKED"
    CONFLICTED = "CONFLICTED"


class WorkingTreeChange(BaseModel):
    """One uncommitted change to a single repository-relative path
    (Current Working Tree Change Detail, Mission 8) -- one record per
    path, exactly as `git status --porcelain=v2` itself reports it. A
    file that is both staged and further modified in the working tree
    is one `WorkingTreeChange` with both `index_status` and
    `worktree_status` set -- never two disconnected entries for the same
    path.

    `index_status`/`worktree_status` are the raw single-character
    porcelain X/Y status codes (e.g. "M", "A", "D") for the index and
    worktree dimensions respectively; a dimension with no change ('.' in
    Git's own output) is `None`, never a literal '.'. `UNTRACKED`
    entries carry neither, since untracked paths have no X/Y field at
    all in Git's output.

    `original_path` is set only for `RENAMED`/`COPIED` and is the
    pre-rename/pre-copy path Git itself reports -- the similarity score,
    diff content, and all other commit/diff metadata are intentionally
    never read or exposed, matching the paths-only boundary already
    established by Checkpoint Change Set Detail (Mission 7). Note Git's
    own rename detection here only ever applies to a *staged* rename
    (index vs HEAD); a rename made in the working tree without staging
    it is reported by Git as a plain delete plus a plain untracked add,
    not as a `RENAMED` record -- this module does not attempt to infer a
    rename Git itself did not detect."""

    path: str
    original_path: str | None = None
    index_status: str | None = None
    worktree_status: str | None = None
    kind: WorkingTreeChangeKind


class TrackingStatus(str, Enum):
    SYNCHRONIZED = "SYNCHRONIZED"
    AHEAD = "AHEAD"
    BEHIND = "BEHIND"
    DIVERGED = "DIVERGED"
    NO_UPSTREAM = "NO_UPSTREAM"
    DETACHED_HEAD = "DETACHED_HEAD"
    NOT_A_REPOSITORY = "NOT_A_REPOSITORY"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class GitStatus(BaseModel):
    """Live local Git truth for one repository, read fresh on every request.

    A locally-known tracking comparison (ahead/behind/diverged against
    `upstream`) proves only local knowledge of that ref -- Control Room V0
    never runs `git fetch`, so this is never "GitHub verified."

    `working_tree_changes`/`working_tree_changes_error` are the Current
    Working Tree Change Detail (Mission 8) -- both derived from the same
    single `git --no-optional-locks status --porcelain=v2 -z
    --untracked-files=all --renames` read that also determines
    `working_tree` (CLEAN/DIRTY) above, never a
    second Git invocation, so the two can never disagree about whether
    the tree is dirty. The coarse CLEAN/DIRTY classification only needs
    to know whether that command's output is empty, which does not
    depend on successfully decoding every individual record; decoding
    the full per-path detail is a stricter, separate step, so it is
    possible (though expected to be rare) for `working_tree` to be a
    trustworthy DIRTY while `working_tree_changes` is `None` with
    `working_tree_changes_error` set, when the coarse output was
    non-empty but a record inside it did not match any recognized
    porcelain-v2 shape. This is a narrower failure than a `git status`
    read failure severe enough to fail the whole snapshot (that failure
    mode still degrades all of `GitStatus`, exactly as it always has).
    `working_tree_changes` is never a partial/best-effort list: any
    unrecognized or malformed record degrades the entire list to `None`
    rather than silently dropping just that one record.
    """

    repository_valid: bool
    branch: str | None = None
    detached_head: bool = False
    head_sha: str | None = None
    head_sha_short: str | None = None
    working_tree: WorkingTreeStatus = WorkingTreeStatus.UNKNOWN
    working_tree_changes: list[WorkingTreeChange] | None = None
    working_tree_changes_error: str | None = None
    tracking: TrackingStatus = TrackingStatus.UNKNOWN
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    error: str | None = None


# -- durable semantic project state (docs/control_room/PROJECT_STATE.yaml) --


class MissionState(BaseModel):
    id: str
    title: str
    phase: str


class CheckpointState(BaseModel):
    label: str
    commit: str
    document: str


class ValidationState(BaseModel):
    status: str
    summary: str


class AttentionState(BaseModel):
    required: bool
    reason: str | None = None


class ProjectState(BaseModel):
    """Semantic/operational meaning for one project. Never contains live
    Git facts (branch, HEAD, working-tree/tracking condition) -- those
    come from GitStatus only."""

    project_id: str
    summary: str
    current_mission: MissionState
    latest_checkpoint: CheckpointState
    validation: ValidationState
    attention: AttentionState


# -- historical mission/checkpoint record (docs/control_room/*_CLOSURE_*.md) -


class MissionHistoryEntry(BaseModel):
    """One historical Control Room mission, parsed fresh on every request
    from its closure document under docs/control_room/. Never persisted
    and never stored in PROJECT_STATE.yaml, which remains a current-state
    record only. A field that could not be determined from the durable
    record is None, never invented -- see `parse_error` for why.

    `validation_section`/`independent_review_section`/`ci_section` are the
    Validation & Evidence Detail (Mission 5): the verbatim body text of
    each named section in the closure document, or None if that heading
    is absent. These are intentionally *not* further decomposed into
    fields like "test count" or "verdict" -- across the four closure
    documents so far, that prose is worded differently mission to mission
    (e.g. "Claude focused validation" vs "Focused Control Room suite"),
    so any such sub-parsing would silently misparse or drop real evidence
    for at least one mission. Showing the section verbatim is the reading
    of proven evidence Mission 5 requires, not a fragile re-derivation of
    it.

    `purpose_section`/`delivered_capability_section`/`deferred_work_section`
    are the Mission Scope & Outcome Detail (Mission 6): the verbatim body
    text of each closure document's `## Purpose`, `## Delivered
    Capability`, and `## Deferred Work` sections, or None if absent. Same
    rule as the evidence fields above: preserved as recorded, never
    synthesized, summarized, scored, or reinterpreted into a derived field
    such as a success score or capability count.

    `checkpoint_changed_files`/`checkpoint_changes_error` are the
    Checkpoint Change Set Detail (Mission 7) -- machine truth, not closure
    prose. `checkpoint_changed_files` is the repository-relative file
    paths `GitReader.read_commit_changed_files()` reports for this entry's
    `checkpoint_commit` -- a real Git query, resolved fresh on every
    request, never parsed from the closure document. Three distinct
    states, never conflated: `(paths-with-len>0, None)` a normal change
    set; `([], None)` a legitimately empty change set (the commit changed
    no tracked files); `(None, <message>)` the change set could not be
    determined at all (unresolved checkpoint, Git failure, or invalid
    input) -- this is deliberately a separate field from `parse_error`,
    which remains reserved for closure-document parsing problems only."""

    mission_number: int | None = None
    title: str | None = None
    status: str = "unknown"
    checkpoint_commit: str | None = None
    checkpoint_resolved: bool | None = None
    closure_document: str
    closure_date: str | None = None
    parse_error: str | None = None
    validation_section: str | None = None
    independent_review_section: str | None = None
    ci_section: str | None = None
    purpose_section: str | None = None
    delivered_capability_section: str | None = None
    deferred_work_section: str | None = None
    checkpoint_changed_files: list[str] | None = None
    checkpoint_changes_error: str | None = None


# -- composed view -----------------------------------------------------------


class ProjectSnapshot(BaseModel):
    """The single object the web layer consumes: registry + live Git +
    semantic state + mission history, combined by ProjectStatusService.
    `attention` here is the *derived, combined* signal (semantic attention
    plus deterministic Git/state-read facts) -- distinct from
    `state.attention`, which is the semantic-only flag as authored in
    PROJECT_STATE.yaml."""

    project_id: str
    name: str
    git: GitStatus
    state: ProjectState | None = None
    state_error: str | None = None
    attention: AttentionState = Field(default_factory=lambda: AttentionState(required=False, reason=None))
    mission_history: list[MissionHistoryEntry] = Field(default_factory=list)
