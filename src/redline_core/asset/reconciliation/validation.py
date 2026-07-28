"""Pure structural validation for Asset Registry reconciliation inputs.

The Slice 2 validator consumes immutable Slice 1 request and snapshot models,
checks only deterministic request/snapshot invariants, and returns immutable
validated inputs. It performs no repository, filesystem, matching,
classification, evidence-building, or plan assembly work.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from redline_core.asset.reconciliation.enums import EvidenceKind
from redline_core.asset.reconciliation.exceptions import (
    AmbiguousEquivalentRootError,
    DuplicateObservationIdError,
    InvalidReconciliationRequestError,
    InvalidRegistrySnapshotError,
    ReconciliationLimitExceededError,
    UnsupportedReconciliationVersionError,
)
from redline_core.asset.reconciliation.limits import ReconciliationLimitPolicy
from redline_core.asset.reconciliation.models import (
    RECONCILIATION_REQUEST_SCHEMA_VERSION,
    AssetObservation,
    ObservationScope,
    RegistryIdentityEvidence,
    RegistrySnapshot,
    ReconciliationRequest,
)


@dataclass(frozen=True, slots=True)
class ValidatedReconciliationInputs:
    """Immutable request/snapshot pair that has passed Slice 2 validation."""

    request: ReconciliationRequest
    snapshot: RegistrySnapshot

    def __post_init__(self) -> None:
        if type(self.request) is not ReconciliationRequest:
            raise ValueError("request must be a ReconciliationRequest instance.")
        if type(self.snapshot) is not RegistrySnapshot:
            raise ValueError("snapshot must be a RegistrySnapshot instance.")


def validate_reconciliation_inputs(
    request: ReconciliationRequest,
    snapshot: RegistrySnapshot,
) -> ValidatedReconciliationInputs:
    """Validate request and snapshot structure before later reconciliation work.

    Validation is deterministic and fail-fast by the approved fatal validation
    stages. Non-fatal ambiguity such as duplicate normalized media paths remains
    represented in the returned inputs for later matching/classification slices.
    """

    _require_exact_request_input(request)
    _require_exact_snapshot_input(snapshot)
    limits = _validate_request_header(request)
    _validate_snapshot_header(snapshot)
    _enforce_top_level_limits(request, snapshot, limits)
    _validate_observation_ids(request.observations, limits)
    _validate_request_relationships(request, limits)
    _validate_snapshot_records(snapshot, limits)
    deduplicated_evidence = _validate_registry_evidence(snapshot, limits)
    _validate_scopes(request.scopes, limits)
    _validate_observation_scope_references(request.observations, request.scopes)

    return ValidatedReconciliationInputs(
        request=request,
        snapshot=replace(snapshot, identity_evidence=deduplicated_evidence),
    )


def _require_exact_request_input(value: object) -> None:
    if type(value) is not ReconciliationRequest:
        raise InvalidReconciliationRequestError(
            "invalid input type",
            context={"field_name": "request"},
            reason_code="invalid_input_type",
        )


def _require_exact_snapshot_input(value: object) -> None:
    if type(value) is not RegistrySnapshot:
        raise InvalidRegistrySnapshotError(
            "invalid snapshot input type",
            context={"field_name": "snapshot"},
            reason_code="invalid_input_type",
        )


def _validate_request_header(request: ReconciliationRequest) -> ReconciliationLimitPolicy:
    if type(request.limit_policy) is not ReconciliationLimitPolicy:
        raise InvalidReconciliationRequestError(
            "invalid limit policy",
            context={"request_id": request.request_id, "field_name": "limit_policy"},
            reason_code="invalid_limit_policy",
        )
    _require_length(request.request_id, request.limit_policy.max_request_id_length, "request_id")
    _require_length(request.schema_version, request.limit_policy.max_identifier_length, "schema_version")
    if request.schema_version != RECONCILIATION_REQUEST_SCHEMA_VERSION:
        raise UnsupportedReconciliationVersionError(
            "unsupported request version",
            context={"request_id": request.request_id, "schema_version": request.schema_version},
        )
    return request.limit_policy


def _validate_snapshot_header(snapshot: RegistrySnapshot) -> None:
    if snapshot.schema_version != RECONCILIATION_REQUEST_SCHEMA_VERSION:
        raise InvalidRegistrySnapshotError(
            "unsupported snapshot version",
            context={"snapshot_id": snapshot.snapshot_id, "schema_version": snapshot.schema_version},
            reason_code="unsupported_snapshot_version",
        )


def _enforce_top_level_limits(
    request: ReconciliationRequest,
    snapshot: RegistrySnapshot,
    limits: ReconciliationLimitPolicy,
) -> None:
    _require_count_at_most(
        len(request.observations),
        limits.max_observations_per_request,
        "max_observations_per_request",
        request.request_id,
    )
    _require_count_at_most(
        len(snapshot.records),
        limits.max_registry_records_per_snapshot,
        "max_registry_records_per_snapshot",
        request.request_id,
    )
    _require_count_at_most(
        len(snapshot.identity_evidence),
        limits.max_registry_evidence_rows,
        "max_registry_evidence_rows",
        request.request_id,
    )


def _validate_observation_ids(
    observations: tuple[AssetObservation, ...],
    limits: ReconciliationLimitPolicy,
) -> None:
    seen: set[str] = set()
    for index, observation in enumerate(observations):
        _require_length(observation.observation_id, limits.max_observation_id_length, "observation_id")
        _require_length(observation.source_id, limits.max_source_id_length, "source_id")
        _require_length(observation.observation_scope_id, limits.max_scope_id_length, "observation_scope_id")
        _require_optional_length(
            observation.normalized_resolved_path,
            limits.max_normalized_path_length,
            "normalized_resolved_path",
        )
        _require_optional_length(observation.claimed_asset_id, limits.max_asset_id_length, "claimed_asset_id")
        if observation.observation_id in seen:
            raise DuplicateObservationIdError(
                "duplicate observation ID",
                context={"observation_id": observation.observation_id, "index": index},
            )
        seen.add(observation.observation_id)


def _validate_request_relationships(request: ReconciliationRequest, limits: ReconciliationLimitPolicy) -> None:
    seen_sources: set[str] = set()
    for source_id in request.trusted_asset_id_source_ids:
        _require_length(source_id, limits.max_source_id_length, "source_id")
        if source_id in seen_sources:
            raise InvalidReconciliationRequestError(
                "duplicate trusted source",
                context={"request_id": request.request_id, "source_id": source_id},
                reason_code="duplicate_trusted_source",
            )
        seen_sources.add(source_id)


def _validate_snapshot_records(snapshot: RegistrySnapshot, limits: ReconciliationLimitPolicy) -> None:
    asset_ids: set[str] = set()
    for record in snapshot.records:
        _require_snapshot_length(record.asset_id, limits.max_asset_id_length, "asset_id", snapshot.snapshot_id)
        _require_optional_snapshot_length(
            record.normalized_resolved_path,
            limits.max_normalized_path_length,
            "normalized_path",
            snapshot.snapshot_id,
        )
        if record.asset_id in asset_ids:
            raise InvalidRegistrySnapshotError(
                "duplicate registry asset ID",
                context={"snapshot_id": snapshot.snapshot_id, "asset_id": record.asset_id},
                reason_code="duplicate_registry_asset_id",
            )
        asset_ids.add(record.asset_id)


def _validate_registry_evidence(
    snapshot: RegistrySnapshot,
    limits: ReconciliationLimitPolicy,
) -> tuple[RegistryIdentityEvidence, ...]:
    record_asset_ids = {record.asset_id for record in snapshot.records}
    by_key: dict[tuple[str, str, str | None, str, str | None, str], RegistryIdentityEvidence] = {}

    for index, evidence in enumerate(snapshot.identity_evidence):
        _require_snapshot_length(evidence.asset_id, limits.max_asset_id_length, "asset_id", snapshot.snapshot_id)
        _require_snapshot_length(evidence.source_id, limits.max_source_id_length, "source_id", snapshot.snapshot_id)
        _require_optional_snapshot_length(evidence.scope_id, limits.max_scope_id_length, "scope_id", snapshot.snapshot_id)
        _require_optional_snapshot_length(
            evidence.algorithm,
            limits.max_algorithm_identifier_length,
            "algorithm",
            snapshot.snapshot_id,
        )
        _require_snapshot_length(
            evidence.normalized_value,
            limits.max_digest_length,
            "normalized_value",
            snapshot.snapshot_id,
        )
        if evidence.evidence_kind is EvidenceKind.FULL_CONTENT_HASH and evidence.algorithm is None:
            raise InvalidRegistrySnapshotError(
                "hash evidence requires algorithm",
                context={"snapshot_id": snapshot.snapshot_id, "index": index},
                reason_code="invalid_registry_evidence",
            )
        if evidence.asset_id not in record_asset_ids:
            raise InvalidRegistrySnapshotError(
                "orphaned registry evidence",
                context={"snapshot_id": snapshot.snapshot_id, "asset_id": evidence.asset_id, "index": index},
                reason_code="orphaned_registry_evidence",
            )
        key = evidence.canonical_identity_key()
        current = by_key.get(key)
        if current is None or evidence.observed_at > current.observed_at:
            by_key[key] = evidence

    return tuple(by_key[key] for key in sorted(by_key, key=_evidence_identity_sort_key))


def _evidence_identity_sort_key(
    key: tuple[str, str, str | None, str, str | None, str],
) -> tuple[str, str, tuple[int, str], str, tuple[int, str], str]:
    asset_id, evidence_kind, algorithm, normalized_value, scope_id, source_id = key
    return (
        asset_id,
        evidence_kind,
        _optional_text_sort_key(algorithm),
        normalized_value,
        _optional_text_sort_key(scope_id),
        source_id,
    )


def _optional_text_sort_key(value: str | None) -> tuple[int, str]:
    if value is None:
        return (0, "")
    return (1, value)


def _validate_scopes(scopes: tuple[ObservationScope, ...], limits: ReconciliationLimitPolicy) -> None:
    scope_ids: set[str] = set()
    for scope in scopes:
        _require_length(scope.scope_id, limits.max_scope_id_length, "scope_id")
        _require_length(scope.source_id, limits.max_source_id_length, "source_id")
        if scope.scope_id in scope_ids:
            raise InvalidReconciliationRequestError(
                "duplicate scope ID",
                context={"scope_id": scope.scope_id},
                reason_code="duplicate_scope_id",
            )
        scope_ids.add(scope.scope_id)
        _require_count_at_most(len(scope.roots), limits.max_roots_per_scope, "max_roots_per_scope", None)
        _require_count_at_most(
            len(scope.explicit_asset_ids),
            limits.max_explicit_asset_ids,
            "max_explicit_asset_ids",
            None,
        )
        if not scope.roots and not scope.explicit_asset_ids:
            raise InvalidReconciliationRequestError(
                "scope lacks roots and explicit IDs",
                context={"scope_id": scope.scope_id},
                reason_code="empty_scope",
            )
        _validate_scope_roots(scope, limits)
        _validate_scope_failures(scope)
        _validate_scope_filters(scope, limits)


def _validate_scope_roots(scope: ObservationScope, limits: ReconciliationLimitPolicy) -> None:
    root_facts: dict[tuple[str, ...], tuple[object, ...]] = {}
    for root in scope.roots:
        _require_length(root.normalized_root_key, limits.max_normalized_path_length, "normalized_root_key")
        _require_count_at_most(
            len(root.inaccessible_subtrees),
            limits.max_inaccessible_subtrees_per_root,
            "max_inaccessible_subtrees_per_root",
            None,
        )
        _require_count_at_most(
            len(root.access_failures),
            limits.max_access_failures_per_root,
            "max_access_failures_per_root",
            None,
        )
        key = root.canonical_key()
        facts = (root.completeness, root.inaccessible_subtrees, root.access_failures)
        if key in root_facts:
            raise AmbiguousEquivalentRootError(
                "duplicate or ambiguous root",
                context={"scope_id": scope.scope_id},
            )
        root_facts[key] = facts


def _validate_scope_failures(scope: ObservationScope) -> None:
    failure_keys: set[tuple[str, str]] = set()
    for failure in scope.explicit_asset_id_failures:
        key = failure.canonical_key()
        if key in failure_keys:
            raise InvalidReconciliationRequestError(
                "duplicate explicit failure",
                context={"scope_id": scope.scope_id, "asset_id": failure.asset_id},
                reason_code="duplicate_explicit_failure",
            )
        failure_keys.add(key)


def _validate_scope_filters(scope: ObservationScope, limits: ReconciliationLimitPolicy) -> None:
    inclusion = scope.inclusion_filters
    exclusion = scope.exclusion_filters
    for values in (
        inclusion.included_media_types,
        inclusion.included_extensions,
        inclusion.included_lifecycle_states,
        inclusion.included_asset_ids,
    ):
        _require_count_at_most(len(values), limits.max_inclusion_filter_values, "max_inclusion_filter_values", None)
    _require_count_at_most(
        len(inclusion.excluded_normalized_subtrees),
        limits.max_exclusion_filter_values,
        "max_exclusion_filter_values",
        None,
    )
    for values in (
        exclusion.included_media_types,
        exclusion.included_extensions,
        exclusion.included_lifecycle_states,
        exclusion.included_asset_ids,
        exclusion.excluded_normalized_subtrees,
    ):
        _require_count_at_most(len(values), limits.max_exclusion_filter_values, "max_exclusion_filter_values", None)


def _validate_observation_scope_references(
    observations: tuple[AssetObservation, ...],
    scopes: tuple[ObservationScope, ...],
) -> None:
    scope_ids = {scope.scope_id for scope in scopes}
    for observation in observations:
        if observation.observation_scope_id not in scope_ids:
            raise InvalidReconciliationRequestError(
                "unknown observation scope",
                context={"observation_id": observation.observation_id, "scope_id": observation.observation_scope_id},
                reason_code="unknown_observation_scope",
            )


def _require_length(value: str, limit: int, field_name: str) -> None:
    if len(value) > limit:
        raise InvalidReconciliationRequestError(
            "identifier limit exceeded",
            context={"field_name": field_name, "limit_name": field_name, "limit_value": limit, "count": len(value)},
            reason_code="field_limit_exceeded",
        )


def _require_optional_length(value: str | None, limit: int, field_name: str) -> None:
    if value is not None:
        _require_length(value, limit, field_name)


def _require_snapshot_length(value: str, limit: int, field_name: str, snapshot_id: str) -> None:
    if len(value) > limit:
        raise InvalidRegistrySnapshotError(
            "snapshot field limit exceeded",
            context={"snapshot_id": snapshot_id, "field_name": field_name, "limit_value": limit, "count": len(value)},
            reason_code="field_limit_exceeded",
        )


def _require_optional_snapshot_length(value: str | None, limit: int, field_name: str, snapshot_id: str) -> None:
    if value is not None:
        _require_snapshot_length(value, limit, field_name, snapshot_id)


def _require_count_at_most(count: int, limit: int, limit_name: str, request_id: str | None) -> None:
    if count > limit:
        context = {"limit_name": limit_name, "limit_value": limit, "count": count}
        if request_id is not None:
            context["request_id"] = request_id
        raise ReconciliationLimitExceededError("limit exceeded", context=context)
