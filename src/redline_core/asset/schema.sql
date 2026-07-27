CREATE TABLE asset_registry_schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE asset_registry (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL UNIQUE,
    declared_path TEXT NOT NULL,
    resolved_path TEXT,
    normalized_resolved_path TEXT,
    approved_root_id TEXT NOT NULL,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('declared', 'active', 'deprecated')),
    availability TEXT NOT NULL CHECK (availability IN ('unknown', 'available', 'missing', 'non_file')),
    verification TEXT NOT NULL CHECK (verification IN ('unverified', 'verified', 'failed')),
    file_size_bytes INTEGER CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
    file_modified_at TEXT,
    last_verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('config_reconciliation')),
    source_detail TEXT,
    diagnostic_code TEXT CHECK (
        diagnostic_code IS NULL
        OR diagnostic_code IN (
            'file_available',
            'file_missing',
            'path_is_not_file',
            'filesystem_access_failed',
            'asset_deprecated'
        )
    ),
    diagnostic_message TEXT
);

CREATE UNIQUE INDEX uq_asset_registry_non_deprecated_normalized_path
ON asset_registry(normalized_resolved_path)
WHERE lifecycle != 'deprecated'
  AND normalized_resolved_path IS NOT NULL;

CREATE INDEX idx_asset_registry_lifecycle
ON asset_registry(lifecycle);

CREATE INDEX idx_asset_registry_availability
ON asset_registry(availability);

CREATE INDEX idx_asset_registry_last_verified_at
ON asset_registry(last_verified_at);

CREATE INDEX idx_asset_registry_approved_root_id
ON asset_registry(approved_root_id);

INSERT INTO asset_registry_schema_metadata(key, value)
VALUES ('schema_version', '1');
