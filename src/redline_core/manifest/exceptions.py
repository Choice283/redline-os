"""Typed exceptions for Episode Manifest V1 loading and validation."""
from __future__ import annotations


class ManifestError(Exception):
    """Base class for all Episode Manifest failures."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


class ManifestLoadError(ManifestError):
    """Raised when a manifest file cannot be read."""


class ManifestParseError(ManifestError):
    """Raised when YAML syntax or document shape is invalid."""


class ManifestSchemaError(ManifestError):
    """Raised when the parsed YAML does not match the manifest schema."""


class ManifestVersionError(ManifestSchemaError):
    """Raised when the manifest schema version is missing, invalid, or unsupported."""


class ManifestValidationError(ManifestError):
    """Raised when manifest domain validation fails."""


class ManifestPathError(ManifestValidationError):
    """Raised when manifest media paths fail safety or filesystem validation."""
