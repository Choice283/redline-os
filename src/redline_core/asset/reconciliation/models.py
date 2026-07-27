"""Immutable domain models for Asset Registry reconciliation planning."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetVerificationState,
)
from redline_core.asset.reconciliation.enums import (
    AssetIdTrustPolicy,
    EvidenceKind,
    ObservationKind,
    PrimaryClassification,
    ScopeCompleteness,
)
from redline_core.asset.reconciliation.limits import DEFAULT_LIMITS, ReconciliationLimitPolicy
from redline_core.asset.reconciliation.subjects import PlanSubject


RECONCILIATION_REQUEST_SCHEMA_VERSION = "1"
"""Supported V1 reconciliation request schema version."""

RECONCILIATION_PLAN_SCHEMA_VERSION = "asset_reconciliation_plan.v1"
"""Supported V1 public reconciliation plan schema version."""


def _as_tuple(values: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(values)


def _as_mapping_proxy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _require_clean_string(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    if value.strip() != value:
        raise ValueError(f"{field_name} must not contain leading or trailing whitespace.")
    if not value:
        raise ValueError(f"{field_name} must not be empty.")


def _require_aware_utc(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field_name} must be UTC.")


@dataclass(frozen=True, slots=True)
class ObservationFilters:
    """Machine-evaluable filters attached to an observation scope."""

    included_media_types: tuple[str, ...] = ()
    included_extensions: tuple[str, ...] = ()
    included_lifecycle_states: tuple[AssetLifecycle, ...] = ()
    included_asset_ids: tuple[str, ...] = ()
    excluded_normalized_subtrees: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "included_media_types", _as_tuple(self.included_media_types))
        object.__setattr__(self, "included_extensions", _as_tuple(self.included_extensions))
        object.__setattr__(self, "included_lifecycle_states", _as_tuple(self.included_lifecycle_states))
        object.__setattr__(self, "included_asset_ids", _as_tuple(self.included_asset_ids))
        object.__setattr__(self, "excluded_normalized_subtrees", _as_tuple(self.excluded_normalized_subtrees))


@dataclass(frozen=True, slots=True)
class ExplicitAssetAccessFailure:
    """Per-Asset ID access failure reported by an explicit-ID scope."""

    asset_id: str
    failure_code: str
    safe_message: str

    def __post_init__(self) -> None:
        _require_clean_string(self.asset_id, "asset_id")
        _require_clean_string(self.failure_code, "failure_code")
        if not isinstance(self.safe_message, str) or not self.safe_message.strip():
            raise ValueError("safe_message must be a non-empty string.")

    def canonical_key(self) -> tuple[str, str]:
        """Return the deterministic key for this access failure."""
        return (self.asset_id, self.failure_code)


@dataclass(frozen=True, slots=True)
class ObservationRootScope:
    """Observation completeness facts for one already-normalized root key."""

    normalized_root_key: str
    completeness: ScopeCompleteness
    inaccessible_subtrees: tuple[str, ...] = ()
    access_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_clean_string(self.normalized_root_key, "normalized_root_key")
        if not isinstance(self.completeness, ScopeCompleteness):
            raise ValueError("completeness must be a ScopeCompleteness enum value.")
        object.__setattr__(self, "inaccessible_subtrees", _as_tuple(self.inaccessible_subtrees))
        object.__setattr__(self, "access_failures", _as_tuple(self.access_failures))

    def canonical_key(self) -> tuple[str, ...]:
        """Return a component-aware key from an already-normalized root key."""
        return tuple(part for part in self.normalized_root_key.replace("\\", "/").split("/") if part)


@dataclass(frozen=True, slots=True)
class ObservationScope:
    """Immutable description of what an observation source expected to see."""

    scope_id: str
    observed_at: datetime
    source_id: str
    roots: tuple[ObservationRootScope, ...] = ()
    explicit_asset_ids: tuple[str, ...] = ()
    explicit_asset_id_completeness: ScopeCompleteness = ScopeCompleteness.UNKNOWN
    explicit_asset_id_failures: tuple[ExplicitAssetAccessFailure, ...] = ()
    inclusion_filters: ObservationFilters = ObservationFilters()
    exclusion_filters: ObservationFilters = ObservationFilters()

    def __post_init__(self) -> None:
        _require_clean_string(self.scope_id, "scope_id")
        _require_clean_string(self.source_id, "source_id")
        _require_aware_utc(self.observed_at, "observed_at")
        if not isinstance(self.explicit_asset_id_completeness, ScopeCompleteness):
            raise ValueError("explicit_asset_id_completeness must be a ScopeCompleteness enum value.")
        if not isinstance(self.inclusion_filters, ObservationFilters):
            raise ValueError("inclusion_filters must be an ObservationFilters instance.")
        if not isinstance(self.exclusion_filters, ObservationFilters):
            raise ValueError("exclusion_filters must be an ObservationFilters instance.")
        object.__setattr__(self, "roots", _as_tuple(self.roots))
        object.__setattr__(self, "explicit_asset_ids", tuple(sorted(_as_tuple(self.explicit_asset_ids))))
        object.__setattr__(self, "explicit_asset_id_failures", _as_tuple(self.explicit_asset_id_failures))

    def canonical_key(self) -> tuple[str]:
        """Return the deterministic scope identity key."""
        return (self.scope_id,)


@dataclass(frozen=True, slots=True)
class RegistryIdentityEvidence:
    """Detached supplemental registry-side identity evidence."""

    asset_id: str
    evidence_kind: EvidenceKind
    algorithm: str | None
    normalized_value: str
    normalization_format: str
    scope_id: str | None
    source_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_clean_string(self.asset_id, "asset_id")
        if not isinstance(self.evidence_kind, EvidenceKind):
            raise ValueError("evidence_kind must be an EvidenceKind enum value.")
        _require_clean_string(self.normalized_value, "normalized_value")
        _require_clean_string(self.normalization_format, "normalization_format")
        _require_clean_string(self.source_id, "source_id")
        if self.algorithm is not None:
            _require_clean_string(self.algorithm, "algorithm")
        if self.scope_id is not None:
            _require_clean_string(self.scope_id, "scope_id")
        _require_aware_utc(self.observed_at, "observed_at")

    def canonical_identity_key(self) -> tuple[str, str, str | None, str, str | None, str]:
        """Return the deterministic identity key defined for detached evidence."""
        return (
            self.asset_id,
            self.evidence_kind.value,
            self.algorithm.lower() if self.algorithm is not None else None,
            self.normalized_value,
            self.scope_id,
            self.source_id,
        )


@dataclass(frozen=True, slots=True)
class AssetObservation:
    """Caller-supplied immutable facts about one media candidate."""

    observation_id: str
    source_id: str
    source_kind: ObservationKind
    observed_at: datetime
    observation_scope_id: str
    availability: AssetAvailability
    verification: AssetVerificationState
    normalized_resolved_path: str | None = None
    resolved_path: str | None = None
    file_name: str | None = None
    extension: str | None = None
    file_size_bytes: int | None = None
    file_modified_at: datetime | None = None
    file_created_at: datetime | None = None
    media_type: str | None = None
    claimed_asset_id: str | None = None
    content_hashes: tuple[tuple[str, str], ...] = ()
    partial_fingerprints: tuple[str, ...] = ()
    filesystem_identity: str | None = None
    diagnostics: tuple[str, ...] = ()
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_clean_string(self.observation_id, "observation_id")
        _require_clean_string(self.source_id, "source_id")
        _require_clean_string(self.observation_scope_id, "observation_scope_id")
        if not isinstance(self.source_kind, ObservationKind):
            raise ValueError("source_kind must be an ObservationKind enum value.")
        if not isinstance(self.availability, AssetAvailability):
            raise ValueError("availability must be an AssetAvailability enum value.")
        if not isinstance(self.verification, AssetVerificationState):
            raise ValueError("verification must be an AssetVerificationState enum value.")
        _require_aware_utc(self.observed_at, "observed_at")
        if self.file_modified_at is not None:
            _require_aware_utc(self.file_modified_at, "file_modified_at")
        if self.file_created_at is not None:
            _require_aware_utc(self.file_created_at, "file_created_at")
        if self.file_size_bytes is not None and (
            not isinstance(self.file_size_bytes, int) or isinstance(self.file_size_bytes, bool) or self.file_size_bytes < 0
        ):
            raise ValueError("file_size_bytes must be a non-negative integer when present.")
        object.__setattr__(self, "content_hashes", _as_tuple(self.content_hashes))
        object.__setattr__(self, "partial_fingerprints", _as_tuple(self.partial_fingerprints))
        object.__setattr__(self, "diagnostics", _as_tuple(self.diagnostics))
        object.__setattr__(self, "metadata", _as_mapping_proxy(self.metadata))

    def canonical_key(self) -> tuple[str]:
        """Return the deterministic observation identity key."""
        return (self.observation_id,)


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """Immutable registry records and detached evidence captured before planning."""

    records: tuple[AssetRegistryRecord, ...]
    identity_evidence: tuple[RegistryIdentityEvidence, ...]
    schema_version: str
    snapshot_id: str
    snapshot_created_at: datetime
    registry_id: str
    approved_root_context: str
    repository_revision: str | None = None

    def __post_init__(self) -> None:
        _require_clean_string(self.schema_version, "schema_version")
        _require_clean_string(self.snapshot_id, "snapshot_id")
        _require_clean_string(self.registry_id, "registry_id")
        _require_clean_string(self.approved_root_context, "approved_root_context")
        if self.repository_revision is not None:
            _require_clean_string(self.repository_revision, "repository_revision")
        _require_aware_utc(self.snapshot_created_at, "snapshot_created_at")
        object.__setattr__(self, "records", _as_tuple(self.records))
        object.__setattr__(self, "identity_evidence", _as_tuple(self.identity_evidence))

    def canonical_key(self) -> tuple[str, str, str]:
        """Return the deterministic snapshot identity key."""
        return (self.registry_id, self.schema_version, self.snapshot_id)


@dataclass(frozen=True, slots=True)
class ReconciliationRequest:
    """Immutable top-level request for future reconciliation planning."""

    request_id: str
    schema_version: str
    created_at: datetime
    observations: tuple[AssetObservation, ...]
    scopes: tuple[ObservationScope, ...]
    asset_id_trust_policy: AssetIdTrustPolicy = AssetIdTrustPolicy.REJECT_ALL
    trusted_asset_id_source_ids: tuple[str, ...] = ()
    limit_policy: ReconciliationLimitPolicy = DEFAULT_LIMITS
    request_metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_clean_string(self.request_id, "request_id")
        _require_clean_string(self.schema_version, "schema_version")
        _require_aware_utc(self.created_at, "created_at")
        if not isinstance(self.asset_id_trust_policy, AssetIdTrustPolicy):
            raise ValueError("asset_id_trust_policy must be an AssetIdTrustPolicy enum value.")
        if not isinstance(self.limit_policy, ReconciliationLimitPolicy):
            raise ValueError("limit_policy must be a ReconciliationLimitPolicy instance.")
        object.__setattr__(self, "observations", _as_tuple(self.observations))
        object.__setattr__(self, "scopes", _as_tuple(self.scopes))
        object.__setattr__(
            self,
            "trusted_asset_id_source_ids",
            tuple(sorted(_as_tuple(self.trusted_asset_id_source_ids))),
        )
        object.__setattr__(self, "request_metadata", _as_mapping_proxy(self.request_metadata))

    def canonical_key(self) -> tuple[str, str]:
        """Return the deterministic request identity key."""
        return (self.schema_version, self.request_id)


@dataclass(frozen=True, slots=True)
class ReconciliationPlanItem:
    """Immutable public shape for one future reconciliation plan item."""

    item_id: str
    subject: PlanSubject
    primary_classification: PrimaryClassification
    findings: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    requires_review: bool = False
    proposal_blocked: bool = False

    def __post_init__(self) -> None:
        _require_clean_string(self.item_id, "item_id")
        if not isinstance(self.primary_classification, PrimaryClassification):
            raise ValueError("primary_classification must be a PrimaryClassification enum value.")
        object.__setattr__(self, "findings", _as_tuple(self.findings))
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        object.__setattr__(self, "actions", _as_tuple(self.actions))


@dataclass(frozen=True, slots=True)
class PlanSummary:
    """Derived count summary for a future immutable reconciliation plan."""

    classifications: Mapping[str, int]
    severities: Mapping[str, int]
    action_kinds: Mapping[str, int]
    review_required_count: int = 0
    proposal_blocked_count: int = 0
    invalid_observation_count: int = 0
    conflict_count: int = 0
    unmatched_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "classifications", _as_mapping_proxy(self.classifications))
        object.__setattr__(self, "severities", _as_mapping_proxy(self.severities))
        object.__setattr__(self, "action_kinds", _as_mapping_proxy(self.action_kinds))


@dataclass(frozen=True, slots=True)
class ReconciliationPlan:
    """Immutable top-level output shape for future reconciliation planning."""

    plan_id: str
    schema_version: str
    request_id: str
    snapshot_id: str
    registry_id: str
    created_at: datetime
    items: tuple[ReconciliationPlanItem, ...]
    evidence: tuple[str, ...]
    summary: PlanSummary
    limit_policy_fingerprint: str
    approved_root_context: str
    repository_revision: str | None = None

    def __post_init__(self) -> None:
        _require_clean_string(self.plan_id, "plan_id")
        _require_clean_string(self.schema_version, "schema_version")
        _require_clean_string(self.request_id, "request_id")
        _require_clean_string(self.snapshot_id, "snapshot_id")
        _require_clean_string(self.registry_id, "registry_id")
        _require_clean_string(self.limit_policy_fingerprint, "limit_policy_fingerprint")
        _require_clean_string(self.approved_root_context, "approved_root_context")
        if self.repository_revision is not None:
            _require_clean_string(self.repository_revision, "repository_revision")
        if not isinstance(self.summary, PlanSummary):
            raise ValueError("summary must be a PlanSummary instance.")
        _require_aware_utc(self.created_at, "created_at")
        object.__setattr__(self, "items", _as_tuple(self.items))
        object.__setattr__(self, "evidence", _as_tuple(self.evidence))
