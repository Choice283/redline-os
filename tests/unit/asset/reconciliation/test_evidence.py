"""Tests for Slice 3 registry evidence helpers."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import subprocess
import sys

import pytest

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)
from redline_core.asset.reconciliation.enums import EvidenceKind
from redline_core.asset.reconciliation.evidence import (
    is_supported_registry_evidence_algorithm,
    validate_registry_identity_evidence,
)
from redline_core.asset.reconciliation.exceptions import InvalidRegistrySnapshotError
from redline_core.asset.reconciliation.limits import DEFAULT_LIMITS
from redline_core.asset.reconciliation.models import RegistryIdentityEvidence, RegistrySnapshot


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


def make_snapshot(*, evidence: tuple[RegistryIdentityEvidence, ...]) -> RegistrySnapshot:
    return RegistrySnapshot(
        records=(make_record(),),
        identity_evidence=evidence,
        schema_version="1",
        snapshot_id="snapshot-1",
        snapshot_created_at=NOW,
        registry_id="registry-1",
        approved_root_context="root-context-1",
    )


def make_evidence(
    *,
    value: str = "abc",
    algorithm: str | None = "sha256",
    normalization_format: str = "hex",
    observed_at: datetime = NOW,
) -> RegistryIdentityEvidence:
    return RegistryIdentityEvidence(
        asset_id="RLG-001",
        evidence_kind=EvidenceKind.FULL_CONTENT_HASH,
        algorithm=algorithm,
        normalized_value=value,
        normalization_format=normalization_format,
        scope_id=None,
        source_id="scan-a",
        observed_at=observed_at,
    )


def test_validate_registry_identity_evidence_deduplicates_without_mutating_snapshot():
    older = make_evidence(observed_at=NOW.replace(hour=10))
    newer = make_evidence(observed_at=NOW.replace(hour=11))
    snapshot = make_snapshot(evidence=(older, newer))
    before = repr(snapshot)

    result = validate_registry_identity_evidence(snapshot, DEFAULT_LIMITS)

    assert result == (newer,)
    assert snapshot.identity_evidence == (older, newer)
    assert repr(snapshot) == before


def test_validate_registry_identity_evidence_distinct_conflicting_values_are_preserved():
    first = make_evidence(value="hash-a")
    second = make_evidence(value="hash-b")

    result = validate_registry_identity_evidence(make_snapshot(evidence=(second, first)), DEFAULT_LIMITS)

    assert result == (first, second)


def test_validate_registry_identity_evidence_missing_hash_algorithm_is_fatal_and_sanitized():
    evidence = make_evidence(algorithm=None)

    with pytest.raises(InvalidRegistrySnapshotError) as error_info:
        validate_registry_identity_evidence(make_snapshot(evidence=(evidence,)), DEFAULT_LIMITS)

    assert error_info.value.error_code == "registry_snapshot_invalid"
    assert error_info.value.context["reason_code"] == "invalid_registry_evidence"
    assert "abc" not in repr(vars(error_info.value))


def test_supported_registry_evidence_algorithm_is_lowercase_allowlisted_only():
    assert is_supported_registry_evidence_algorithm("sha256") is True
    assert is_supported_registry_evidence_algorithm("SHA256") is True
    assert is_supported_registry_evidence_algorithm("sha512") is False
    assert is_supported_registry_evidence_algorithm(None) is False


def test_registry_evidence_deduplication_is_hash_seed_independent():
    script = (
        "from datetime import datetime, timezone\n"
        "from tests.unit.asset.reconciliation.test_evidence import make_evidence, make_snapshot\n"
        "from redline_core.asset.reconciliation.evidence import validate_registry_identity_evidence\n"
        "from redline_core.asset.reconciliation.limits import DEFAULT_LIMITS\n"
        "now=datetime(2026,7,27,12,0,tzinfo=timezone.utc)\n"
        "items=(make_evidence(value='b'), make_evidence(value='a'), make_evidence(value='b', observed_at=now.replace(hour=13)))\n"
        "result=validate_registry_identity_evidence(make_snapshot(evidence=items), DEFAULT_LIMITS)\n"
        "print('|'.join(item.normalized_value + ':' + item.observed_at.isoformat() for item in result))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    outputs = []
    for seed in ("1", "987654321"):
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            env=env,
            text=True,
        )
        outputs.append(completed.stdout.strip())

    assert outputs == [
        "a:2026-07-27T12:00:00+00:00|b:2026-07-27T13:00:00+00:00",
        "a:2026-07-27T12:00:00+00:00|b:2026-07-27T13:00:00+00:00",
    ]
