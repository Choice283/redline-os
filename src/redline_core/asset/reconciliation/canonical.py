"""Canonical keys for already-normalized reconciliation facts."""
from __future__ import annotations

from datetime import datetime
import hashlib

from redline_core.asset.reconciliation.models import RegistryIdentityEvidence


OptionalTextSortKey = tuple[int, str]
RegistryEvidenceIdentityKey = tuple[str, str, OptionalTextSortKey, str, OptionalTextSortKey, str]
RegistryEvidenceLookupKey = tuple[str, OptionalTextSortKey, str, str, OptionalTextSortKey]
RegistryEvidenceRepresentativeKey = tuple[
    datetime,
    tuple[str, str, OptionalTextSortKey, str, str, OptionalTextSortKey, str],
]


def _optional_text_sort_key(value: str | None) -> OptionalTextSortKey:
    """Return a total-order key for optional text values."""

    if value is None:
        return (0, "")
    return (1, value)


def _normalize_algorithm(value: str | None) -> str | None:
    """Return the canonical algorithm token for already-validated evidence."""

    if value is None:
        return None
    return value.lower()


def _hash_sensitive(value: str) -> str:
    """Return a stable SHA-256 fingerprint for sensitive canonical values."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _registry_evidence_identity_key(evidence: RegistryIdentityEvidence) -> RegistryEvidenceIdentityKey:
    """Return the identity key that defines exact duplicate registry evidence."""

    return (
        evidence.asset_id,
        evidence.evidence_kind.value,
        _optional_text_sort_key(_normalize_algorithm(evidence.algorithm)),
        evidence.normalized_value,
        _optional_text_sort_key(evidence.scope_id),
        evidence.source_id,
    )


def _registry_evidence_representative_selection_key(
    evidence: RegistryIdentityEvidence,
) -> RegistryEvidenceRepresentativeKey:
    """Return the representative key: latest timestamp, then stable row state."""

    return (
        evidence.observed_at,
        _registry_evidence_row_tie_break_key(evidence),
    )


def _registry_evidence_row_tie_break_key(
    evidence: RegistryIdentityEvidence,
) -> tuple[str, str, OptionalTextSortKey, str, str, OptionalTextSortKey, str]:
    """Return a deterministic tie-breaker for equal-timestamp duplicate evidence."""

    return (
        evidence.asset_id,
        evidence.evidence_kind.value,
        _optional_text_sort_key(_normalize_algorithm(evidence.algorithm)),
        evidence.normalized_value,
        evidence.normalization_format,
        _optional_text_sort_key(evidence.scope_id),
        evidence.source_id,
    )


def _registry_evidence_output_sort_key(evidence: RegistryIdentityEvidence) -> RegistryEvidenceIdentityKey:
    """Return the canonical output ordering key for deduplicated registry evidence."""

    return _registry_evidence_identity_key(evidence)


def _registry_evidence_lookup_key(evidence: RegistryIdentityEvidence) -> RegistryEvidenceLookupKey:
    """Return the future comparable-evidence lookup key without building indexes."""

    return (
        evidence.evidence_kind.value,
        _optional_text_sort_key(_normalize_algorithm(evidence.algorithm)),
        evidence.normalized_value,
        evidence.normalization_format,
        _optional_text_sort_key(evidence.scope_id),
    )
