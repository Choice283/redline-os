"""Tests for reconciliation tagged subject models."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from redline_core.asset.reconciliation.enums import ConflictKind
from redline_core.asset.reconciliation.subjects import (
    MixedConflictSubject,
    ObservationGroupSubject,
    ObservationSubject,
    RegistryRecordGroupSubject,
    RegistryRecordSubject,
)


def test_registry_record_subject_is_frozen_and_has_canonical_key():
    subject = RegistryRecordSubject(asset_id="RLG-001", record_id=1)

    assert subject.canonical_key() == ("registry_record", "RLG-001")
    with pytest.raises(FrozenInstanceError):
        subject.asset_id = "RLG-002"  # type: ignore[misc]


def test_observation_subject_requires_clean_identifier():
    assert ObservationSubject("obs-1").canonical_key() == ("observation", "obs-1")

    with pytest.raises(ValueError):
        ObservationSubject(" obs-1")


def test_group_subjects_sort_and_freeze_identifiers():
    registry_group = RegistryRecordGroupSubject(("RLG-002", "RLG-001"))
    observation_group = ObservationGroupSubject(("obs-2", "obs-1"))

    assert registry_group.asset_ids == ("RLG-001", "RLG-002")
    assert registry_group.canonical_key() == ("registry_record_group", ("RLG-001", "RLG-002"))
    assert observation_group.observation_ids == ("obs-1", "obs-2")
    assert observation_group.canonical_key() == ("observation_group", ("obs-1", "obs-2"))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: RegistryRecordGroupSubject(()),
        lambda: RegistryRecordGroupSubject(("RLG-001", "RLG-001")),
        lambda: ObservationGroupSubject(()),
        lambda: ObservationGroupSubject(("obs-1", "obs-1")),
    ],
)
def test_group_subjects_reject_empty_or_duplicate_identifiers(factory):
    with pytest.raises(ValueError):
        factory()


def test_mixed_conflict_subject_requires_both_identifier_sets_and_conflict_kind():
    subject = MixedConflictSubject(
        asset_ids=("RLG-002", "RLG-001"),
        observation_ids=("obs-2", "obs-1"),
        conflict_kind=ConflictKind.MIXED_IDENTITY_COLLISION,
    )

    assert subject.asset_ids == ("RLG-001", "RLG-002")
    assert subject.observation_ids == ("obs-1", "obs-2")
    assert subject.canonical_key() == (
        "mixed_conflict",
        "mixed_identity_collision",
        ("RLG-001", "RLG-002"),
        ("obs-1", "obs-2"),
    )

    with pytest.raises(ValueError):
        MixedConflictSubject(("RLG-001",), ("obs-1",), "mixed_identity_collision")  # type: ignore[arg-type]
