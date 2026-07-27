"""Tests for sanitized reconciliation exceptions."""
from __future__ import annotations

from types import MappingProxyType

import pytest

from redline_core.asset.exceptions import AssetRegistryError
from redline_core.asset.reconciliation.exceptions import (
    AmbiguousEquivalentRootError,
    DuplicateObservationIdError,
    InvalidReconciliationRequestError,
    InvalidRegistrySnapshotError,
    MissingObservationIdError,
    ReconciliationInvariantError,
    ReconciliationLimitExceededError,
    UnsupportedReconciliationVersionError,
)


def test_reconciliation_exception_uses_stable_error_code_and_safe_context():
    error = InvalidRegistrySnapshotError(
        "Snapshot evidence is invalid.",
        context={
            "snapshot_id": "snapshot-1",
            "raw_digest": "abc123",
            "normalized_path": "c:/secret/assets/clip.mov",
            "sql": "SELECT secret",
            "metadata": {"token": "secret"},
        },
    )

    assert isinstance(error, AssetRegistryError)
    assert error.error_code == "registry_snapshot_invalid"
    assert error.context["snapshot_id"] == "snapshot-1"
    assert error.context["raw_digest"] == "[redacted]"
    assert error.context["normalized_path"] == "[redacted]"
    assert error.context["sql"] == "[redacted]"
    assert error.context["metadata"] == "[redacted]"
    assert "abc123" not in str(error)
    assert "c:/secret" not in str(error)


def test_reconciliation_exception_context_is_immutable():
    error = InvalidReconciliationRequestError("Bad request.", context={"request_id": "req-1"})

    assert isinstance(error.context, MappingProxyType)
    with pytest.raises(TypeError):
        error.context["request_id"] = "changed"  # type: ignore[index]


def test_public_exception_error_codes_are_stable():
    assert InvalidReconciliationRequestError.error_code == "invalid_reconciliation_request"
    assert InvalidRegistrySnapshotError.error_code == "registry_snapshot_invalid"
    assert UnsupportedReconciliationVersionError.error_code == "unsupported_reconciliation_version"
    assert ReconciliationLimitExceededError.error_code == "reconciliation_limit_exceeded"
    assert DuplicateObservationIdError.error_code == "duplicate_observation_id"
    assert MissingObservationIdError.error_code == "missing_observation_id"
    assert AmbiguousEquivalentRootError.error_code == "ambiguous_equivalent_root_declarations"
    assert ReconciliationInvariantError.error_code == "internal_reconciliation_invariant_violation"
