"""Trusted ID and exact-path matching for Asset Registry reconciliation.

Implements Phase 3 Slice 6 ("Trusted ID and exact-path matching"): the
trusted-claimed-Asset-ID and exact-normalized-path portions of the matching
pipeline described in the approved architecture and implementation plan.

Explicitly out of scope this slice (deferred to Slice 7 and later): strong
full-content-hash matching, partial-fingerprint matching, filesystem-identity
matching, weak matching, unmatched-subject production, final classification,
findings, action generation, plan assembly, and public serialization. This
module is expected to be extended, not rewritten, once that work begins.

``findings.py`` and the originally-planned richer ``evidence.py`` types
(``PlanEvidence``, ``EvidenceCandidate``, ...) do not exist in this
repository. Blocking reasons and conflict facts are represented the same way
``scope.py`` and ``indexes.py`` already do: plain bounded static string codes
and the existing ``ConflictKind``/``subjects.py`` types -- not finding
objects. A blocking code is a neutral fact, not a final
``PrimaryClassification`` -- mapping one onto the other is classification.py's
job (Slice 8), not this module's.

This module performs no filesystem, SQLite, network, or Resolve access, no
hash or weak-candidate matching, no final classification, and no mutation of
its inputs.

Evidence fact vocabulary (small and closed, one term per outcome):

- ``duplicate_observation_path`` -- observation blocked by an observation-side
  path collision.
- ``registry_path_collision`` -- record (or an observation claiming it) blocked
  by a registry-side path collision.
- ``unknown_trusted_asset_id`` -- trusted claim names an Asset ID absent from
  the registry.
- ``trusted_asset_id_claimed_by_multiple_observations`` -- two or more trusted
  observations claim the same Asset ID.
- ``trusted_asset_id`` -- a trusted-claim-only definitive association.
- ``exact_path`` -- an exact-path-only definitive association.
- ``trusted_asset_id_exact_path_agreement`` -- trusted claim and exact path
  name the same Asset ID.
- ``trusted_asset_id_exact_path_conflict`` -- trusted claim and exact path
  disagree for one observation.
- ``cross_observation_asset_id_conflict`` -- two different observations each
  produced a clean single-signal candidate for the same Asset ID.

No evidence fact ever embeds a raw normalized path, source ID, claimed Asset
ID, digest, fingerprint, filesystem identity, or any other user-controlled
value.
"""
from __future__ import annotations

from dataclasses import dataclass

from redline_core.asset.reconciliation.enums import AssetIdTrustPolicy, ConflictKind
from redline_core.asset.reconciliation.indexes import ReconciliationIndexes
from redline_core.asset.reconciliation.subjects import MixedConflictSubject, PlanSubject
from redline_core.asset.reconciliation.validation import ValidatedReconciliationInputs


_DUPLICATE_OBSERVATION_PATH = "duplicate_observation_path"
_REGISTRY_PATH_COLLISION = "registry_path_collision"
_UNKNOWN_TRUSTED_ASSET_ID = "unknown_trusted_asset_id"
_TRUSTED_ID_CLAIMED_BY_MULTIPLE_OBSERVATIONS = "trusted_asset_id_claimed_by_multiple_observations"

_TRUSTED_ASSET_ID_KIND = "trusted_asset_id"
_EXACT_PATH_KIND = "exact_path"
_TRUSTED_AND_PATH_KIND = "trusted_asset_id_and_exact_path"

_FACT_TRUSTED_ASSET_ID = "trusted_asset_id"
_FACT_EXACT_PATH = "exact_path"
_FACT_TRUSTED_EXACT_PATH_AGREEMENT = "trusted_asset_id_exact_path_agreement"
_FACT_TRUSTED_EXACT_PATH_CONFLICT = "trusted_asset_id_exact_path_conflict"
_FACT_CROSS_OBSERVATION_CONFLICT = "cross_observation_asset_id_conflict"

_ObservationToAssetId = dict[str, str]
"""Internal candidate map: observation_id -> candidate asset_id."""


@dataclass(frozen=True, slots=True)
class DefinitiveAssociation:
    """One resolved, non-conflicting Asset ID <-> observation pairing."""

    asset_id: str
    observation_id: str
    association_kind: str
    evidence_facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BlockedObservation:
    """One observation excluded from this slice's matching, with a stable reason."""

    observation_id: str
    blocking_code: str
    evidence_facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BlockedRecord:
    """One registry record excluded from this slice's matching, with a stable reason."""

    asset_id: str
    blocking_code: str
    evidence_facts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConflictGroup:
    """One authoritative-identity disagreement between two or more candidates."""

    subject: PlanSubject
    conflict_kind: ConflictKind
    asset_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    evidence_facts: tuple[str, ...]
    proposal_blocked: bool = True


@dataclass(frozen=True, slots=True)
class ConsumedIds:
    """Asset IDs and observation IDs consumed by a surviving definitive association."""

    asset_ids: frozenset[str]
    observation_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class MatchingState:
    """Immutable Slice 6 matching result: trusted-ID and exact-path facts only."""

    definitive_associations: tuple[DefinitiveAssociation, ...]
    blocked_observations: tuple[BlockedObservation, ...]
    blocked_records: tuple[BlockedRecord, ...]
    conflict_groups: tuple[ConflictGroup, ...]
    consumed: ConsumedIds


def build_matching_state(
    inputs: ValidatedReconciliationInputs,
    indexes: ReconciliationIndexes,
) -> MatchingState:
    """Build the Slice 6 matching state: trusted-ID and exact-path facts only.

    Pure function: does not mutate ``inputs`` or ``indexes``, or any mapping
    or tuple contained in either. Performs no filesystem, SQLite, network, or
    Resolve access, and no hash, weak-candidate, or final-classification work.
    Raises nothing for validated input.
    """
    blocked_observation_codes, blocked_record_codes = _build_duplicate_path_blocks(indexes)

    trusted_candidates, trusted_blocks = _match_trusted_ids(inputs, indexes, blocked_observation_codes, blocked_record_codes)
    blocked_observation_codes = {**blocked_observation_codes, **trusted_blocks}

    path_candidates = _match_exact_paths(indexes, blocked_observation_codes, blocked_record_codes)

    associations, conflicts = _combine_authoritative_candidates(trusted_candidates, path_candidates)
    associations, extra_conflicts = _detect_cross_observation_conflicts(associations)
    conflicts = conflicts + extra_conflicts

    blocked_observations = tuple(
        sorted(
            (
                BlockedObservation(observation_id=obs_id, blocking_code=code, evidence_facts=_sorted_facts(code))
                for obs_id, code in blocked_observation_codes.items()
            ),
            key=lambda blocked: blocked.observation_id,
        )
    )
    blocked_records = tuple(
        sorted(
            (
                BlockedRecord(asset_id=asset_id, blocking_code=code, evidence_facts=_sorted_facts(code))
                for asset_id, code in blocked_record_codes.items()
            ),
            key=lambda blocked: blocked.asset_id,
        )
    )
    definitive_associations = tuple(sorted(associations, key=lambda a: (a.observation_id, a.asset_id)))
    conflict_groups = tuple(sorted(conflicts, key=lambda c: c.subject.canonical_key()))

    consumed = ConsumedIds(
        asset_ids=frozenset(a.asset_id for a in definitive_associations),
        observation_ids=frozenset(a.observation_id for a in definitive_associations),
    )

    return MatchingState(
        definitive_associations=definitive_associations,
        blocked_observations=blocked_observations,
        blocked_records=blocked_records,
        conflict_groups=conflict_groups,
        consumed=consumed,
    )


def _sorted_facts(*facts: str) -> tuple[str, ...]:
    """Return a sorted, deduplicated tuple of bounded evidence-fact codes."""
    return tuple(sorted(set(facts)))


def _build_duplicate_path_blocks(
    indexes: ReconciliationIndexes,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (blocked observation codes, blocked record codes) from Slice 5's collision groups.

    Reuses ``indexes.observations.path_collision_groups`` and
    ``indexes.registry.path_collision_groups`` directly -- path collisions
    are not recomputed here.
    """
    blocked_observation_codes: dict[str, str] = {}
    blocked_record_codes: dict[str, str] = {}

    for group in indexes.observations.path_collision_groups:
        for observation_id in group.observation_ids:
            blocked_observation_codes[observation_id] = _DUPLICATE_OBSERVATION_PATH
    for group in indexes.registry.path_collision_groups:
        for asset_id in group.asset_ids:
            blocked_record_codes[asset_id] = _REGISTRY_PATH_COLLISION

    return blocked_observation_codes, blocked_record_codes


def _match_trusted_ids(
    inputs: ValidatedReconciliationInputs,
    indexes: ReconciliationIndexes,
    blocked_observation_codes: dict[str, str],
    blocked_record_codes: dict[str, str],
) -> tuple[_ObservationToAssetId, dict[str, str]]:
    """Return (observation_id -> trusted candidate asset_id, observation_id -> new block code).

    Runs only when ``asset_id_trust_policy`` is ``ALLOW_LISTED_SOURCES``.
    Under ``REJECT_ALL``, no trusted candidates and no unknown-ID blocks are
    produced -- claimed Asset IDs are simply not used for matching.
    """
    candidates: _ObservationToAssetId = {}
    new_blocks: dict[str, str] = {}

    if inputs.request.asset_id_trust_policy is not AssetIdTrustPolicy.ALLOW_LISTED_SOURCES:
        return candidates, new_blocks

    for claimed_asset_id, observation_ids in indexes.observations.trusted_claimed_asset_id_to_observation_ids.items():
        if len(observation_ids) > 1:
            for observation_id in observation_ids:
                if observation_id in blocked_observation_codes:
                    continue
                new_blocks[observation_id] = _TRUSTED_ID_CLAIMED_BY_MULTIPLE_OBSERVATIONS
            continue

        observation_id = observation_ids[0]
        if observation_id in blocked_observation_codes:
            continue

        if claimed_asset_id not in indexes.registry.asset_id_to_record:
            new_blocks[observation_id] = _UNKNOWN_TRUSTED_ASSET_ID
            continue

        if claimed_asset_id in blocked_record_codes:
            new_blocks[observation_id] = blocked_record_codes[claimed_asset_id]
            continue

        candidates[observation_id] = claimed_asset_id

    return candidates, new_blocks


def _match_exact_paths(
    indexes: ReconciliationIndexes,
    blocked_observation_codes: dict[str, str],
    blocked_record_codes: dict[str, str],
) -> _ObservationToAssetId:
    """Return observation_id -> exact-path candidate asset_id.

    Runs regardless of trust policy. A candidate exists only when the same
    normalized path key resolves to exactly one Asset ID and exactly one
    observation ID on both sides, and neither is already blocked.
    """
    candidates: _ObservationToAssetId = {}

    registry_paths = indexes.registry.path_key_to_asset_ids
    observation_paths = indexes.observations.path_key_to_observation_ids

    for path_key, asset_ids in registry_paths.items():
        if len(asset_ids) != 1:
            continue
        observation_ids = observation_paths.get(path_key)
        if not observation_ids or len(observation_ids) != 1:
            continue

        asset_id = asset_ids[0]
        observation_id = observation_ids[0]
        if observation_id in blocked_observation_codes or asset_id in blocked_record_codes:
            continue

        candidates[observation_id] = asset_id

    return candidates


def _combine_authoritative_candidates(
    trusted_candidates: _ObservationToAssetId,
    path_candidates: _ObservationToAssetId,
) -> tuple[list[DefinitiveAssociation], list[ConflictGroup]]:
    """Combine per-observation trusted and path candidates into associations/conflicts."""
    associations: list[DefinitiveAssociation] = []
    conflicts: list[ConflictGroup] = []

    observation_ids = set(trusted_candidates) | set(path_candidates)
    for observation_id in observation_ids:
        trusted = trusted_candidates.get(observation_id)
        path = path_candidates.get(observation_id)

        if trusted is not None and path is not None:
            if trusted == path:
                associations.append(
                    DefinitiveAssociation(
                        asset_id=trusted,
                        observation_id=observation_id,
                        association_kind=_TRUSTED_AND_PATH_KIND,
                        evidence_facts=_sorted_facts(_FACT_TRUSTED_EXACT_PATH_AGREEMENT),
                    )
                )
            else:
                conflicts.append(
                    _authoritative_conflict(
                        (trusted, path), (observation_id,), _FACT_TRUSTED_EXACT_PATH_CONFLICT
                    )
                )
            continue

        if trusted is not None:
            associations.append(
                DefinitiveAssociation(
                    asset_id=trusted,
                    observation_id=observation_id,
                    association_kind=_TRUSTED_ASSET_ID_KIND,
                    evidence_facts=_sorted_facts(_FACT_TRUSTED_ASSET_ID),
                )
            )
            continue

        associations.append(
            DefinitiveAssociation(
                asset_id=path,
                observation_id=observation_id,
                association_kind=_EXACT_PATH_KIND,
                evidence_facts=_sorted_facts(_FACT_EXACT_PATH),
            )
        )

    return associations, conflicts


def _detect_cross_observation_conflicts(
    associations: list[DefinitiveAssociation],
) -> tuple[list[DefinitiveAssociation], list[ConflictGroup]]:
    """Detect two different observations independently claiming the same Asset ID.

    Pure trusted-vs-trusted or path-vs-path duplication for one Asset ID is
    already impossible by construction (trusted claims are pre-deduplicated in
    ``_match_trusted_ids``, and a record has exactly one normalized path, so
    it can be the unique-match target of at most one path key). The only
    residual case is one trusted-only and one path-only association naming
    the same Asset ID from two different observations.
    """
    by_asset_id: dict[str, list[DefinitiveAssociation]] = {}
    for association in associations:
        by_asset_id.setdefault(association.asset_id, []).append(association)

    kept: list[DefinitiveAssociation] = []
    conflicts: list[ConflictGroup] = []
    for asset_id, group in by_asset_id.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        observation_ids = tuple(sorted(a.observation_id for a in group))
        conflicts.append(_authoritative_conflict((asset_id,), observation_ids, _FACT_CROSS_OBSERVATION_CONFLICT))

    return kept, conflicts


def _authoritative_conflict(
    asset_ids: tuple[str, ...],
    observation_ids: tuple[str, ...],
    fact: str,
) -> ConflictGroup:
    """Return one AUTHORITATIVE_IDENTITY conflict group for the given IDs."""
    unique_asset_ids = tuple(sorted(set(asset_ids)))
    unique_observation_ids = tuple(sorted(set(observation_ids)))
    subject = MixedConflictSubject(
        asset_ids=unique_asset_ids,
        observation_ids=unique_observation_ids,
        conflict_kind=ConflictKind.AUTHORITATIVE_IDENTITY,
    )
    return ConflictGroup(
        subject=subject,
        conflict_kind=ConflictKind.AUTHORITATIVE_IDENTITY,
        asset_ids=unique_asset_ids,
        observation_ids=unique_observation_ids,
        evidence_facts=_sorted_facts(fact),
        proposal_blocked=True,
    )
