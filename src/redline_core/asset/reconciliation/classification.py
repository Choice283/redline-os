"""classification.py -- Phase 3 Slice 8: central ordered classification rules.

Implements the approved "Slice 8 Implementation Contract -- Revision 3".
Consumes ``ValidatedReconciliationInputs``, ``ReconciliationIndexes`` (Slice
5), and ``MatchingState`` (Slice 6/7) for one already-validated,
already-indexed, already-matched reconciliation call, plus a caller-supplied
``observability_by_asset_id`` mapping (Revision 3's explicit input contract,
replacing an open-ended scope-resolution placeholder), and produces one
``ClassificationDecision`` per reachable subject.

This module performs no filesystem, SQLite, network, or Resolve access, no
additional validation (Tier 1/2/3 are out of scope -- Decision 6), and no
plan/evidence/action assembly (``findings.py``/``actions.py`` do not exist
yet in this repository; they belong to a later "Action generation"
milestone). Facts are represented the same way ``matching.py`` already
represents them: plain bounded string codes in ``evidence_facts``, not
``Finding`` objects.

Precedence is a strict, ordered 15-rank table (contract section 2); a
subject is classified by exactly one rank, first match wins. Four
``PrimaryClassification`` enum members have no predicate in this module
today and are intentionally never produced: ``REGISTRY_SNAPSHOT_INVALID``
(a pre-classification exception), ``INVALID_OBSERVATION`` (Tier 2,
unimplemented), ``UNSUPPORTED_OBSERVATION`` (no current ``ObservationKind``
triggers it), and ``DIAGNOSTIC_ONLY`` (no distinct predicate exists yet --
it is not a catch-all; falling through every rank is an internal invariant
violation, not a silent default).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetVerificationState,
)
from redline_core.asset.reconciliation.canonical import _normalize_algorithm
from redline_core.asset.reconciliation.enums import (
    ConflictKind,
    EvidenceKind,
    PrimaryClassification,
)
from redline_core.asset.reconciliation.exceptions import ReconciliationInvariantError
from redline_core.asset.reconciliation.indexes import ReconciliationIndexes
from redline_core.asset.reconciliation.matching import DefinitiveAssociation, MatchingState
from redline_core.asset.reconciliation.models import AssetObservation, RegistryIdentityEvidence
from redline_core.asset.reconciliation.scope import ObservabilityDecision
from redline_core.asset.reconciliation.subjects import (
    ObservationGroupSubject,
    ObservationSubject,
    PlanSubject,
    RegistryRecordSubject,
)
from redline_core.asset.reconciliation.validation import ValidatedReconciliationInputs


# ---------------------------------------------------------------------------
# Public data shapes (contract section 1.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    """One immutable classification outcome for one plan subject."""

    subject: PlanSubject
    primary_classification: PrimaryClassification
    evidence_facts: tuple[str, ...] = ()
    requires_review: bool = False
    proposal_blocked: bool = False


@dataclass(frozen=True, slots=True)
class ClassificationState:
    """Immutable Slice 8 output: one decision per reachable subject."""

    decisions: tuple[ClassificationDecision, ...]


# ---------------------------------------------------------------------------
# Bounded evidence-fact vocabulary (matching.py convention)
# ---------------------------------------------------------------------------

_FACT_REGISTRY_IDENTITY_EVIDENCE_CONFLICT = "registry_identity_evidence_conflict"
_FACT_CONTENT_HASH_MISMATCH = "content_hash_mismatch"
_FACT_DUPLICATE_OBSERVATION_PATH = "duplicate_observation_path"
_FACT_REGISTRY_PATH_COLLISION = "registry_path_collision"
_FACT_TRUSTED_ID_CLAIMED_BY_MULTIPLE = "trusted_asset_id_claimed_by_multiple_observations"
_FACT_UNKNOWN_TRUSTED_ASSET_ID = "unknown_trusted_asset_id"
_FACT_PATH_MOVED = "path_moved"
_FACT_LIFECYCLE_REACTIVATION_BLOCKED = "lifecycle_deprecated_reactivation_blocked"
_FACT_AVAILABILITY_STATE_CHANGED = "availability_state_changed"
_FACT_AVAILABILITY_RECOVERED = "availability_recovered"
_FACT_RECORD_NOT_OBSERVED = "record_not_observed_complete_scope"
_FACT_NEW_UNREGISTERED_OBSERVATION = "new_unregistered_observation"
_FACT_UNCHANGED = "unchanged"
_FACT_MODIFIED_TIME_DIFFERS = "modified_time_differs"
_FACT_PATH_DIFFERS_NON_STRONG_IDENTITY = "path_differs_non_strong_identity"
_FACT_SIZE_DIFFERS_NO_COMPARABLE_HASH = "size_differs_no_comparable_hash"
_FACT_INSUFFICIENT_SCOPE = "insufficient_scope"

_UNIQUE_STRONG_IDENTITY_KIND = "unique_strong_identity"

# Contract section 3.2: matching-derived conflict_kind -> PrimaryClassification.
# OBSERVATION_IDENTITY_COLLISION and MIXED_IDENTITY_COLLISION both route to
# AMBIGUOUS_MATCH (rank 6) rather than a new enum member -- both describe
# "more than one observation could be the same registry record."
_CONFLICT_KIND_TO_CLASSIFICATION: Mapping[ConflictKind, PrimaryClassification] = {
    ConflictKind.REGISTRY_IDENTITY_COLLISION: PrimaryClassification.REGISTRY_IDENTITY_COLLISION,
    ConflictKind.OBSERVATION_IDENTITY_COLLISION: PrimaryClassification.AMBIGUOUS_MATCH,
    ConflictKind.MIXED_IDENTITY_COLLISION: PrimaryClassification.AMBIGUOUS_MATCH,
    ConflictKind.AUTHORITATIVE_IDENTITY: PrimaryClassification.AUTHORITATIVE_IDENTITY_CONFLICT,
    ConflictKind.CONTENT: PrimaryClassification.CONTENT_CONFLICT,
}

# Contract section 3.4: availability transition table (Decision 2).
_AVAILABILITY_NOT_CHANGED = frozenset(
    {
        (AssetAvailability.AVAILABLE, AssetAvailability.AVAILABLE),
    }
)
_AVAILABILITY_METADATA_DRIFT = frozenset(
    {
        (AssetAvailability.MISSING, AssetAvailability.AVAILABLE),
        (AssetAvailability.UNKNOWN, AssetAvailability.AVAILABLE),
    }
)

# Ranks requiring operator review by default, per the architecture's action
# table (Section "Lifecycle And Availability" / disposition table).
_REQUIRES_REVIEW_BY_DEFAULT = frozenset(
    {
        PrimaryClassification.REGISTRY_IDENTITY_EVIDENCE_CONFLICT,
        PrimaryClassification.REGISTRY_IDENTITY_COLLISION,
        PrimaryClassification.AUTHORITATIVE_IDENTITY_CONFLICT,
        PrimaryClassification.CONTENT_CONFLICT,
        PrimaryClassification.DUPLICATE_PATH_CONFLICT,
        PrimaryClassification.AMBIGUOUS_MATCH,
        PrimaryClassification.UNKNOWN_AUTHORITATIVE_ASSET_ID,
        PrimaryClassification.PATH_CHANGED,
        PrimaryClassification.LIFECYCLE_CONFLICT,
        PrimaryClassification.AVAILABILITY_CHANGED,
        PrimaryClassification.NEW_UNREGISTERED_OBSERVATION,
    }
)


def _sorted_facts(*facts: str) -> tuple[str, ...]:
    return tuple(sorted(set(facts)))


def _decision(
    subject: PlanSubject,
    classification: PrimaryClassification,
    *facts: str,
    requires_review: bool | None = None,
    proposal_blocked: bool = False,
) -> ClassificationDecision:
    review = classification in _REQUIRES_REVIEW_BY_DEFAULT if requires_review is None else requires_review
    return ClassificationDecision(
        subject=subject,
        primary_classification=classification,
        evidence_facts=_sorted_facts(*facts),
        requires_review=review,
        proposal_blocked=proposal_blocked,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def classify_reconciliation(
    inputs: ValidatedReconciliationInputs,
    indexes: ReconciliationIndexes,
    matching_state: MatchingState,
    observability_by_asset_id: Mapping[str, ObservabilityDecision],
) -> ClassificationState:
    """Classify one already-matched reconciliation call into ordered decisions.

    Pure function: does not mutate ``inputs``, ``indexes``, ``matching_state``,
    or ``observability_by_asset_id``. Raises nothing for validated,
    already-matched input with a complete ``observability_by_asset_id``
    mapping. Raises ``ReconciliationInvariantError`` in exactly three cases
    (contract section 1.1): a dangling association reference, a missing
    observability decision for an unconsumed record, or (defensively) no rule
    matching a subject.
    """
    decisions: list[ClassificationDecision] = []
    claimed_asset_ids: set[str] = set()
    claimed_observation_ids: set[str] = set()

    # Rank 1: registry identity evidence conflict -- independent of matching,
    # checked first (contract 3.1).
    for asset_id in sorted(indexes.registry.record_evidence_by_asset_id):
        if asset_id in claimed_asset_ids:
            continue
        evidence_rows = indexes.registry.record_evidence_by_asset_id[asset_id]
        if _has_registry_identity_evidence_conflict(evidence_rows):
            decisions.append(
                _decision(
                    RegistryRecordSubject(asset_id=asset_id),
                    PrimaryClassification.REGISTRY_IDENTITY_EVIDENCE_CONFLICT,
                    _FACT_REGISTRY_IDENTITY_EVIDENCE_CONFLICT,
                    proposal_blocked=True,
                )
            )
            claimed_asset_ids.add(asset_id)

    # Ranks 2, 3, 4a, 6b: matching-derived conflicts, pass-through (contract 3.2).
    for conflict in matching_state.conflict_groups:
        if conflict.asset_ids and set(conflict.asset_ids) & claimed_asset_ids:
            continue
        if conflict.observation_ids and set(conflict.observation_ids) & claimed_observation_ids:
            continue
        classification = _CONFLICT_KIND_TO_CLASSIFICATION.get(conflict.conflict_kind)
        if classification is None:
            # ConflictKind.DUPLICATE_PATH / SCOPE are not produced by matching.py
            # today; defensively skip rather than mis-map an unknown kind.
            continue
        decisions.append(
            _decision(
                conflict.subject,
                classification,
                *conflict.evidence_facts,
                proposal_blocked=conflict.proposal_blocked,
            )
        )
        claimed_asset_ids.update(conflict.asset_ids)
        claimed_observation_ids.update(conflict.observation_ids)

    # Rank 5: duplicate path conflict groups, pass-through from indexes.py.
    for group in indexes.observations.path_collision_groups:
        if set(group.observation_ids) & claimed_observation_ids:
            continue
        decisions.append(
            _decision(
                group,
                PrimaryClassification.DUPLICATE_PATH_CONFLICT,
                _FACT_DUPLICATE_OBSERVATION_PATH,
                proposal_blocked=True,
            )
        )
        claimed_observation_ids.update(group.observation_ids)
    for group in indexes.registry.path_collision_groups:
        if set(group.asset_ids) & claimed_asset_ids:
            continue
        decisions.append(
            _decision(
                group,
                PrimaryClassification.DUPLICATE_PATH_CONFLICT,
                _FACT_REGISTRY_PATH_COLLISION,
                proposal_blocked=True,
            )
        )
        claimed_asset_ids.update(group.asset_ids)

    # Rank 6a: trusted Asset ID claimed by multiple observations (Decision 1).
    for group in _group_trusted_id_ambiguity(indexes, matching_state):
        if set(group.observation_ids) & claimed_observation_ids:
            continue
        decisions.append(
            _decision(
                group,
                PrimaryClassification.AMBIGUOUS_MATCH,
                _FACT_TRUSTED_ID_CLAIMED_BY_MULTIPLE,
                proposal_blocked=True,
            )
        )
        claimed_observation_ids.update(group.observation_ids)

    # Rank 7: unknown trusted Asset ID.
    for blocked in matching_state.blocked_observations:
        if blocked.blocking_code != "unknown_trusted_asset_id":
            continue
        if blocked.observation_id in claimed_observation_ids:
            continue
        decisions.append(
            _decision(
                ObservationSubject(observation_id=blocked.observation_id),
                PrimaryClassification.UNKNOWN_AUTHORITATIVE_ASSET_ID,
                _FACT_UNKNOWN_TRUSTED_ASSET_ID,
                proposal_blocked=True,
            )
        )
        claimed_observation_ids.add(blocked.observation_id)

    # Ranks 8-10, 13-14: field comparison over definitively matched pairs.
    for association in matching_state.definitive_associations:
        if association.asset_id in claimed_asset_ids or association.observation_id in claimed_observation_ids:
            # A higher-rank, Slice-8-only conflict (rank 1) already claimed
            # this asset_id; account for the observation too so it is not
            # later mis-classified as NEW_UNREGISTERED_OBSERVATION.
            claimed_asset_ids.add(association.asset_id)
            claimed_observation_ids.add(association.observation_id)
            continue

        record, observation = _resolve_association(indexes, association)
        record_evidence = indexes.registry.record_evidence_by_asset_id.get(association.asset_id, ())
        decision = _classify_matched_pair(association, record, observation, record_evidence)
        decisions.append(decision)
        claimed_asset_ids.add(association.asset_id)
        claimed_observation_ids.add(association.observation_id)

    # Ranks 11, 15: unconsumed registry records.
    for asset_id in sorted(indexes.registry.asset_id_to_record):
        if asset_id in claimed_asset_ids:
            continue
        try:
            observability = observability_by_asset_id[asset_id]
        except KeyError as exc:
            raise ReconciliationInvariantError(
                "unconsumed record missing a resolved observability decision",
                context={"asset_id": asset_id},
                reason_code="classification_missing_observability_decision",
            ) from exc

        if observability.expected_observable:
            decisions.append(
                _decision(
                    RegistryRecordSubject(asset_id=asset_id),
                    PrimaryClassification.RECORD_NOT_OBSERVED,
                    _FACT_RECORD_NOT_OBSERVED,
                    requires_review=False,
                )
            )
        else:
            decisions.append(
                _decision(
                    RegistryRecordSubject(asset_id=asset_id),
                    PrimaryClassification.INSUFFICIENT_SCOPE,
                    _FACT_INSUFFICIENT_SCOPE,
                    requires_review=False,
                )
            )
        claimed_asset_ids.add(asset_id)

    # Rank 12: unconsumed observations.
    for observation_id in sorted(indexes.observations.observation_id_to_observation):
        if observation_id in claimed_observation_ids:
            continue
        decisions.append(
            _decision(
                ObservationSubject(observation_id=observation_id),
                PrimaryClassification.NEW_UNREGISTERED_OBSERVATION,
                _FACT_NEW_UNREGISTERED_OBSERVATION,
            )
        )
        claimed_observation_ids.add(observation_id)

    return ClassificationState(decisions=tuple(sorted(decisions, key=lambda d: d.subject.canonical_key())))


# ---------------------------------------------------------------------------
# Rank 1 predicate (contract 3.1)
# ---------------------------------------------------------------------------


def _has_registry_identity_evidence_conflict(
    evidence_rows: tuple[RegistryIdentityEvidence, ...],
) -> bool:
    """True if this asset_id's evidence rows disagree on a comparable identity fact."""
    values_by_key: dict[tuple[EvidenceKind, str | None], set[str]] = {}
    for evidence in evidence_rows:
        key = (evidence.evidence_kind, _normalize_algorithm(evidence.algorithm))
        values_by_key.setdefault(key, set()).add(evidence.normalized_value)
    return any(len(values) > 1 for values in values_by_key.values())


# ---------------------------------------------------------------------------
# Rank 6a grouping (contract Decision 1 / 3.2 note)
# ---------------------------------------------------------------------------


def _group_trusted_id_ambiguity(
    indexes: ReconciliationIndexes,
    matching_state: MatchingState,
) -> tuple[ObservationGroupSubject, ...]:
    """Reconstruct the per-claimed-Asset-ID group for Decision 1's AMBIGUOUS_MATCH.

    ``matching.BlockedObservation`` carries only ``observation_id`` and
    ``blocking_code`` -- no ``claimed_asset_id`` -- so the grouping is
    reconstructed here from each blocked observation's original
    ``claimed_asset_id`` via ``indexes.observations.observation_id_to_observation``,
    grouping observations that share one claimed Asset ID into one subject.
    """
    grouped: dict[str, list[str]] = {}
    for blocked in matching_state.blocked_observations:
        if blocked.blocking_code != "trusted_asset_id_claimed_by_multiple_observations":
            continue
        observation = indexes.observations.observation_id_to_observation[blocked.observation_id]
        grouped.setdefault(observation.claimed_asset_id, []).append(blocked.observation_id)

    return tuple(
        ObservationGroupSubject(observation_ids=tuple(sorted(observation_ids)))
        for _claimed_asset_id, observation_ids in sorted(grouped.items())
    )


# ---------------------------------------------------------------------------
# Ranks 8-10, 13-14: field comparison over one definitively matched pair
# ---------------------------------------------------------------------------


def _resolve_association(
    indexes: ReconciliationIndexes,
    association: DefinitiveAssociation,
) -> tuple[AssetRegistryRecord, AssetObservation]:
    try:
        record = indexes.registry.asset_id_to_record[association.asset_id]
        observation = indexes.observations.observation_id_to_observation[association.observation_id]
    except KeyError as exc:
        raise ReconciliationInvariantError(
            "definitive association references an object absent from indexes",
            context={"asset_id": association.asset_id, "observation_id": association.observation_id},
            reason_code="classification_dangling_association_reference",
        ) from exc
    return record, observation


@dataclass(frozen=True, slots=True)
class _MatchedPairContext:
    """Bundled arguments for one matched-pair rank rule (internal only)."""

    association: DefinitiveAssociation
    record: AssetRegistryRecord
    observation: AssetObservation
    record_evidence: tuple[RegistryIdentityEvidence, ...]
    subject: RegistryRecordSubject


def _rule_path_changed(ctx: _MatchedPairContext) -> ClassificationDecision | None:
    """Rank 8 (Decision 4 -- unique_strong_identity only)."""
    if _path_changed(ctx.association, ctx.record, ctx.observation):
        return _decision(ctx.subject, PrimaryClassification.PATH_CHANGED, _FACT_PATH_MOVED)
    return None


def _rule_lifecycle_conflict(ctx: _MatchedPairContext) -> ClassificationDecision | None:
    """Rank 9 -- no silent reactivation of a deprecated record."""
    if ctx.record.lifecycle is AssetLifecycle.DEPRECATED:
        return _decision(
            ctx.subject,
            PrimaryClassification.LIFECYCLE_CONFLICT,
            _FACT_LIFECYCLE_REACTIVATION_BLOCKED,
            proposal_blocked=True,
        )
    return None


def _rule_content_conflict(ctx: _MatchedPairContext) -> ClassificationDecision | None:
    """Rank 10, content half (contract 3.3)."""
    comparable = _comparable_verified_hash_pair(ctx.record_evidence, ctx.record, ctx.observation)
    if comparable is not None and comparable[0] != comparable[1]:
        return _decision(ctx.subject, PrimaryClassification.CONTENT_CONFLICT, _FACT_CONTENT_HASH_MISMATCH)
    return None


def _rule_availability(ctx: _MatchedPairContext) -> ClassificationDecision | None:
    """Rank 10, availability half (contract 3.4, Decision 2)."""
    classification = _availability_rule(ctx.record, ctx.observation)
    if classification is PrimaryClassification.AVAILABILITY_CHANGED:
        return _decision(ctx.subject, PrimaryClassification.AVAILABILITY_CHANGED, _FACT_AVAILABILITY_STATE_CHANGED)
    if classification is PrimaryClassification.METADATA_DRIFT:
        return _decision(ctx.subject, PrimaryClassification.METADATA_DRIFT, _FACT_AVAILABILITY_RECOVERED)
    return None


def _rule_remaining_fields(ctx: _MatchedPairContext) -> ClassificationDecision | None:
    """Ranks 13-14 -- always terminal (UNCHANGED or METADATA_DRIFT); never
    returns None in real usage. Kept as a normal rule (not a hardcoded
    fallback) so the dispatch loop in ``_classify_matched_pair`` is the only
    place that decides "no rule matched" (contract 1.1, case 3)."""
    return _classify_remaining_fields(ctx.association, ctx.subject, ctx.record, ctx.observation)


_MATCHED_PAIR_RULES: tuple[Callable[[_MatchedPairContext], ClassificationDecision | None], ...] = (
    _rule_path_changed,
    _rule_lifecycle_conflict,
    _rule_content_conflict,
    _rule_availability,
    _rule_remaining_fields,
)
"""Ordered ranks 8-10, 13-14 as an explicit rule chain (contract section 5's
"ordered if/elif chain per pair"). ``_classify_matched_pair`` iterates this
tuple and raises ``ReconciliationInvariantError`` if every rule returns
``None`` -- unreachable with ``_rule_remaining_fields`` present and correct,
but a real, testable code path (contract test 32) rather than an assumption."""


def _classify_matched_pair(
    association: DefinitiveAssociation,
    record: AssetRegistryRecord,
    observation: AssetObservation,
    record_evidence: tuple[RegistryIdentityEvidence, ...],
) -> ClassificationDecision:
    ctx = _MatchedPairContext(
        association=association,
        record=record,
        observation=observation,
        record_evidence=record_evidence,
        subject=RegistryRecordSubject(asset_id=association.asset_id),
    )
    for rule in _MATCHED_PAIR_RULES:
        decision = rule(ctx)
        if decision is not None:
            return decision
    raise ReconciliationInvariantError(
        "no classification rule matched this subject",
        context={"asset_id": association.asset_id},
        reason_code="classification_no_rule_matched",
    )


def _path_changed(
    association: DefinitiveAssociation,
    record: AssetRegistryRecord,
    observation: AssetObservation,
) -> bool:
    return (
        association.association_kind == _UNIQUE_STRONG_IDENTITY_KIND
        and record.normalized_resolved_path is not None
        and observation.normalized_resolved_path is not None
        and record.normalized_resolved_path != observation.normalized_resolved_path
    )


def _comparable_verified_hash_pair(
    record_evidence: tuple[RegistryIdentityEvidence, ...],
    record: AssetRegistryRecord,
    observation: AssetObservation,
) -> tuple[str, str] | None:
    """Return (registry_value, observation_value) for the first comparable
    verified full-content-hash pair, or None if no comparable pair exists.

    Absence of a hash on either side is never treated as a mismatch (per
    architecture: "missing hash does not imply verification failure").
    """
    if record.verification is not AssetVerificationState.VERIFIED:
        return None
    if observation.verification is not AssetVerificationState.VERIFIED:
        return None

    registry_hashes = {
        _normalize_algorithm(evidence.algorithm): evidence.normalized_value
        for evidence in record_evidence
        if evidence.evidence_kind is EvidenceKind.FULL_CONTENT_HASH
    }
    if not registry_hashes:
        return None

    for algorithm, digest in sorted(observation.content_hashes):
        normalized_algorithm = _normalize_algorithm(algorithm)
        if normalized_algorithm in registry_hashes:
            return (registry_hashes[normalized_algorithm], digest)
    return None


def _availability_rule(
    record: AssetRegistryRecord,
    observation: AssetObservation,
) -> PrimaryClassification | None:
    pair = (record.availability, observation.availability)
    if pair in _AVAILABILITY_NOT_CHANGED:
        return None
    if pair in _AVAILABILITY_METADATA_DRIFT:
        return PrimaryClassification.METADATA_DRIFT
    return PrimaryClassification.AVAILABILITY_CHANGED


def _classify_remaining_fields(
    association: DefinitiveAssociation,
    subject: RegistryRecordSubject,
    record: AssetRegistryRecord,
    observation: AssetObservation,
) -> ClassificationDecision:
    facts: list[str] = []
    requires_review = False

    path_differs = (
        association.association_kind != _UNIQUE_STRONG_IDENTITY_KIND
        and record.normalized_resolved_path is not None
        and observation.normalized_resolved_path is not None
        and record.normalized_resolved_path != observation.normalized_resolved_path
    )
    if path_differs:
        facts.append(_FACT_PATH_DIFFERS_NON_STRONG_IDENTITY)

    if record.file_modified_at != observation.file_modified_at:
        facts.append(_FACT_MODIFIED_TIME_DIFFERS)

    size_differs = record.file_size_bytes != observation.file_size_bytes
    if size_differs:
        facts.append(_FACT_SIZE_DIFFERS_NO_COMPARABLE_HASH)
        requires_review = True

    if not facts:
        return _decision(subject, PrimaryClassification.UNCHANGED, _FACT_UNCHANGED, requires_review=False)

    return _decision(subject, PrimaryClassification.METADATA_DRIFT, *facts, requires_review=requires_review)
