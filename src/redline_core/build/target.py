"""Pure build-target parsing for Phase 13."""
from __future__ import annotations

import re
from dataclasses import dataclass

from redline_core.config.schema import NamingConfig

_TARGET_PATTERN = re.compile(r"^Episode_(?P<digits>[0-9]{4})$")


class BuildTargetError(ValueError):
    """Raised when a build target does not match the canonical target contract."""


@dataclass(frozen=True, slots=True)
class BuildTarget:
    original_target: str
    episode_number: int
    episode_id: str


def parse_build_target(target: str, naming: NamingConfig) -> BuildTarget:
    """Parse an exact Episode_#### target into Redline episode identity."""
    if not isinstance(target, str):
        raise BuildTargetError("build target must be a string.")
    if not isinstance(naming, NamingConfig):
        raise BuildTargetError("naming must be a NamingConfig.")

    match = _TARGET_PATTERN.fullmatch(target)
    if match is None:
        raise BuildTargetError("build target must match Episode_####.")

    episode_number = int(match.group("digits"))
    if episode_number <= 0:
        raise BuildTargetError("build target episode number must be greater than zero.")

    episode_id = naming.episode_id_pattern.format(episode_number=episode_number)
    return BuildTarget(original_target=target, episode_number=episode_number, episode_id=episode_id)
