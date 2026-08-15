"""Project registry reader for Control Room V0.

Answers exactly one question: which projects should Control Room display,
and where do their repository and semantic state file live? It never
reads live Git state or semantic project state itself -- those are
GitReader's and StateReader's jobs respectively.

`repository` and `state_file` in config/control_room/projects.yaml are
resolved relative to `base_dir` (the directory Control Room is launched
from -- see control_room.app), the same convention
redline_core.config.loader uses for its own config files.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from control_room.models import ProjectDefinition

logger = logging.getLogger("redline_os.control_room.project_registry")


class RegistryError(Exception):
    """Raised when the project registry is missing, malformed, or invalid."""


class ProjectRegistry:
    """Loads config/control_room/projects.yaml (or an equivalent path)."""

    def __init__(self, registry_path: str | Path, base_dir: str | Path | None = None):
        self._registry_path = Path(registry_path)
        self._base_dir = Path(base_dir) if base_dir is not None else Path.cwd()

    def load(self) -> list[ProjectDefinition]:
        if not self._registry_path.is_file():
            message = f"project registry not found: {self._registry_path}"
            logger.error("control room registry load failed: %s", message)
            raise RegistryError(message)

        try:
            raw_text = self._registry_path.read_text(encoding="utf-8")
        except OSError as exc:
            message = f"unable to read project registry {self._registry_path}: {exc}"
            logger.error("control room registry load failed: %s", message)
            raise RegistryError(message) from exc

        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            message = f"malformed YAML in project registry {self._registry_path}: {exc}"
            logger.error("control room registry load failed: %s", message)
            raise RegistryError(message) from exc

        if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
            message = f"project registry {self._registry_path} must contain a top-level 'projects' list"
            logger.error("control room registry load failed: %s", message)
            raise RegistryError(message)

        definitions: list[ProjectDefinition] = []
        for entry in data["projects"]:
            try:
                definitions.append(ProjectDefinition(**entry))
            except (TypeError, ValidationError) as exc:
                message = f"invalid project entry in registry {self._registry_path}: {exc}"
                logger.error("control room registry load failed: %s", message)
                raise RegistryError(message) from exc

        seen_ids = set()
        for definition in definitions:
            if definition.id in seen_ids:
                message = f"duplicate project id '{definition.id}' in registry {self._registry_path}"
                logger.error("control room registry load failed: %s", message)
                raise RegistryError(message)
            seen_ids.add(definition.id)

        return definitions

    def get(self, project_id: str) -> ProjectDefinition | None:
        for definition in self.load():
            if definition.id == project_id:
                return definition
        return None

    def resolve_repository_path(self, definition: ProjectDefinition) -> Path:
        return (self._base_dir / definition.repository).resolve()

    def resolve_state_file_path(self, definition: ProjectDefinition) -> Path:
        return (self._base_dir / definition.state_file).resolve()
