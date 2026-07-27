"""Typed exceptions for the Persistent Asset Registry domain."""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


class AssetRegistryError(Exception):
    """Base class for asset registry errors with optional safe context."""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = MappingProxyType(dict(context or {}))


class AssetDeclarationError(AssetRegistryError):
    """Raised when an asset declaration is malformed or unsafe."""


class InvalidAssetIdError(AssetDeclarationError):
    """Raised when an asset ID is missing, blank, or whitespace-mutated."""


class DuplicateAssetIdError(AssetDeclarationError):
    """Raised when a desired declaration set contains the same asset ID twice."""


class UnsafeAssetPathError(AssetDeclarationError):
    """Raised when a declared asset path is absolute, traversing, or outside the approved root."""


class AssetNotFoundError(AssetRegistryError):
    """Raised when a requested asset registry record does not exist."""


class AssetConflictError(AssetRegistryError):
    """Raised when registry state conflicts with a requested operation."""


class AssetPathConflictError(AssetConflictError):
    """Raised when multiple assets conflict on the same normalized resolved path."""


class StaleReconciliationPlanError(AssetConflictError):
    """Raised when a reconciliation plan no longer matches current registry context."""


class AssetLifecycleError(AssetRegistryError):
    """Raised when lifecycle, availability, and verification state are inconsistent."""


class AssetFilesystemError(AssetRegistryError):
    """Raised when the filesystem cannot be inspected due to an infrastructure failure."""


class AssetPersistenceError(AssetRegistryError):
    """Raised when durable asset registry storage fails."""
