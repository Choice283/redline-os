"""Tests for reconciliation finite limit policy."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from redline_core.asset.reconciliation.limits import DEFAULT_LIMITS, ReconciliationLimitPolicy


def test_default_limits_match_slice_one_plan_values():
    assert DEFAULT_LIMITS.max_observations_per_request == 10000
    assert DEFAULT_LIMITS.max_registry_records_per_snapshot == 10000
    assert DEFAULT_LIMITS.max_registry_evidence_rows == 30000
    assert DEFAULT_LIMITS.max_observation_evidence_fields == 32
    assert DEFAULT_LIMITS.max_identifier_length == 128
    assert DEFAULT_LIMITS.max_normalized_path_length == 4096
    assert DEFAULT_LIMITS.max_weak_candidates_per_observation == 25
    assert DEFAULT_LIMITS.max_total_plan_items == 20000
    assert DEFAULT_LIMITS.max_serialized_public_plan_bytes == 10000000


def test_all_default_limits_are_finite_positive_integers():
    for field in fields(DEFAULT_LIMITS):
        value = getattr(DEFAULT_LIMITS, field.name)
        assert isinstance(value, int)
        assert not isinstance(value, bool)
        assert value > 0


@pytest.mark.parametrize("value", [0, -1, True, "100"])
def test_limit_policy_rejects_non_positive_or_non_integer_values(value):
    with pytest.raises(ValueError, match="max_observations_per_request"):
        ReconciliationLimitPolicy(max_observations_per_request=value)  # type: ignore[arg-type]


def test_limit_policy_is_frozen():
    with pytest.raises(FrozenInstanceError):
        DEFAULT_LIMITS.max_observations_per_request = 1  # type: ignore[misc]
