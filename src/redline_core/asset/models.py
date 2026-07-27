"""Persistent Asset Registry V1 domain contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from redline_core.asset.exceptions import InvalidAssetIdError, AssetLifecycleError


class AssetLifecycle(str, Enum):
    DECLARED = "declared"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class AssetAvailability(str, Enum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    MISSING = "missing"
    NON_FILE = "non_file"


class AssetVerificationState(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"


class AssetReconciliationActionType(str, Enum):
    CREATE = "create"
    PATH_UPDATE = "path_update"
    NOOP = "noop"
    DEPRECATE = "deprecate"


class AssetSourceKind(str, Enum):
    CONFIG_RECONCILIATION = "config_reconciliation"


class AssetDiagnosticCode(str, Enum):
    FILE_AVAILABLE = "file_available"
    FILE_MISSING = "file_missing"
    PATH_IS_NOT_FILE = "path_is_not_file"
    FILESYSTEM_ACCESS_FAILED = "filesystem_access_failed"
    ASSET_DEPRECATED = "asset_deprecated"


def _require_clean_asset_id(asset_id: str) -> None:
    if not isinstance(asset_id, str):
        raise InvalidAssetIdError("Asset ID must be a string.")
    if asset_id.strip() != asset_id:
        raise InvalidAssetIdError("Asset ID must not contain leading or trailing whitespace.")
    if not asset_id:
        raise InvalidAssetIdError("Asset ID must not be empty.")


def _require_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty.")


def _require_aware_utc(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field_name} must be UTC.")


def validate_asset_state(
    lifecycle: AssetLifecycle,
    availability: AssetAvailability,
    verification: AssetVerificationState,
) -> None:
    """Validate normal lifecycle, availability, and verification combinations."""
    if not isinstance(lifecycle, AssetLifecycle):
        raise AssetLifecycleError(
            "Asset lifecycle must be an AssetLifecycle enum value.",
            context={"lifecycle": repr(lifecycle)},
        )
    if not isinstance(availability, AssetAvailability):
        raise AssetLifecycleError(
            "Asset availability must be an AssetAvailability enum value.",
            context={"availability": repr(availability)},
        )
    if not isinstance(verification, AssetVerificationState):
        raise AssetLifecycleError(
            "Asset verification state must be an AssetVerificationState enum value.",
            context={"verification": repr(verification)},
        )

    allowed_declared = {
        (AssetAvailability.UNKNOWN, AssetVerificationState.UNVERIFIED),
        (AssetAvailability.MISSING, AssetVerificationState.VERIFIED),
        (AssetAvailability.NON_FILE, AssetVerificationState.VERIFIED),
        (AssetAvailability.UNKNOWN, AssetVerificationState.FAILED),
    }
    allowed_active = {
        (AssetAvailability.AVAILABLE, AssetVerificationState.VERIFIED),
        (AssetAvailability.MISSING, AssetVerificationState.VERIFIED),
        (AssetAvailability.NON_FILE, AssetVerificationState.VERIFIED),
        (AssetAvailability.UNKNOWN, AssetVerificationState.FAILED),
    }
    allowed_deprecated = allowed_declared | allowed_active

    allowed_by_lifecycle = {
        AssetLifecycle.DECLARED: allowed_declared,
        AssetLifecycle.ACTIVE: allowed_active,
        AssetLifecycle.DEPRECATED: allowed_deprecated,
    }
    if (availability, verification) not in allowed_by_lifecycle[lifecycle]:
        raise AssetLifecycleError(
            "Asset lifecycle, availability, and verification state are inconsistent.",
            context={
                "lifecycle": lifecycle.value,
                "availability": availability.value,
                "verification": verification.value,
            },
        )


@dataclass(frozen=True)
class AssetDeclaration:
    asset_id: str
    declared_path: str
    source_kind: AssetSourceKind = AssetSourceKind.CONFIG_RECONCILIATION
    source_detail: str | None = None

    def __post_init__(self) -> None:
        _require_clean_asset_id(self.asset_id)
        _require_non_empty_string(self.declared_path, "declared_path")


@dataclass(frozen=True)
class AssetRegistryRecord:
    record_id: int | None
    asset_id: str
    declared_path: str
    resolved_path: str | None
    normalized_resolved_path: str | None
    approved_root_id: str
    lifecycle: AssetLifecycle
    availability: AssetAvailability
    verification: AssetVerificationState
    file_size_bytes: int | None
    file_modified_at: datetime | None
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_kind: AssetSourceKind
    source_detail: str | None
    diagnostic_code: AssetDiagnosticCode | None
    diagnostic_message: str | None

    def __post_init__(self) -> None:
        _require_clean_asset_id(self.asset_id)
        _require_non_empty_string(self.declared_path, "declared_path")
        _require_non_empty_string(self.approved_root_id, "approved_root_id")
        validate_asset_state(self.lifecycle, self.availability, self.verification)

        if self.record_id is not None and self.record_id < 0:
            raise ValueError("record_id must be non-negative.")
        if self.file_size_bytes is not None and self.file_size_bytes < 0:
            raise ValueError("file_size_bytes must be non-negative.")
        if self.file_size_bytes is not None and self.availability is not AssetAvailability.AVAILABLE:
            raise ValueError("file_size_bytes is only valid for available files.")
        if self.file_modified_at is not None and self.availability is not AssetAvailability.AVAILABLE:
            raise ValueError("file_modified_at is only valid for available files.")

        _require_aware_utc(self.created_at, "created_at")
        _require_aware_utc(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be greater than or equal to created_at.")
        if self.file_modified_at is not None:
            _require_aware_utc(self.file_modified_at, "file_modified_at")
        if self.last_verified_at is not None:
            _require_aware_utc(self.last_verified_at, "last_verified_at")
        if self.verification is AssetVerificationState.UNVERIFIED and self.last_verified_at is not None:
            raise ValueError("last_verified_at must be empty for unverified records.")
        if self.verification is not AssetVerificationState.UNVERIFIED and self.last_verified_at is None:
            raise ValueError("last_verified_at is required for completed verification states.")
        if self.availability is AssetAvailability.AVAILABLE and (
            self.file_size_bytes is None or self.file_modified_at is None
        ):
            raise ValueError("available files require file size and modified timestamp.")


@dataclass(frozen=True)
class AssetPathResolution:
    declared_path: str
    approved_root: Path
    resolved_path: Path
    normalized_path_key: str
    approved_root_id: str


@dataclass(frozen=True)
class AssetPathObservation:
    availability: AssetAvailability
    verification: AssetVerificationState
    resolved_path: Path
    normalized_path_key: str
    file_size_bytes: int | None
    file_modified_at: datetime | None
    diagnostic_code: AssetDiagnosticCode
    diagnostic_message: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.availability, AssetAvailability):
            raise AssetLifecycleError(
                "Asset path observation availability must be an AssetAvailability enum value.",
                context={"availability": repr(self.availability)},
            )
        if not isinstance(self.verification, AssetVerificationState):
            raise AssetLifecycleError(
                "Asset path observation verification must be an AssetVerificationState enum value.",
                context={"verification": repr(self.verification)},
            )
        if not isinstance(self.resolved_path, Path):
            raise AssetLifecycleError("Asset path observation resolved_path must be a Path.")
        if not isinstance(self.normalized_path_key, str) or not self.normalized_path_key.strip():
            raise AssetLifecycleError("Asset path observation normalized_path_key must be a non-empty string.")
        if not isinstance(self.diagnostic_code, AssetDiagnosticCode):
            raise AssetLifecycleError(
                "Asset path observation diagnostic_code must be an AssetDiagnosticCode enum value.",
                context={"diagnostic_code": repr(self.diagnostic_code)},
            )
        if self.diagnostic_message is not None and not isinstance(self.diagnostic_message, str):
            raise AssetLifecycleError("Asset path observation diagnostic_message must be a string when present.")
        if self.file_size_bytes is not None:
            if not isinstance(self.file_size_bytes, int) or isinstance(self.file_size_bytes, bool):
                raise AssetLifecycleError("Asset path observation file_size_bytes must be an integer when present.")
            if self.file_size_bytes < 0:
                raise AssetLifecycleError("Asset path observation file_size_bytes must be non-negative.")
        if self.file_modified_at is not None:
            if not isinstance(self.file_modified_at, datetime):
                raise AssetLifecycleError("Asset path observation file_modified_at must be a datetime when present.")
            if self.file_modified_at.tzinfo is None or self.file_modified_at.utcoffset() is None:
                raise AssetLifecycleError("Asset path observation file_modified_at must be timezone-aware.")
            if self.file_modified_at.utcoffset() != timezone.utc.utcoffset(self.file_modified_at):
                raise AssetLifecycleError("Asset path observation file_modified_at must be UTC.")

        if self.verification is not AssetVerificationState.VERIFIED:
            raise AssetLifecycleError("Asset path observations must represent completed normal verification.")
        if self.availability is AssetAvailability.UNKNOWN:
            raise AssetLifecycleError("Asset path observations cannot use unknown availability.")

        if self.availability is AssetAvailability.AVAILABLE:
            if self.file_size_bytes is None or self.file_modified_at is None:
                raise AssetLifecycleError("Available asset observations require file facts.")
            if self.diagnostic_code is not AssetDiagnosticCode.FILE_AVAILABLE:
                raise AssetLifecycleError("Available asset observations require FILE_AVAILABLE diagnostic code.")
            return

        if self.availability is AssetAvailability.MISSING:
            if self.file_size_bytes is not None or self.file_modified_at is not None:
                raise AssetLifecycleError("Missing asset observations must not include regular-file facts.")
            if self.diagnostic_code is not AssetDiagnosticCode.FILE_MISSING:
                raise AssetLifecycleError("Missing asset observations require FILE_MISSING diagnostic code.")
            return

        if self.availability is AssetAvailability.NON_FILE:
            if self.file_size_bytes is not None or self.file_modified_at is not None:
                raise AssetLifecycleError("Non-file asset observations must not include regular-file facts.")
            if self.diagnostic_code is not AssetDiagnosticCode.PATH_IS_NOT_FILE:
                raise AssetLifecycleError("Non-file asset observations require PATH_IS_NOT_FILE diagnostic code.")
            return

        raise AssetLifecycleError("Asset path observation availability is not valid for normal observation.")


@dataclass(frozen=True)
class AssetVerificationResult:
    asset_id: str
    record_before: AssetRegistryRecord
    record_after: AssetRegistryRecord
    observation: AssetPathObservation
    lifecycle_changed: bool


@dataclass(frozen=True)
class AssetRegistryContext:
    registry_id: str
    registry_revision: str
    approved_root_id: str
    approved_root_fingerprint: str


@dataclass(frozen=True)
class AssetReconciliationConflict:
    asset_id: str
    message: str
    diagnostic_code: AssetDiagnosticCode | None = None


@dataclass(frozen=True)
class AssetReconciliationAction:
    action_type: AssetReconciliationActionType
    asset_id: str
    declaration: AssetDeclaration | None = None
    record_before: AssetRegistryRecord | None = None
    record_after: AssetRegistryRecord | None = None


@dataclass(frozen=True)
class AssetReconciliationPlan:
    context: AssetRegistryContext
    created_at: datetime
    actions: tuple[AssetReconciliationAction, ...]
    conflicts: tuple[AssetReconciliationConflict, ...]
    desired_state_fingerprint: str

    def __post_init__(self) -> None:
        _require_aware_utc(self.created_at, "created_at")
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))


@dataclass(frozen=True)
class AssetReconciliationApplyResult:
    context: AssetRegistryContext
    applied_at: datetime
    actions_applied: tuple[AssetReconciliationAction, ...]
    conflicts: tuple[AssetReconciliationConflict, ...]

    def __post_init__(self) -> None:
        _require_aware_utc(self.applied_at, "applied_at")
        object.__setattr__(self, "actions_applied", tuple(self.actions_applied))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))
