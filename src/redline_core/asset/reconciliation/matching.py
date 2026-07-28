"""Trusted ID, exact-path, and strong-identity matching for Asset Registry
reconciliation.

Implements Phase 3 Slice 6 ("Trusted ID and exact-path matching") and Slice 7
("Strong identity matching"): the trusted-claimed-Asset-ID,
exact-normalized-path, and unique full-content/partial-fingerprint/
filesystem-identity portions of the matching pipeline described in the
approved architecture and implementation plan. Precedence is strict:
trusted Asset ID > exact normalized path > unique strong identity.

Explicitly out of scope (deferred to Slice 8 and later): weak matching,
unmatched-subject production, final classification, findings, action
generation, plan assembly, and public serialization. This module is expected
to be extended, not rewritten, once that work begins.

``findings.py`` and the originally-planned richer ``evidence.py`` types
(``PlanEvidence``, ``EvidenceCandidate``, ...) do not exist in this
repository. Blocking reasons and conflict facts are represented the same way
``scope.py`` and ``indexes.py`` already do: plain bounded static string codes
and the existing ``ConflictKind``/``subjects.py`` types -- not finding
objects. A blocking code is a neutral fact, not a final
``PrimaryClassification`` -- mapping one onto the other is classification.py's
job (Slice 8), not this module's.

This module performs no filesystem, SQLite, network, or Resolve access, no
weak-candidate matching, no final classification, and no mutation of its
inputs.

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
- ``unique_strong_identity`` -- a strong-identity-only definitive association
  (Slice 7): exactly one registry record and one observation share a strong
  identity fact, and neither side is already blocked, already
  Slice-6-conflicted, or claimed by a different strong-identity candidate.
- ``registry_identity_collision`` -- two or more registry records share one
  reduced cross-reference identity key that also matches exactly one
  observation (Slice 7).
- ``observation_identity_collision`` -- two or more observations share one
  identity key that also matches exactly one registry record (Slice 7).
- ``mixed_identity_collision`` -- two or more registry records and two or
  more observations share one reduced cross-reference identity key
  (Slice 7).
- ``strong_identity_conflicting_candidates`` -- a registry record or
  observation is proposed as a clean strong-identity candidate by more than
  one reduced identity key, with different partners on each side (Slice 7).
- ``strong_identity_authoritative_conflict`` -- a strong-identity candidate
  disagrees with an existing trusted-Asset-ID-based definitive association
  (Slice 7).
- ``strong_identity_content_conflict`` -- a strong-identity candidate
  disagrees with an existing exact-path-only definitive association
  (Slice 7).

No evidence fact ever embeds a raw normalized path, source ID, claimed Asset
ID, digest, fingerprint, filesystem identity, or any other user-controlled
value.

Slice 7 bridge (registry/observation identity-key shape mismatch):
``indexes.registry.identity_key_to_asset_ids`` is keyed by the 5-tuple
``RegistryEvidenceLookupKey`` (``evidence_kind``, ``algorithm_sort_key``,
``normalized_value``, ``normalization_format``, ``scope_id_sort_key``), while
``indexes.observations.identity_key_to_observation_ids`` is keyed by the
3-tuple ``ObservationIdentityKey`` (``evidence_kind``, ``algorithm_sort_key``,
``normalized_value``) -- ``AssetObservation`` carries no
``normalization_format`` or per-fact ``scope_id`` to fill the other two
components. A 3-tuple and a 5-tuple never compare equal, so these two indexes
cannot be joined directly. This module bridges the gap privately (see
``_reduce_registry_key``/``_group_registry_by_reduced_key`` below) by
projecting every registry key down to the observation-side 3-tuple shape
purely for cross-referencing. ``indexes.py`` is not modified and its full
5-tuple index remains authoritative for registry-internal indexing and
collision detection; the reduction exists only inside this module, only for
Slice 7 cross-side comparison.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from redline_core.asset.reconciliation.canonical import OptionalTextSortKey, RegistryEvidenceLookupKey
from redline_core.asset.reconciliation.enums import AssetIdTrustPolicy, ConflictKind
from redline_core.asset.reconciliation.exceptions import ReconciliationInvariantError
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

_UNIQUE_STRONG_IDENTITY_KIND = "unique_strong_identity"

_FACT_UNIQUE_STRONG_IDENTITY = "unique_strong_identity"
_FACT_REGISTRY_IDENTITY_COLLISION = "registry_identity_collision"
_FACT_OBSERVATION_IDENTITY_COLLISION = "observation_identity_collision"
_FACT_MIXED_IDENTITY_COLLISION = "mixed_identity_collision"
_FACT_STRONG_IDENTITY_CONFLICTING_CANDIDATES = "strong_identity_conflicting_candidates"
_FACT_STRONG_IDENTITY_AUTHORITATIVE_CONFLICT = "strong_identity_authoritative_conflict"
_FACT_STRONG_IDENTITY_CONTENT_CONFLICT = "strong_identity_content_conflict"

_TRUSTED_BASED_KINDS = frozenset({_TRUSTED_ASSET_ID_KIND, _TRUSTED_AND_PATH_KIND})
"""Existing association kinds that count as trusted-Asset-ID-based for Slice 7 conflict-kind selection."""

_ObservationToAssetId = dict[str, str]
"""Internal candidate map: observation_id -> candidate asset_id."""

_CrossReferenceKey = tuple[str, OptionalTextSortKey, str]
"""Reduced (evidence_kind, algorithm_sort_key, normalized_value) key used only for
Slice 7 registry-vs-observation cross-referencing. Same shape as ``ObservationIdentityKey``
(``indexes.py``); see module docstring "Slice 7 bridge" section.
"""


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
    """Build the Slice 6/7 matching state: trusted-ID, exact-path, and strong-identity facts.

    Runs strong-identity matching (Slice 7) strictly after trusted-ID and
    exact-path matching (Slice 6) have produced their associations,
    conflicts, and blocks for this call -- precedence is trusted Asset ID >
    exact normalized path > unique strong identity. Pure function: does not
    mutate ``inputs`` or ``indexes``, or any mapping or tuple contained in
    either. Performs no filesystem, SQLite, network, or Resolve access, no
    weak-candidate matching, and no final-classification work. Raises
    nothing for validated input; raises ``ReconciliationInvariantError`` only
    if a required ownership invariant cannot be constructed.
    """
    blocked_observation_codes, blocked_record_codes = _build_duplicate_path_blocks(indexes)

    trusted_candidates, trusted_blocks = _match_trusted_ids(inputs, indexes, blocked_observation_codes, blocked_record_codes)
    blocked_observation_codes = {**blocked_observation_codes, **trusted_blocks}

    path_candidates = _match_exact_paths(indexes, blocked_observation_codes, blocked_record_codes)

    associations, conflicts = _combine_authoritative_candidates(trusted_candidates, path_candidates)
    associations, extra_conflicts = _detect_cross_observation_conflicts(associations)
    conflicts = conflicts + extra_conflicts

    strong_associations, strong_conflicts = _match_strong_identity(
        indexes,
        tuple(associations),
        blocked_observation_codes,
        blocked_record_codes,
        tuple(conflicts),
    )
    associations = associations + list(strong_associations)
    conflicts = conflicts + list(strong_conflicts)

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
    definitive_associations = tuple(
        sorted(associations, key=lambda a: (a.observation_id, a.asset_id, a.association_kind))
    )
    conflict_groups = tuple(sorted(conflicts, key=lambda c: c.subject.canonical_key()))

    _verify_slice7_ownership_invariants(definitive_associations, strong_associations, strong_conflicts)

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


# ---------------------------------------------------------------------------
# Slice 7: strong identity matching
# ---------------------------------------------------------------------------


def _reduce_registry_key(key: RegistryEvidenceLookupKey) -> _CrossReferenceKey:
    """Project one registry 5-tuple identity key onto the observation-side 3-tuple shape.

    This reduction exists only for Slice 7 cross-side (registry-vs-observation)
    strong-identity comparison; it is never used for registry-internal
    indexing or collision detection. It intentionally drops
    ``normalization_format`` and ``scope_id_sort_key`` -- ``AssetObservation``
    (Slice 1) carries neither field, so no directly comparable 5-tuple can
    ever be constructed from caller-supplied observation data. The original
    5-tuple key returned by ``indexes.registry.identity_key_to_asset_ids``
    (Slice 5) is never replaced or mutated by this function.

    Semantic consequence, intentional and disclosed: two registry evidence
    rows sharing (evidence_kind, algorithm_sort_key, normalized_value) but
    differing only by ``normalization_format`` or ``scope_id`` collapse into
    one reduced group for cross-side comparison. If that reduced group's
    Asset IDs span more than one distinct record, Slice 7 treats it as an
    ambiguous ``REGISTRY_IDENTITY_COLLISION`` rather than arbitrarily picking
    one -- see ``_group_registry_by_reduced_key`` and ``_match_strong_identity``.
    """
    evidence_kind, algorithm_sort_key, normalized_value, _normalization_format, _scope_id_sort_key = key
    return (evidence_kind, algorithm_sort_key, normalized_value)


def _group_registry_by_reduced_key(
    identity_key_to_asset_ids: Mapping[RegistryEvidenceLookupKey, tuple[str, ...]],
) -> dict[_CrossReferenceKey, tuple[str, ...]]:
    """Build the reduced registry identity grouping once per matching call.

    Combines Asset ID memberships from every full 5-tuple registry key that
    reduces to the same 3-tuple comparison key, deduplicates, and sorts.
    Built exactly once per ``build_matching_state`` call (O(R) over registry
    identity memberships) and reused for every reduced-key lookup in
    ``_match_strong_identity`` -- never rebuilt per observation or per key.
    """
    grouped: dict[_CrossReferenceKey, set[str]] = {}
    for key, asset_ids in identity_key_to_asset_ids.items():
        reduced_key = _reduce_registry_key(key)
        grouped.setdefault(reduced_key, set()).update(asset_ids)
    return {key: tuple(sorted(members)) for key, members in grouped.items()}


def _conflict_kind_for_existing_association(existing_kinds: tuple[str, ...]) -> ConflictKind:
    """Return the conflict kind for a strong-identity disagreement with existing association(s).

    Trusted-Asset-ID-based associations (``trusted_asset_id`` or
    ``trusted_asset_id_and_exact_path``) outrank exact-path-only associations
    per the "Matching Conflict Matrix": a disagreement touching any
    trusted-ID-based association is ``AUTHORITATIVE_IDENTITY``; a
    disagreement touching only exact-path-only associations is ``CONTENT``.
    """
    if any(kind in _TRUSTED_BASED_KINDS for kind in existing_kinds):
        return ConflictKind.AUTHORITATIVE_IDENTITY
    return ConflictKind.CONTENT


def _collision_conflict(
    asset_ids: tuple[str, ...],
    observation_ids: tuple[str, ...],
    conflict_kind: ConflictKind,
    fact: str,
) -> ConflictGroup:
    """Return one bounded strong-identity collision conflict group.

    Never selects a member arbitrarily and never expands into a pairwise or
    Cartesian-product set of conflicts -- exactly one ``ConflictGroup`` per
    collision. Consistent with the existing Slice 6 convention, this conflict
    never consumes any Asset ID or observation ID: ``ConsumedIds`` is rebuilt
    exclusively from surviving ``DefinitiveAssociation`` rows (see
    ``build_matching_state``), so an ID's appearance here has no bearing on
    its consumption state.
    """
    unique_asset_ids = tuple(sorted(set(asset_ids)))
    unique_observation_ids = tuple(sorted(set(observation_ids)))
    subject = MixedConflictSubject(
        asset_ids=unique_asset_ids,
        observation_ids=unique_observation_ids,
        conflict_kind=conflict_kind,
    )
    return ConflictGroup(
        subject=subject,
        conflict_kind=conflict_kind,
        asset_ids=unique_asset_ids,
        observation_ids=unique_observation_ids,
        evidence_facts=_sorted_facts(fact),
        proposal_blocked=True,
    )


def _group_connected_components(
    pairs: frozenset[tuple[str, str]],
) -> tuple[tuple[frozenset[str], frozenset[str]], ...]:
    """Return the connected components of the bipartite (asset_id, observation_id) candidate graph.

    Two candidate pairs belong to the same component when they share an
    Asset ID or an observation ID (directly or transitively). A component of
    shape (1 asset, 1 observation) is an unambiguous strong-identity
    candidate; any larger component means the same Asset ID or observation ID
    was proposed by more than one reduced identity key with different
    partners, and must be resolved as a conflict rather than an arbitrary
    pick. Deterministic: iterates and returns components in sorted order,
    independent of set/dict iteration order.
    """
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for asset_id, observation_id in pairs:
        asset_node = ("asset", asset_id)
        observation_node = ("observation", observation_id)
        adjacency.setdefault(asset_node, set()).add(observation_node)
        adjacency.setdefault(observation_node, set()).add(asset_node)

    visited: set[tuple[str, str]] = set()
    components: list[tuple[frozenset[str], frozenset[str]]] = []
    for start_node in sorted(adjacency):
        if start_node in visited:
            continue
        visited.add(start_node)
        stack = [start_node]
        component_assets: set[str] = set()
        component_observations: set[str] = set()
        while stack:
            node_kind, node_value = stack.pop()
            if node_kind == "asset":
                component_assets.add(node_value)
            else:
                component_observations.add(node_value)
            for neighbor in adjacency[(node_kind, node_value)]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        components.append((frozenset(component_assets), frozenset(component_observations)))

    return tuple(
        sorted(components, key=lambda component: (tuple(sorted(component[0])), tuple(sorted(component[1]))))
    )


def _reconcile_strong_identity_candidate(
    asset_id: str,
    observation_id: str,
    association_by_asset_id: Mapping[str, DefinitiveAssociation],
    association_by_observation_id: Mapping[str, DefinitiveAssociation],
) -> tuple[DefinitiveAssociation | None, ConflictGroup | None]:
    """Reconcile one unambiguous strong-identity candidate against existing Slice 6 associations.

    Strong identity never overwrites an existing trusted-Asset-ID or
    exact-path association (precedence: trusted Asset ID > exact normalized
    path > unique strong identity). Returns the new association to add (if
    the pair is genuinely new and unconsumed), or a conflict describing the
    disagreement (if either side is already owned by a different existing
    association), or ``(None, None)`` if the candidate already matches an
    existing association exactly (already associated to each other -- no
    duplicate association is created, and the earlier association is left
    unchanged rather than replaced).
    """
    existing_by_asset = association_by_asset_id.get(asset_id)
    existing_by_observation = association_by_observation_id.get(observation_id)

    if existing_by_asset is None and existing_by_observation is None:
        return (
            DefinitiveAssociation(
                asset_id=asset_id,
                observation_id=observation_id,
                association_kind=_UNIQUE_STRONG_IDENTITY_KIND,
                evidence_facts=_sorted_facts(_FACT_UNIQUE_STRONG_IDENTITY),
            ),
            None,
        )

    if (
        existing_by_asset is not None
        and existing_by_observation is not None
        and existing_by_asset is existing_by_observation
    ):
        # Already associated to each other by Slice 6 -- preserve the earlier
        # authoritative association unchanged rather than replacing it.
        return None, None

    existing_kinds: list[str] = []
    involved_asset_ids = {asset_id}
    involved_observation_ids = {observation_id}
    if existing_by_asset is not None:
        existing_kinds.append(existing_by_asset.association_kind)
        involved_asset_ids.add(existing_by_asset.asset_id)
        involved_observation_ids.add(existing_by_asset.observation_id)
    if existing_by_observation is not None:
        existing_kinds.append(existing_by_observation.association_kind)
        involved_asset_ids.add(existing_by_observation.asset_id)
        involved_observation_ids.add(existing_by_observation.observation_id)

    conflict_kind = _conflict_kind_for_existing_association(tuple(existing_kinds))
    fact = (
        _FACT_STRONG_IDENTITY_AUTHORITATIVE_CONFLICT
        if conflict_kind is ConflictKind.AUTHORITATIVE_IDENTITY
        else _FACT_STRONG_IDENTITY_CONTENT_CONFLICT
    )
    unique_asset_ids = tuple(sorted(involved_asset_ids))
    unique_observation_ids = tuple(sorted(involved_observation_ids))
    subject = MixedConflictSubject(
        asset_ids=unique_asset_ids,
        observation_ids=unique_observation_ids,
        conflict_kind=conflict_kind,
    )
    conflict = ConflictGroup(
        subject=subject,
        conflict_kind=conflict_kind,
        asset_ids=unique_asset_ids,
        observation_ids=unique_observation_ids,
        evidence_facts=_sorted_facts(fact),
        proposal_blocked=True,
    )
    return None, conflict


def _match_strong_identity(
    indexes: ReconciliationIndexes,
    existing_associations: tuple[DefinitiveAssociation, ...],
    blocked_observation_codes: Mapping[str, str],
    blocked_record_codes: Mapping[str, str],
    existing_conflicts: tuple[ConflictGroup, ...],
) -> tuple[tuple[DefinitiveAssociation, ...], tuple[ConflictGroup, ...]]:
    """Build Slice 7 strong-identity associations and conflicts.

    Runs after trusted-ID and exact-path matching (Slice 6) have already
    produced ``existing_associations``/``existing_conflicts`` for this call.
    Never removes or rewrites an existing association -- only appends new
    strong-identity associations for previously untouched, unambiguous pairs,
    and new conflict groups for collisions or disagreements this stage
    discovers. A Slice-7-created conflict never shares an Asset ID or
    observation ID with a Slice-7-created association (enforced by
    construction and re-checked in ``_verify_slice7_ownership_invariants``);
    a Slice-7-created conflict *may* reference an ID already owned by an
    existing Slice 6 association -- that is the disagreement scenario this
    function is required to flag, per "emit the appropriate conflict rather
    than replacing the earlier result."

    Complexity: O(R + O + K log K) -- the reduced registry grouping is built
    once (O(R)); every registry and observation identity membership is
    visited once; the K distinct reduced keys are sorted once for
    deterministic traversal; no nested registry-by-observation scan and no
    Cartesian-product conflict expansion is ever performed.
    """
    reduced_registry_groups = _group_registry_by_reduced_key(indexes.registry.identity_key_to_asset_ids)
    observation_groups = indexes.observations.identity_key_to_observation_ids

    blocked_asset_ids = frozenset(blocked_record_codes)
    blocked_observation_ids = frozenset(blocked_observation_codes)
    conflicted_asset_ids = frozenset(asset_id for conflict in existing_conflicts for asset_id in conflict.asset_ids)
    conflicted_observation_ids = frozenset(
        observation_id for conflict in existing_conflicts for observation_id in conflict.observation_ids
    )

    association_by_asset_id = {association.asset_id: association for association in existing_associations}
    association_by_observation_id = {association.observation_id: association for association in existing_associations}

    all_keys = sorted(set(reduced_registry_groups) | set(observation_groups))

    new_conflicts: list[ConflictGroup] = []
    slice7_conflicted_asset_ids: set[str] = set()
    slice7_conflicted_observation_ids: set[str] = set()
    candidate_pairs: set[tuple[str, str]] = set()

    for key in all_keys:
        eligible_asset_ids = tuple(
            sorted(
                asset_id
                for asset_id in reduced_registry_groups.get(key, ())
                if asset_id not in blocked_asset_ids and asset_id not in conflicted_asset_ids
            )
        )
        eligible_observation_ids = tuple(
            sorted(
                observation_id
                for observation_id in observation_groups.get(key, ())
                if observation_id not in blocked_observation_ids and observation_id not in conflicted_observation_ids
            )
        )

        if not eligible_asset_ids or not eligible_observation_ids:
            # Evidence on only one side (or nothing eligible survives filtering):
            # no association, no cross-side collision for this key.
            continue

        if len(eligible_asset_ids) == 1 and len(eligible_observation_ids) == 1:
            candidate_pairs.add((eligible_asset_ids[0], eligible_observation_ids[0]))
            continue

        if len(eligible_asset_ids) > 1 and len(eligible_observation_ids) == 1:
            conflict = _collision_conflict(
                eligible_asset_ids,
                eligible_observation_ids,
                ConflictKind.REGISTRY_IDENTITY_COLLISION,
                _FACT_REGISTRY_IDENTITY_COLLISION,
            )
        elif len(eligible_asset_ids) == 1 and len(eligible_observation_ids) > 1:
            conflict = _collision_conflict(
                eligible_asset_ids,
                eligible_observation_ids,
                ConflictKind.OBSERVATION_IDENTITY_COLLISION,
                _FACT_OBSERVATION_IDENTITY_COLLISION,
            )
        else:
            conflict = _collision_conflict(
                eligible_asset_ids,
                eligible_observation_ids,
                ConflictKind.MIXED_IDENTITY_COLLISION,
                _FACT_MIXED_IDENTITY_COLLISION,
            )
        new_conflicts.append(conflict)
        slice7_conflicted_asset_ids.update(eligible_asset_ids)
        slice7_conflicted_observation_ids.update(eligible_observation_ids)

    # Resolve ambiguity across different reduced keys: an Asset ID or
    # observation ID proposed as a clean 1-1 candidate by more than one key,
    # with different partners, is not a valid unambiguous match.
    for component_assets, component_observations in _group_connected_components(frozenset(candidate_pairs)):
        if len(component_assets) == 1 and len(component_observations) == 1:
            continue
        asset_ids = tuple(sorted(component_assets))
        observation_ids = tuple(sorted(component_observations))
        new_conflicts.append(
            _collision_conflict(
                asset_ids,
                observation_ids,
                ConflictKind.MIXED_IDENTITY_COLLISION,
                _FACT_STRONG_IDENTITY_CONFLICTING_CANDIDATES,
            )
        )
        slice7_conflicted_asset_ids.update(asset_ids)
        slice7_conflicted_observation_ids.update(observation_ids)

    clean_pairs = sorted(
        (asset_id, observation_id)
        for asset_id, observation_id in candidate_pairs
        if asset_id not in slice7_conflicted_asset_ids and observation_id not in slice7_conflicted_observation_ids
    )

    new_associations: list[DefinitiveAssociation] = []
    for asset_id, observation_id in clean_pairs:
        association, conflict = _reconcile_strong_identity_candidate(
            asset_id, observation_id, association_by_asset_id, association_by_observation_id
        )
        if association is not None:
            new_associations.append(association)
        if conflict is not None:
            new_conflicts.append(conflict)

    return tuple(new_associations), tuple(new_conflicts)


def _verify_slice7_ownership_invariants(
    definitive_associations: tuple[DefinitiveAssociation, ...],
    strong_associations: tuple[DefinitiveAssociation, ...],
    strong_conflicts: tuple[ConflictGroup, ...],
) -> None:
    """Defensively verify the required Slice 7 ownership invariants.

    Checks that: no Asset ID or observation ID repeats across the final
    merged ``definitive_associations``, and no Slice-7-created association
    shares an Asset ID or observation ID with a Slice-7-created conflict
    group. Raises ``ReconciliationInvariantError`` if either check fails;
    by construction in ``_match_strong_identity`` this should never
    trigger, but the check is required by contract rather than assumed.
    """
    asset_ids = [association.asset_id for association in definitive_associations]
    observation_ids = [association.observation_id for association in definitive_associations]
    if len(asset_ids) != len(set(asset_ids)) or len(observation_ids) != len(set(observation_ids)):
        raise ReconciliationInvariantError(
            "duplicate ownership in definitive associations",
            reason_code="duplicate_definitive_association_ownership",
        )

    strong_conflict_asset_ids = {asset_id for conflict in strong_conflicts for asset_id in conflict.asset_ids}
    strong_conflict_observation_ids = {
        observation_id for conflict in strong_conflicts for observation_id in conflict.observation_ids
    }
    for association in strong_associations:
        if association.asset_id in strong_conflict_asset_ids or association.observation_id in strong_conflict_observation_ids:
            raise ReconciliationInvariantError(
                "strong-identity association overlaps a strong-identity conflict",
                context={"asset_id": association.asset_id, "observation_id": association.observation_id},
                reason_code="strong_identity_ownership_overlap",
            )
