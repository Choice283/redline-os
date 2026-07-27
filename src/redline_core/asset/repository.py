"""Repository contract for Persistent Asset Registry V1 persistence."""
from __future__ import annotations

import sqlite3
from typing import Iterator, Protocol

from redline_core.asset.models import AssetLifecycle, AssetRegistryRecord


class AssetRepository(Protocol):
    """Persistence-only contract for asset registry records."""

    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open a caller-owned write transaction."""
        ...

    def get_by_asset_id(
        self,
        asset_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> AssetRegistryRecord | None:
        """Return one record by external Asset ID, or None."""
        ...

    def get_by_record_id(
        self,
        record_id: int,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> AssetRegistryRecord | None:
        """Return one record by persistence ID, or None."""
        ...

    def get_by_normalized_path(
        self,
        normalized_path_key: str,
        *,
        include_deprecated: bool = False,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[AssetRegistryRecord, ...]:
        """Return records matching a normalized path key."""
        ...

    def list_records(
        self,
        *,
        include_deprecated: bool = True,
        lifecycle: AssetLifecycle | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[AssetRegistryRecord, ...]:
        """Return records in deterministic Asset ID order."""
        ...

    def count_records(
        self,
        *,
        include_deprecated: bool = True,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        """Return the count of persisted records."""
        ...

    def insert(
        self,
        record: AssetRegistryRecord,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> AssetRegistryRecord:
        """Insert a new prevalidated record and return it with its generated ID."""
        ...

    def update(
        self,
        record: AssetRegistryRecord,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> AssetRegistryRecord:
        """Persist a full prevalidated record update by immutable record ID."""
        ...
