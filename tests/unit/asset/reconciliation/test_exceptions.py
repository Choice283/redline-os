"""Tests for sanitized reconciliation exceptions."""
from __future__ import annotations

from types import MappingProxyType

import pytest

from redline_core.asset.exceptions import AssetRegistryError
from redline_core.asset.reconciliation.enums import ScopeCompleteness
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


HOSTILE_VALUES = (
    r"C:\Users\Paul\secret.mov",
    "/home/paul/secret.mov",
    "a" * 64,
    "SELECT * FROM asset_registry",
    "sk-test-secret",
    "Bearer test-token",
    "password=example",
    "line-one\nline-two\x00",
    "x" * 10000,
)


def public_exception_surfaces(error: Exception) -> tuple[str, ...]:
    return (
        str(error),
        repr(error),
        repr(error.args),
        repr(vars(error)),
    )


@pytest.mark.parametrize("hostile_value", HOSTILE_VALUES)
def test_attempted_raw_message_never_reaches_public_exception_surfaces(hostile_value):
    error = InvalidRegistrySnapshotError(hostile_value, context={"snapshot_id": "snapshot-1"})

    assert isinstance(error, AssetRegistryError)
    assert error.error_code == "registry_snapshot_invalid"
    assert error.args == ("Registry snapshot is invalid.",)
    for surface in public_exception_surfaces(error):
        assert hostile_value not in surface


@pytest.mark.parametrize("hostile_value", HOSTILE_VALUES)
def test_safe_looking_context_key_with_unsafe_value_is_redacted(hostile_value):
    error = InvalidReconciliationRequestError(
        "ignored",
        context={
            "request_id": hostile_value,
            "unsupported_key": hostile_value,
        },
    )

    assert error.context["request_id"] == "<redacted>"
    assert "unsupported_key" not in error.context
    for surface in public_exception_surfaces(error):
        assert hostile_value not in surface


def test_public_context_is_allowlisted_immutable_and_deterministically_ordered():
    error = InvalidReconciliationRequestError(
        "ignored",
        context={
            "snapshot_id": "snapshot-1",
            "count": 2,
            "field_name": "observation_id",
            "schema_version": ScopeCompleteness.COMPLETE,
            "unsupported": "safe-looking",
            "request_id": "request-1",
            "limit_value": True,
        },
        reason_code="duplicate-observation-id",
    )

    assert isinstance(error.context, MappingProxyType)
    assert tuple(error.context.items()) == (
        ("count", 2),
        ("field_name", "observation_id"),
        ("limit_value", True),
        ("reason_code", "duplicate-observation-id"),
        ("request_id", "request-1"),
        ("schema_version", "complete"),
        ("snapshot_id", "snapshot-1"),
    )
    with pytest.raises(TypeError):
        error.context["request_id"] = "changed"  # type: ignore[index]


def test_chained_cause_text_is_not_exposed_by_public_exception_output():
    cause = ValueError(r"C:\Users\Paul\secret.mov")
    try:
        raise InvalidRegistrySnapshotError("ignored") from cause
    except InvalidRegistrySnapshotError as error:
        assert str(error) == "Registry snapshot is invalid."
        assert repr(error) == "InvalidRegistrySnapshotError(error_code='registry_snapshot_invalid')"
        assert error.args == ("Registry snapshot is invalid.",)
        assert r"C:\Users\Paul\secret.mov" not in repr(vars(error))


def test_public_exception_error_codes_and_messages_are_stable():
    expected = {
        InvalidReconciliationRequestError: (
            "invalid_reconciliation_request",
            "Reconciliation request is invalid.",
        ),
        InvalidRegistrySnapshotError: ("registry_snapshot_invalid", "Registry snapshot is invalid."),
        UnsupportedReconciliationVersionError: (
            "unsupported_reconciliation_version",
            "Reconciliation schema version is unsupported.",
        ),
        ReconciliationLimitExceededError: ("reconciliation_limit_exceeded", "Reconciliation limit was exceeded."),
        DuplicateObservationIdError: (
            "duplicate_observation_id",
            "Reconciliation request contains duplicate observation IDs.",
        ),
        MissingObservationIdError: (
            "missing_observation_id",
            "Reconciliation request contains an observation without an ID.",
        ),
        AmbiguousEquivalentRootError: (
            "ambiguous_equivalent_root_declarations",
            "Reconciliation request contains ambiguous equivalent root declarations.",
        ),
        ReconciliationInvariantError: (
            "internal_reconciliation_invariant_violation",
            "An internal reconciliation invariant failed.",
        ),
    }

    for exception_type, (error_code, public_message) in expected.items():
        error = exception_type("ignored")
        assert error.error_code == error_code
        assert error.public_message == public_message
        assert str(error) == public_message
