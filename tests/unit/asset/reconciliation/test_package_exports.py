"""Tests for the reconciliation package public export surface."""
from __future__ import annotations


def test_package_import_and_explicit_public_exports():
    import redline_core.asset.reconciliation as reconciliation

    expected_exports = [
        "ActionKind",
        "AmbiguousEquivalentRootError",
        "AssetIdTrustPolicy",
        "AssetObservation",
        "ComparisonResult",
        "ConflictKind",
        "DEFAULT_LIMITS",
        "DuplicateObservationIdError",
        "EvidenceAuthority",
        "EvidenceKind",
        "EvidenceSourceKind",
        "ExplicitAssetAccessFailure",
        "FindingSeverity",
        "InvalidReconciliationRequestError",
        "InvalidRegistrySnapshotError",
        "InvalidityTier",
        "MissingObservationIdError",
        "MixedConflictSubject",
        "ObservationAccessibility",
        "ObservationFilters",
        "ObservationGroupSubject",
        "ObservationKind",
        "ObservationRootScope",
        "ObservationScope",
        "ObservationSubject",
        "PlanSubject",
        "PlanSummary",
        "PrimaryClassification",
        "PublicVisibility",
        "ReconciliationError",
        "ReconciliationInvariantError",
        "ReconciliationLimitExceededError",
        "ReconciliationLimitPolicy",
        "ReconciliationPlan",
        "ReconciliationPlanItem",
        "ReconciliationRequest",
        "RegistryIdentityEvidence",
        "RegistryRecordGroupSubject",
        "RegistryRecordSubject",
        "RegistrySnapshot",
        "ScopeCompleteness",
        "UniquenessResult",
        "UnsupportedReconciliationVersionError",
    ]

    assert reconciliation.__all__ == expected_exports
    for public_name in expected_exports:
        assert hasattr(reconciliation, public_name)


def test_package_does_not_export_internal_helpers_or_later_slice_api():
    import redline_core.asset.reconciliation as reconciliation

    forbidden_exports = {
        "EVIDENCE_AUTHORITY_RANK",
        "FINDING_SEVERITY_RANK",
        "ReconciliationPlanner",
        "UNIQUENESS_RANK",
        "_deep_freeze",
        "_sanitize_context",
        "plan_reconciliation",
        "serialize_public_plan",
    }

    assert forbidden_exports.isdisjoint(reconciliation.__all__)
    for name in forbidden_exports:
        assert not hasattr(reconciliation, name)
