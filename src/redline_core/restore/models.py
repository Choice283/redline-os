"""Result/record/attestation dataclasses for Restore Manager (Mission 1B-A1).

Frozen and slotted, mirroring ``redline_core.backup.models``'s convention:
success is a typed, immutable value; every failure mode is a distinct
exception (see ``redline_core.restore.exceptions``), never a "success with a
false flag" shape -- except ``RestorePlanResult``, which is deliberately the
one read-only, non-raising report in this package (``backup restore-plan``
must be able to report *why* a restore would not proceed without raising).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class QuiescenceAttestations:
    """The three itemized, operator-supplied attestations required before a
    destructive restore may proceed. Each is a distinct, separately-checked
    boolean -- there is no single blanket "--yes" flag. None of these is a
    process-supervision check; Mission 1B-A1 implements no new
    process-supervision framework. The only *proved* precondition is the
    separate ``BEGIN IMMEDIATE`` quiescence probe
    (``RestoreQuiescenceFailedError``); these three are operator-asserted
    facts, trusted as attestations, not independently verified.
    """

    mcp_stopped: bool
    control_room_stopped: bool
    no_other_cli_operation: bool

    def missing(self) -> tuple[str, ...]:
        names = []
        if not self.mcp_stopped:
            names.append("mcp_stopped")
        if not self.control_room_stopped:
            names.append("control_room_stopped")
        if not self.no_other_cli_operation:
            names.append("no_other_cli_operation")
        return tuple(names)

    def all_true(self) -> bool:
        return not self.missing()


@dataclass(frozen=True, slots=True)
class RestorePlanResult:
    """The result of ``RestoreManager.restore_plan()`` -- a read-only report
    of whether a restore of ``backup_id`` would currently be able to
    proceed, and why not if it wouldn't. Never mutates anything: creates no
    pre-restore safety backup, stages nothing, replaces nothing. The
    schema-compatibility check still builds and discards a disposable
    comparison database via ``Database.init_schema()`` (never against the
    live or target database) and the quiescence check still opens and
    immediately rolls back a real probe transaction against the live
    database -- both are read-only from the live system's point of view.
    """

    backup_id: str
    target_verified: bool
    schema_compatible: bool
    quiescence_probe_passed: bool
    sidecar_check_passed: bool
    sidecars_present: tuple[str, ...]
    blocking_issues: tuple[str, ...]

    @property
    def would_proceed(self) -> bool:
        return not self.blocking_issues


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """The result of a fully completed, verified ``RestoreManager.restore()``
    call -- only ever returned after ``VERIFIED_SUCCESS`` is durably
    recorded in the restore transaction journal. Every failure mode raises
    a typed ``RestoreError`` subclass instead (see
    ``redline_core.restore.exceptions``); this type is never returned with
    a false/partial success flag."""

    restore_id: str
    backup_id: str
    pre_restore_backup_id: str
    journal_dir: Path
    database_sha256: str
    database_size_bytes: int
    config_file_count: int
    superseded_config_path: Path
    completed_at: str
