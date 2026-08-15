"""Combines ProjectDefinition + live GitStatus + ProjectState into a
single ProjectSnapshot -- the only boundary the web layer talks to.

Neither the HTML/JS frontend nor app.py's routes touch GitReader,
StateReader, or ProjectRegistry directly; they call this service and
render whatever ProjectSnapshot it returns, including degraded/unknown
states.
"""
from __future__ import annotations

import logging

from control_room.git_reader import GitReader
from control_room.models import AttentionState, ProjectDefinition, ProjectSnapshot, TrackingStatus, WorkingTreeStatus
from control_room.project_registry import ProjectRegistry
from control_room.state_reader import StateReader, StateReadError

logger = logging.getLogger("redline_os.control_room.project_status_service")


class ProjectNotFoundError(Exception):
    """Raised when a requested project id is not present in the registry."""


class ProjectStatusService:
    def __init__(self, registry: ProjectRegistry, state_reader: StateReader | None = None):
        self._registry = registry
        self._state_reader = state_reader or StateReader()

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

        return ProjectSnapshot(
            project_id=definition.id,
            name=definition.name,
            git=git_status,
            state=state,
            state_error=state_error,
            attention=attention,
        )

    @staticmethod
    def _checkpoint_valid(repository_path, git_status, state) -> bool | None:
        if state is None or not git_status.repository_valid:
            return None
        return GitReader(repository_path).commit_exists(state.latest_checkpoint.commit)

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
