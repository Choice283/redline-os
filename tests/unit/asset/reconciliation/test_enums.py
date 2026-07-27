"""Tests for reconciliation enum stability."""
from __future__ import annotations

from redline_core.asset.models import AssetAvailability, AssetLifecycle, AssetVerificationState
from redline_core.asset.reconciliation.enums import (
    ActionKind,
    AssetIdTrustPolicy,
    ComparisonResult,
    ConflictKind,
    EvidenceAuthority,
    EVIDENCE_AUTHORITY_RANK,
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
    UNIQUENESS_RANK,
    UniquenessResult,
)


EXPECTED_ENUM_VALUES = {
    AssetIdTrustPolicy: {
        "REJECT_ALL": "reject_all",
        "ALLOW_LISTED_SOURCES": "allow_listed_sources",
    },
    ScopeCompleteness: {
        "COMPLETE": "complete",
        "INCOMPLETE": "incomplete",
        "UNKNOWN": "unknown",
    },
    ObservationKind: {
        "FILESYSTEM_SCAN": "filesystem_scan",
        "INGEST": "ingest",
        "ARCHIVE": "archive",
        "MANUAL": "manual",
        "MCP": "mcp",
        "RESOLVE": "resolve",
        "TEST_FIXTURE": "test_fixture",
    },
    ObservationAccessibility: {
        "ACCESSIBLE": "accessible",
        "MISSING": "missing",
        "NON_FILE": "non_file",
        "INACCESSIBLE": "inaccessible",
        "UNSUPPORTED": "unsupported",
    },
    PrimaryClassification: {
        "INVALID_OBSERVATION": "invalid_observation",
        "REGISTRY_SNAPSHOT_INVALID": "registry_snapshot_invalid",
        "REGISTRY_IDENTITY_EVIDENCE_CONFLICT": "registry_identity_evidence_conflict",
        "REGISTRY_IDENTITY_COLLISION": "registry_identity_collision",
        "AUTHORITATIVE_IDENTITY_CONFLICT": "authoritative_identity_conflict",
        "CONTENT_CONFLICT": "content_conflict",
        "DUPLICATE_PATH_CONFLICT": "duplicate_path_conflict",
        "AMBIGUOUS_MATCH": "ambiguous_match",
        "UNKNOWN_AUTHORITATIVE_ASSET_ID": "unknown_authoritative_asset_id",
        "PATH_CHANGED": "path_changed",
        "METADATA_DRIFT": "metadata_drift",
        "LIFECYCLE_CONFLICT": "lifecycle_conflict",
        "AVAILABILITY_CHANGED": "availability_changed",
        "RECORD_NOT_OBSERVED": "record_not_observed",
        "NEW_UNREGISTERED_OBSERVATION": "new_unregistered_observation",
        "UNCHANGED": "unchanged",
        "INSUFFICIENT_SCOPE": "insufficient_scope",
        "UNSUPPORTED_OBSERVATION": "unsupported_observation",
        "DIAGNOSTIC_ONLY": "diagnostic_only",
    },
    FindingSeverity: {
        "INFO": "info",
        "WARNING": "warning",
        "ERROR": "error",
    },
    ActionKind: {
        "NO_ACTION": "no_action",
        "REGISTER_CANDIDATE": "register_candidate",
        "UPDATE_RESOLVED_PATH": "update_resolved_path",
        "UPDATE_AVAILABILITY": "update_availability",
        "RESTORE_AVAILABILITY": "restore_availability",
        "MARK_MISSING": "mark_missing",
        "UPDATE_VERIFICATION_STATE": "update_verification_state",
        "UPDATE_OBSERVED_METADATA": "update_observed_metadata",
        "REQUIRE_REVIEW": "require_review",
        "FLAG_CONFLICT": "flag_conflict",
        "DIAGNOSTIC_ONLY": "diagnostic_only",
    },
    EvidenceKind: {
        "TRUSTED_ASSET_ID": "trusted_asset_id",
        "NORMALIZED_PATH": "normalized_path",
        "FULL_CONTENT_HASH": "full_content_hash",
        "FILESYSTEM_IDENTITY": "filesystem_identity",
        "PARTIAL_FINGERPRINT": "partial_fingerprint",
        "FILE_SIZE": "file_size",
        "MODIFIED_TIME": "modified_time",
        "METADATA": "metadata",
        "SCOPE": "scope",
        "DIAGNOSTIC": "diagnostic",
        "LIFECYCLE": "lifecycle",
        "AVAILABILITY": "availability",
    },
    EvidenceAuthority: {
        "AUTHORITATIVE": "authoritative",
        "STRONG": "strong",
        "WEAK": "weak",
        "DIAGNOSTIC": "diagnostic",
    },
    EvidenceSourceKind: {
        "REGISTRY_RECORD": "registry_record",
        "REGISTRY_IDENTITY_EVIDENCE": "registry_identity_evidence",
        "OBSERVATION": "observation",
        "REQUEST": "request",
        "SCOPE": "scope",
        "DERIVED": "derived",
    },
    ComparisonResult: {
        "MATCH": "match",
        "MISMATCH": "mismatch",
        "UNAVAILABLE": "unavailable",
        "UNSUPPORTED": "unsupported",
        "MALFORMED": "malformed",
    },
    UniquenessResult: {
        "UNIQUE": "unique",
        "NON_UNIQUE_REGISTRY": "non_unique_registry",
        "NON_UNIQUE_OBSERVATION": "non_unique_observation",
        "NON_UNIQUE_BOTH": "non_unique_both",
        "NOT_APPLICABLE": "not_applicable",
    },
    PublicVisibility: {
        "PUBLIC_VALUE": "public_value",
        "SAFE_SUMMARY": "safe_summary",
        "REDACT_VALUE": "redact_value",
        "INTERNAL_ONLY": "internal_only",
    },
    InvalidityTier: {
        "REQUEST": "request",
        "SNAPSHOT": "snapshot",
        "OBSERVATION": "observation",
        "OPTIONAL_EVIDENCE_FIELD": "optional_evidence_field",
    },
    ConflictKind: {
        "AUTHORITATIVE_IDENTITY": "authoritative_identity",
        "CONTENT": "content",
        "DUPLICATE_PATH": "duplicate_path",
        "REGISTRY_IDENTITY_EVIDENCE": "registry_identity_evidence",
        "REGISTRY_IDENTITY_COLLISION": "registry_identity_collision",
        "OBSERVATION_IDENTITY_COLLISION": "observation_identity_collision",
        "MIXED_IDENTITY_COLLISION": "mixed_identity_collision",
        "LIFECYCLE": "lifecycle",
        "SCOPE": "scope",
    },
}


def test_reconciliation_enums_use_exact_member_sets_and_values():
    assert len(EXPECTED_ENUM_VALUES) == 15
    for enum_type, expected in EXPECTED_ENUM_VALUES.items():
        assert enum_type.__members__ == {name: enum_type(value) for name, value in expected.items()}
        assert {member.name: member.value for member in enum_type} == expected
        assert len({member.value for member in enum_type}) == len(expected)


def test_rank_maps_are_explicit_and_do_not_depend_on_declaration_order():
    assert set(FINDING_SEVERITY_RANK) == set(FindingSeverity)
    assert set(EVIDENCE_AUTHORITY_RANK) == set(EvidenceAuthority)
    assert set(UNIQUENESS_RANK) == set(UniquenessResult)
    assert FINDING_SEVERITY_RANK[FindingSeverity.ERROR] < FINDING_SEVERITY_RANK[FindingSeverity.WARNING]
    assert FINDING_SEVERITY_RANK[FindingSeverity.WARNING] < FINDING_SEVERITY_RANK[FindingSeverity.INFO]
    assert EVIDENCE_AUTHORITY_RANK[EvidenceAuthority.AUTHORITATIVE] < EVIDENCE_AUTHORITY_RANK[EvidenceAuthority.STRONG]
    assert EVIDENCE_AUTHORITY_RANK[EvidenceAuthority.STRONG] < EVIDENCE_AUTHORITY_RANK[EvidenceAuthority.WEAK]
    assert EVIDENCE_AUTHORITY_RANK[EvidenceAuthority.WEAK] < EVIDENCE_AUTHORITY_RANK[EvidenceAuthority.DIAGNOSTIC]
    assert UNIQUENESS_RANK[UniquenessResult.NON_UNIQUE_BOTH] < UNIQUENESS_RANK[UniquenessResult.UNIQUE]
    assert UNIQUENESS_RANK[UniquenessResult.UNIQUE] < UNIQUENESS_RANK[UniquenessResult.NOT_APPLICABLE]
    assert len(set(FINDING_SEVERITY_RANK.values())) == len(FINDING_SEVERITY_RANK)
    assert len(set(EVIDENCE_AUTHORITY_RANK.values())) == len(EVIDENCE_AUTHORITY_RANK)
    assert len(set(UNIQUENESS_RANK.values())) == len(UNIQUENESS_RANK)


def test_phase_one_enums_are_not_redefined_by_reconciliation_package():
    import redline_core.asset.reconciliation as reconciliation

    assert not hasattr(reconciliation, "AssetLifecycle")
    assert not hasattr(reconciliation, "AssetAvailability")
    assert not hasattr(reconciliation, "AssetVerificationState")
    assert AssetLifecycle.ACTIVE.value == "active"
    assert AssetAvailability.AVAILABLE.value == "available"
    assert AssetVerificationState.VERIFIED.value == "verified"
