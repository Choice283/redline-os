"""Tests for redline_core.restore.recovery_execution (Mission 1B-A2-3):
Recovery Execution + Journal/Evidence Integration end-to-end.
"""
from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

from redline_core.restore.capture_models import CaptureItemOutcome, StatFingerprint
from redline_core.restore.exceptions import (
    RecoveryAttestationMissingError,
    RecoveryBlockedError,
    RecoveryChangedDuringCaptureError,
    RecoveryConfirmationError,
    RecoveryDispositionFailedError,
    RecoveryStabilityMismatchError,
    RestoreConfigReplacementFailedError,
    RestoreDatabaseReplacementFailedError,
)
from redline_core.restore.journal import discover_journal_chain
from redline_core.restore.models import QuiescenceAttestations
from redline_core.restore.recovery_execution import execute_recovery, require_recovery_authorization
from redline_core.restore.recovery_models import RecoveryAuthorization

from tests.unit._restore_test_helpers import make_environment, make_target_backup

_ALL_TRUE_QUIESCENCE = QuiescenceAttestations(mcp_stopped=True, control_room_stopped=True, no_other_cli_operation=True)


def _full_auth(backup_id: str, **overrides) -> RecoveryAuthorization:
    fields = {
        "confirm_backup_id": backup_id,
        "quiescence": _ALL_TRUE_QUIESCENCE,
        "disposition_understood": True,
        "no_automatic_rollback_understood": True,
    }
    fields.update(overrides)
    return RecoveryAuthorization(**fields)


def _query_episode_ids(db_path: Path) -> list[str]:
    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT episode_id FROM episodes ORDER BY episode_id").fetchall()]
    finally:
        conn.close()


# -- require_recovery_authorization(): validation order -------------------------------


_VALID_BACKUP_ID = "b1-20260817T030606Z-8abd0a149de5"


def test_require_recovery_authorization_rejects_malformed_backup_id():
    auth = _full_auth(_VALID_BACKUP_ID)
    with pytest.raises(ValueError):
        require_recovery_authorization(auth, backup_id="not-a-real-backup-id")


def test_require_recovery_authorization_rejects_confirm_mismatch():
    auth = _full_auth(_VALID_BACKUP_ID, confirm_backup_id="b1-20260817T030606Z-000000000000")
    with pytest.raises(RecoveryConfirmationError):
        require_recovery_authorization(auth, backup_id=_VALID_BACKUP_ID)


def test_require_recovery_authorization_rejects_missing_quiescence_attestation():
    auth = _full_auth(_VALID_BACKUP_ID, quiescence=QuiescenceAttestations(mcp_stopped=False, control_room_stopped=True, no_other_cli_operation=True))
    from redline_core.restore.exceptions import RestoreAttestationMissingError

    with pytest.raises(RestoreAttestationMissingError):
        require_recovery_authorization(auth, backup_id=_VALID_BACKUP_ID)


def test_require_recovery_authorization_rejects_missing_recovery_attestation():
    auth = _full_auth(_VALID_BACKUP_ID, disposition_understood=False)
    with pytest.raises(RecoveryAttestationMissingError):
        require_recovery_authorization(auth, backup_id=_VALID_BACKUP_ID)


def test_require_recovery_authorization_passes_when_everything_given():
    auth = _full_auth(_VALID_BACKUP_ID)
    require_recovery_authorization(auth, backup_id=_VALID_BACKUP_ID)  # does not raise


# -- happy paths: MISSING and DEGRADED-in-place database -------------------------------


def test_execute_recovery_missing_database_full_flow_reaches_verified_success(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E501")
    env.db_path.unlink()

    result = execute_recovery(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
        backup_id=target_id, authorization=_full_auth(target_id),
    )

    assert result.backup_id == target_id
    assert result.disposed_targets == ()
    assert _query_episode_ids(env.db_path) == ["RLC-E501"]

    chain = discover_journal_chain(result.journal_dir)
    states = [t.state for t in chain]
    assert states[0] == "RECOVERY_INITIATED"
    assert states[-1] == "VERIFIED_SUCCESS"
    assert "CAPTURE_COMPLETE" in states
    assert "CAPTURE_REVERIFIED" in states
    assert "SOURCE_RECLASSIFIED" in states
    assert "PRE_MUTATION_STABILITY_CONFIRMED" in states
    assert "FINAL_STABILITY_CONFIRMED" in states
    assert chain[0].payload["attempt_kind"] == "recovery"


def test_execute_recovery_degraded_database_skips_quiescence_probe(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E502")
    env.db_path.write_bytes(b"not a sqlite file at all")

    result = execute_recovery(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
        backup_id=target_id, authorization=_full_auth(target_id),
    )

    chain = discover_journal_chain(result.journal_dir)
    states = [t.state for t in chain]
    assert "QUIESCENCE_NOT_APPLICABLE" in states
    assert "QUIESCENCE_CONFIRMED" not in states
    assert _query_episode_ids(env.db_path) == ["RLC-E502"]


def test_execute_recovery_creates_a_brand_new_capture_every_attempt(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E503")
    env.db_path.unlink()

    result1 = execute_recovery(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
        backup_id=target_id, authorization=_full_auth(target_id),
    )
    env.db_path.unlink()
    result2 = execute_recovery(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
        backup_id=target_id, authorization=_full_auth(target_id),
    )

    assert result1.capture_id != result2.capture_id
    assert result1.capture_path != result2.capture_path
    assert result1.capture_path.is_dir()  # not deleted, still preserved evidence
    assert result2.capture_path.is_dir()


def test_execute_recovery_signature_has_no_capture_id_parameter():
    import inspect

    params = inspect.signature(execute_recovery).parameters
    assert "capture_id" not in params
    assert "confirm_capture_id" not in params


# -- WRONG_TYPE database disposition ----------------------------------------------------


def test_execute_recovery_disposes_wrong_type_database_directory(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E504")
    env.db_path.unlink()
    env.db_path.mkdir()
    (env.db_path / "stray.txt").write_text("must be preserved")

    result = execute_recovery(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
        backup_id=target_id, authorization=_full_auth(target_id),
    )

    assert "database" in result.disposed_targets
    assert env.db_path.is_file()  # the ordinary database file now lives here
    assert _query_episode_ids(env.db_path) == ["RLC-E504"]

    superseded = [p for p in env.db_path.parent.iterdir() if p.name.startswith("redline.db__superseded-")]
    assert len(superseded) == 1
    assert superseded[0].is_dir()
    assert (superseded[0] / "stray.txt").read_text() == "must be preserved"

    chain = discover_journal_chain(result.journal_dir)
    disposition_details = [t.payload["detail"] for t in chain if t.state == "DISPOSITION_INTENT"]
    assert disposition_details[0]["target_kind"] == "database"


# -- WRONG_TYPE config disposition ------------------------------------------------------


def test_execute_recovery_disposes_wrong_type_config_regular_file(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E505")

    import shutil

    shutil.rmtree(env.config_dir)
    env.config_dir.write_bytes(b"a regular file where a config directory belongs")

    result = execute_recovery(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
        backup_id=target_id, authorization=_full_auth(target_id),
    )

    assert "config" in result.disposed_targets
    assert env.config_dir.is_dir()
    superseded = [p for p in env.config_dir.parent.iterdir() if p.name.startswith("config__superseded-")]
    assert any(p.is_file() for p in superseded)


# -- SAFE_REGULAR sidecar disposition ---------------------------------------------------


def test_execute_recovery_disposes_safe_regular_sidecar(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E506")
    env.db_path.unlink()
    wal_path = Path(str(env.db_path) + "-wal")
    wal_path.write_bytes(b"leftover wal bytes")

    result = execute_recovery(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
        backup_id=target_id, authorization=_full_auth(target_id),
    )

    assert "-wal" in result.disposed_targets
    assert not wal_path.exists()
    superseded = [p for p in env.db_path.parent.iterdir() if p.name.startswith("redline.db-wal__superseded-")]
    assert len(superseded) == 1
    assert superseded[0].read_bytes() == b"leftover wal bytes"


# -- RECOVERY_BLOCKED: initial validation -----------------------------------------------


def test_execute_recovery_blocked_at_initial_validation_by_unsafe_object(tmp_path: Path, monkeypatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E507")

    monkeypatch.setattr("redline_core.restore.recovery_classification.fsutil.is_unsafe_link", lambda st: True)

    with pytest.raises(RecoveryBlockedError):
        execute_recovery(
            backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
            backup_id=target_id, authorization=_full_auth(target_id),
        )

    # zero live mutation: the environment's own original content (never the
    # target backup's RLC-E507) is still what the live database holds
    assert _query_episode_ids(env.db_path) == ["RLC-E001"]


# -- RECOVERY_BLOCKED: post-capture reclassification -------------------------------------


def test_execute_recovery_blocked_at_post_capture_reclassification(tmp_path: Path, monkeypatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E508")
    env.db_path.unlink()

    from redline_core.restore import recovery_execution as mod

    real_build_plan = mod.build_recovery_plan
    call_count = {"n": 0}

    def _flaky_plan(**kwargs):
        call_count["n"] += 1
        plan = real_build_plan(**kwargs)
        if call_count["n"] == 1:
            return plan  # initial validation: passes
        # post-capture reclassification: force RECOVERY_BLOCKED
        return dataclasses.replace(plan, blocking_issues=("sidecar recovery blocked: injected by test",))

    monkeypatch.setattr(mod, "build_recovery_plan", _flaky_plan)

    with pytest.raises(RecoveryBlockedError):
        execute_recovery(
            backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
            backup_id=target_id, authorization=_full_auth(target_id),
        )

    assert call_count["n"] == 2
    # the capture itself still exists (it happened before the block) but
    # zero live-target mutation occurred
    assert not env.db_path.exists()


# -- CHANGED_DURING_CAPTURE: unconditional terminal hard stop ---------------------------


def test_execute_recovery_changed_during_capture_is_terminal_hard_stop(tmp_path: Path, monkeypatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E509")
    env.db_path.unlink()

    from redline_core.restore import recovery_execution as mod

    real_capture_fn = mod.build_degraded_source_capture

    def _tampered_capture(**kwargs):
        capture = real_capture_fn(**kwargs)
        tampered_db = dataclasses.replace(capture.database, outcome=CaptureItemOutcome.CHANGED_DURING_CAPTURE)
        return dataclasses.replace(capture, database=tampered_db)

    monkeypatch.setattr(mod, "build_degraded_source_capture", _tampered_capture)

    with pytest.raises(RecoveryChangedDuringCaptureError):
        execute_recovery(
            backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
            backup_id=target_id, authorization=_full_auth(target_id),
        )

    assert not env.db_path.exists()  # never reached disposition or replacement


# -- UNREADABLE database: with and without sufficient fingerprint evidence --------------


def test_execute_recovery_unreadable_db_with_fingerprint_triggers_evidence_preservation(tmp_path: Path, monkeypatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E510")

    import os

    st = os.lstat(env.db_path)
    fp = StatFingerprint(size=st.st_size, mtime_ns=st.st_mtime_ns, ino=getattr(st, "st_ino", None) or None, dev=getattr(st, "st_dev", None) or None)

    from redline_core.restore import recovery_execution as mod

    real_capture_fn = mod.build_degraded_source_capture

    def _fake_unreadable_capture(**kwargs):
        capture = real_capture_fn(**kwargs)
        fake_db = dataclasses.replace(
            capture.database, outcome=CaptureItemOutcome.UNREADABLE, captured_relative_path=None,
            size_bytes=None, sha256=None, stat_fingerprint=fp,
        )
        return dataclasses.replace(capture, database=fake_db)

    monkeypatch.setattr(mod, "build_degraded_source_capture", _fake_unreadable_capture)

    result = execute_recovery(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
        backup_id=target_id, authorization=_full_auth(target_id),
    )

    assert "database" in result.disposed_targets
    chain = discover_journal_chain(result.journal_dir)
    intents = [t.payload["detail"] for t in chain if t.state == "DISPOSITION_INTENT" and t.payload["detail"]["target_kind"] == "database"]
    assert intents[0]["reason"] == "evidence_preservation"


def test_execute_recovery_unreadable_db_without_fingerprint_fails_at_pre_mutation_stability(tmp_path: Path, monkeypatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E511")

    from redline_core.restore import recovery_execution as mod

    real_capture_fn = mod.build_degraded_source_capture

    def _fake_unreadable_capture(**kwargs):
        capture = real_capture_fn(**kwargs)
        fake_db = dataclasses.replace(
            capture.database, outcome=CaptureItemOutcome.UNREADABLE, captured_relative_path=None,
            size_bytes=None, sha256=None, stat_fingerprint=None,
        )
        return dataclasses.replace(capture, database=fake_db)

    monkeypatch.setattr(mod, "build_degraded_source_capture", _fake_unreadable_capture)

    with pytest.raises(RecoveryStabilityMismatchError):
        execute_recovery(
            backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
            backup_id=target_id, authorization=_full_auth(target_id),
        )

    # never reached disposition
    original_bytes = env.db_path.read_bytes()
    assert original_bytes  # still present, untouched


# -- mutation-bound stability: immediate pre-replacement / pre-install rechecks ---------


def test_execute_recovery_pre_replacement_db_drift_blocks_and_does_not_replace(tmp_path: Path, monkeypatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E512")
    env.db_path.unlink()

    from redline_core.restore import recovery_execution as mod

    real_stage_database = mod.stage_database
    replace_calls = []

    def _stage_then_drift(**kwargs):
        staged = real_stage_database(**kwargs)
        # simulate a concurrent actor creating the live database out from
        # under this attempt, immediately after staging completes
        env.db_path.write_bytes(b"raced in by another process")
        return staged

    def _tracking_replace(staged, live):
        replace_calls.append((staged, live))

    monkeypatch.setattr(mod, "stage_database", _stage_then_drift)
    monkeypatch.setattr(mod, "replace_database", _tracking_replace)

    with pytest.raises(RecoveryStabilityMismatchError):
        execute_recovery(
            backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
            backup_id=target_id, authorization=_full_auth(target_id),
        )

    assert replace_calls == []  # os.replace() was never reached


# -- FINAL_STABILITY: a disposed target must be missing ---------------------------------


def test_execute_recovery_final_stability_catches_reappearance_after_disposition(tmp_path: Path, monkeypatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E513")
    env.db_path.unlink()
    env.db_path.mkdir()  # WRONG_TYPE database -> will be disposed

    from redline_core.restore import recovery_execution as mod

    real_dispose_target = mod.dispose_target

    def _dispose_then_race_back(path, *, target_kind, expected_regular, restore_id):
        result = real_dispose_target(path, target_kind=target_kind, expected_regular=expected_regular, restore_id=restore_id)
        if target_kind == "database":
            Path(path).write_bytes(b"raced back in immediately after disposition")
        return result

    monkeypatch.setattr(mod, "dispose_target", _dispose_then_race_back)

    with pytest.raises(RecoveryStabilityMismatchError):
        execute_recovery(
            backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
            backup_id=target_id, authorization=_full_auth(target_id),
        )


# -- disposition failure (collision / open-handle) --------------------------------------


def test_execute_recovery_disposition_failure_leaves_partial_state_preserved(tmp_path: Path, monkeypatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E514")
    env.db_path.unlink()
    env.db_path.mkdir()

    from redline_core.restore import recovery_execution as mod

    def _boom(path, *, target_kind, expected_regular, restore_id):
        raise RecoveryDispositionFailedError("simulated open-handle failure during disposition")

    monkeypatch.setattr(mod, "dispose_target", _boom)

    with pytest.raises(RecoveryDispositionFailedError):
        execute_recovery(
            backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
            backup_id=target_id, authorization=_full_auth(target_id),
        )

    assert env.db_path.is_dir()  # filesystem left exactly as observed, no partial mutation


# -- exact recovery journal state ordering (full happy path) ----------------------------


def test_execute_recovery_exact_state_ordering_missing_database(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E515")
    env.db_path.unlink()

    result = execute_recovery(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
        backup_id=target_id, authorization=_full_auth(target_id),
    )

    chain = discover_journal_chain(result.journal_dir)
    states = [t.state for t in chain]
    assert states == [
        "RECOVERY_INITIATED",
        "RECOVERY_PLAN_VALIDATED",
        "CAPTURE_INTENT",
        "CAPTURE_COMPLETE",
        "CAPTURE_REVERIFICATION_INTENT",
        "CAPTURE_REVERIFIED",
        "SOURCE_RECLASSIFICATION_INTENT",
        "SOURCE_RECLASSIFIED",
        "PRE_MUTATION_STABILITY_INTENT",
        "PRE_MUTATION_STABILITY_CONFIRMED",
        "QUIESCENCE_CONFIRMED",
        "FINAL_STABILITY_INTENT",
        "FINAL_STABILITY_CONFIRMED",
        "SIDECAR_CHECK_PASSED_PRE",
        "STAGING_INTENT",
        "STAGING_COMPLETE",
        "DB_REPLACE_INTENT",
        "DB_REPLACED",
        "CONFIG_RENAME_ASIDE_INTENT",
        "CONFIG_RENAMED_ASIDE",
        "CONFIG_INSTALL_INTENT",
        "CONFIG_REPLACED",
        "VERIFICATION_INTENT",
        "VERIFIED_SUCCESS",
    ]


# -- failure doctrine: no automatic retry/rollback/resume --------------------------------


def test_execute_recovery_never_retries_automatically_on_capture_failure(tmp_path: Path, monkeypatch):
    from redline_core.restore.capture_exceptions import CaptureConfigurationError

    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E516")
    env.db_path.unlink()

    from redline_core.restore import recovery_execution as mod

    call_count = {"n": 0}

    def _always_fails(**kwargs):
        call_count["n"] += 1
        raise CaptureConfigurationError("simulated capture failure")

    monkeypatch.setattr(mod, "build_degraded_source_capture", _always_fails)

    from redline_core.restore.exceptions import RecoveryCaptureFailedError

    with pytest.raises(RecoveryCaptureFailedError):
        execute_recovery(
            backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir,
            backup_id=target_id, authorization=_full_auth(target_id),
        )

    assert call_count["n"] == 1  # exactly one attempt, no automatic retry
