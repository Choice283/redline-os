"""Tests for Persistent Asset Registry V1 domain models."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from redline_core.asset.exceptions import AssetLifecycleError, InvalidAssetIdError
from redline_core.asset.models import (
    AssetAvailability,
    AssetDiagnosticCode,
    AssetDeclaration,
    AssetLifecycle,
    AssetPathObservation,
    AssetRegistryContext,
    AssetRegistryRecord,
    AssetReconciliationAction,
    AssetReconciliationActionType,
    AssetReconciliationApplyResult,
    AssetReconciliationPlan,
    AssetSourceKind,
    AssetVerificationState,
    validate_asset_state,
)


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def make_record(
    *,
    lifecycle: AssetLifecycle = AssetLifecycle.DECLARED,
    availability: AssetAvailability = AssetAvailability.UNKNOWN,
    verification: AssetVerificationState = AssetVerificationState.UNVERIFIED,
    last_verified_at: datetime | None = None,
    file_size_bytes: int | None = None,
    file_modified_at: datetime | None = None,
) -> AssetRegistryRecord:
    return AssetRegistryRecord(
        record_id=1,
        asset_id="RLG-001",
        declared_path="logos/lower_third.png",
        resolved_path="C:/assets/logos/lower_third.png",
        normalized_resolved_path="c:/assets/logos/lower_third.png",
        approved_root_id="assets_path",
        lifecycle=lifecycle,
        availability=availability,
        verification=verification,
        file_size_bytes=file_size_bytes,
        file_modified_at=file_modified_at,
        last_verified_at=last_verified_at,
        created_at=NOW,
        updated_at=NOW,
        source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
        source_detail=None,
        diagnostic_code=None,
        diagnostic_message=None,
    )


def make_observation(
    *,
    availability: AssetAvailability = AssetAvailability.AVAILABLE,
    verification: AssetVerificationState = AssetVerificationState.VERIFIED,
    file_size_bytes: int | None = 0,
    file_modified_at: datetime | None = NOW,
    diagnostic_code: AssetDiagnosticCode = AssetDiagnosticCode.FILE_AVAILABLE,
    normalized_path_key: str = "c:/assets/logos/lower_third.png",
) -> AssetPathObservation:
    return AssetPathObservation(
        availability=availability,
        verification=verification,
        resolved_path=Path("C:/assets/logos/lower_third.png"),
        normalized_path_key=normalized_path_key,
        file_size_bytes=file_size_bytes,
        file_modified_at=file_modified_at,
        diagnostic_code=diagnostic_code,
        diagnostic_message=None,
    )


def test_asset_declaration_is_frozen_and_validates_id():
    declaration = AssetDeclaration(asset_id="RLG-001", declared_path="logos/lower_third.png")

    assert declaration.source_kind is AssetSourceKind.CONFIG_RECONCILIATION
    with pytest.raises(FrozenInstanceError):
        declaration.asset_id = "RLG-002"  # type: ignore[misc]


@pytest.mark.parametrize("asset_id", ["", " RLG-001", "RLG-001 ", 123])
def test_asset_declaration_rejects_invalid_ids(asset_id):
    with pytest.raises(InvalidAssetIdError):
        AssetDeclaration(asset_id=asset_id, declared_path="logos/lower_third.png")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lifecycle", "declared"),
        ("availability", "unknown"),
        ("verification", "verified"),
        ("lifecycle", object()),
        ("availability", object()),
        ("verification", object()),
    ],
)
def test_validate_asset_state_rejects_raw_or_invalid_enum_values(field, value):
    values = {
        "lifecycle": AssetLifecycle.DECLARED,
        "availability": AssetAvailability.UNKNOWN,
        "verification": AssetVerificationState.UNVERIFIED,
    }
    values[field] = value

    with pytest.raises(AssetLifecycleError):
        validate_asset_state(values["lifecycle"], values["availability"], values["verification"])


@pytest.mark.parametrize(
    ("lifecycle", "availability", "verification"),
    [
        (AssetLifecycle.DECLARED, AssetAvailability.UNKNOWN, AssetVerificationState.UNVERIFIED),
        (AssetLifecycle.DECLARED, AssetAvailability.MISSING, AssetVerificationState.VERIFIED),
        (AssetLifecycle.DECLARED, AssetAvailability.NON_FILE, AssetVerificationState.VERIFIED),
        (AssetLifecycle.DECLARED, AssetAvailability.UNKNOWN, AssetVerificationState.FAILED),
        (AssetLifecycle.ACTIVE, AssetAvailability.AVAILABLE, AssetVerificationState.VERIFIED),
        (AssetLifecycle.ACTIVE, AssetAvailability.MISSING, AssetVerificationState.VERIFIED),
        (AssetLifecycle.ACTIVE, AssetAvailability.NON_FILE, AssetVerificationState.VERIFIED),
        (AssetLifecycle.ACTIVE, AssetAvailability.UNKNOWN, AssetVerificationState.FAILED),
        (AssetLifecycle.DEPRECATED, AssetAvailability.UNKNOWN, AssetVerificationState.UNVERIFIED),
        (AssetLifecycle.DEPRECATED, AssetAvailability.AVAILABLE, AssetVerificationState.VERIFIED),
    ],
)
def test_validate_asset_state_allows_v1_normal_combinations(lifecycle, availability, verification):
    validate_asset_state(lifecycle, availability, verification)


@pytest.mark.parametrize(
    ("lifecycle", "availability", "verification"),
    [
        (AssetLifecycle.DECLARED, AssetAvailability.AVAILABLE, AssetVerificationState.VERIFIED),
        (AssetLifecycle.ACTIVE, AssetAvailability.UNKNOWN, AssetVerificationState.UNVERIFIED),
        (AssetLifecycle.DEPRECATED, AssetAvailability.AVAILABLE, AssetVerificationState.UNVERIFIED),
    ],
)
def test_validate_asset_state_rejects_invalid_combinations(lifecycle, availability, verification):
    with pytest.raises(AssetLifecycleError):
        validate_asset_state(lifecycle, availability, verification)


def test_record_requires_completed_verification_timestamp():
    with pytest.raises(ValueError, match="last_verified_at is required"):
        make_record(
            lifecycle=AssetLifecycle.ACTIVE,
            availability=AssetAvailability.AVAILABLE,
            verification=AssetVerificationState.VERIFIED,
            file_size_bytes=10,
            file_modified_at=NOW,
        )


def test_record_rejects_file_facts_for_missing_asset():
    with pytest.raises(ValueError, match="only valid for available"):
        make_record(
            lifecycle=AssetLifecycle.ACTIVE,
            availability=AssetAvailability.MISSING,
            verification=AssetVerificationState.VERIFIED,
            last_verified_at=NOW,
            file_size_bytes=10,
        )


def test_record_accepts_available_file_facts():
    record = make_record(
        lifecycle=AssetLifecycle.ACTIVE,
        availability=AssetAvailability.AVAILABLE,
        verification=AssetVerificationState.VERIFIED,
        last_verified_at=NOW,
        file_size_bytes=10,
        file_modified_at=NOW,
    )

    assert record.file_size_bytes == 10


def test_path_observation_accepts_zero_byte_available_file():
    observation = make_observation()

    assert observation.availability is AssetAvailability.AVAILABLE
    assert observation.file_size_bytes == 0


def test_path_observation_accepts_valid_missing_observation():
    observation = make_observation(
        availability=AssetAvailability.MISSING,
        file_size_bytes=None,
        file_modified_at=None,
        diagnostic_code=AssetDiagnosticCode.FILE_MISSING,
    )

    assert observation.availability is AssetAvailability.MISSING


def test_path_observation_accepts_valid_non_file_observation():
    observation = make_observation(
        availability=AssetAvailability.NON_FILE,
        file_size_bytes=None,
        file_modified_at=None,
        diagnostic_code=AssetDiagnosticCode.PATH_IS_NOT_FILE,
    )

    assert observation.availability is AssetAvailability.NON_FILE


@pytest.mark.parametrize(
    "kwargs",
    [
        {"availability": AssetAvailability.UNKNOWN},
        {"verification": AssetVerificationState.UNVERIFIED},
        {"verification": AssetVerificationState.FAILED},
        {"file_size_bytes": None},
        {"file_modified_at": None},
        {"diagnostic_code": AssetDiagnosticCode.FILE_MISSING},
        {"file_size_bytes": -1},
        {"file_modified_at": datetime(2026, 7, 27, 12, 0)},
        {"normalized_path_key": ""},
        {"availability": "available"},
        {"verification": "verified"},
        {"diagnostic_code": "file_available"},
    ],
)
def test_path_observation_rejects_invalid_available_observations(kwargs):
    with pytest.raises(AssetLifecycleError):
        make_observation(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"file_size_bytes": 1},
        {"file_modified_at": NOW},
        {"diagnostic_code": AssetDiagnosticCode.FILE_AVAILABLE},
    ],
)
def test_path_observation_rejects_invalid_missing_observations(kwargs):
    values = {
        "availability": AssetAvailability.MISSING,
        "file_size_bytes": None,
        "file_modified_at": None,
        "diagnostic_code": AssetDiagnosticCode.FILE_MISSING,
    }
    values.update(kwargs)

    with pytest.raises(AssetLifecycleError):
        make_observation(**values)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"file_size_bytes": 1},
        {"file_modified_at": NOW},
        {"diagnostic_code": AssetDiagnosticCode.FILE_MISSING},
    ],
)
def test_path_observation_rejects_invalid_non_file_observations(kwargs):
    values = {
        "availability": AssetAvailability.NON_FILE,
        "file_size_bytes": None,
        "file_modified_at": None,
        "diagnostic_code": AssetDiagnosticCode.PATH_IS_NOT_FILE,
    }
    values.update(kwargs)

    with pytest.raises(AssetLifecycleError):
        make_observation(**values)


def test_record_requires_utc_timestamps():
    with pytest.raises(ValueError, match="created_at must be timezone-aware"):
        AssetRegistryRecord(
            record_id=None,
            asset_id="RLG-001",
            declared_path="logos/lower_third.png",
            resolved_path=None,
            normalized_resolved_path=None,
            approved_root_id="assets_path",
            lifecycle=AssetLifecycle.DECLARED,
            availability=AssetAvailability.UNKNOWN,
            verification=AssetVerificationState.UNVERIFIED,
            file_size_bytes=None,
            file_modified_at=None,
            last_verified_at=None,
            created_at=datetime(2026, 7, 27, 12, 0),
            updated_at=NOW,
            source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
            source_detail=None,
            diagnostic_code=None,
            diagnostic_message=None,
        )


def test_record_rejects_updated_before_created():
    with pytest.raises(ValueError, match="updated_at"):
        AssetRegistryRecord(
            record_id=None,
            asset_id="RLG-001",
            declared_path="logos/lower_third.png",
            resolved_path=None,
            normalized_resolved_path=None,
            approved_root_id="assets_path",
            lifecycle=AssetLifecycle.DECLARED,
            availability=AssetAvailability.UNKNOWN,
            verification=AssetVerificationState.UNVERIFIED,
            file_size_bytes=None,
            file_modified_at=None,
            last_verified_at=None,
            created_at=NOW,
            updated_at=NOW - timedelta(seconds=1),
            source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
            source_detail=None,
            diagnostic_code=None,
            diagnostic_message=None,
        )


def test_reconciliation_models_convert_sequences_to_tuples():
    context = AssetRegistryContext(
        registry_id="asset_registry_v1",
        registry_revision="rev-1",
        approved_root_id="assets_path",
        approved_root_fingerprint="root-1",
    )
    action = AssetReconciliationAction(
        action_type=AssetReconciliationActionType.CREATE,
        asset_id="RLG-001",
        declaration=AssetDeclaration(asset_id="RLG-001", declared_path="logos/lower_third.png"),
    )

    plan = AssetReconciliationPlan(
        context=context,
        created_at=NOW,
        actions=[action],  # type: ignore[arg-type]
        conflicts=[],
        desired_state_fingerprint="desired-1",
    )
    result = AssetReconciliationApplyResult(
        context=context,
        applied_at=NOW,
        actions_applied=[action],  # type: ignore[arg-type]
        conflicts=[],
    )

    assert plan.actions == (action,)
    assert result.actions_applied == (action,)
