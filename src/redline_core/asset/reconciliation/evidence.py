"""Registry evidence validation and canonical deduplication helpers."""
from __future__ import annotations

from redline_core.asset.reconciliation.canonical import (
    RegistryEvidenceIdentityKey,
    _registry_evidence_identity_key,
    _registry_evidence_output_sort_key,
    _registry_evidence_representative_selection_key,
)
from redline_core.asset.reconciliation.enums import EvidenceKind
from redline_core.asset.reconciliation.exceptions import InvalidRegistrySnapshotError
from redline_core.asset.reconciliation.limits import ReconciliationLimitPolicy
from redline_core.asset.reconciliation.models import RegistryIdentityEvidence, RegistrySnapshot


SUPPORTED_REGISTRY_EVIDENCE_ALGORITHMS = ("sha256",)
"""Algorithms eligible for future definitive matching; unsupported values remain non-fatal."""


def validate_registry_identity_evidence(
    snapshot: RegistrySnapshot,
    limits: ReconciliationLimitPolicy,
) -> tuple[RegistryIdentityEvidence, ...]:
    """Validate and deterministically deduplicate detached registry evidence."""

    record_asset_ids = {record.asset_id for record in snapshot.records}
    by_key: dict[RegistryEvidenceIdentityKey, RegistryIdentityEvidence] = {}

    for index, evidence in enumerate(snapshot.identity_evidence):
        _validate_registry_identity_evidence_row(evidence, index, snapshot, limits, record_asset_ids)
        key = _registry_evidence_identity_key(evidence)
        current = by_key.get(key)
        if current is None or _registry_evidence_representative_selection_key(
            evidence
        ) > _registry_evidence_representative_selection_key(current):
            by_key[key] = evidence

    return tuple(sorted(by_key.values(), key=_registry_evidence_output_sort_key))


def is_supported_registry_evidence_algorithm(algorithm: str | None) -> bool:
    """Return whether an algorithm may be used by later definitive matching."""

    return algorithm is not None and algorithm.lower() in SUPPORTED_REGISTRY_EVIDENCE_ALGORITHMS


def _validate_registry_identity_evidence_row(
    evidence: RegistryIdentityEvidence,
    index: int,
    snapshot: RegistrySnapshot,
    limits: ReconciliationLimitPolicy,
    record_asset_ids: set[str],
) -> None:
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
