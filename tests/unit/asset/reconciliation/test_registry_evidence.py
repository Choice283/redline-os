"""Validation-facing tests for Slice 3 registry evidence behavior."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)
from redline_core.asset.reconciliation.enums import EvidenceKind
from redline_core.asset.reconciliation.exceptions import InvalidRegistrySnapshotError
from redline_core.asset.reconciliation.models import (
    ReconciliationRequest,
    RegistryIdentityEvidence,
    RegistrySnapshot,
)
from redline_core.asset.reconciliation.validation import validate_reconciliation_inputs


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def make_record(asset_id: str = "RLG-001", *, record_id: int = 1) -> AssetRegistryRecord:
    return AssetRegistryRecord(
        record_id=record_id,
        asset_id=asset_id,
        declared_path=f"assets/{asset_id}.mov",
        resolved_path=f"C:/assets/{asset_id}.mov",
        normalized_resolved_path=f"c:/assets/{asset_id}.mov",
        approved_root_id="assets_path",
        lifecycle=AssetLifecycle.DECLARED,
        availability=AssetAvailability.UNKNOWN,
        verification=AssetVerificationState.UNVERIFIED,
        file_size_bytes=None,
        file_modified_at=None,
        last_verified_at=None,
        created_at=NOW,
        updated_at=NOW,
        source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
        source_detail="config/assets.yaml",
        diagnostic_code=None,
        diagnostic_message=None,
    )


def make_request() -> ReconciliationRequest:
    return ReconciliationRequest(
        request_id="request-1",
        schema_version="1",
        created_at=NOW,
        observations=(),
        scopes=(),
    )


def make_snapshot(
    *,
    records: tuple[AssetRegistryRecord, ...] = (make_record(),),
    evidence: tuple[RegistryIdentityEvidence, ...],
) -> RegistrySnapshot:
    return RegistrySnapshot(
        records=records,
        identity_evidence=evidence,
        schema_version="1",
        snapshot_id="snapshot-1",
        snapshot_created_at=NOW,
        registry_id="registry-1",
        approved_root_context="root-context-1",
    )


def make_evidence(
    asset_id: str = "RLG-001",
    *,
    value: str = "abc",
    algorithm: str | None = "sha256",
    kind: EvidenceKind = EvidenceKind.FULL_CONTENT_HASH,
    normalization_format: str = "hex",
    scope_id: str | None = None,
    source_id: str = "scan-a",
    observed_at: datetime = NOW,
) -> RegistryIdentityEvidence:
    return RegistryIdentityEvidence(
        asset_id=asset_id,
        evidence_kind=kind,
        algorithm=algorithm,
        normalized_value=value,
        normalization_format=normalization_format,
        scope_id=scope_id,
        source_id=source_id,
        observed_at=observed_at,
    )


def test_validate_registry_evidence_exact_output_order_is_canonical():
    evidence = (
        make_evidence("RLG-002", value="b", source_id="scan-b"),
        make_evidence("RLG-001", value="b", algorithm="sha512"),
        make_evidence("RLG-001", value="a", algorithm="SHA256", scope_id="scope-a"),
        make_evidence("RLG-001", value="a", algorithm=None, kind=EvidenceKind.METADATA),
    )
    records = (make_record("RLG-001"), make_record("RLG-002", record_id=2))

    result = validate_reconciliation_inputs(make_request(), make_snapshot(records=records, evidence=tuple(reversed(evidence))))

    assert result.snapshot.identity_evidence == (
        evidence[2],
        evidence[1],
        evidence[3],
        evidence[0],
    )


def test_validate_registry_evidence_deduplicates_case_insensitive_algorithm_identity():
    lower = make_evidence(algorithm="sha256", observed_at=NOW.replace(hour=10))
    upper = make_evidence(algorithm="SHA256", observed_at=NOW.replace(hour=11))

    result = validate_reconciliation_inputs(make_request(), make_snapshot(evidence=(lower, upper)))

    assert result.snapshot.identity_evidence == (upper,)


def test_validate_registry_evidence_preserves_same_record_conflict_for_later_slice():
    first = make_evidence(value="hash-a")
    second = make_evidence(value="hash-b")

    result = validate_reconciliation_inputs(make_request(), make_snapshot(evidence=(second, first)))

    assert result.snapshot.identity_evidence == (first, second)


def test_validate_registry_evidence_unsupported_algorithm_is_deferred_not_fatal():
    unsupported = make_evidence(algorithm="sha512")

    result = validate_reconciliation_inputs(make_request(), make_snapshot(evidence=(unsupported,)))

    assert result.snapshot.identity_evidence == (unsupported,)


def test_validate_registry_evidence_orphan_is_fatal_snapshot_error_without_raw_digest():
    orphan = make_evidence("RLG-404", value="a" * 64)

    with pytest.raises(InvalidRegistrySnapshotError) as error_info:
        validate_reconciliation_inputs(make_request(), make_snapshot(evidence=(orphan,)))

    assert error_info.value.error_code == "registry_snapshot_invalid"
    assert error_info.value.context["reason_code"] == "orphaned_registry_evidence"
    for surface in (str(error_info.value), repr(error_info.value), repr(vars(error_info.value))):
        assert "a" * 64 not in surface
        assert "select" not in surface.lower()


def test_validate_registry_evidence_representative_tie_break_does_not_use_input_order():
    lower = make_evidence(value="same", normalization_format="format-a")
    upper = replace(lower, normalization_format="format-z")

    first = validate_reconciliation_inputs(make_request(), make_snapshot(evidence=(lower, upper)))
    second = validate_reconciliation_inputs(make_request(), make_snapshot(evidence=(upper, lower)))

    assert first.snapshot.identity_evidence == (upper,)
    assert second.snapshot.identity_evidence == (upper,)
