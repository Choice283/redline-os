"""Sanitized exceptions for Asset Registry reconciliation planning."""
from __future__ import annotations

from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping

from redline_core.asset.exceptions import AssetRegistryError


_PUBLIC_CONTEXT_KEYS = {
    "asset_id",
    "count",
    "field_name",
    "index",
    "limit_name",
    "limit_value",
    "observation_id",
    "reason_code",
    "registry_id",
    "request_id",
    "schema_version",
    "scope_id",
    "source_id",
    "snapshot_id",
}
_PUBLIC_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_REDACTED_VALUE = "<redacted>"


def _sanitize_context(context: Mapping[str, Any] | None) -> MappingProxyType:
    """Return deterministic immutable context containing only safe public values."""
    safe: dict[str, str | int | bool | None] = {}
    for key, value in dict(context or {}).items():
        key_text = str(key)
        if key_text not in _PUBLIC_CONTEXT_KEYS:
            continue
        safe[key_text] = _sanitize_value(value)
    return MappingProxyType(dict(sorted(safe.items())))


def _sanitize_value(value: Any) -> str | int | bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Enum):
        return _sanitize_identifier(value.value)
    if isinstance(value, str):
        return _sanitize_identifier(value)
    return _REDACTED_VALUE


def _sanitize_identifier(value: str) -> str:
    if not _PUBLIC_IDENTIFIER_PATTERN.fullmatch(value):
        return _REDACTED_VALUE
    lowered = value.lower()
    if lowered.startswith(("sk-", "bearer", "password", "token")):
        return _REDACTED_VALUE
    if lowered in {"select", "insert", "update", "delete", "drop", "pragma"}:
        return _REDACTED_VALUE
    if len(value) in {32, 40, 64, 128} and all(char in "0123456789abcdefABCDEF" for char in value):
        return _REDACTED_VALUE
    return value


class ReconciliationError(AssetRegistryError):
    """Base class for reconciliation errors with stable safe public output."""

    error_code = "reconciliation_error"
    public_message = "Reconciliation failed."

    def __init__(
        self,
        attempted_message: str | None = None,
        *,
        context: Mapping[str, Any] | None = None,
        reason_code: str | None = None,
    ) -> None:
        safe_context = dict(_sanitize_context(context))
        if reason_code is not None:
            safe_context["reason_code"] = _sanitize_value(reason_code)
        safe_context = dict(sorted(safe_context.items()))
        super().__init__(self.__class__.public_message, context=safe_context)
        self.error_code = self.__class__.error_code
        self.public_message = self.__class__.public_message
        self.context = MappingProxyType(safe_context)

    def __repr__(self) -> str:
        """Return deterministic representation without raw caller input."""
        return f"{self.__class__.__name__}(error_code={self.error_code!r})"


class InvalidReconciliationRequestError(ReconciliationError):
    """Raised when a reconciliation request is structurally invalid."""

    error_code = "invalid_reconciliation_request"
    public_message = "Reconciliation request is invalid."


class InvalidRegistrySnapshotError(ReconciliationError):
    """Raised when a registry snapshot cannot be trusted for planning."""

    error_code = "registry_snapshot_invalid"
    public_message = "Registry snapshot is invalid."


class UnsupportedReconciliationVersionError(InvalidReconciliationRequestError):
    """Raised when a request or snapshot version is unsupported."""

    error_code = "unsupported_reconciliation_version"
    public_message = "Reconciliation schema version is unsupported."


class ReconciliationLimitExceededError(InvalidReconciliationRequestError):
    """Raised when a structural reconciliation limit is exceeded."""

    error_code = "reconciliation_limit_exceeded"
    public_message = "Reconciliation limit was exceeded."


class DuplicateObservationIdError(InvalidReconciliationRequestError):
    """Raised when observation identity is duplicated in one request."""

    error_code = "duplicate_observation_id"
    public_message = "Reconciliation request contains duplicate observation IDs."


class MissingObservationIdError(InvalidReconciliationRequestError):
    """Raised when an observation lacks stable request-local identity."""

    error_code = "missing_observation_id"
    public_message = "Reconciliation request contains an observation without an ID."


class AmbiguousEquivalentRootError(InvalidReconciliationRequestError):
    """Raised when equivalent roots declare conflicting scope facts."""

    error_code = "ambiguous_equivalent_root_declarations"
    public_message = "Reconciliation request contains ambiguous equivalent root declarations."


class ReconciliationInvariantError(ReconciliationError):
    """Raised when internal reconciliation state violates required invariants."""

    error_code = "internal_reconciliation_invariant_violation"
    public_message = "An internal reconciliation invariant failed."
