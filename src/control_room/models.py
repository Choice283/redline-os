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
    """

    repository_valid: bool
    branch: str | None = None
    detached_head: bool = False
    head_sha: str | None = None
    head_sha_short: str | None = None
    working_tree: WorkingTreeStatus = WorkingTreeStatus.UNKNOWN
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
    such as a success score or capability count."""

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
