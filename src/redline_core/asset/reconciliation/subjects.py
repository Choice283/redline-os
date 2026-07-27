"""Tagged subjects for Asset Registry reconciliation plan items."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from redline_core.asset.reconciliation.enums import ConflictKind


def _require_clean_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    if value.strip() != value:
        raise ValueError(f"{field_name} must not contain leading or trailing whitespace.")
    if not value:
        raise ValueError(f"{field_name} must not be empty.")


def _clean_unique_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    cleaned = tuple(values)
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    for value in cleaned:
        _require_clean_identifier(value, field_name)
    if len(set(cleaned)) != len(cleaned):
        raise ValueError(f"{field_name} must not contain duplicates.")
    return tuple(sorted(cleaned))


@dataclass(frozen=True, slots=True)
class RegistryRecordSubject:
    """Subject that references exactly one registry record."""

    asset_id: str
    record_id: int | None = None

    def __post_init__(self) -> None:
        _require_clean_identifier(self.asset_id, "asset_id")
        if self.record_id is not None and (
            not isinstance(self.record_id, int) or isinstance(self.record_id, bool) or self.record_id < 0
        ):
            raise ValueError("record_id must be a non-negative integer when present.")

    def canonical_key(self) -> tuple[object, ...]:
        """Return the deterministic key for this subject."""
        return ("registry_record", self.asset_id)


@dataclass(frozen=True, slots=True)
class ObservationSubject:
    """Subject that references exactly one caller-supplied observation."""

    observation_id: str

    def __post_init__(self) -> None:
        _require_clean_identifier(self.observation_id, "observation_id")

    def canonical_key(self) -> tuple[object, ...]:
        """Return the deterministic key for this subject."""
        return ("observation", self.observation_id)


@dataclass(frozen=True, slots=True)
class RegistryRecordGroupSubject:
    """Subject that references a deterministic group of registry records."""

    asset_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_ids", _clean_unique_tuple(self.asset_ids, "asset_ids"))

    def canonical_key(self) -> tuple[object, ...]:
        """Return the deterministic key for this subject."""
        return ("registry_record_group", self.asset_ids)


@dataclass(frozen=True, slots=True)
class ObservationGroupSubject:
    """Subject that references a deterministic group of observations."""

    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_ids", _clean_unique_tuple(self.observation_ids, "observation_ids"))

    def canonical_key(self) -> tuple[object, ...]:
        """Return the deterministic key for this subject."""
        return ("observation_group", self.observation_ids)


@dataclass(frozen=True, slots=True)
class MixedConflictSubject:
    """Subject for conflicts that span records and observations."""

    asset_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    conflict_kind: ConflictKind

    def __post_init__(self) -> None:
        if not isinstance(self.conflict_kind, ConflictKind):
            raise ValueError("conflict_kind must be a ConflictKind enum value.")
        object.__setattr__(self, "asset_ids", _clean_unique_tuple(self.asset_ids, "asset_ids"))
        object.__setattr__(
            self,
            "observation_ids",
            _clean_unique_tuple(self.observation_ids, "observation_ids"),
        )

    def canonical_key(self) -> tuple[object, ...]:
        """Return the deterministic key for this subject."""
        return ("mixed_conflict", self.conflict_kind.value, self.asset_ids, self.observation_ids)


PlanSubject: TypeAlias = (
    RegistryRecordSubject
    | ObservationSubject
    | RegistryRecordGroupSubject
    | ObservationGroupSubject
    | MixedConflictSubject
)
"""Tagged union of public reconciliation subject variants."""
