"""Stable enum values for Asset Registry reconciliation planning."""
from __future__ import annotations

from enum import Enum


class AssetIdTrustPolicy(str, Enum):
    """Request-level policy for caller-supplied Asset IDs."""

    REJECT_ALL = "reject_all"
    ALLOW_LISTED_SOURCES = "allow_listed_sources"


class ScopeCompleteness(str, Enum):
    """Completeness state for a declared observation scope."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class ObservationKind(str, Enum):
    """Kind of source that produced an asset observation."""

    FILESYSTEM_SCAN = "filesystem_scan"
    INGEST = "ingest"
    ARCHIVE = "archive"
    MANUAL = "manual"
    MCP = "mcp"
    RESOLVE = "resolve"
    TEST_FIXTURE = "test_fixture"


class ObservationAccessibility(str, Enum):
    """Accessibility state reported by an observation source."""

    ACCESSIBLE = "accessible"
    MISSING = "missing"
    NON_FILE = "non_file"
    INACCESSIBLE = "inaccessible"
    UNSUPPORTED = "unsupported"


class PrimaryClassification(str, Enum):
    """Primary reconciliation outcome for one future plan item."""

    INVALID_OBSERVATION = "invalid_observation"
    REGISTRY_SNAPSHOT_INVALID = "registry_snapshot_invalid"
    REGISTRY_IDENTITY_EVIDENCE_CONFLICT = "registry_identity_evidence_conflict"
    REGISTRY_IDENTITY_COLLISION = "registry_identity_collision"
    AUTHORITATIVE_IDENTITY_CONFLICT = "authoritative_identity_conflict"
    CONTENT_CONFLICT = "content_conflict"
    DUPLICATE_PATH_CONFLICT = "duplicate_path_conflict"
    AMBIGUOUS_MATCH = "ambiguous_match"
    UNKNOWN_AUTHORITATIVE_ASSET_ID = "unknown_authoritative_asset_id"
    PATH_CHANGED = "path_changed"
    METADATA_DRIFT = "metadata_drift"
    LIFECYCLE_CONFLICT = "lifecycle_conflict"
    AVAILABILITY_CHANGED = "availability_changed"
    RECORD_NOT_OBSERVED = "record_not_observed"
    NEW_UNREGISTERED_OBSERVATION = "new_unregistered_observation"
    UNCHANGED = "unchanged"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    UNSUPPORTED_OBSERVATION = "unsupported_observation"
    DIAGNOSTIC_ONLY = "diagnostic_only"


class FindingSeverity(str, Enum):
    """Severity assigned to a structured reconciliation finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ActionKind(str, Enum):
    """Inert action kinds a future plan may describe."""

    NO_ACTION = "no_action"
    REGISTER_CANDIDATE = "register_candidate"
    UPDATE_RESOLVED_PATH = "update_resolved_path"
    UPDATE_AVAILABILITY = "update_availability"
    RESTORE_AVAILABILITY = "restore_availability"
    MARK_MISSING = "mark_missing"
    UPDATE_VERIFICATION_STATE = "update_verification_state"
    UPDATE_OBSERVED_METADATA = "update_observed_metadata"
    REQUIRE_REVIEW = "require_review"
    FLAG_CONFLICT = "flag_conflict"
    DIAGNOSTIC_ONLY = "diagnostic_only"


class EvidenceKind(str, Enum):
    """Stable kind for plan-local or input identity evidence."""

    TRUSTED_ASSET_ID = "trusted_asset_id"
    NORMALIZED_PATH = "normalized_path"
    FULL_CONTENT_HASH = "full_content_hash"
    FILESYSTEM_IDENTITY = "filesystem_identity"
    PARTIAL_FINGERPRINT = "partial_fingerprint"
    FILE_SIZE = "file_size"
    MODIFIED_TIME = "modified_time"
    METADATA = "metadata"
    SCOPE = "scope"
    DIAGNOSTIC = "diagnostic"
    LIFECYCLE = "lifecycle"
    AVAILABILITY = "availability"


class EvidenceAuthority(str, Enum):
    """Planner-derived authority of one evidence fact."""

    AUTHORITATIVE = "authoritative"
    STRONG = "strong"
    WEAK = "weak"
    DIAGNOSTIC = "diagnostic"


class EvidenceSourceKind(str, Enum):
    """Source category for evidence retained in a reconciliation plan."""

    REGISTRY_RECORD = "registry_record"
    REGISTRY_IDENTITY_EVIDENCE = "registry_identity_evidence"
    OBSERVATION = "observation"
    REQUEST = "request"
    SCOPE = "scope"
    DERIVED = "derived"


class ComparisonResult(str, Enum):
    """Result of comparing two compatible evidence facts."""

    MATCH = "match"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    MALFORMED = "malformed"


class UniquenessResult(str, Enum):
    """Uniqueness state for evidence used in identity matching."""

    UNIQUE = "unique"
    NON_UNIQUE_REGISTRY = "non_unique_registry"
    NON_UNIQUE_OBSERVATION = "non_unique_observation"
    NON_UNIQUE_BOTH = "non_unique_both"
    NOT_APPLICABLE = "not_applicable"


class PublicVisibility(str, Enum):
    """Public exposure policy for an internal evidence value."""

    PUBLIC_VALUE = "public_value"
    SAFE_SUMMARY = "safe_summary"
    REDACT_VALUE = "redact_value"
    INTERNAL_ONLY = "internal_only"


class InvalidityTier(str, Enum):
    """Tier that determines whether invalid input aborts or becomes a finding."""

    REQUEST = "request"
    SNAPSHOT = "snapshot"
    OBSERVATION = "observation"
    OPTIONAL_EVIDENCE_FIELD = "optional_evidence_field"


class ConflictKind(str, Enum):
    """Stable conflict category used by subjects and future findings."""

    AUTHORITATIVE_IDENTITY = "authoritative_identity"
    CONTENT = "content"
    DUPLICATE_PATH = "duplicate_path"
    REGISTRY_IDENTITY_EVIDENCE = "registry_identity_evidence"
    REGISTRY_IDENTITY_COLLISION = "registry_identity_collision"
    OBSERVATION_IDENTITY_COLLISION = "observation_identity_collision"
    MIXED_IDENTITY_COLLISION = "mixed_identity_collision"
    LIFECYCLE = "lifecycle"
    SCOPE = "scope"


FINDING_SEVERITY_RANK: dict[FindingSeverity, int] = {
    FindingSeverity.ERROR: 0,
    FindingSeverity.WARNING: 1,
    FindingSeverity.INFO: 2,
}
"""Explicit severity ordering used by future finding sorting."""

EVIDENCE_AUTHORITY_RANK: dict[EvidenceAuthority, int] = {
    EvidenceAuthority.AUTHORITATIVE: 0,
    EvidenceAuthority.STRONG: 1,
    EvidenceAuthority.WEAK: 2,
    EvidenceAuthority.DIAGNOSTIC: 3,
}
"""Explicit evidence-authority ordering used by future evidence sorting."""

UNIQUENESS_RANK: dict[UniquenessResult, int] = {
    UniquenessResult.NON_UNIQUE_BOTH: 0,
    UniquenessResult.NON_UNIQUE_REGISTRY: 1,
    UniquenessResult.NON_UNIQUE_OBSERVATION: 2,
    UniquenessResult.UNIQUE: 3,
    UniquenessResult.NOT_APPLICABLE: 4,
}
"""Explicit uniqueness ordering used by future conflict analysis."""
