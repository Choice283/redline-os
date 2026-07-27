"""Asset Manager — verifies approved assets exist before an episode needs them.

Redline OS does not create, approve, or name assets. Asset IDs (RLG-001,
etc.) and what they represent are owned by the Redline Universe project.
This module only checks that the *file* backing an already-approved Asset ID
is actually present on disk at paths.assets_path, per config/assets.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from redline_core.config.schema import AssetDefinition, RedlineConfig


@dataclass
class AssetVerificationResult:
    """Result of checking a set of required Asset IDs against disk."""

    found: list[AssetDefinition] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # asset_ids that are unregistered or missing on disk

    @property
    def all_present(self) -> bool:
        return not self.missing


class MissingAssetsError(Exception):
    """Raised by ensure_assets_for_episode() when required assets are missing."""


class AssetManager:
    def __init__(self, config: RedlineConfig):
        self.config = config

    def list_available_assets(self) -> list[AssetDefinition]:
        """Every asset currently registered in config/assets.yaml (not necessarily on disk)."""
        return list(self.config.assets.assets)

    def verify_assets_for_episode(self, asset_ids: list[str] | None = None) -> AssetVerificationResult:
        """Check that each required asset is both registered and present on disk.

        If `asset_ids` is omitted, uses `assets.required_for_episode` from
        config/assets.yaml. Does not raise — callers decide whether missing
        assets should block anything (see ensure_assets_for_episode below
        for the raising variant).
        """
        ids = asset_ids if asset_ids is not None else self.config.assets.required_for_episode
        assets_path = Path(self.config.paths.assets_path)

        result = AssetVerificationResult()
        for asset_id in ids:
            definition = self.config.assets.get(asset_id)
            if definition is None:
                # Not in the registry at all — nothing to check on disk.
                result.missing.append(asset_id)
                continue
            if (assets_path / definition.filename).is_file():
                result.found.append(definition)
            else:
                result.missing.append(asset_id)
        return result

    def ensure_assets_for_episode(self, asset_ids: list[str] | None = None) -> AssetVerificationResult:
        """Same as verify_assets_for_episode, but raises MissingAssetsError if anything is missing."""
        result = self.verify_assets_for_episode(asset_ids)
        if not result.all_present:
            raise MissingAssetsError(f"Missing required assets: {', '.join(result.missing)}")
        return result
