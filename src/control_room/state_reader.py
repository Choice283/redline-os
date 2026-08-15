"""Reader for a project's durable semantic state file
(docs/control_room/PROJECT_STATE.yaml or equivalent).

Mirrors the shape of redline_core.config.loader: this is the only place
that reads a project-state YAML file directly and validates it against
the Pydantic schema in control_room.models. Callers receive either a
validated ProjectState or a StateReadError -- never a partially-trusted
dict, and never a value invented for a field that was actually missing.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from control_room.models import ProjectState

logger = logging.getLogger("redline_os.control_room.state_reader")


class StateReadError(Exception):
    """Raised when a project's semantic state file is missing, malformed,
    or fails schema validation."""


class StateReader:
    """Loads and validates a single project's PROJECT_STATE.yaml."""

    def read(self, state_file_path: str | Path) -> ProjectState:
        path = Path(state_file_path)
        if not path.is_file():
            message = f"project state file not found: {path}"
            logger.error("control room state read failed: %s", message)
            raise StateReadError(message)

        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            message = f"unable to read project state file {path}: {exc}"
            logger.error("control room state read failed: %s", message)
            raise StateReadError(message) from exc

        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            message = f"malformed YAML in project state file {path}: {exc}"
            logger.error("control room state read failed: %s", message)
            raise StateReadError(message) from exc

        if not isinstance(data, dict):
            message = f"project state file {path} must contain a YAML mapping at the top level"
            logger.error("control room state read failed: %s", message)
            raise StateReadError(message)

        try:
            return ProjectState(**data)
        except ValidationError as exc:
            message = f"project state file {path} failed schema validation: {exc}"
            logger.error("control room state read failed: %s", message)
            raise StateReadError(message) from exc
