"""Recovery execution orchestration (Mission 1B-A2-3: Recovery Execution +
Journal/Evidence Integration).

``execute_recovery()`` is the one public entry point. Every attempt:

  explicit RecoveryAuthorization
  -> fresh recovery-plan validation
  -> mandatory fresh degraded-source capture (Mission 1B-A2-2)
  -> capture reverification (exact same capture_id)
  -> CHANGED_DURING_CAPTURE hard-stop check
  -> fresh source/sidecar reclassification (Mission 1B-A2-1)
  -> PRE_MUTATION_STABILITY
  -> quiescence (proved probe, or not-applicable)
  -> disposition (fixed order: database -> config -> -journal -> -wal -> -shm)
  -> FINAL_STABILITY
  -> existing sidecar pre-check (Mission 1B-A1, reused unmodified)
  -> staging/replacement (Mission 1B-A1 staging.py, reused unmodified)
  -> shared final verification (redline_core.restore.verification)
  -> terminal journal state

Every attempt builds a brand-new capture; a pre-existing capture is never
an execution input -- there is no ``--capture-id`` anywhere in this
module or its CLI surface. ``RECOVERY_BLOCKED`` is absolutely
non-overridable. No automatic retry, rollback, resume, delete fallback,
or overwrite fallback exists anywhere in this module.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from redline_core.backup.manager import BackupManager
from redline_core.backup.package import MANIFEST_FILENAME
from redline_core.backup.paths import format_utc_iso, validate_backup_id, validate_backup_root_containment
from redline_core.restore.capture_exceptions import CaptureError
from redline_core.restore.capture_manager import build_degraded_source_capture, verify_degraded_source_capture
from redline_core.restore.capture_models import CaptureItemOutcome, CaptureItemRecord, CaptureResult
from redline_core.restore.exceptions import (
    RecoveryAttestationMissingError,
    RecoveryBlockedError,
    RecoveryCaptureFailedError,
    RecoveryChangedDuringCaptureError,
    RecoveryConfirmationError,
    RecoveryDispositionFailedError,
    RecoveryStabilityMismatchError,
    RestoreError,
    RestoreQuiescenceFailedError,
)
from redline_core.restore.journal import JOURNAL_DIRNAME, RestoreJournal, RestoreState, build_restore_id
from redline_core.restore.quiescence import probe_quiescence, require_attestations
from redline_core.restore.recovery_disposition import DispositionResult, dispose_target
from redline_core.restore.recovery_models import RecoveryAuthorization, SourceCondition
from redline_core.restore.recovery_planning import build_recovery_plan
from redline_core.restore.recovery_stability import (
    ExpectedTargetState,
    TargetStabilityResult,
    check_config_inventory_stability,
    check_target_stability,
    expected_state_from_capture_record,
    expected_state_missing,
)
from redline_core.restore.sidecar import SIDECAR_SUFFIXES, require_no_sidecars
from redline_core.restore.sidecar_classification import SidecarCondition
from redline_core.restore.staging import (
    install_staged_config,
    rename_config_aside,
    replace_database,
    stage_config,
    stage_database,
    superseded_config_path,
)
from redline_core.restore.verification import verify_restore

Clock = Callable[[], datetime]

_SIDECAR_ITEM_PREFIX = "sidecar:"


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _load_manifest(package_dir: Path) -> dict:
    return json.loads((package_dir / MANIFEST_FILENAME).read_bytes())


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """The result of one fully completed, verified
    ``execute_recovery()`` call -- only ever returned after
    ``VERIFIED_SUCCESS`` is durably recorded. Every failure mode raises a
    typed exception instead; this type is never returned with a
    false/partial success flag."""

    restore_id: str
    backup_id: str
    capture_id: str
    capture_path: Path
    journal_dir: Path
    disposed_targets: tuple[str, ...]
    database_sha256: str
    database_size_bytes: int
    config_file_count: int
    superseded_config_path: Path
    completed_at: str


def require_recovery_authorization(authorization: RecoveryAuthorization, *, backup_id: str) -> None:
    """The exact four-step validation order the ratified architecture
    requires, run before any capture or live mutation is attempted:
    1. ``backup_id`` itself is a well-formed backup identifier.
    2. ``confirm_backup_id`` exactly matches ``backup_id``.
    3. The three existing itemized ``QuiescenceAttestations`` are given
       (the locked, unmodified ``quiescence.require_attestations()``).
    4. The two recovery-specific attestations are given.
    There is no blanket ``--yes`` anywhere in this taxonomy."""
    validate_backup_id(backup_id)
    if authorization.confirm_backup_id != backup_id:
        raise RecoveryConfirmationError(
            f"confirm_backup_id {authorization.confirm_backup_id!r} does not match backup_id {backup_id!r}; "
            "refusing to proceed with a recovery attempt."
        )
    require_attestations(authorization.quiescence)
    missing = authorization.missing_recovery_attestations()
    if missing:
        raise RecoveryAttestationMissingError(
            "the following required recovery-specific attestation(s) were not given: "
            f"{', '.join(missing)}. All recovery attestations must be explicitly given before a recovery "
            "attempt may proceed."
        )


class _Baseline:
    """This attempt's fresh capture, indexed for cheap expected-state
    lookups. Never mutates anything; a thin read-only view over one
    ``CaptureResult``."""

    def __init__(self, capture: CaptureResult):
        self.capture = capture
        self._sidecars: dict[str, CaptureItemRecord] = {
            record.item_key[len(_SIDECAR_ITEM_PREFIX):]: record for record in capture.sidecars
        }

    def database_expected(self, *, disposed: bool) -> ExpectedTargetState:
        if disposed:
            return expected_state_missing(detail="database disposed by a previously verified disposition")
        return expected_state_from_capture_record(self.capture.database)

    def sidecar_expected(self, suffix: str, *, disposed: bool) -> ExpectedTargetState:
        if disposed:
            return expected_state_missing(detail=f"sidecar {suffix!r} disposed by a previously verified disposition")
        record = self._sidecars.get(suffix)
        if record is None:
            return expected_state_missing(detail=f"sidecar {suffix!r} was MISSING at fresh capture time")
        return expected_state_from_capture_record(record)


def _check_database_stability(db_path: Path, baseline: _Baseline, *, disposed: bool) -> TargetStabilityResult:
    return check_target_stability(db_path, baseline.database_expected(disposed=disposed), target_key="database")


def _check_sidecar_stability(db_path: Path, suffix: str, baseline: _Baseline, *, disposed: bool) -> TargetStabilityResult:
    path = Path(str(db_path) + suffix)
    return check_target_stability(path, baseline.sidecar_expected(suffix, disposed=disposed), target_key=f"sidecar:{suffix}")


def _check_config_stability(config_dir: Path, baseline: _Baseline, *, disposed: bool) -> TargetStabilityResult:
    """One aggregate stability result for the whole config side: the
    container itself when the capture recorded an abnormal container
    (missing/unsafe/wrong-type/changed), or -- for the normal, safe,
    enumerable-directory case -- the shallow directory inventory plus
    every required file, each independently."""
    if disposed:
        return check_target_stability(
            config_dir, expected_state_missing(detail="config disposed by a previously verified disposition"), target_key="config"
        )
    capture = baseline.capture
    if capture.config_directory is not None:
        # a config container's WRONG_TYPE_RECORDED means "not a directory" --
        # the Windows disposition proof's own scenario is a regular file.
        expected = expected_state_from_capture_record(capture.config_directory, expected_regular=True)
        return check_target_stability(config_dir, expected, target_key="config")

    inventory_result = check_config_inventory_stability(config_dir, capture.config_directory_inventory)
    if not inventory_result.confirmed:
        return inventory_result
    for record in capture.config_files:
        filename = record.item_key.split(":", 1)[1]
        file_path = config_dir / filename
        result = check_target_stability(file_path, expected_state_from_capture_record(record), target_key=record.item_key)
        if not result.confirmed:
            return result
    return TargetStabilityResult(
        target_key="config", path=config_dir, confirmed=True,
        detail="config directory, inventory, and every required file match the fresh capture baseline",
    )


def _first_mismatch(db_path: Path, config_dir: Path, baseline: _Baseline, *, disposed) -> TargetStabilityResult | None:
    db_result = _check_database_stability(db_path, baseline, disposed=("database" in disposed))
    if not db_result.confirmed:
        return db_result
    config_result = _check_config_stability(config_dir, baseline, disposed=("config" in disposed))
    if not config_result.confirmed:
        return config_result
    for suffix in SIDECAR_SUFFIXES:
        sidecar_result = _check_sidecar_stability(db_path, suffix, baseline, disposed=(suffix in disposed))
        if not sidecar_result.confirmed:
            return sidecar_result
    return None


def _dispose_one(
    journal: RestoreJournal, *, target_kind: str, path: Path, expected_regular: bool,
    expected_state: ExpectedTargetState, restore_id: str, reason_tag: str,
) -> DispositionResult:
    journal.record(RestoreState.DISPOSITION_INTENT, {"target_kind": target_kind, "reason": reason_tag})

    stability = check_target_stability(path, expected_state, target_key=target_kind)
    if not stability.confirmed:
        journal.record(
            RestoreState.DISPOSITION_FAILED,
            {"target_kind": target_kind, "phase": "pre_disposition_stability", "detail": stability.detail},
        )
        raise RecoveryStabilityMismatchError(f"pre-disposition stability check failed for {target_kind!r}: {stability.detail}")

    try:
        result = dispose_target(path, target_kind=target_kind, expected_regular=expected_regular, restore_id=restore_id)
    except RecoveryDispositionFailedError as exc:
        journal.record(RestoreState.DISPOSITION_FAILED, {"target_kind": target_kind, "phase": "rename", "error": str(exc)})
        raise

    journal.record(
        RestoreState.DISPOSITION_COMPLETE, {"target_kind": target_kind, "superseded_path": str(result.superseded_path)}
    )
    return result


def execute_recovery(
    *,
    backup_manager: BackupManager,
    db_path: Path,
    config_dir: Path,
    backup_id: str,
    authorization: RecoveryAuthorization,
    reason: str | None = None,
    clock: Clock = _default_clock,
) -> RecoveryResult:
    """Execute one, brand-new Mission 1B-A2-3 recovery attempt for
    ``backup_id``. Always a fresh attempt, its own fresh ``restore_id``
    and journal, its own fresh capture -- never resumes, repairs, or
    continues a prior attempt. See the module docstring for the full
    ordering."""
    db_path = Path(db_path)
    config_dir = Path(config_dir)
    backup_id = validate_backup_id(backup_id)
    require_recovery_authorization(authorization, backup_id=backup_id)

    backup_path = backup_manager.config.paths.backup_path
    if not backup_path:
        raise RestoreError(
            "paths.backup_path is not configured; Mission 1B-A2-3 recovery requires the same configured "
            "backup destination Mission 1A/1B-A1/1B-A2 already use."
        )
    backup_root = validate_backup_root_containment(backup_root=Path(backup_path), db_path=db_path, config_dir=config_dir)

    restore_id = build_restore_id(clock())
    journal = RestoreJournal.create(backup_root / JOURNAL_DIRNAME, restore_id, backup_id, clock=clock, attempt_kind="recovery")
    journal.record(RestoreState.RECOVERY_INITIATED, {"reason": reason, "db_path": str(db_path), "config_dir": str(config_dir)})

    # -- fresh recovery-plan validation (initial) ----------------------------
    initial_plan = build_recovery_plan(backup_manager=backup_manager, db_path=db_path, config_dir=config_dir, backup_id=backup_id)
    if not initial_plan.would_proceed:
        journal.record(RestoreState.RECOVERY_PLAN_BLOCKED, {"blocking_issues": list(initial_plan.blocking_issues)})
        raise RecoveryBlockedError(
            f"fresh recovery-plan validation for {backup_id!r} is not architecturally eligible to proceed: "
            f"{'; '.join(initial_plan.blocking_issues)}"
        )
    journal.record(
        RestoreState.RECOVERY_PLAN_VALIDATED,
        {
            "target_verified": initial_plan.target_verified,
            "schema_compatible": initial_plan.schema_compatible,
            "database_condition": initial_plan.database.condition.value,
            "config_condition": initial_plan.config.condition.value,
        },
    )

    # -- mandatory fresh degraded-source capture -----------------------------
    journal.record(RestoreState.CAPTURE_INTENT, {})
    try:
        capture = build_degraded_source_capture(
            db_path=db_path, config_dir=config_dir, backup_path=backup_path,
            database_assessment=initial_plan.database, config_assessment=initial_plan.config,
            reason=reason, clock=clock,
        )
    except CaptureError as exc:
        journal.record(RestoreState.CAPTURE_FAILED, {"error": str(exc)})
        raise RecoveryCaptureFailedError(
            f"mandatory fresh degraded-source capture failed; zero live-target mutation occurred: {exc}"
        ) from exc
    journal.record(RestoreState.CAPTURE_COMPLETE, {"capture_id": capture.capture_id, "capture_path": str(capture.capture_path)})

    # -- capture reverification, exact same capture_id -----------------------
    journal.record(RestoreState.CAPTURE_REVERIFICATION_INTENT, {"capture_id": capture.capture_id})
    try:
        verify_degraded_source_capture(capture.capture_id, capture.capture_path)
    except CaptureError as exc:
        journal.record(RestoreState.CAPTURE_REVERIFICATION_FAILED, {"capture_id": capture.capture_id, "error": str(exc)})
        raise RecoveryCaptureFailedError(
            f"fresh capture {capture.capture_id!r} failed reverification; zero live-target mutation occurred: {exc}"
        ) from exc
    journal.record(RestoreState.CAPTURE_REVERIFIED, {"capture_id": capture.capture_id})

    # -- CHANGED_DURING_CAPTURE: unconditional terminal hard stop ------------
    all_records: list[CaptureItemRecord] = (
        [capture.database]
        + ([capture.config_directory] if capture.config_directory is not None else [])
        + list(capture.config_files)
        + list(capture.sidecars)
    )
    changed = [record.item_key for record in all_records if record.outcome is CaptureItemOutcome.CHANGED_DURING_CAPTURE]
    if changed:
        journal.record(RestoreState.CAPTURE_CHANGED_DURING_CAPTURE, {"items": changed})
        raise RecoveryChangedDuringCaptureError(
            f"fresh capture {capture.capture_id!r} recorded CHANGED_DURING_CAPTURE for: {changed}; this is an "
            "unconditional terminal hard stop. Zero live-target mutation occurred."
        )

    # -- fresh source/sidecar reclassification --------------------------------
    journal.record(RestoreState.SOURCE_RECLASSIFICATION_INTENT, {})
    reclass = build_recovery_plan(backup_manager=backup_manager, db_path=db_path, config_dir=config_dir, backup_id=backup_id)
    if not reclass.would_proceed:
        journal.record(RestoreState.SOURCE_RECLASSIFICATION_BLOCKED, {"blocking_issues": list(reclass.blocking_issues)})
        raise RecoveryBlockedError(
            f"fresh post-capture source/sidecar reclassification for {backup_id!r} is RECOVERY_BLOCKED: "
            f"{'; '.join(reclass.blocking_issues)}. Zero live-target mutation occurred. No authorization flag "
            "may override this."
        )
    journal.record(
        RestoreState.SOURCE_RECLASSIFIED,
        {"database_condition": reclass.database.condition.value, "config_condition": reclass.config.condition.value},
    )

    baseline = _Baseline(capture)
    sidecar_conditions = {assessment.suffix: assessment.condition for assessment in reclass.sidecar_assessments}

    # -- PRE_MUTATION_STABILITY ------------------------------------------------
    journal.record(RestoreState.PRE_MUTATION_STABILITY_INTENT, {})
    mismatch = _first_mismatch(db_path, config_dir, baseline, disposed=())
    if mismatch is not None:
        journal.record(RestoreState.PRE_MUTATION_STABILITY_MISMATCH, {"target_key": mismatch.target_key, "detail": mismatch.detail})
        raise RecoveryStabilityMismatchError(
            f"PRE_MUTATION_STABILITY failed for {mismatch.target_key!r}: {mismatch.detail}. Zero live-target "
            "mutation occurred."
        )
    journal.record(RestoreState.PRE_MUTATION_STABILITY_CONFIRMED, {})

    # -- quiescence: proved probe when applicable, otherwise not-applicable --
    if reclass.database.condition is SourceCondition.DEGRADED:
        journal.record(
            RestoreState.QUIESCENCE_NOT_APPLICABLE,
            {"reason": "database source is degraded; a BEGIN IMMEDIATE probe cannot be reliably run against it."},
        )
    else:
        try:
            probe_quiescence(db_path)
        except RestoreQuiescenceFailedError as exc:
            journal.record(RestoreState.QUIESCENCE_FAILED, {"error": str(exc)})
            raise
        journal.record(RestoreState.QUIESCENCE_CONFIRMED, {"attestations": asdict(authorization.quiescence)})

    # -- disposition, fixed deterministic order --------------------------------
    disposed: dict[str, DispositionResult] = {}

    db_wrong_type = reclass.database.disposition_required
    db_evidence_preservation = capture.database.outcome is CaptureItemOutcome.UNREADABLE
    if db_wrong_type or db_evidence_preservation:
        disposed["database"] = _dispose_one(
            journal, target_kind="database", path=db_path, expected_regular=db_evidence_preservation,
            expected_state=baseline.database_expected(disposed=False), restore_id=restore_id,
            reason_tag="evidence_preservation" if db_evidence_preservation else "wrong_type",
        )

    if reclass.config.disposition_required:
        if capture.config_directory is None:
            raise RecoveryStabilityMismatchError(
                "config recovery-plan reclassification reports disposition_required, but the fresh capture "
                "recorded a normal config container; refusing to guess which object to dispose."
            )
        disposed["config"] = _dispose_one(
            journal, target_kind="config", path=config_dir, expected_regular=True,
            expected_state=expected_state_from_capture_record(capture.config_directory, expected_regular=True),
            restore_id=restore_id, reason_tag="wrong_type",
        )

    for suffix in SIDECAR_SUFFIXES:
        if sidecar_conditions.get(suffix) is SidecarCondition.SAFE_REGULAR:
            sidecar_path = Path(str(db_path) + suffix)
            disposed[suffix] = _dispose_one(
                journal, target_kind=suffix, path=sidecar_path, expected_regular=True,
                expected_state=baseline.sidecar_expected(suffix, disposed=False), restore_id=restore_id,
                reason_tag="safe_regular_sidecar",
            )

    # -- FINAL_STABILITY --------------------------------------------------------
    journal.record(RestoreState.FINAL_STABILITY_INTENT, {})
    mismatch = _first_mismatch(db_path, config_dir, baseline, disposed=disposed)
    if mismatch is not None:
        journal.record(RestoreState.FINAL_STABILITY_MISMATCH, {"target_key": mismatch.target_key, "detail": mismatch.detail})
        raise RecoveryStabilityMismatchError(
            f"FINAL_STABILITY failed for {mismatch.target_key!r}: {mismatch.detail}. All already-completed "
            "dispositions and evidence are preserved; no rollback occurs."
        )
    journal.record(RestoreState.FINAL_STABILITY_CONFIRMED, {})

    # -- existing sidecar pre-check, reused unmodified ---------------------------
    try:
        require_no_sidecars(db_path, when="before database replacement (Mission 1B-A2-3 recovery)")
    except RestoreError as exc:
        journal.record(RestoreState.SIDECAR_PRESENT_PRE, {"error": str(exc)})
        raise
    journal.record(RestoreState.SIDECAR_CHECK_PASSED_PRE, {})

    # -- staging: identical target-backup staging Mission 1B-A1 already uses --
    verification = backup_manager.verify_backup(backup_id)
    package_dir = verification.backup_path
    manifest = _load_manifest(package_dir)
    db_entry = manifest["database"]
    target_db_path = package_dir / db_entry["relative_path"]
    target_config_dir = package_dir / "payload" / "config"

    journal.record(RestoreState.STAGING_INTENT, {})
    try:
        staged_db_path = stage_database(
            target_db_path=target_db_path, db_manifest_entry=db_entry, live_db_path=db_path, restore_id=restore_id
        )
        staged_config_dir = stage_config(
            target_config_dir=target_config_dir, config_manifest_entries=manifest["config_files"],
            live_config_dir=config_dir, restore_id=restore_id,
        )
    except RestoreError as exc:
        journal.record(RestoreState.STAGING_FAILED, {"error": str(exc)})
        raise
    journal.record(RestoreState.STAGING_COMPLETE, {"staged_db_path": str(staged_db_path), "staged_config_dir": str(staged_config_dir)})

    # -- database replacement: mutation-bound stability recheck + os.replace --
    journal.record(RestoreState.DB_REPLACE_INTENT, {})
    db_check = _check_database_stability(db_path, baseline, disposed=("database" in disposed))
    if not db_check.confirmed:
        journal.record(RestoreState.DB_REPLACE_FAILED, {"phase": "pre_replacement_stability", "detail": db_check.detail})
        raise RecoveryStabilityMismatchError(f"pre-replacement database stability check failed: {db_check.detail}")
    try:
        replace_database(staged_db_path, db_path)
    except RestoreError as exc:
        journal.record(RestoreState.DB_REPLACE_FAILED, {"phase": "replace", "error": str(exc)})
        raise
    journal.record(RestoreState.DB_REPLACED, {})

    # -- config replacement: rename-aside skipped when the path is already ----
    # vacant (disposed, or genuinely MISSING to begin with); either way, the
    # path must be vacant immediately before install.
    config_disposed = "config" in disposed
    if config_disposed:
        superseded_path = disposed["config"].superseded_path
    else:
        superseded_path = superseded_config_path(config_dir, restore_id)
        if reclass.config.condition is not SourceCondition.MISSING:
            journal.record(RestoreState.CONFIG_RENAME_ASIDE_INTENT, {"superseded_path": str(superseded_path)})
            config_check = _check_config_stability(config_dir, baseline, disposed=False)
            if not config_check.confirmed:
                journal.record(RestoreState.CONFIG_REPLACE_FAILED, {"phase": "pre_rename_stability", "detail": config_check.detail})
                raise RecoveryStabilityMismatchError(f"pre-rename config stability check failed: {config_check.detail}")
            try:
                rename_config_aside(config_dir, superseded_path)
            except RestoreError as exc:
                journal.record(RestoreState.CONFIG_REPLACE_FAILED, {"phase": "rename_aside", "error": str(exc)})
                raise
            journal.record(RestoreState.CONFIG_RENAMED_ASIDE, {})

    journal.record(RestoreState.CONFIG_INSTALL_INTENT, {})
    install_check = check_target_stability(
        config_dir, expected_state_missing(detail="config path must be vacant immediately before staged-config install"),
        target_key="config",
    )
    if not install_check.confirmed:
        journal.record(RestoreState.CONFIG_REPLACE_FAILED, {"phase": "pre_install_stability", "detail": install_check.detail})
        raise RecoveryStabilityMismatchError(f"pre-install config stability check failed: {install_check.detail}")
    try:
        install_staged_config(staged_config_dir, config_dir, superseded_path=superseded_path)
    except RestoreError as exc:
        journal.record(RestoreState.CONFIG_REPLACE_FAILED, {"phase": "install", "error": str(exc)})
        raise
    journal.record(RestoreState.CONFIG_REPLACED, {})

    # -- shared final verification, identical to Mission 1B-A1 -------------------
    journal.record(RestoreState.VERIFICATION_INTENT, {})
    try:
        verify_restore(db_path=db_path, config_dir=config_dir, backup_manager=backup_manager, manifest=manifest, backup_id=backup_id)
    except RestoreError as exc:
        journal.record(RestoreState.VERIFICATION_FAILED, {"error": str(exc)})
        raise
    journal.record(RestoreState.VERIFIED_SUCCESS, {})

    return RecoveryResult(
        restore_id=restore_id, backup_id=backup_id, capture_id=capture.capture_id, capture_path=capture.capture_path,
        journal_dir=journal.journal_dir, disposed_targets=tuple(sorted(disposed)),
        database_sha256=db_entry["sha256"], database_size_bytes=db_entry["size_bytes"],
        config_file_count=len(manifest["config_files"]), superseded_config_path=superseded_path,
        completed_at=format_utc_iso(clock()),
    )
