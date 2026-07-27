"""Tests for reconciliation enum stability and package exports."""
from __future__ import annotations

import redline_core.asset.reconciliation as reconciliation
from redline_core.asset.models import AssetAvailability, AssetLifecycle, AssetVerificationState
from redline_core.asset.reconciliation.enums import (
    ActionKind,
    AssetIdTrustPolicy,
    ComparisonResult,
    ConflictKind,
    EvidenceAuthority,
    EvidenceKind,
    EvidenceSourceKind,
    FindingSeverity,
    FINDING_SEVERITY_RANK,
    InvalidityTier,
    ObservationAccessibility,
    ObservationKind,
    PrimaryClassification,
    PublicVisibility,
    ScopeCompleteness,
    UniquenessResult,
)


def test_reconciliation_enums_use_stable_serialized_values():
    assert AssetIdTrustPolicy.REJECT_ALL.value == "reject_all"
    assert AssetIdTrustPolicy.ALLOW_LISTED_SOURCES.value == "allow_listed_sources"
    assert ScopeCompleteness.COMPLETE.value == "complete"
    assert ObservationKind.FILESYSTEM_SCAN.value == "filesystem_scan"
    assert ObservationAccessibility.INACCESSIBLE.value == "inaccessible"
    assert PrimaryClassification.AUTHORITATIVE_IDENTITY_CONFLICT.value == "authoritative_identity_conflict"
    assert FindingSeverity.ERROR.value == "error"
    assert ActionKind.UPDATE_RESOLVED_PATH.value == "update_resolved_path"
    assert EvidenceKind.FULL_CONTENT_HASH.value == "full_content_hash"
    assert EvidenceAuthority.STRONG.value == "strong"
    assert EvidenceSourceKind.REGISTRY_IDENTITY_EVIDENCE.value == "registry_identity_evidence"
    assert ComparisonResult.MALFORMED.value == "malformed"
    assert UniquenessResult.NON_UNIQUE_BOTH.value == "non_unique_both"
    assert PublicVisibility.INTERNAL_ONLY.value == "internal_only"
    assert InvalidityTier.OPTIONAL_EVIDENCE_FIELD.value == "optional_evidence_field"
    assert ConflictKind.MIXED_IDENTITY_COLLISION.value == "mixed_identity_collision"


def test_rank_maps_are_explicit_and_do_not_depend_on_declaration_order():
    assert FINDING_SEVERITY_RANK[FindingSeverity.ERROR] < FINDING_SEVERITY_RANK[FindingSeverity.WARNING]
    assert FINDING_SEVERITY_RANK[FindingSeverity.WARNING] < FINDING_SEVERITY_RANK[FindingSeverity.INFO]


def test_phase_one_enums_are_not_redefined_by_reconciliation_package():
    assert not hasattr(reconciliation, "AssetLifecycle")
    assert not hasattr(reconciliation, "AssetAvailability")
    assert not hasattr(reconciliation, "AssetVerificationState")
    assert AssetLifecycle.ACTIVE.value == "active"
    assert AssetAvailability.AVAILABLE.value == "available"
    assert AssetVerificationState.VERIFIED.value == "verified"


def test_package_exports_minimal_foundation_api():
    assert reconciliation.ReconciliationRequest.__name__ == "ReconciliationRequest"
    assert reconciliation.RegistrySnapshot.__name__ == "RegistrySnapshot"
    assert reconciliation.RegistryRecordSubject.__name__ == "RegistryRecordSubject"
    assert reconciliation.DEFAULT_LIMITS.max_observations_per_request == 10000
    assert "ReconciliationPlanner" not in reconciliation.__all__
    assert "serialize_public_plan" not in reconciliation.__all__
