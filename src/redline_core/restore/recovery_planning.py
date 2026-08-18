"""Read-only recovery-planning orchestration (Mission 1B-A2-1).

Combines target-backup verification/schema-compatibility (built from
Mission 1B-A1's own public primitives directly -- ``BackupManager.
verify_backup()``, ``redline_core.restore.schema_fingerprint``'s public
functions -- never duplicated destructively, never routed through
``RestoreManager`` itself) with the new, independent live-source
classification (``recovery_classification.py``) to answer whether a future,
not-yet-implemented Mission 1B-A2 recovery execution would be
architecturally eligible to proceed for one explicitly selected
``backup_id``.

Deliberately does **not** call ``RestoreManager.restore_plan()``: that
method unconditionally calls ``redline_core.restore.quiescence.
probe_quiescence()`` against the live database, and ``quiescence.py``'s own
``except sqlite3.OperationalError`` clause around ``BEGIN IMMEDIATE`` does
not catch ``sqlite3.DatabaseError`` -- the exception SQLite actually raises
against a corrupt or non-SQLite file on first real access (``sqlite3.
connect()`` itself is lazy and does not validate file format at open time).
Calling it against a database already known to be degraded would risk an
uncaught exception propagating out of a command that is supposed to be
purely observational. This is recorded as an out-of-scope observation for a
possible future Mission 1B-A1 hardening pass -- Mission 1B-A1 is locked and
is not modified by this mission. Instead, this module calls
``probe_quiescence()`` itself, but only when the database has already been
classified ``HEALTHY`` or ``MISSING`` (the two cases already known safe by
Mission 1B-A1's own design and test coverage); for a ``DEGRADED`` database
it substitutes a descriptive, non-probing message instead.

Creates nothing, mutates nothing, journals nothing. See
``build_recovery_plan()``'s own docstring for the exact read-only guarantee.
"""
from __future__ import annotations

import json
from pathlib import Path

from redline_core.backup.exceptions import BackupError
from redline_core.backup.manager import BackupManager
from redline_core.backup.package import MANIFEST_FILENAME
from redline_core.backup.paths import validate_backup_id
from redline_core.restore.exceptions import RestoreError, RestoreQuiescenceFailedError
from redline_core.restore.quiescence import probe_quiescence
from redline_core.restore.recovery_classification import classify_config_source, classify_database_source
from redline_core.restore.recovery_models import RecoveryFeasibility, RecoveryPlanResult, SourceCondition
from redline_core.restore.schema_fingerprint import (
    build_reference_schema_fingerprint,
    build_schema_fingerprint,
    compare_schema_fingerprints,
)
from redline_core.restore.sidecar import find_present_sidecars


def _load_manifest(package_dir: Path) -> dict:
    """Re-read a sealed backup package's manifest JSON. Only ever called
    immediately after ``BackupManager.verify_backup()`` has already
    independently re-proven that manifest's sidecar hash and payload
    content -- data extraction from an already-trusted manifest, not a new
    trust decision (mirrors ``redline_core.restore.manager``'s own private
    helper of the same shape and purpose; duplicated here rather than
    imported so this new, read-only planning module has no dependency on
    another module's private implementation detail)."""
    return json.loads((package_dir / MANIFEST_FILENAME).read_bytes())


def _describe_quiescence_implication(db_condition: SourceCondition, db_path: Path) -> str:
    """Describe what is knowable about live-database quiescence, strictly
    read-only, without ever calling ``probe_quiescence()`` against a
    database already classified ``DEGRADED`` -- see this module's own
    docstring for exactly why."""
    if db_condition is SourceCondition.DEGRADED:
        return (
            "not determinable: the database source is degraded, so a BEGIN IMMEDIATE quiescence "
            "probe cannot be reliably run against it; quiescence proof is deferred to a future, "
            "not-yet-implemented authorized recovery execution."
        )

    try:
        probe_quiescence(db_path)
    except RestoreQuiescenceFailedError as exc:
        return f"not quiescent: {exc}"

    if not Path(db_path).exists():
        return "not applicable: database does not exist."
    return "quiescent: no other connection currently holds a write lock."


def build_recovery_plan(
    *, backup_manager: BackupManager, db_path: Path, config_dir: Path, backup_id: str
) -> RecoveryPlanResult:
    """Build one read-only ``RecoveryPlanResult`` for ``backup_id`` against
    the current live ``db_path``/``config_dir``.

    Creates no backup, no degraded-source capture, no restore/recovery
    journal, no staging directory, no SQLite write connection, and performs
    no rename/replace/delete/move-aside of anything: every check here
    either reads the live source through a strictly read-only connection or
    ``os.lstat()``, or inspects an already-sealed, already-independently-
    verified backup package. The selected recovery source is always the
    explicit ``backup_id`` positional argument (never "latest") and must be
    a genuine sealed Mission 1A backup -- ``validate_backup_id()`` rejects
    anything not matching that exact schema by construction, which also
    structurally prevents ever accepting a future degraded-source capture
    ID (a different schema entirely) as a recovery source here.
    """
    backup_id = validate_backup_id(backup_id)
    db_path = Path(db_path)
    config_dir = Path(config_dir)

    blocking: list[str] = []

    # -- target backup side: built from the exact same public primitives
    # Mission 1B-A1's own restore_plan() uses, never duplicated destructively,
    # and completely independent of live-source health below.
    target_verified = False
    verification = None
    try:
        verification = backup_manager.verify_backup(backup_id)
        target_verified = True
    except BackupError as exc:
        blocking.append(f"target backup verification failed: {exc}")

    schema_compatible = False
    if target_verified:
        try:
            manifest = _load_manifest(verification.backup_path)
            target_db_path = verification.backup_path / manifest["database"]["relative_path"]
            reference = build_reference_schema_fingerprint()
            target = build_schema_fingerprint(target_db_path, read_only=True)
            compare_schema_fingerprints(reference, target)
            schema_compatible = True
        except (RestoreError, OSError, ValueError, KeyError) as exc:
            blocking.append(f"schema incompatible: {exc}")
    else:
        blocking.append("schema compatibility not checked: target backup did not verify")

    # -- live source classification: new, Mission 1B-A2-1, source-side only.
    # A backup-infrastructure failure above never influences this -- these two
    # calls never touch backup_manager or the target backup at all.
    database = classify_database_source(db_path)
    config = classify_config_source(config_dir)

    if database.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED:
        blocking.append(f"database recovery blocked: {database.blocking_reason}")
    if config.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED:
        blocking.append(f"config recovery blocked: {config.blocking_reason}")

    sidecars_present = tuple(str(p) for p in find_present_sidecars(db_path))
    quiescence_implication = _describe_quiescence_implication(database.condition, db_path)

    return RecoveryPlanResult(
        backup_id=backup_id,
        target_verified=target_verified,
        schema_compatible=schema_compatible,
        database=database,
        config=config,
        sidecars_present=sidecars_present,
        quiescence_implication=quiescence_implication,
        blocking_issues=tuple(blocking),
    )
