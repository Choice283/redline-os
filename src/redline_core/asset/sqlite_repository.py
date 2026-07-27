"""SQLite persistence for Persistent Asset Registry V1."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.resources import files
import logging
from pathlib import Path
import sqlite3
from typing import Iterator

from redline_core.asset.exceptions import (
    AssetConflictError,
    AssetNotFoundError,
    AssetPathConflictError,
    AssetPersistenceError,
    DuplicateAssetIdError,
)
from redline_core.asset.models import (
    AssetAvailability,
    AssetDiagnosticCode,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)

logger = logging.getLogger(__name__)

ASSET_REGISTRY_SCHEMA_VERSION = "1"
_SCHEMA_PACKAGE = "redline_core.asset"
_SCHEMA_RESOURCE = "schema.sql"


def initialize_asset_registry_database(database_path: str | Path) -> None:
    """Explicitly initialize or validate a V1 asset registry database."""
    db_path = _validate_database_path(database_path)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = _open_connection(db_path)
    except OSError as exc:
        raise AssetPersistenceError("Asset registry database path could not be prepared.") from exc
    except sqlite3.Error as exc:
        raise AssetPersistenceError("Asset registry database could not be opened.") from exc

    try:
        try:
            connection.execute("BEGIN")
            version = _read_schema_version(connection)
            if version is None:
                _ensure_no_partial_asset_schema(connection)
                schema_sql = _read_schema_sql()
                _execute_schema(connection, schema_sql)
            elif version != ASSET_REGISTRY_SCHEMA_VERSION:
                raise AssetPersistenceError(
                    "Unsupported asset registry schema version.",
                    context={"schema_version": version},
                )
            _validate_schema(connection)
            connection.commit()
            logger.info("Asset registry schema initialized.")
        except Exception:
            connection.rollback()
            raise
    except AssetPersistenceError:
        raise
    except sqlite3.Error as exc:
        raise AssetPersistenceError("Asset registry schema initialization failed.") from exc
    finally:
        connection.close()


class SQLiteAssetRepository:
    """SQLite implementation of the AssetRepository contract."""

    def __init__(self, database_path: str | Path, *, timeout_seconds: float = 5.0) -> None:
        self.database_path = _validate_database_path(database_path)
        self.timeout_seconds = timeout_seconds
        self._transaction_open = False

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open one write transaction. Nested transactions on this instance are rejected."""
        if self._transaction_open:
            raise AssetPersistenceError("Nested asset registry transactions are not supported.")
        self._transaction_open = True
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            try:
                connection.rollback()
            except sqlite3.Error as rollback_error:
                logger.warning("Asset registry transaction rollback failed: %s", rollback_error.__class__.__name__)
            logger.warning("Asset registry transaction rolled back.")
            raise AssetPersistenceError("Asset registry transaction failed.") from exc
        except Exception:
            try:
                connection.rollback()
            except sqlite3.Error as rollback_error:
                logger.warning("Asset registry transaction rollback failed: %s", rollback_error.__class__.__name__)
            logger.warning("Asset registry transaction rolled back.")
            raise
        finally:
            connection.close()
            self._transaction_open = False

    def get_by_asset_id(
        self,
        asset_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> AssetRegistryRecord | None:
        row = self._fetchone(
            "SELECT * FROM asset_registry WHERE asset_id = ?",
            (asset_id,),
            connection=connection,
        )
        return _row_to_record(row) if row is not None else None

    def get_by_record_id(
        self,
        record_id: int,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> AssetRegistryRecord | None:
        row = self._fetchone(
            "SELECT * FROM asset_registry WHERE record_id = ?",
            (record_id,),
            connection=connection,
        )
        return _row_to_record(row) if row is not None else None

    def get_by_normalized_path(
        self,
        normalized_path_key: str,
        *,
        include_deprecated: bool = False,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[AssetRegistryRecord, ...]:
        sql = "SELECT * FROM asset_registry WHERE normalized_resolved_path = ?"
        params: tuple[object, ...] = (normalized_path_key,)
        if not include_deprecated:
            sql += " AND lifecycle != ?"
            params = (normalized_path_key, AssetLifecycle.DEPRECATED.value)
        sql += " ORDER BY asset_id ASC"
        return self._fetchall_records(sql, params, connection=connection)

    def list_records(
        self,
        *,
        include_deprecated: bool = True,
        lifecycle: AssetLifecycle | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[AssetRegistryRecord, ...]:
        if lifecycle is not None and not isinstance(lifecycle, AssetLifecycle):
            raise AssetPersistenceError("Lifecycle filter must be an AssetLifecycle enum value.")
        sql = "SELECT * FROM asset_registry"
        clauses: list[str] = []
        params: list[object] = []
        if not include_deprecated:
            clauses.append("lifecycle != ?")
            params.append(AssetLifecycle.DEPRECATED.value)
        if lifecycle is not None:
            clauses.append("lifecycle = ?")
            params.append(lifecycle.value)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY asset_id ASC"
        return self._fetchall_records(sql, tuple(params), connection=connection)

    def count_records(
        self,
        *,
        include_deprecated: bool = True,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        sql = "SELECT COUNT(*) AS count FROM asset_registry"
        params: tuple[object, ...] = ()
        if not include_deprecated:
            sql += " WHERE lifecycle != ?"
            params = (AssetLifecycle.DEPRECATED.value,)
        row = self._fetchone(sql, params, connection=connection)
        return int(row["count"]) if row is not None else 0

    def insert(
        self,
        record: AssetRegistryRecord,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> AssetRegistryRecord:
        if record.record_id is not None:
            raise AssetPersistenceError("Inserted asset registry records must not already have a record_id.")
        if connection is None:
            with self.transaction() as owned_connection:
                return self._insert(record, owned_connection)
        return self._insert(record, connection)

    def update(
        self,
        record: AssetRegistryRecord,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> AssetRegistryRecord:
        if record.record_id is None or record.record_id <= 0:
            raise AssetPersistenceError("Updated asset registry records require a positive record_id.")
        if connection is None:
            with self.transaction() as owned_connection:
                return self._update(record, owned_connection)
        return self._update(record, connection)

    def _connect(self) -> sqlite3.Connection:
        try:
            return _open_connection(self.database_path, timeout_seconds=self.timeout_seconds)
        except sqlite3.Error as exc:
            raise AssetPersistenceError("Asset registry database could not be opened.") from exc

    def _insert(self, record: AssetRegistryRecord, connection: sqlite3.Connection) -> AssetRegistryRecord:
        params = _record_to_parameters(record)
        try:
            cursor = connection.execute(
                """
                INSERT INTO asset_registry (
                    asset_id,
                    declared_path,
                    resolved_path,
                    normalized_resolved_path,
                    approved_root_id,
                    lifecycle,
                    availability,
                    verification,
                    file_size_bytes,
                    file_modified_at,
                    last_verified_at,
                    created_at,
                    updated_at,
                    source_kind,
                    source_detail,
                    diagnostic_code,
                    diagnostic_message
                ) VALUES (
                    :asset_id,
                    :declared_path,
                    :resolved_path,
                    :normalized_resolved_path,
                    :approved_root_id,
                    :lifecycle,
                    :availability,
                    :verification,
                    :file_size_bytes,
                    :file_modified_at,
                    :last_verified_at,
                    :created_at,
                    :updated_at,
                    :source_kind,
                    :source_detail,
                    :diagnostic_code,
                    :diagnostic_message
                )
                """,
                params,
            )
        except sqlite3.IntegrityError as exc:
            raise _translate_integrity_error(exc, asset_id=record.asset_id) from exc
        except sqlite3.Error as exc:
            raise AssetPersistenceError("Asset registry insert failed.", context={"asset_id": record.asset_id}) from exc

        stored = self.get_by_record_id(int(cursor.lastrowid), connection=connection)
        if stored is None:
            raise AssetPersistenceError("Asset registry insert did not return a stored record.")
        logger.debug("Asset registry record inserted.", extra={"asset_id": stored.asset_id})
        return stored

    def _update(self, record: AssetRegistryRecord, connection: sqlite3.Connection) -> AssetRegistryRecord:
        existing = self.get_by_record_id(record.record_id, connection=connection)
        if existing is None:
            raise AssetNotFoundError("Asset registry record was not found.", context={"record_id": record.record_id})
        if existing.asset_id != record.asset_id:
            raise AssetConflictError("Asset ID cannot be changed for an existing registry record.")
        if existing.created_at != record.created_at:
            raise AssetConflictError("created_at cannot be changed for an existing registry record.")

        params = _record_to_parameters(record)
        params["record_id"] = record.record_id
        try:
            cursor = connection.execute(
                """
                UPDATE asset_registry
                SET declared_path = :declared_path,
                    resolved_path = :resolved_path,
                    normalized_resolved_path = :normalized_resolved_path,
                    approved_root_id = :approved_root_id,
                    lifecycle = :lifecycle,
                    availability = :availability,
                    verification = :verification,
                    file_size_bytes = :file_size_bytes,
                    file_modified_at = :file_modified_at,
                    last_verified_at = :last_verified_at,
                    updated_at = :updated_at,
                    source_kind = :source_kind,
                    source_detail = :source_detail,
                    diagnostic_code = :diagnostic_code,
                    diagnostic_message = :diagnostic_message
                WHERE record_id = :record_id
                  AND asset_id = :asset_id
                """,
                params,
            )
        except sqlite3.IntegrityError as exc:
            raise _translate_integrity_error(exc, asset_id=record.asset_id) from exc
        except sqlite3.Error as exc:
            raise AssetPersistenceError("Asset registry update failed.", context={"asset_id": record.asset_id}) from exc

        if cursor.rowcount != 1:
            raise AssetNotFoundError("Asset registry record was not found.", context={"record_id": record.record_id})
        stored = self.get_by_record_id(record.record_id, connection=connection)
        if stored is None:
            raise AssetPersistenceError("Asset registry update did not return a stored record.")
        logger.debug("Asset registry record updated.", extra={"asset_id": stored.asset_id})
        return stored

    def _fetchone(
        self,
        sql: str,
        params: tuple[object, ...],
        *,
        connection: sqlite3.Connection | None,
    ) -> sqlite3.Row | None:
        if connection is not None:
            try:
                return connection.execute(sql, params).fetchone()
            except sqlite3.Error as exc:
                raise AssetPersistenceError("Asset registry read failed.") from exc
        owned_connection = self._connect()
        try:
            try:
                return owned_connection.execute(sql, params).fetchone()
            except sqlite3.Error as exc:
                raise AssetPersistenceError("Asset registry read failed.") from exc
        finally:
            owned_connection.close()

    def _fetchall_records(
        self,
        sql: str,
        params: tuple[object, ...],
        *,
        connection: sqlite3.Connection | None,
    ) -> tuple[AssetRegistryRecord, ...]:
        if connection is not None:
            try:
                rows = connection.execute(sql, params).fetchall()
            except sqlite3.Error as exc:
                raise AssetPersistenceError("Asset registry read failed.") from exc
            return tuple(_row_to_record(row) for row in rows)
        owned_connection = self._connect()
        try:
            try:
                rows = owned_connection.execute(sql, params).fetchall()
            except sqlite3.Error as exc:
                raise AssetPersistenceError("Asset registry read failed.") from exc
            return tuple(_row_to_record(row) for row in rows)
        finally:
            owned_connection.close()


def _validate_database_path(database_path: str | Path) -> Path:
    if not isinstance(database_path, (str, Path)):
        raise AssetPersistenceError("Asset registry database path must be a filesystem path.")
    path = Path(database_path)
    if not str(path).strip():
        raise AssetPersistenceError("Asset registry database path must not be empty.")
    if path.exists() and path.is_dir():
        raise AssetPersistenceError("Asset registry database path must not be a directory.")
    return path


def _open_connection(database_path: Path, *, timeout_seconds: float = 5.0) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, timeout=timeout_seconds)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    busy_timeout_ms = max(1, int(timeout_seconds * 1000))
    connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    return connection


def _read_schema_version(connection: sqlite3.Connection) -> str | None:
    metadata_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'asset_registry_schema_metadata'"
    ).fetchone()
    if metadata_exists is None:
        return None
    row = connection.execute(
        "SELECT value FROM asset_registry_schema_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        raise AssetPersistenceError("Asset registry schema version is missing.")
    version = row["value"]
    if not isinstance(version, str) or version != version.strip() or not version:
        raise AssetPersistenceError("Asset registry schema version is malformed.")
    return version


def _ensure_no_partial_asset_schema(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE name LIKE 'asset_registry%'
        ORDER BY name
        """
    ).fetchall()
    if rows:
        raise AssetPersistenceError("Partial asset registry schema exists without a valid schema version.")


def _validate_schema(connection: sqlite3.Connection) -> None:
    _validate_table_definition(
        connection,
        table_name="asset_registry_schema_metadata",
        expected_columns=(
            _ColumnSpec("key", "TEXT", not_null=False, primary_key_position=1),
            _ColumnSpec("value", "TEXT", not_null=True, primary_key_position=0),
        ),
    )
    _validate_table_definition(
        connection,
        table_name="asset_registry",
        expected_columns=(
            _ColumnSpec("record_id", "INTEGER", not_null=False, primary_key_position=1),
            _ColumnSpec("asset_id", "TEXT", not_null=True, primary_key_position=0),
            _ColumnSpec("declared_path", "TEXT", not_null=True, primary_key_position=0),
            _ColumnSpec("resolved_path", "TEXT", not_null=False, primary_key_position=0),
            _ColumnSpec("normalized_resolved_path", "TEXT", not_null=False, primary_key_position=0),
            _ColumnSpec("approved_root_id", "TEXT", not_null=True, primary_key_position=0),
            _ColumnSpec("lifecycle", "TEXT", not_null=True, primary_key_position=0),
            _ColumnSpec("availability", "TEXT", not_null=True, primary_key_position=0),
            _ColumnSpec("verification", "TEXT", not_null=True, primary_key_position=0),
            _ColumnSpec("file_size_bytes", "INTEGER", not_null=False, primary_key_position=0),
            _ColumnSpec("file_modified_at", "TEXT", not_null=False, primary_key_position=0),
            _ColumnSpec("last_verified_at", "TEXT", not_null=False, primary_key_position=0),
            _ColumnSpec("created_at", "TEXT", not_null=True, primary_key_position=0),
            _ColumnSpec("updated_at", "TEXT", not_null=True, primary_key_position=0),
            _ColumnSpec("source_kind", "TEXT", not_null=True, primary_key_position=0),
            _ColumnSpec("source_detail", "TEXT", not_null=False, primary_key_position=0),
            _ColumnSpec("diagnostic_code", "TEXT", not_null=False, primary_key_position=0),
            _ColumnSpec("diagnostic_message", "TEXT", not_null=False, primary_key_position=0),
        ),
    )
    _validate_schema_version_row(connection)
    _validate_unique_index(connection, "asset_registry", ("asset_id",), partial=False)
    _validate_named_index(connection, "idx_asset_registry_lifecycle", ("lifecycle",), unique=False, partial=False)
    _validate_named_index(connection, "idx_asset_registry_availability", ("availability",), unique=False, partial=False)
    _validate_named_index(
        connection,
        "idx_asset_registry_last_verified_at",
        ("last_verified_at",),
        unique=False,
        partial=False,
    )
    _validate_named_index(
        connection,
        "idx_asset_registry_approved_root_id",
        ("approved_root_id",),
        unique=False,
        partial=False,
    )
    _validate_named_index(
        connection,
        "uq_asset_registry_non_deprecated_normalized_path",
        ("normalized_resolved_path",),
        unique=True,
        partial=True,
    )
    _validate_partial_normalized_path_predicate(connection)
    _validate_schema_sql_constraints(connection)


class _ColumnSpec:
    def __init__(
        self,
        name: str,
        declared_type: str,
        *,
        not_null: bool,
        primary_key_position: int,
        default_value: str | None = None,
    ) -> None:
        self.name = name
        self.declared_type = declared_type
        self.not_null = not_null
        self.primary_key_position = primary_key_position
        self.default_value = default_value


def _read_schema_sql() -> str:
    try:
        schema_resource = files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_RESOURCE)
        if not schema_resource.is_file():
            raise AssetPersistenceError("Asset registry schema resource is not a readable file.")
        return schema_resource.read_text(encoding="utf-8")
    except AssetPersistenceError:
        raise
    except Exception as exc:
        raise AssetPersistenceError("Asset registry schema resource could not be read.") from exc


def _validate_table_definition(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    expected_columns: tuple[_ColumnSpec, ...],
) -> None:
    table = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if table is None:
        raise AssetPersistenceError("Asset registry schema table is missing.", context={"table": table_name})

    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    if len(columns) != len(expected_columns):
        raise AssetPersistenceError("Asset registry schema column count does not match V1.", context={"table": table_name})

    for position, (column, expected) in enumerate(zip(columns, expected_columns), start=1):
        if column["cid"] != position - 1 or column["name"] != expected.name:
            raise AssetPersistenceError("Asset registry schema columns do not match V1.", context={"table": table_name})
        if _normalize_type(column["type"]) != expected.declared_type:
            raise AssetPersistenceError("Asset registry schema column type does not match V1.", context={"table": table_name})
        if bool(column["notnull"]) != expected.not_null:
            raise AssetPersistenceError(
                "Asset registry schema column nullability does not match V1.",
                context={"table": table_name, "column": expected.name},
            )
        if int(column["pk"]) != expected.primary_key_position:
            raise AssetPersistenceError(
                "Asset registry schema primary key does not match V1.",
                context={"table": table_name, "column": expected.name},
            )
        if column["dflt_value"] != expected.default_value:
            raise AssetPersistenceError(
                "Asset registry schema column default does not match V1.",
                context={"table": table_name, "column": expected.name},
            )


def _validate_schema_version_row(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT value FROM asset_registry_schema_metadata WHERE key = 'schema_version'"
    ).fetchall()
    if len(rows) != 1:
        raise AssetPersistenceError("Asset registry schema version row is invalid.")
    if rows[0]["value"] != ASSET_REGISTRY_SCHEMA_VERSION:
        raise AssetPersistenceError(
            "Unsupported asset registry schema version.",
            context={"schema_version": rows[0]["value"]},
        )


def _validate_unique_index(
    connection: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
    *,
    partial: bool,
) -> None:
    indexes = _index_list(connection, table_name)
    for index in indexes:
        if bool(index["unique"]) and bool(index["partial"]) is partial:
            if _index_columns(connection, index["name"]) == columns:
                return
    raise AssetPersistenceError("Asset registry schema unique constraint is missing.")


def _validate_named_index(
    connection: sqlite3.Connection,
    index_name: str,
    columns: tuple[str, ...],
    *,
    unique: bool,
    partial: bool,
) -> None:
    indexes = {row["name"]: row for row in _index_list(connection, "asset_registry")}
    index = indexes.get(index_name)
    if index is None:
        raise AssetPersistenceError("Asset registry schema index is missing.", context={"index": index_name})
    if bool(index["unique"]) != unique:
        raise AssetPersistenceError("Asset registry schema index uniqueness does not match V1.", context={"index": index_name})
    if bool(index["partial"]) != partial:
        raise AssetPersistenceError("Asset registry schema index predicate does not match V1.", context={"index": index_name})
    if _index_columns(connection, index_name) != columns:
        raise AssetPersistenceError("Asset registry schema index columns do not match V1.", context={"index": index_name})


def _validate_partial_normalized_path_predicate(connection: sqlite3.Connection) -> None:
    sql = _schema_object_sql(connection, "index", "uq_asset_registry_non_deprecated_normalized_path")
    tokens = _tokenize_sql(sql)
    try:
        where_index = tokens.index("where")
    except ValueError:
        raise AssetPersistenceError("Asset registry schema index predicate is missing.")
    predicate_tokens = tokens[where_index + 1 :]
    if not _is_approved_normalized_path_predicate(predicate_tokens):
        raise AssetPersistenceError("Asset registry schema index predicate does not match V1.")


def _is_approved_normalized_path_predicate(tokens: tuple[str, ...]) -> bool:
    predicate_tokens = _strip_outer_parentheses(tokens)
    terms = _split_top_level_and(predicate_tokens)
    if terms is None or len(terms) != 2:
        return False
    canonical_terms = {_canonical_normalized_path_predicate_term(term) for term in terms}
    return canonical_terms == {"non_deprecated_lifecycle", "non_null_normalized_path"}


def _split_top_level_and(tokens: tuple[str, ...]) -> list[tuple[str, ...]] | None:
    terms: list[tuple[str, ...]] = []
    start = 0
    depth = 0
    for index, token in enumerate(tokens):
        if token == "(":
            depth += 1
            continue
        if token == ")":
            depth -= 1
            if depth < 0:
                return None
            continue
        if depth == 0 and token == "or":
            return None
        if depth == 0 and token == "and":
            terms.append(tokens[start:index])
            start = index + 1
    if depth != 0:
        return None
    terms.append(tokens[start:])
    return terms


def _canonical_normalized_path_predicate_term(tokens: tuple[str, ...]) -> str | None:
    term = _strip_outer_parentheses(tokens)
    if term == ("normalized_resolved_path", "is", "not", "null"):
        return "non_null_normalized_path"
    if len(term) == 3 and term[0] == "lifecycle" and term[1] in {"!=", "<>"} and term[2] == "'deprecated'":
        return "non_deprecated_lifecycle"
    return None


def _strip_outer_parentheses(tokens: tuple[str, ...]) -> tuple[str, ...]:
    stripped = tuple(token for token in tokens if token)
    while len(stripped) >= 2 and stripped[0] == "(" and stripped[-1] == ")":
        depth = 0
        wraps_entire_expression = True
        for index, token in enumerate(stripped):
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                if depth < 0:
                    return stripped
                if depth == 0 and index != len(stripped) - 1:
                    wraps_entire_expression = False
                    break
        if not wraps_entire_expression or depth != 0:
            return stripped
        stripped = stripped[1:-1]
    return stripped


def _tokenize_sql(sql: str) -> tuple[str, ...]:
    tokens: list[str] = []
    index = 0
    while index < len(sql):
        char = sql[index]
        if char.isspace() or char == ";":
            index += 1
            continue
        if char in "()":
            tokens.append(char)
            index += 1
            continue
        if char == "'":
            literal, index = _read_sql_single_quoted_literal(sql, index)
            tokens.append(literal)
            continue
        if char in {'"', "`"}:
            identifier, index = _read_sql_quoted_identifier(sql, index, char)
            tokens.append(identifier.lower())
            continue
        if char == "[":
            identifier, index = _read_sql_bracketed_identifier(sql, index)
            tokens.append(identifier.lower())
            continue
        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(sql) and (sql[index].isalnum() or sql[index] == "_"):
                index += 1
            tokens.append(sql[start:index].lower())
            continue
        if char in {"!", "<", ">", "="}:
            if index + 1 < len(sql) and sql[index : index + 2] in {"!=", "<>", "<=", ">="}:
                tokens.append(sql[index : index + 2])
                index += 2
            else:
                tokens.append(char)
                index += 1
            continue
        tokens.append(char)
        index += 1
    return tuple(tokens)


def _read_sql_single_quoted_literal(sql: str, start: int) -> tuple[str, int]:
    index = start + 1
    value: list[str] = []
    while index < len(sql):
        char = sql[index]
        if char == "'":
            if index + 1 < len(sql) and sql[index + 1] == "'":
                value.append("'")
                index += 2
                continue
            return f"'{''.join(value)}'", index + 1
        value.append(char)
        index += 1
    return "", len(sql)


def _read_sql_quoted_identifier(sql: str, start: int, quote: str) -> tuple[str, int]:
    index = start + 1
    value: list[str] = []
    while index < len(sql):
        char = sql[index]
        if char == quote:
            if index + 1 < len(sql) and sql[index + 1] == quote:
                value.append(quote)
                index += 2
                continue
            return "".join(value), index + 1
        value.append(char)
        index += 1
    return "", len(sql)


def _read_sql_bracketed_identifier(sql: str, start: int) -> tuple[str, int]:
    index = start + 1
    value: list[str] = []
    while index < len(sql):
        char = sql[index]
        if char == "]":
            return "".join(value), index + 1
        value.append(char)
        index += 1
    return "", len(sql)


def _validate_schema_sql_constraints(connection: sqlite3.Connection) -> None:
    sql = _normalize_sql(_schema_object_sql(connection, "table", "asset_registry"))
    required_fragments = (
        "lifecycle text not null check (lifecycle in ('declared', 'active', 'deprecated'))",
        "availability text not null check (availability in ('unknown', 'available', 'missing', 'non_file'))",
        "verification text not null check (verification in ('unverified', 'verified', 'failed'))",
        "source_kind text not null check (source_kind in ('config_reconciliation'))",
        "diagnostic_code text check ( diagnostic_code is null or diagnostic_code in ( 'file_available', 'file_missing', 'path_is_not_file', 'filesystem_access_failed', 'asset_deprecated' ) )",
        "file_size_bytes integer check (file_size_bytes is null or file_size_bytes >= 0)",
    )
    if not all(fragment in sql for fragment in required_fragments):
        raise AssetPersistenceError("Asset registry schema CHECK constraints do not match V1.")


def _index_list(connection: sqlite3.Connection, table_name: str) -> tuple[sqlite3.Row, ...]:
    return tuple(connection.execute(f"PRAGMA index_list({table_name})").fetchall())


def _index_columns(connection: sqlite3.Connection, index_name: str) -> tuple[str, ...]:
    return tuple(row["name"] for row in connection.execute(f"PRAGMA index_info({index_name})").fetchall())


def _schema_object_sql(connection: sqlite3.Connection, object_type: str, name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
        (object_type, name),
    ).fetchone()
    if row is None or not isinstance(row["sql"], str):
        raise AssetPersistenceError("Asset registry schema object definition is missing.", context={"object": name})
    return row["sql"]


def _normalize_type(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.replace("\r", " ").replace("\n", " ").replace("\t", " ").lower().split())


def _execute_schema(connection: sqlite3.Connection, schema_sql: str) -> None:
    for statement in schema_sql.split(";"):
        sql = statement.strip()
        if sql:
            connection.execute(sql)


def _record_to_parameters(record: AssetRegistryRecord) -> dict[str, object]:
    return {
        "asset_id": record.asset_id,
        "declared_path": record.declared_path,
        "resolved_path": record.resolved_path,
        "normalized_resolved_path": record.normalized_resolved_path,
        "approved_root_id": record.approved_root_id,
        "lifecycle": record.lifecycle.value,
        "availability": record.availability.value,
        "verification": record.verification.value,
        "file_size_bytes": record.file_size_bytes,
        "file_modified_at": _serialize_datetime(record.file_modified_at),
        "last_verified_at": _serialize_datetime(record.last_verified_at),
        "created_at": _serialize_datetime(record.created_at),
        "updated_at": _serialize_datetime(record.updated_at),
        "source_kind": record.source_kind.value,
        "source_detail": record.source_detail,
        "diagnostic_code": record.diagnostic_code.value if record.diagnostic_code is not None else None,
        "diagnostic_message": record.diagnostic_message,
    }


def _row_to_record(row: sqlite3.Row) -> AssetRegistryRecord:
    try:
        return AssetRegistryRecord(
            record_id=row["record_id"],
            asset_id=row["asset_id"],
            declared_path=row["declared_path"],
            resolved_path=row["resolved_path"],
            normalized_resolved_path=row["normalized_resolved_path"],
            approved_root_id=row["approved_root_id"],
            lifecycle=AssetLifecycle(row["lifecycle"]),
            availability=AssetAvailability(row["availability"]),
            verification=AssetVerificationState(row["verification"]),
            file_size_bytes=row["file_size_bytes"],
            file_modified_at=_parse_datetime(row["file_modified_at"], "file_modified_at"),
            last_verified_at=_parse_datetime(row["last_verified_at"], "last_verified_at"),
            created_at=_parse_required_datetime(row["created_at"], "created_at"),
            updated_at=_parse_required_datetime(row["updated_at"], "updated_at"),
            source_kind=AssetSourceKind(row["source_kind"]),
            source_detail=row["source_detail"],
            diagnostic_code=(
                AssetDiagnosticCode(row["diagnostic_code"]) if row["diagnostic_code"] is not None else None
            ),
            diagnostic_message=row["diagnostic_message"],
        )
    except Exception as exc:
        if isinstance(exc, AssetPersistenceError):
            raise
        raise AssetPersistenceError("Asset registry row could not be mapped to a domain record.") from exc


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise AssetPersistenceError("Asset registry timestamps must be timezone-aware.")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise AssetPersistenceError("Asset registry timestamps must be UTC.")
    return value.isoformat()


def _parse_required_datetime(value: object, field_name: str) -> datetime:
    parsed = _parse_datetime(value, field_name)
    if parsed is None:
        raise AssetPersistenceError("Asset registry required timestamp is missing.", context={"field": field_name})
    return parsed


def _parse_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AssetPersistenceError("Asset registry timestamp is not text.", context={"field": field_name})
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AssetPersistenceError("Asset registry timestamp is malformed.", context={"field": field_name}) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AssetPersistenceError("Asset registry timestamp must be timezone-aware.", context={"field": field_name})
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AssetPersistenceError("Asset registry timestamp must be UTC.", context={"field": field_name})
    return parsed


def _translate_integrity_error(exc: sqlite3.IntegrityError, *, asset_id: str) -> AssetPersistenceError:
    message = str(exc)
    if "asset_registry.asset_id" in message:
        return DuplicateAssetIdError("Asset ID already exists in the asset registry.", context={"asset_id": asset_id})
    if "normalized_resolved_path" in message:
        return AssetPathConflictError("Normalized asset path already exists in the asset registry.")
    return AssetPersistenceError("Asset registry constraint failed.", context={"asset_id": asset_id})
