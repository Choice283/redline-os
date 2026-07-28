"""Tests for Slice 3 canonical reconciliation keys."""
from __future__ import annotations

from datetime import datetime, timezone

from redline_core.asset.reconciliation.canonical import (
    _hash_sensitive,
    _optional_text_sort_key,
    _registry_evidence_identity_key,
    _registry_evidence_lookup_key,
    _registry_evidence_output_sort_key,
    _registry_evidence_representative_selection_key,
)
from redline_core.asset.reconciliation.enums import EvidenceKind
from redline_core.asset.reconciliation.models import RegistryIdentityEvidence


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def make_evidence(
    *,
    asset_id: str = "RLG-001",
    evidence_kind: EvidenceKind = EvidenceKind.FULL_CONTENT_HASH,
    algorithm: str | None = "SHA256",
    normalized_value: str = "ABCDEF",
    normalization_format: str = "hex",
    scope_id: str | None = None,
    source_id: str = "scan-a",
    observed_at: datetime = NOW,
) -> RegistryIdentityEvidence:
    return RegistryIdentityEvidence(
        asset_id=asset_id,
        evidence_kind=evidence_kind,
        algorithm=algorithm,
        normalized_value=normalized_value,
        normalization_format=normalization_format,
        scope_id=scope_id,
        source_id=source_id,
        observed_at=observed_at,
    )


def test_registry_evidence_identity_key_canonicalizes_algorithm_and_optionals():
    evidence = make_evidence(algorithm="SHA256", scope_id=None)

    assert _registry_evidence_identity_key(evidence) == (
        "RLG-001",
        "full_content_hash",
        (1, "sha256"),
        "ABCDEF",
        (0, ""),
        "scan-a",
    )


def test_registry_evidence_identity_fields_remain_distinct():
    base = make_evidence()
    variants = (
        make_evidence(asset_id="RLG-002"),
        make_evidence(evidence_kind=EvidenceKind.METADATA, algorithm=None),
        make_evidence(algorithm="sha512"),
        make_evidence(normalized_value="123456"),
        make_evidence(scope_id="scope-a"),
        make_evidence(source_id="scan-b"),
    )

    keys = {_registry_evidence_identity_key(item) for item in (base,) + variants}

    assert len(keys) == 1 + len(variants)


def test_normalization_format_is_representative_only_not_identity():
    lower = make_evidence(normalization_format="format-a")
    upper = make_evidence(normalization_format="format-z")

    assert _registry_evidence_identity_key(lower) == _registry_evidence_identity_key(upper)
    assert _registry_evidence_representative_selection_key(upper) > _registry_evidence_representative_selection_key(lower)


def test_registry_evidence_output_sort_key_has_total_optional_order():
    evidence = (
        make_evidence(asset_id="RLG-002", algorithm=None, evidence_kind=EvidenceKind.METADATA, scope_id="scope-b"),
        make_evidence(asset_id="RLG-001", algorithm="sha512", scope_id=None),
        make_evidence(asset_id="RLG-001", algorithm=None, evidence_kind=EvidenceKind.METADATA, scope_id=None),
        make_evidence(asset_id="RLG-001", algorithm="sha256", scope_id="scope-a"),
    )

    ordered = tuple(sorted(reversed(evidence), key=_registry_evidence_output_sort_key))

    assert ordered == (
        evidence[3],
        evidence[1],
        evidence[2],
        evidence[0],
    )


def test_registry_evidence_lookup_key_includes_normalization_format():
    first = make_evidence(normalization_format="hex")
    second = make_evidence(normalization_format="base64")

    assert _registry_evidence_identity_key(first) == _registry_evidence_identity_key(second)
    assert _registry_evidence_lookup_key(first) != _registry_evidence_lookup_key(second)


def test_optional_text_key_sorts_without_comparing_none_to_strings():
    ordered = tuple(sorted(("b", None, "a"), key=_optional_text_sort_key))

    assert ordered == (None, "a", "b")


def test_hash_sensitive_is_stable_sha256_without_raw_value():
    fingerprint = _hash_sensitive("sensitive registry digest")

    assert fingerprint == "19f326a08363b139c4774082122d70413d02720b942c13db1bae1ca2a3077bbc"
    assert "sensitive" not in fingerprint
