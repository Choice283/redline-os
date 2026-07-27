"""Tests for the AssetRepository persistence contract shape."""
from __future__ import annotations

from typing import get_type_hints

from redline_core.asset.repository import AssetRepository


def test_asset_repository_contract_exposes_persistence_only_methods():
    expected = {
        "transaction",
        "get_by_asset_id",
        "get_by_record_id",
        "get_by_normalized_path",
        "list_records",
        "count_records",
        "insert",
        "update",
    }

    public_methods = {name for name in AssetRepository.__dict__ if not name.startswith("_")}

    assert expected.issubset(public_methods)
    assert "delete" not in public_methods
    assert "register_asset" not in public_methods
    assert "plan_reconciliation" not in public_methods
    assert "apply_reconciliation" not in public_methods


def test_asset_repository_contract_returns_immutable_collection_types():
    hints = get_type_hints(AssetRepository.list_records)

    assert "tuple" in str(hints["return"])
