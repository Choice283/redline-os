"""Sanitized exceptions for Asset Registry reconciliation planning."""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from redline_core.asset.exceptions import AssetRegistryError


_PROHIBITED_CONTEXT_MARKERS = ("path", "digest", "sql", "metadata")


def _sanitize_context(context: Mapping[str, Any] | None) -> MappingProxyType:
    """Return immutable public context without known sensitive fields."""
    safe: dict[str, Any] = {}
    for key, value in dict(context or {}).items():
        key_text = str(key)
        if any(marker in key_text.lower() for marker in _PROHIBITED_CONTEXT_MARKERS):
            safe[key_text] = "[redacted]"
            continue
        safe[key_text] = _sanitize_value(value)
    return MappingProxyType(safe)


def _sanitize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)
    if isinstance(value, list):
        return tuple(_sanitize_value(item) for item in value)
    if isinstance(value, Mapping):
        return _sanitize_context(value)
    return repr(value)


class ReconciliationError(AssetRegistryError):
    """Base class for reconciliation errors with stable public error codes."""

    error_code = "reconciliation_error"

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(message, context={})
        self.error_code = self.__class__.error_code
        self.context = _sanitize_context(context)


class InvalidReconciliationRequestError(ReconciliationError):
    """Raised when a reconciliation request is structurally invalid."""

    error_code = "invalid_reconciliation_request"


class InvalidRegistrySnapshotError(ReconciliationError):
    """Raised when a registry snapshot cannot be trusted for planning."""

    error_code = "registry_snapshot_invalid"


class UnsupportedReconciliationVersionError(InvalidReconciliationRequestError):
    """Raised when a request or snapshot version is unsupported."""

    error_code = "unsupported_reconciliation_version"


class ReconciliationLimitExceededError(InvalidReconciliationRequestError):
    """Raised when a structural reconciliation limit is exceeded."""

    error_code = "reconciliation_limit_exceeded"


class DuplicateObservationIdError(InvalidReconciliationRequestError):
    """Raised when observation identity is duplicated in one request."""

    error_code = "duplicate_observation_id"


class MissingObservationIdError(InvalidReconciliationRequestError):
    """Raised when an observation lacks stable request-local identity."""

    error_code = "missing_observation_id"


class AmbiguousEquivalentRootError(InvalidReconciliationRequestError):
    """Raised when equivalent roots declare conflicting scope facts."""

    error_code = "ambiguous_equivalent_root_declarations"


class ReconciliationInvariantError(ReconciliationError):
    """Raised when internal reconciliation state violates required invariants."""

    error_code = "internal_reconciliation_invariant_violation"
