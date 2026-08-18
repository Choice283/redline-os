"""Tests for redline_core.restore.recovery_planning.build_recovery_plan()
(Mission 1B-A2-1): the read-only orchestration combining target-backup
verification/schema-compatibility with live source classification. Reuses
tests/unit/_restore_test_helpers.py's Environment/make_target_backup exactly
as tests/unit/test_restore_manager.py does.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from redline_core import fsutil
from redline_core.config.loader import REQUIRED_FILES
from redline_core.restore.recovery_models import RecoveryFeasibility, SourceCondition
from redline_core.restore.recovery_planning import build_recovery_plan

from tests.unit._restore_test_helpers import make_environment, make_target_backup


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_hashes(config_dir: Path) -> dict[str, str]:
    return {filename: _sha256_bytes(config_dir / filename) for filename in REQUIRED_FILES.values()}


def _plan(env, backup_id):
    return build_recovery_plan(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir, backup_id=backup_id
    )


# -- healthy target + healthy source -------------------------------------------------


def test_recovery_plan_healthy_target_and_source_would_proceed(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    plan = _plan(env, target_id)

    assert plan.target_verified is True
    assert plan.schema_compatible is True
    assert plan.database.condition is SourceCondition.HEALTHY
    assert plan.config.condition is SourceCondition.HEALTHY
    assert plan.database.feasibility is RecoveryFeasibility.NOT_APPLICABLE
    assert plan.config.feasibility is RecoveryFeasibility.NOT_APPLICABLE
    assert plan.blocking_issues == ()
    assert plan.would_proceed is True
    assert "quiescent" in plan.quiescence_implication


# -- target backup problems ---------------------------------------------------------


def test_recovery_plan_missing_backup_id(tmp_path: Path):
    env = make_environment(tmp_path)
    make_target_backup(tmp_path, env)

    plan = _plan(env, "b1-20260817T000000Z-000000000000")

    assert plan.target_verified is False
    assert plan.would_proceed is False
    assert any("verification failed" in issue for issue in plan.blocking_issues)


def test_recovery_plan_invalid_backup_id_format(tmp_path: Path):
    env = make_environment(tmp_path)

    with pytest.raises(ValueError):
        _plan(env, "not-a-real-backup-id")


def test_recovery_plan_tampered_backup(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    package_dir = env.backup_root / "system_backups" / target_id
    snapshot_path = package_dir / "payload" / "database" / "redline.db"
    data = bytearray(snapshot_path.read_bytes())
    data[0] ^= 0xFF
    snapshot_path.write_bytes(bytes(data))

    plan = _plan(env, target_id)

    assert plan.target_verified is False
    assert plan.would_proceed is False


def test_recovery_plan_schema_incompatible_backup(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(
        tmp_path, env, db_statements=["CREATE TABLE wrong_shape (id INTEGER PRIMARY KEY)"], unique_dir="bad_schema"
    )

    plan = _plan(env, target_id)

    assert plan.target_verified is True
    assert plan.schema_compatible is False
    assert plan.would_proceed is False


# -- degraded/missing source, independently reported --------------------------------


def test_recovery_plan_degraded_db_recoverable(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.db_path.write_bytes(b"corrupted, not a real sqlite file")

    plan = _plan(env, target_id)

    assert plan.database.condition is SourceCondition.DEGRADED
    assert plan.database.feasibility is RecoveryFeasibility.RECOVERABLE
    assert plan.config.condition is SourceCondition.HEALTHY
    # DEGRADED + RECOVERABLE means a future A2 recovery path is believed
    # architecturally eligible -- it is NOT itself a blocking condition
    # (only RECOVERY_BLOCKED, or a target-backup failure, is).
    assert plan.would_proceed is True
    assert not any("recovery blocked" in issue for issue in plan.blocking_issues)
    assert "not determinable" in plan.quiescence_implication


def test_recovery_plan_degraded_db_recovery_blocked_unsafe_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    from redline_core.restore import recovery_classification as rc

    monkeypatch.setattr(rc.fsutil, "is_unsafe_link", lambda st: True)

    plan = _plan(env, target_id)

    assert plan.database.condition is SourceCondition.DEGRADED
    assert plan.database.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED
    assert plan.would_proceed is False
    assert any("database recovery blocked" in issue for issue in plan.blocking_issues)


def test_recovery_plan_config_recovery_blocked_unsafe_link_isolates_config_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Coverage-gap 1 (Mission 1B-A2-1 post-implementation review): the
    config-side RECOVERY_BLOCKED branch in build_recovery_plan() had a
    passing sibling only on the DB side. This isolates the config side --
    the DB side and the target backup must remain completely unaffected,
    proving the two sides classify and block independently, matching
    test_classify_config_unsafe_link_required_file_is_recovery_blocked's
    own ino/dev-scoped monkeypatch technique
    (tests/unit/test_recovery_classification.py) rather than the DB-side
    sibling's global patch, which would have also blocked the DB side."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    from redline_core.restore import recovery_classification as rc

    config_dir_ino_dev = (env.config_dir.stat().st_ino, env.config_dir.stat().st_dev)
    real_is_unsafe_link = rc.fsutil.is_unsafe_link

    def _fake_is_unsafe_link(st):
        if (st.st_ino, st.st_dev) == config_dir_ino_dev:
            return True
        return real_is_unsafe_link(st)

    monkeypatch.setattr(rc.fsutil, "is_unsafe_link", _fake_is_unsafe_link)

    plan = _plan(env, target_id)

    # DB side and target backup must remain completely unaffected -- proves
    # the config-side block is isolated, not an accidental side effect of a
    # global unsafe-link patch.
    assert plan.database.condition is SourceCondition.HEALTHY
    assert plan.database.feasibility is RecoveryFeasibility.NOT_APPLICABLE
    assert plan.target_verified is True
    assert plan.schema_compatible is True

    # Config side: the exact contract this coverage gap requires.
    assert plan.config.condition is SourceCondition.DEGRADED
    assert plan.config.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED
    assert plan.config.blocking_reason is not None
    assert "symlink" in plan.config.blocking_reason

    assert any("config recovery blocked" in issue for issue in plan.blocking_issues)
    assert not any("database recovery blocked" in issue for issue in plan.blocking_issues)
    assert plan.would_proceed is False


def test_recovery_plan_missing_db_recoverable(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.db_path.unlink()

    plan = _plan(env, target_id)

    assert plan.database.condition is SourceCondition.MISSING
    assert plan.database.feasibility is RecoveryFeasibility.RECOVERABLE
    assert "not applicable" in plan.quiescence_implication


def test_recovery_plan_missing_db_with_sidecar_present_is_surfaced_independently(tmp_path: Path):
    """Coverage-gap 2 (Mission 1B-A2-1 post-implementation review): DB
    missing + an orphaned SQLite sidecar (-wal) present had no dedicated
    test. Freezes the exact current architecture-defined behavior: sidecar
    presence is reported independently of DB classification, never treated
    as the database itself, and never opened/moved/renamed/deleted by
    planning."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    env.db_path.unlink()
    wal_path = Path(str(env.db_path) + "-wal")
    wal_content = b"orphaned wal debris"
    wal_path.write_bytes(wal_content)

    plan = _plan(env, target_id)

    # DB side: architecture-defined MISSING/RECOVERABLE (parent intact) --
    # the sidecar's presence does not change the DB's own classification.
    assert plan.database.condition is SourceCondition.MISSING
    assert plan.database.feasibility is RecoveryFeasibility.RECOVERABLE
    assert plan.database.capture_required is True
    assert plan.database.disposition_required is False

    # Sidecar independently surfaced -- never folded into database.* and
    # never magically treated as the database itself.
    assert str(wal_path) in plan.sidecars_present

    # MISSING + RECOVERABLE alone is not a hard block.
    assert plan.would_proceed is True
    assert "not applicable" in plan.quiescence_implication

    # Read-only guarantee: the sidecar was never opened, moved, renamed, or
    # deleted, and planning never recreated the "missing" database.
    assert wal_path.exists()
    assert wal_path.read_bytes() == wal_content
    assert not env.db_path.exists()


def test_recovery_plan_missing_db_parent_also_missing_is_recovery_blocked(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.db_path.unlink()
    env.db_path.parent.rmdir()

    plan = _plan(env, target_id)

    assert plan.database.condition is SourceCondition.MISSING
    assert plan.database.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED
    assert plan.would_proceed is False


def test_recovery_plan_mixed_degraded_db_and_missing_config(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.db_path.write_bytes(b"corrupted")
    import shutil

    shutil.rmtree(env.config_dir)

    plan = _plan(env, target_id)

    assert plan.database.condition is SourceCondition.DEGRADED
    assert plan.database.feasibility is RecoveryFeasibility.RECOVERABLE
    assert plan.config.condition is SourceCondition.MISSING
    assert plan.config.feasibility is RecoveryFeasibility.RECOVERABLE


# -- infrastructure failure never reclassifies source health ------------------------


def test_backup_infrastructure_failure_does_not_alter_source_classification(tmp_path: Path):
    """A backup-root misconfiguration is a Mission 1A infrastructure
    concern, surfaced via target_verified/blocking_issues -- it must never
    make database.condition/config.condition anything other than what the
    live source actually is."""
    env = make_environment(tmp_path, configure_backup_path=False)

    plan = build_recovery_plan(
        backup_manager=env.backup_manager,
        db_path=env.db_path,
        config_dir=env.config_dir,
        backup_id="b1-20260817T000000Z-000000000000",
    )

    assert plan.target_verified is False
    assert plan.database.condition is SourceCondition.HEALTHY
    assert plan.config.condition is SourceCondition.HEALTHY
    assert plan.database.feasibility is RecoveryFeasibility.NOT_APPLICABLE
    assert plan.config.feasibility is RecoveryFeasibility.NOT_APPLICABLE


def test_classification_never_calls_create_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Classification must be a direct, independent probe of the live
    source -- never 'call create_backup() and guess from the exception'."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    def _forbidden(*args, **kwargs):
        raise AssertionError("build_recovery_plan() must never call BackupManager.create_backup()")

    monkeypatch.setattr(env.backup_manager, "create_backup", _forbidden)

    plan = _plan(env, target_id)

    assert plan.database.condition is SourceCondition.HEALTHY
    assert plan.config.condition is SourceCondition.HEALTHY


# -- read-only guarantee -----------------------------------------------------------


def test_recovery_plan_never_mutates_anything(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    db_hash_before = _sha256_bytes(env.db_path)
    config_hashes_before = _config_hashes(env.config_dir)
    config_inventory_before = sorted(p.name for p in env.config_dir.iterdir())
    backups_before = set((env.backup_root / "system_backups").iterdir())
    backup_root_entries_before = set(env.backup_root.iterdir())

    _plan(env, target_id)

    assert _sha256_bytes(env.db_path) == db_hash_before
    assert _config_hashes(env.config_dir) == config_hashes_before
    assert sorted(p.name for p in env.config_dir.iterdir()) == config_inventory_before
    assert set((env.backup_root / "system_backups").iterdir()) == backups_before
    # No staging directory, no restore_journal directory, no new top-level
    # entry under backup_root of any kind.
    assert set(env.backup_root.iterdir()) == backup_root_entries_before
    assert not (env.backup_root / "restore_journal").exists()

    for suffix in ("-journal", "-wal", "-shm"):
        assert not Path(str(env.db_path) + suffix).exists()


def test_recovery_plan_creates_no_staging_directory_even_for_degraded_source(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.db_path.write_bytes(b"corrupted")

    from redline_core.restore.staging import STAGING_DIRNAME

    _plan(env, target_id)

    assert not (env.db_path.parent / STAGING_DIRNAME).exists()


def test_recovery_plan_degraded_db_does_not_probe_quiescence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The documented reason this module never calls probe_quiescence()
    against a DEGRADED database: quiescence.py's exception mapping doesn't
    catch sqlite3.DatabaseError, which a corrupt file typically raises."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.db_path.write_bytes(b"corrupted, not a real sqlite file")

    from redline_core.restore import recovery_planning as rp

    def _forbidden(db_path):
        raise AssertionError("probe_quiescence() must never be called against a DEGRADED database")

    monkeypatch.setattr(rp, "probe_quiescence", _forbidden)

    plan = _plan(env, target_id)  # must not raise

    assert plan.database.condition is SourceCondition.DEGRADED
    assert "not determinable" in plan.quiescence_implication
