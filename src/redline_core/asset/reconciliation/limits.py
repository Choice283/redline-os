"""Finite limit policy for Asset Registry reconciliation planning."""
from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class ReconciliationLimitPolicy:
    """Immutable finite limits applied before expensive reconciliation work."""

    max_observations_per_request: int = 10000
    max_registry_records_per_snapshot: int = 10000
    max_registry_evidence_rows: int = 30000
    max_observation_evidence_fields: int = 32
    max_identifier_length: int = 128
    max_request_id_length: int = 128
    max_observation_id_length: int = 128
    max_asset_id_length: int = 128
    max_source_id_length: int = 128
    max_scope_id_length: int = 128
    max_normalized_path_length: int = 4096
    max_safe_display_path_length: int = 512
    max_algorithm_identifier_length: int = 32
    max_digest_length: int = 256
    max_metadata_field_count: int = 64
    max_metadata_key_length: int = 64
    max_metadata_value_length: int = 512
    max_metadata_bytes_per_observation: int = 8192
    max_roots_per_scope: int = 128
    max_inaccessible_subtrees_per_root: int = 256
    max_access_failures_per_root: int = 256
    max_inclusion_filter_values: int = 256
    max_exclusion_filter_values: int = 256
    max_explicit_asset_ids: int = 10000
    max_duplicate_group_size: int = 100
    max_weak_candidates_per_observation: int = 25
    max_findings_per_item: int = 50
    max_evidence_per_item: int = 50
    max_actions_per_item: int = 10
    max_total_plan_items: int = 20000
    max_serialized_public_plan_bytes: int = 10000000

    def __post_init__(self) -> None:
        """Reject non-positive or boolean limit values."""
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field.name} must be a positive integer.")


DEFAULT_LIMITS = ReconciliationLimitPolicy()
"""Default finite limits for Phase 3 V1 reconciliation planning."""
