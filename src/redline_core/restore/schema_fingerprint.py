"""Full application-schema compatibility fingerprinting (Mission 1B-A1).

``Database.init_schema()`` (``redline_core.db.database``) is called ONLY
against a disposable, temporary comparison database built fresh for this
check and discarded immediately after -- never against the live database
and never against a restored/target database. The *reference* fingerprint
therefore always reflects exactly the schema the currently-installed
application code would create today; the *target* fingerprint is built by
directly and read-only inspecting a database file (a target backup's
payload, or the live database post-replacement during verification)
through ``PRAGMA``/``sqlite_master`` alone, never through ``Database``.

Comparison is exact and structural, never "close enough":

- table inventory (exact set of table names)
- column shape (``PRAGMA table_info``: cid, name, type, notnull,
  dflt_value, pk -- every field, in column order)
- index inventory (exact set of index names per table)
- index structure (``PRAGMA index_xinfo``: seqno, cid, name, desc, coll,
  key -- for every indexed column) plus uniqueness/origin/partial flags
  from ``PRAGMA index_list``
- for **explicit** indexes (``origin == 'c'``, i.e. created by a real
  ``CREATE INDEX`` statement -- which is also where a partial index's
  ``WHERE`` predicate lives, since SQLite exposes no PRAGMA for it): an
  additional whitespace-normalized ``sqlite_master.sql`` text comparison,
  which is what actually proves partial-index predicate identity.
- for **autoindexes** (``origin in ('u', 'pk')`` -- SQLite-generated,
  with no ``sqlite_master.sql`` text of their own): structural
  (``PRAGMA index_xinfo`` + uniqueness) comparison only -- there is
  nothing else to compare.
- any view or trigger present in either fingerprint fails closed
  (``RestoreUnsupportedSchemaObjectError``) rather than being silently
  ignored or partially validated -- Mission 1B-A1 does not implement
  view/trigger compatibility checking at all.
"""
from __future__ import annotations

import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from redline_core.db.database import Database
from redline_core.restore.exceptions import RestoreSchemaIncompatibleError, RestoreUnsupportedSchemaObjectError

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_sql(sql: str | None) -> str | None:
    if sql is None:
        return None
    return _WHITESPACE_RE.sub(" ", sql).strip()


@dataclass(frozen=True, slots=True)
class ColumnFingerprint:
    cid: int
    name: str
    type: str
    notnull: int
    dflt_value: object
    pk: int


@dataclass(frozen=True, slots=True)
class IndexColumnFingerprint:
    seqno: int
    cid: int
    name: str | None
    desc: int
    coll: str
    key: int


@dataclass(frozen=True, slots=True)
class IndexFingerprint:
    name: str
    unique: bool
    origin: str
    partial: bool
    columns: tuple[IndexColumnFingerprint, ...]
    normalized_sql: str | None


@dataclass(frozen=True, slots=True)
class TableFingerprint:
    name: str
    normalized_sql: str | None
    columns: tuple[ColumnFingerprint, ...]
    indexes: tuple[IndexFingerprint, ...]


@dataclass(frozen=True, slots=True)
class SchemaFingerprint:
    tables: tuple[TableFingerprint, ...]
    unsupported_objects: tuple[str, ...]


def _read_only_uri(db_path: Path) -> str:
    return f"{db_path.as_uri()}?mode=ro"


def build_schema_fingerprint(db_path: Path, *, read_only: bool) -> SchemaFingerprint:
    """Build a structural schema fingerprint of ``db_path`` by direct
    ``PRAGMA``/``sqlite_master`` inspection. Never calls
    ``Database.init_schema()`` -- see ``build_reference_schema_fingerprint()``
    for the one place that is permitted to.

    ``read_only=True`` opens strictly read-only (``mode=ro``), for a target
    backup payload (which must remain read-only) or the live/restored
    database. ``read_only=False`` is used only for the disposable
    comparison database this module itself creates and discards.
    """
    db_path = Path(db_path)
    uri = _read_only_uri(db_path) if read_only else str(db_path)
    conn = sqlite3.connect(uri, uri=read_only)
    try:
        master_rows = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()

        unsupported_objects = tuple(sorted(row[1] for row in master_rows if row[0] in ("view", "trigger")))

        table_names = sorted(
            row[1] for row in master_rows if row[0] == "table" and not row[1].startswith("sqlite_")
        )
        index_sql_by_name = {row[1]: row[3] for row in master_rows if row[0] == "index"}

        tables: list[TableFingerprint] = []
        for table_name in table_names:
            table_sql = next(
                (row[3] for row in master_rows if row[0] == "table" and row[1] == table_name), None
            )
            columns = tuple(
                ColumnFingerprint(
                    cid=row[0], name=row[1], type=row[2], notnull=row[3], dflt_value=row[4], pk=row[5]
                )
                for row in conn.execute(f"PRAGMA table_info({table_name!r})").fetchall()
            )

            indexes: list[IndexFingerprint] = []
            for idx_row in conn.execute(f"PRAGMA index_list({table_name!r})").fetchall():
                idx_name, unique, origin, partial = idx_row[1], bool(idx_row[2]), idx_row[3], bool(idx_row[4])
                idx_columns = tuple(
                    IndexColumnFingerprint(
                        seqno=r[0], cid=r[1], name=r[2], desc=r[3], coll=r[4], key=r[5]
                    )
                    for r in conn.execute(f"PRAGMA index_xinfo({idx_name!r})").fetchall()
                )
                normalized_sql = _normalize_sql(index_sql_by_name.get(idx_name)) if origin == "c" else None
                indexes.append(
                    IndexFingerprint(
                        name=idx_name,
                        unique=unique,
                        origin=origin,
                        partial=partial,
                        columns=idx_columns,
                        normalized_sql=normalized_sql,
                    )
                )
            indexes.sort(key=lambda i: i.name)

            tables.append(
                TableFingerprint(
                    name=table_name,
                    normalized_sql=_normalize_sql(table_sql),
                    columns=columns,
                    indexes=tuple(indexes),
                )
            )

        return SchemaFingerprint(tables=tuple(tables), unsupported_objects=unsupported_objects)
    finally:
        conn.close()


def build_reference_schema_fingerprint() -> SchemaFingerprint:
    """Build the reference fingerprint from a fresh, disposable database
    created by the real, current ``Database.init_schema()`` -- the one and
    only place in Mission 1B-A1 permitted to call it. The disposable
    database lives in a temporary directory that is always removed before
    this function returns, success or failure; it is never the live
    database, never a restored database, and never persisted anywhere.
    """
    with tempfile.TemporaryDirectory(prefix="redline_restore_schema_ref_") as tmp_dir:
        reference_db_path = Path(tmp_dir) / "schema_reference.db"
        db = Database(reference_db_path).connect()
        try:
            db.init_schema()
        finally:
            db.close()
        return build_schema_fingerprint(reference_db_path, read_only=True)


def _describe_index(index: IndexFingerprint) -> str:
    return f"{index.name} (unique={index.unique}, origin={index.origin!r}, partial={index.partial})"


def compare_schema_fingerprints(reference: SchemaFingerprint, target: SchemaFingerprint) -> None:
    """Raise on the first structural difference found. Raises
    ``RestoreUnsupportedSchemaObjectError`` if either fingerprint contains
    a view or trigger, before any table-level comparison is attempted.
    Raises ``RestoreSchemaIncompatibleError`` for every other mismatch:
    table inventory, column shape, index inventory, index structure, or
    (for explicit indexes only) whitespace-normalized definition text.
    """
    if reference.unsupported_objects or target.unsupported_objects:
        raise RestoreUnsupportedSchemaObjectError(
            "unsupported schema object(s) present -- Mission 1B-A1 does not implement view/trigger "
            f"compatibility checking: reference={list(reference.unsupported_objects)!r} "
            f"target={list(target.unsupported_objects)!r}"
        )

    reference_tables = {t.name: t for t in reference.tables}
    target_tables = {t.name: t for t in target.tables}
    if set(reference_tables) != set(target_tables):
        missing = sorted(set(reference_tables) - set(target_tables))
        extra = sorted(set(target_tables) - set(reference_tables))
        raise RestoreSchemaIncompatibleError(
            f"table inventory mismatch: missing from target={missing!r}, unexpected in target={extra!r}"
        )

    for name in sorted(reference_tables):
        _compare_table(reference_tables[name], target_tables[name])


def _compare_table(reference: TableFingerprint, target: TableFingerprint) -> None:
    if reference.columns != target.columns:
        raise RestoreSchemaIncompatibleError(
            f"table {reference.name!r} column shape mismatch:\n  reference={reference.columns!r}\n"
            f"  target={target.columns!r}"
        )

    reference_indexes = {i.name: i for i in reference.indexes}
    target_indexes = {i.name: i for i in target.indexes}
    if set(reference_indexes) != set(target_indexes):
        missing = sorted(set(reference_indexes) - set(target_indexes))
        extra = sorted(set(target_indexes) - set(reference_indexes))
        raise RestoreSchemaIncompatibleError(
            f"table {reference.name!r} index inventory mismatch: missing from target={missing!r}, "
            f"unexpected in target={extra!r}"
        )

    for idx_name in sorted(reference_indexes):
        ref_index = reference_indexes[idx_name]
        tgt_index = target_indexes[idx_name]
        if (
            ref_index.unique != tgt_index.unique
            or ref_index.origin != tgt_index.origin
            or ref_index.partial != tgt_index.partial
            or ref_index.columns != tgt_index.columns
        ):
            raise RestoreSchemaIncompatibleError(
                f"table {reference.name!r} index {idx_name!r} structural mismatch:\n"
                f"  reference={_describe_index(ref_index)} columns={ref_index.columns!r}\n"
                f"  target={_describe_index(tgt_index)} columns={tgt_index.columns!r}"
            )
        if ref_index.origin == "c" and ref_index.normalized_sql != tgt_index.normalized_sql:
            raise RestoreSchemaIncompatibleError(
                f"table {reference.name!r} explicit index {idx_name!r} definition mismatch "
                "(whitespace-normalized CREATE INDEX text differs -- this also covers a partial "
                "index's WHERE predicate):\n"
                f"  reference={ref_index.normalized_sql!r}\n  target={tgt_index.normalized_sql!r}"
            )


def require_schema_compatible(target_db_path: Path) -> None:
    """Build a fresh reference fingerprint (via disposable
    ``Database.init_schema()``) and compare it against ``target_db_path``
    (opened strictly read-only, never via ``Database``). Raises on any
    incompatibility; returns None on success."""
    reference = build_reference_schema_fingerprint()
    target = build_schema_fingerprint(Path(target_db_path), read_only=True)
    compare_schema_fingerprints(reference, target)
