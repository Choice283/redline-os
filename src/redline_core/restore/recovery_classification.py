"""Read-only source classification (Mission 1B-A2-1).

Classifies the live database and the live required-configuration source
independently, each as ``HEALTHY``/``DEGRADED``/``MISSING`` plus an
orthogonal ``RECOVERY_BLOCKED``/``RECOVERABLE``/``NOT_APPLICABLE``
feasibility (``redline_core.restore.recovery_models``). Every check here is
a **direct, read-only probe of the live source** -- never an attempt to
call ``BackupManager.create_backup()`` and infer source health from which
exception it raises. That distinction matters: ``create_backup()`` can also
fail for reasons that have nothing to do with source health (backup-root
misconfiguration, destination disk exhaustion, publish/manifest failure --
see ``redline_core.backup.exceptions``), and a healthy source must never be
reclassified as degraded merely because backup infrastructure is broken.

``HEALTHY`` is defined exactly as the source-side prerequisites of Mission
1A's own, unmodified ``create_backup()`` contract -- not broadened. In
particular: config file *content* validity (parseable YAML, a valid
``RedlineConfig`` schema) is deliberately **not** a HEALTHY requirement,
because ``create_backup()`` itself never parses or schema-validates config
content (only ``require_safe_regular_file()`` -- existence, regular file,
not a symlink); it copies whatever bytes are there. What IS a HEALTHY
requirement -- because ``create_backup()``'s own copy step depends on it --
is that each required file's bytes can actually be read/streamed safely
and stably, which is why config classification reuses
``redline_core.fsutil.hash_stable_file()`` (the exact same read primitive
Mission 1A's own config-copy path uses internally) as a read/copy
satisfiability probe, never a YAML parse.

For the database, HEALTHY additionally requires the live file to open as
SQLite and pass ``PRAGMA integrity_check`` -- because Mission 1A's own
``build_staged_backup()`` calls ``require_integrity_ok()`` (not the
non-raising ``run_integrity_check()``) against the snapshot, and therefore
already fails closed on this exact condition today; it is not new scope,
only a direct, non-mutating re-derivation of an already-locked Mission 1A
prerequisite, checked against the live source instead of a fresh snapshot.

Unsafe filesystem objects (symlink, Windows junction, other reparse point --
detected via the same domain-neutral ``redline_core.fsutil.is_unsafe_link()``
Mission 1A and 1B-A1 already use) are never followed, never opened, and
never mutated: classification reports their presence via ``os.lstat()``
metadata only and always resolves to ``RECOVERY_BLOCKED`` -- no
repository-proven safe non-following disposition exists for this case (see
``docs/BACKUP_RECOVERY_ARCHITECTURE.md`` §Mission 1B-A2 for the accepted
architecture record). A database or config path whose *parent* directory is
also absent is likewise ``RECOVERY_BLOCKED`` -- reconstructing missing
installation structure is disaster-bootstrap/provisioning work, explicitly
out of Mission 1B-A2's scope.
"""
from __future__ import annotations

import os
import sqlite3
import stat as stat_module
from pathlib import Path

from redline_core import fsutil
from redline_core.config.loader import REQUIRED_FILES
from redline_core.restore.recovery_models import RecoveryFeasibility, SourceCondition, SourceSideAssessment

_INTEGRITY_OK = "ok"

_UNSAFE_LINK_BLOCKING_REASON_TEMPLATE = (
    "{description} is a symlink, junction, or reparse point. No repository-proven safe "
    "disposition exists that moves it aside without following it or inspecting its target; "
    "Founder/manual intervention is required before any future recovery execution may proceed."
)

_WRONG_TYPE_DISPOSITION_NOTE_TEMPLATE = (
    "{description} is not the expected object type. A future, not-yet-implemented Mission "
    "1B-A2-3 recovery execution would need to move the existing object aside (a "
    "restore-ID-scoped superseded path, never deleted) before replacement could proceed. The "
    "required Windows rename semantics for this exact case are not yet repository-proven -- see "
    "the Windows disposition proof gate recorded in docs/BACKUP_RECOVERY_ARCHITECTURE.md. Mission "
    "1B-A2-1 predicts this requirement only; it performs no disposition."
)


def _read_only_uri(path: Path) -> str:
    return f"{path.as_uri()}?mode=ro"


def _missing_side_assessment(*, path: Path, description: str) -> SourceSideAssessment:
    """The expected exact path does not exist. If its parent is also
    absent, this is a structural installation-loss case (RECOVERY_BLOCKED,
    per the accepted architecture) rather than ordinary source absence."""
    if not path.parent.exists():
        return SourceSideAssessment(
            condition=SourceCondition.MISSING,
            feasibility=RecoveryFeasibility.RECOVERY_BLOCKED,
            blocking_reason=(
                f"{description} parent directory {path.parent} does not exist. Structural "
                "installation loss is out of Mission 1B-A2's scope (not disaster-bootstrap/"
                "provisioning) and requires Founder-level intervention before any future "
                "recovery execution may proceed."
            ),
            capture_required=False,
            disposition_required=False,
            disposition_description=None,
            details=(f"{description} path {path} and its parent directory are both absent.",),
        )
    return SourceSideAssessment(
        condition=SourceCondition.MISSING,
        feasibility=RecoveryFeasibility.RECOVERABLE,
        blocking_reason=None,
        capture_required=True,
        disposition_required=False,
        disposition_description=None,
        details=(f"{description} path {path} does not exist; its parent directory is present.",),
    )


def _unsafe_link_assessment(*, path: Path, description: str, extra_details: tuple[str, ...] = ()) -> SourceSideAssessment:
    return SourceSideAssessment(
        condition=SourceCondition.DEGRADED,
        feasibility=RecoveryFeasibility.RECOVERY_BLOCKED,
        blocking_reason=_UNSAFE_LINK_BLOCKING_REASON_TEMPLATE.format(description=description),
        capture_required=True,
        disposition_required=False,
        disposition_description=None,
        details=(f"{description} at {path} is an unsafe filesystem object (symlink/junction/reparse).",) + extra_details,
    )


def _cannot_inspect_assessment(*, path: Path, description: str, error: OSError) -> SourceSideAssessment:
    """``os.lstat()`` itself failed with something other than
    ``FileNotFoundError`` (e.g. permission denied). The object's type
    cannot be determined at all, so this is conservatively blocked rather
    than guessed at -- the same fail-closed bias applied to unsafe links."""
    return SourceSideAssessment(
        condition=SourceCondition.DEGRADED,
        feasibility=RecoveryFeasibility.RECOVERY_BLOCKED,
        blocking_reason=(
            f"{description} at {path} could not be inspected ({error}); its type cannot be "
            "safely determined, so classification cannot proceed without manual review."
        ),
        capture_required=True,
        disposition_required=False,
        disposition_description=None,
        details=(f"os.lstat({path}) failed: {error}",),
    )


def classify_database_source(db_path: Path) -> SourceSideAssessment:
    """Classify the live database at ``db_path``, strictly read-only.
    Never opens a write connection, never creates a journal/WAL/SHM file,
    never mutates anything. Mirrors Mission 1A's own DB-side
    ``create_backup()`` prerequisite exactly (exists, safe regular file,
    opens as SQLite, passes ``PRAGMA integrity_check``) -- it neither
    broadens nor narrows that contract."""
    db_path = Path(db_path)

    try:
        st = os.lstat(db_path)
    except FileNotFoundError:
        return _missing_side_assessment(path=db_path, description="database")
    except OSError as exc:
        return _cannot_inspect_assessment(path=db_path, description="database", error=exc)

    if fsutil.is_unsafe_link(st):
        return _unsafe_link_assessment(path=db_path, description="database path")

    if not stat_module.S_ISREG(st.st_mode):
        return SourceSideAssessment(
            condition=SourceCondition.DEGRADED,
            feasibility=RecoveryFeasibility.RECOVERABLE,
            blocking_reason=None,
            capture_required=True,
            disposition_required=True,
            disposition_description=_WRONG_TYPE_DISPOSITION_NOTE_TEMPLATE.format(description="the database path"),
            details=(f"database path {db_path} exists but is not a regular file.",),
        )

    # Safe regular file -- probe openability and integrity, strictly read-only
    # (mode=ro; a plain SELECT/PRAGMA against a non-WAL database creates no
    # -journal/-wal/-shm sidecar, matching this repository's own established
    # read-only inspection pattern in restore/schema_fingerprint.py and
    # restore/manager.py's own post-restore verification STEP 2).
    try:
        conn = sqlite3.connect(_read_only_uri(db_path), uri=True)
    except sqlite3.Error as exc:
        return SourceSideAssessment(
            condition=SourceCondition.DEGRADED,
            feasibility=RecoveryFeasibility.RECOVERABLE,
            blocking_reason=None,
            capture_required=True,
            disposition_required=False,
            disposition_description=None,
            details=(f"database file exists but could not be opened as SQLite: {exc}",),
        )

    try:
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.Error as exc:
            # Deliberately catches the broad sqlite3.Error base, not only
            # sqlite3.OperationalError -- a corrupt/non-SQLite file
            # typically raises sqlite3.DatabaseError on first real access
            # (sqlite3.connect() itself is lazy and does not validate file
            # format at open time), which is a *sibling* of
            # OperationalError, not a subclass of it.
            return SourceSideAssessment(
                condition=SourceCondition.DEGRADED,
                feasibility=RecoveryFeasibility.RECOVERABLE,
                blocking_reason=None,
                capture_required=True,
                disposition_required=False,
                disposition_description=None,
                details=(f"database file opened but PRAGMA integrity_check could not run: {exc}",),
            )
    finally:
        conn.close()

    ok = len(rows) == 1 and rows[0][0] == _INTEGRITY_OK
    if not ok:
        result_text = "; ".join(str(row[0]) for row in rows) if rows else "no result"
        return SourceSideAssessment(
            condition=SourceCondition.DEGRADED,
            feasibility=RecoveryFeasibility.RECOVERABLE,
            blocking_reason=None,
            capture_required=True,
            disposition_required=False,
            disposition_description=None,
            details=(f"PRAGMA integrity_check did not return 'ok': {result_text}",),
        )

    return SourceSideAssessment(
        condition=SourceCondition.HEALTHY,
        feasibility=RecoveryFeasibility.NOT_APPLICABLE,
        blocking_reason=None,
        capture_required=False,
        disposition_required=False,
        disposition_description=None,
        details=(),
    )


def classify_config_source(config_dir: Path) -> SourceSideAssessment:
    """Classify the live required-configuration directory at
    ``config_dir``, strictly read-only. Never opens a write handle, never
    creates or modifies anything. Config *content* validity (YAML
    parse/``RedlineConfig`` schema) is deliberately never checked -- Mission
    1A's own ``create_backup()`` never requires it either; only
    existence/safety/read-stability of each of the six required files is
    checked, via the exact same ``redline_core.fsutil.hash_stable_file()``
    primitive Mission 1A's own config-copy path already relies on."""
    config_dir = Path(config_dir)

    try:
        st = os.lstat(config_dir)
    except FileNotFoundError:
        return _missing_side_assessment(path=config_dir, description="config directory")
    except OSError as exc:
        return _cannot_inspect_assessment(path=config_dir, description="config directory", error=exc)

    if fsutil.is_unsafe_link(st):
        return _unsafe_link_assessment(path=config_dir, description="config directory path")

    if not stat_module.S_ISDIR(st.st_mode):
        return SourceSideAssessment(
            condition=SourceCondition.DEGRADED,
            feasibility=RecoveryFeasibility.RECOVERABLE,
            blocking_reason=None,
            capture_required=True,
            disposition_required=True,
            disposition_description=_WRONG_TYPE_DISPOSITION_NOTE_TEMPLATE.format(description="the config directory path"),
            details=(f"config path {config_dir} exists but is not a directory.",),
        )

    findings: list[str] = []
    any_unsafe_link = False
    any_problem = False

    for filename in sorted(REQUIRED_FILES.values()):
        file_path = config_dir / filename
        try:
            file_st = os.lstat(file_path)
        except FileNotFoundError:
            findings.append(f"required config file {filename!r} is missing.")
            any_problem = True
            continue
        except OSError as exc:
            findings.append(f"required config file {filename!r} could not be inspected: {exc}")
            any_problem = True
            continue

        if fsutil.is_unsafe_link(file_st):
            findings.append(f"required config file {filename!r} is a symlink, junction, or reparse point.")
            any_unsafe_link = True
            any_problem = True
            continue

        if not stat_module.S_ISREG(file_st.st_mode):
            findings.append(f"required config file {filename!r} exists but is not a regular file.")
            any_problem = True
            continue

        try:
            fsutil.hash_stable_file(file_path)
        except fsutil.SafeFileError as exc:
            findings.append(f"required config file {filename!r} is unreadable or unstable: {exc}")
            any_problem = True

    if any_unsafe_link:
        return SourceSideAssessment(
            condition=SourceCondition.DEGRADED,
            feasibility=RecoveryFeasibility.RECOVERY_BLOCKED,
            blocking_reason=(
                "one or more required config files is a symlink, junction, or reparse point; no "
                "repository-proven safe disposition exists that moves it aside without following "
                "it, so Founder/manual intervention is required."
            ),
            capture_required=True,
            disposition_required=False,
            disposition_description=None,
            details=tuple(findings),
        )

    if any_problem:
        return SourceSideAssessment(
            condition=SourceCondition.DEGRADED,
            feasibility=RecoveryFeasibility.RECOVERABLE,
            blocking_reason=None,
            capture_required=True,
            disposition_required=False,
            disposition_description=None,
            details=tuple(findings),
        )

    return SourceSideAssessment(
        condition=SourceCondition.HEALTHY,
        feasibility=RecoveryFeasibility.NOT_APPLICABLE,
        blocking_reason=None,
        capture_required=False,
        disposition_required=False,
        disposition_description=None,
        details=(),
    )
