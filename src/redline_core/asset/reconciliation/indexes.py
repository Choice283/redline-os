"""Deterministic index construction for Asset Registry reconciliation planning.

Implements Phase 3 Slice 5 ("Indexes and collision analysis"): builds
immutable, already-grouped lookup structures over an already-validated
``ValidatedReconciliationInputs`` pair so later matching and classification
slices (``matching.py``, ``classification.py``) can avoid broad
record-by-observation comparisons.

This module performs no structural validation of its own -- it assumes
``asset_id`` and ``observation_id`` are already unique, because
``validation.py`` (Slices 2-3, approved) already enforces that before
``build_indexes`` ever runs. It performs no classification, no matching
decisions, no action generation, and no filesystem, SQLite, or Resolve work.
It does not mutate its inputs.

Registry-side and observation-side identity keys are intentionally different
shapes: registry evidence (``RegistryIdentityEvidence``) carries
``normalization_format`` and a per-row ``scope_id`` that caller-supplied
``AssetObservation`` facts do not carry. Cross-referencing the two sides to
decide an actual match is a matching-time (Slice 6/7) responsibility, not an
indexing-time one -- this module only proves collisions within one side at a
time.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetVerificationState,
)
from redline_core.asset.reconciliation.canonical import (
    RegistryEvidenceLookupKey,
    OptionalTextSortKey,
    _normalize_algorithm,
    _optional_text_sort_key,
    _registry_evidence_lookup_key,
    _registry_evidence_output_sort_key,
)
from redline_core.asset.reconciliation.enums import EvidenceKind
from redline_core.asset.reconciliation.exceptions import ReconciliationLimitExceededError
from redline_core.asset.reconciliation.models import (
    AssetObservation,
    ObservationRootScope,
    RegistryIdentityEvidence,
    ReconciliationRequest,
    RegistrySnapshot,
)
from redline_core.asset.reconciliation.subjects import ObservationGroupSubject, RegistryRecordGroupSubject
from redline_core.asset.reconciliation.validation import ValidatedReconciliationInputs


ObservationIdentityKey = tuple[str, OptionalTextSortKey, str]
"""Observation-side comparable evidence key: (kind, algorithm, normalized_value).

Deliberately narrower than ``RegistryEvidenceLookupKey``: ``AssetObservation``
carries no ``normalization_format`` or per-fact ``scope_id``, so this key is
not directly joinable against the registry-side key. See module docstring.
"""

WeakCandidateKey = tuple[str, tuple[int, int]]
"""Weak candidate bucket key: (normalized file name, optional file size)."""


@dataclass(frozen=True, slots=True)
class RecordState:
    """Deterministic lifecycle/availability/verification projection for one record."""

    lifecycle: AssetLifecycle
    availability: AssetAvailability
    verification: AssetVerificationState


@dataclass(frozen=True, slots=True)
class RegistryIndexes:
    """Deterministic registry-side lookup structures built from one snapshot."""

    asset_id_to_record: Mapping[str, AssetRegistryRecord]
    path_key_to_asset_ids: Mapping[str, tuple[str, ...]]
    identity_key_to_asset_ids: Mapping[RegistryEvidenceLookupKey, tuple[str, ...]]
    record_evidence_by_asset_id: Mapping[str, tuple[RegistryIdentityEvidence, ...]]
    record_state_by_asset_id: Mapping[str, RecordState]
    path_collision_groups: tuple[RegistryRecordGroupSubject, ...]
    identity_collision_groups: tuple[RegistryRecordGroupSubject, ...]


@dataclass(frozen=True, slots=True)
class ObservationIndexes:
    """Deterministic observation-side lookup structures built from one request."""

    observation_id_to_observation: Mapping[str, AssetObservation]
    path_key_to_observation_ids: Mapping[str, tuple[str, ...]]
    identity_key_to_observation_ids: Mapping[ObservationIdentityKey, tuple[str, ...]]
    trusted_claimed_asset_id_to_observation_ids: Mapping[str, tuple[str, ...]]
    weak_candidate_buckets: Mapping[WeakCandidateKey, tuple[str, ...]]
    path_collision_groups: tuple[ObservationGroupSubject, ...]
    identity_collision_groups: tuple[ObservationGroupSubject, ...]


@dataclass(frozen=True, slots=True)
class ScopeIndexes:
    """Deterministic per-scope lookup structures built from one request's scopes."""

    roots_by_scope_id: Mapping[str, tuple[ObservationRootScope, ...]]
    explicit_asset_ids_by_scope_id: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ReconciliationIndexes:
    """Top-level bundle of all Slice 5 indexes for one validated input pair."""

    registry: RegistryIndexes
    observations: ObservationIndexes
    scopes: ScopeIndexes


def build_indexes(inputs: ValidatedReconciliationInputs) -> ReconciliationIndexes:
    """Build deterministic registry, observation, and scope indexes.

    ``inputs`` must already be the output of ``validate_reconciliation_inputs``.
    Performs no filesystem, SQLite, or Resolve access. Does not mutate
    ``inputs`` or any nested object.
    """
    limits = inputs.request.limit_policy
    registry = _build_registry_indexes(inputs.snapshot, limits.max_duplicate_group_size)
    observations = _build_observation_indexes(inputs.request, limits.max_duplicate_group_size)
    scopes = _build_scope_indexes(inputs.request)
    return ReconciliationIndexes(registry=registry, observations=observations, scopes=scopes)


# ---------------------------------------------------------------------------
# Shared grouping helpers
# ---------------------------------------------------------------------------


def _group_by(items: Any, key_fn: Callable[[Any], Any], value_fn: Callable[[Any], str]) -> dict[Any, list[str]]:
    """Group ``value_fn(item)`` under ``key_fn(item)`` for every item, in encounter order."""
    groups: dict[Any, list[str]] = {}
    for item in items:
        groups.setdefault(key_fn(item), []).append(value_fn(item))
    return groups


def _finalize_groups(
    groups: dict[Any, list[str]],
    limit: int,
    group_kind: str,
) -> dict[Any, tuple[str, ...]]:
    """Sort each group's members and the group table itself; enforce the size bound."""
    finalized: dict[Any, tuple[str, ...]] = {}
    for key, members in groups.items():
        unique_sorted = tuple(sorted(set(members)))
        if len(unique_sorted) > limit:
            raise ReconciliationLimitExceededError(
                "duplicate group limit exceeded",
                context={"limit_name": "max_duplicate_group_size", "limit_value": limit, "count": len(unique_sorted)},
                reason_code=group_kind,
            )
        finalized[key] = unique_sorted
    return dict(sorted(finalized.items()))


def _detect_index_collisions(
    grouped: Mapping[Any, tuple[str, ...]],
    subject_factory: Callable[[tuple[str, ...]], Any],
) -> tuple[Any, ...]:
    """Return group-subject collisions for every key with more than one member."""
    groups = [subject_factory(members) for members in grouped.values() if len(members) > 1]
    return tuple(sorted(groups, key=lambda subject: subject.canonical_key()))


# ---------------------------------------------------------------------------
# Registry indexes
# ---------------------------------------------------------------------------


def _build_registry_indexes(snapshot: RegistrySnapshot, group_limit: int) -> RegistryIndexes:
    asset_id_to_record = MappingProxyType(
        dict(sorted(((record.asset_id, record) for record in snapshot.records)))
    )

    path_groups = _group_by(
        (record for record in snapshot.records if record.normalized_resolved_path is not None),
        key_fn=lambda record: record.normalized_resolved_path,
        value_fn=lambda record: record.asset_id,
    )
    path_key_to_asset_ids = MappingProxyType(
        _finalize_groups(path_groups, group_limit, "registry_path_collision")
    )

    identity_groups = _group_by(
        snapshot.identity_evidence,
        key_fn=_registry_evidence_lookup_key,
        value_fn=lambda evidence: evidence.asset_id,
    )
    identity_key_to_asset_ids = MappingProxyType(
        _finalize_groups(identity_groups, group_limit, "registry_identity_collision")
    )

    evidence_by_asset_id: dict[str, list[RegistryIdentityEvidence]] = {}
    for evidence in snapshot.identity_evidence:
        evidence_by_asset_id.setdefault(evidence.asset_id, []).append(evidence)
    record_evidence_by_asset_id = MappingProxyType(
        {
            asset_id: tuple(sorted(rows, key=_registry_evidence_output_sort_key))
            for asset_id, rows in sorted(evidence_by_asset_id.items())
        }
    )

    record_state_by_asset_id = MappingProxyType(
        dict(
            sorted(
                (
                    record.asset_id,
                    RecordState(
                        lifecycle=record.lifecycle,
                        availability=record.availability,
                        verification=record.verification,
                    ),
                )
                for record in snapshot.records
            )
        )
    )

    path_collision_groups = _detect_index_collisions(
        path_key_to_asset_ids, lambda ids: RegistryRecordGroupSubject(asset_ids=ids)
    )
    identity_collision_groups = _detect_index_collisions(
        identity_key_to_asset_ids, lambda ids: RegistryRecordGroupSubject(asset_ids=ids)
    )

    return RegistryIndexes(
        asset_id_to_record=asset_id_to_record,
        path_key_to_asset_ids=path_key_to_asset_ids,
        identity_key_to_asset_ids=identity_key_to_asset_ids,
        record_evidence_by_asset_id=record_evidence_by_asset_id,
        record_state_by_asset_id=record_state_by_asset_id,
        path_collision_groups=path_collision_groups,
        identity_collision_groups=identity_collision_groups,
    )


# ---------------------------------------------------------------------------
# Observation indexes
# ---------------------------------------------------------------------------


def _observation_identity_facts(observation: AssetObservation) -> tuple[ObservationIdentityKey, ...]:
    """Return every comparable identity key one observation contributes."""
    facts: list[ObservationIdentityKey] = []
    for algorithm, digest in observation.content_hashes:
        facts.append(
            (EvidenceKind.FULL_CONTENT_HASH.value, _optional_text_sort_key(_normalize_algorithm(algorithm)), digest)
        )
    for fingerprint in observation.partial_fingerprints:
        facts.append((EvidenceKind.PARTIAL_FINGERPRINT.value, _optional_text_sort_key(None), fingerprint))
    if observation.filesystem_identity is not None:
        facts.append(
            (EvidenceKind.FILESYSTEM_IDENTITY.value, _optional_text_sort_key(None), observation.filesystem_identity)
        )
    return tuple(facts)


def _weak_candidate_key(observation: AssetObservation) -> WeakCandidateKey | None:
    """Return the weak-candidate bucket key for one observation, or None if unusable."""
    if observation.file_name is None or not observation.file_name.strip():
        return None
    normalized_name = observation.file_name.strip().lower()
    size = observation.file_size_bytes
    size_key = (0, 0) if size is None else (1, size)
    return (normalized_name, size_key)


def _build_observation_indexes(request: ReconciliationRequest, group_limit: int) -> ObservationIndexes:
    observation_id_to_observation = MappingProxyType(
        dict(sorted((observation.observation_id, observation) for observation in request.observations))
    )

    path_groups = _group_by(
        (obs for obs in request.observations if obs.normalized_resolved_path is not None),
        key_fn=lambda obs: obs.normalized_resolved_path,
        value_fn=lambda obs: obs.observation_id,
    )
    path_key_to_observation_ids = MappingProxyType(
        _finalize_groups(path_groups, group_limit, "observation_path_collision")
    )

    identity_groups: dict[ObservationIdentityKey, list[str]] = {}
    for observation in request.observations:
        for key in _observation_identity_facts(observation):
            identity_groups.setdefault(key, []).append(observation.observation_id)
    identity_key_to_observation_ids = MappingProxyType(
        _finalize_groups(identity_groups, group_limit, "observation_identity_collision")
    )

    trusted_sources = set(request.trusted_asset_id_source_ids)
    trusted_groups = _group_by(
        (
            obs
            for obs in request.observations
            if obs.source_id in trusted_sources and obs.claimed_asset_id is not None
        ),
        key_fn=lambda obs: obs.claimed_asset_id,
        value_fn=lambda obs: obs.observation_id,
    )
    trusted_claimed_asset_id_to_observation_ids = MappingProxyType(
        _finalize_groups(trusted_groups, group_limit, "trusted_claimed_asset_id_group")
    )

    weak_groups: dict[WeakCandidateKey, list[str]] = {}
    for observation in request.observations:
        key = _weak_candidate_key(observation)
        if key is not None:
            weak_groups.setdefault(key, []).append(observation.observation_id)
    weak_candidate_buckets = MappingProxyType(
        _finalize_groups(weak_groups, group_limit, "weak_candidate_bucket")
    )

    path_collision_groups = _detect_index_collisions(
        path_key_to_observation_ids, lambda ids: ObservationGroupSubject(observation_ids=ids)
    )
    identity_collision_groups = _detect_index_collisions(
        identity_key_to_observation_ids, lambda ids: ObservationGroupSubject(observation_ids=ids)
    )

    return ObservationIndexes(
        observation_id_to_observation=observation_id_to_observation,
        path_key_to_observation_ids=path_key_to_observation_ids,
        identity_key_to_observation_ids=identity_key_to_observation_ids,
        trusted_claimed_asset_id_to_observation_ids=trusted_claimed_asset_id_to_observation_ids,
        weak_candidate_buckets=weak_candidate_buckets,
        path_collision_groups=path_collision_groups,
        identity_collision_groups=identity_collision_groups,
    )


# ---------------------------------------------------------------------------
# Scope indexes
# ---------------------------------------------------------------------------


def _build_scope_indexes(request: ReconciliationRequest) -> ScopeIndexes:
    roots_by_scope_id = MappingProxyType(
        dict(
            sorted(
                (
                    scope.scope_id,
                    tuple(
                        sorted(
                            scope.roots,
                            key=lambda root: (-len(root.canonical_key()), root.canonical_key()),
                        )
                    ),
                )
                for scope in request.scopes
            )
        )
    )
    explicit_asset_ids_by_scope_id = MappingProxyType(
        dict(sorted((scope.scope_id, scope.explicit_asset_ids) for scope in request.scopes))
    )
    return ScopeIndexes(
        roots_by_scope_id=roots_by_scope_id,
        explicit_asset_ids_by_scope_id=explicit_asset_ids_by_scope_id,
    )
