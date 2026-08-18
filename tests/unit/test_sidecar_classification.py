"""Tests for redline_core.restore.sidecar_classification (Mission
1B-A2-3-Prep2): the one shared, read-only, lstat-based SQLite sidecar
safety classifier (MISSING/SAFE_REGULAR/WRONG_TYPE/UNSAFE), plus its
integration into Mission 1B-A2-1 recovery planning
(``redline_core.restore.recovery_planning``) and Mission 1B-A2-2 capture
(``redline_core.restore.capture_package``).

Unsafe/dangling-unsafe simulation uses the established repository
convention (``tests/unit/test_backup_paths.py``,
``tests/unit/test_capture_package.py``'s own ``test_capture_sidecars_
dangling_unsafe_*`` tests): monkeypatching ``os.lstat``/
``redline_core.fsutil.is_unsafe_link`` on the shared module objects
(never real symlink/junction creation, which can require elevated
privileges on Windows). Patching ``sidecar_classification.os``/``.fsutil``
patches the same singleton ``os``/``redline_core.fsutil`` module objects
every other module in this package imports, so the same patch is visible
to ``recovery_planning.py`` and ``capture_package.py`` alike without
needing three separate patch targets.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from redline_core.restore import capture_package as cp
from redline_core.restore import recovery_planning as rp
from redline_core.restore import sidecar_classification as sc
from redline_core.restore.capture_models import CaptureItemOutcome
from redline_core.restore.recovery_models import SourceCondition
from redline_core.restore.sidecar import SIDECAR_SUFFIXES
from redline_core.restore.sidecar_classification import SidecarCondition, classify_sidecar, classify_sidecars

from tests.unit._restore_test_helpers import make_environment, make_target_backup


# == Direct classifier tests =================================================


def test_classify_sidecar_missing(tmp_path: Path):
    env = make_environment(tmp_path)

    result = classify_sidecar(env.db_path, "-wal")

    assert result.condition is SidecarCondition.MISSING
    assert result.suffix == "-wal"
    assert result.path == str(env.db_path) + "-wal"


def test_classify_sidecar_safe_regular(tmp_path: Path):
    env = make_environment(tmp_path)
    wal_path = Path(str(env.db_path) + "-wal")
    wal_path.write_bytes(b"wal-bytes")

    result = classify_sidecar(env.db_path, "-wal")

    assert result.condition is SidecarCondition.SAFE_REGULAR
    # Read-only: bytes untouched, nothing else created.
    assert wal_path.read_bytes() == b"wal-bytes"


def test_classify_sidecar_wrong_type_directory(tmp_path: Path):
    env = make_environment(tmp_path)
    shm_path = Path(str(env.db_path) + "-shm")
    shm_path.mkdir()
    (shm_path / "stray.txt").write_bytes(b"must never be read as sidecar bytes")

    result = classify_sidecar(env.db_path, "-shm")

    assert result.condition is SidecarCondition.WRONG_TYPE
    assert "not a regular file" in result.detail
    # Never recursively inspected -- contents untouched, no read attempted.
    assert (shm_path / "stray.txt").read_bytes() == b"must never be read as sidecar bytes"


def test_classify_sidecar_unsafe_simulated_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    journal_path = Path(str(env.db_path) + "-journal")
    journal_path.write_bytes(b"placeholder")  # real object present; only its "unsafe" flag is simulated

    monkeypatch.setattr(sc.fsutil, "is_unsafe_link", lambda st: True)

    result = classify_sidecar(env.db_path, "-journal")

    assert result.condition is SidecarCondition.UNSAFE
    assert "symlink, junction, or reparse point" in result.detail


def test_classify_sidecar_unsafe_dangling_never_created_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A dangling unsafe sidecar (symlink/junction/reparse point whose
    target does not exist): nothing is ever actually created at the
    sidecar path -- ``Path.exists()`` would report ``False`` throughout,
    exactly the blindness the locked ``find_present_sidecars()`` has and
    this classifier must not share. Mirrors
    ``test_capture_sidecars_dangling_unsafe_wal_recorded_never_followed``'s
    exact simulation technique."""
    env = make_environment(tmp_path)
    wal_path = Path(str(env.db_path) + "-wal")
    assert not wal_path.exists()

    real_lstat = sc.os.lstat
    sentinel_stat = real_lstat(env.db_path)  # stands in for the dangling object's own (link) metadata

    def _fake_lstat(path, *a, **kw):
        if Path(path) == wal_path:
            return sentinel_stat
        return real_lstat(path, *a, **kw)

    real_is_unsafe = sc.fsutil.is_unsafe_link

    def _fake_is_unsafe(st):
        if st is sentinel_stat:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(sc.os, "lstat", _fake_lstat)
    monkeypatch.setattr(sc.fsutil, "is_unsafe_link", _fake_is_unsafe)

    result = classify_sidecar(env.db_path, "-wal")

    assert result.condition is SidecarCondition.UNSAFE
    assert not wal_path.exists()  # Path.exists() would report False throughout -- never followed, never created


def test_classify_sidecar_cannot_inspect_folds_into_unsafe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An lstat() failure other than FileNotFoundError (e.g. permission
    denied) means the object's real type cannot be safely determined --
    conservatively classified UNSAFE rather than guessed at, mirroring
    recovery_classification._cannot_inspect_assessment()'s identical
    fail-closed doctrine."""
    env = make_environment(tmp_path)
    wal_path = Path(str(env.db_path) + "-wal")
    wal_path.write_bytes(b"content")

    real_lstat = sc.os.lstat

    def _fake_lstat(path, *a, **kw):
        if Path(path) == wal_path:
            raise PermissionError("simulated permission denied")
        return real_lstat(path, *a, **kw)

    monkeypatch.setattr(sc.os, "lstat", _fake_lstat)

    result = classify_sidecar(env.db_path, "-wal")

    assert result.condition is SidecarCondition.UNSAFE
    assert "could not be inspected" in result.detail


def test_classify_sidecars_returns_every_recognized_suffix(tmp_path: Path):
    env = make_environment(tmp_path)

    results = classify_sidecars(env.db_path)

    assert len(results) == len(SIDECAR_SUFFIXES)
    assert {r.suffix for r in results} == set(SIDECAR_SUFFIXES)
    assert all(r.condition is SidecarCondition.MISSING for r in results)


def test_classify_sidecar_never_opens_anything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    wal_path = Path(str(env.db_path) + "-wal")
    wal_path.write_bytes(b"content")

    def _forbidden_open(self, *args, **kwargs):
        raise AssertionError(f"classify_sidecar() must never open {self}")

    monkeypatch.setattr(Path, "open", _forbidden_open)

    result = classify_sidecar(env.db_path, "-wal")

    assert result.condition is SidecarCondition.SAFE_REGULAR


def test_classify_sidecar_independent_of_db_existence(tmp_path: Path):
    """DB missing and sidecar observation are independent facts -- the
    classifier's result for a given sidecar path never changes based on
    whether db_path itself currently exists."""
    env = make_environment(tmp_path)
    wal_path = Path(str(env.db_path) + "-wal")
    wal_path.write_bytes(b"orphaned wal debris")

    result_db_present = classify_sidecar(env.db_path, "-wal")
    env.db_path.unlink()
    result_db_missing = classify_sidecar(env.db_path, "-wal")

    assert result_db_present.condition is SidecarCondition.SAFE_REGULAR
    assert result_db_missing.condition is SidecarCondition.SAFE_REGULAR
    assert not env.db_path.exists()
    assert wal_path.read_bytes() == b"orphaned wal debris"


def test_classify_sidecar_never_mutates_filesystem(tmp_path: Path):
    env = make_environment(tmp_path)
    wal_path = Path(str(env.db_path) + "-wal")
    wal_path.write_bytes(b"content")
    entries_before = sorted(p.name for p in env.db_path.parent.iterdir())

    classify_sidecars(env.db_path)

    entries_after = sorted(p.name for p in env.db_path.parent.iterdir())
    assert entries_after == entries_before
    assert wal_path.read_bytes() == b"content"


# == A2-1 recovery planning integration ======================================


def _plan(env, backup_id):
    return rp.build_recovery_plan(
        backup_manager=env.backup_manager, db_path=env.db_path, config_dir=env.config_dir, backup_id=backup_id
    )


def test_recovery_plan_safe_regular_sidecar_does_not_block(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    wal_path = Path(str(env.db_path) + "-wal")
    wal_path.write_bytes(b"normal wal content")

    plan = _plan(env, target_id)

    wal_assessment = next(a for a in plan.sidecar_assessments if a.suffix == "-wal")
    assert wal_assessment.condition is SidecarCondition.SAFE_REGULAR
    assert plan.would_proceed is True
    assert not any("sidecar recovery blocked" in issue for issue in plan.blocking_issues)
    # Backward compatibility: the original presence-only field is unchanged.
    assert str(wal_path) in plan.sidecars_present


def test_recovery_plan_missing_sidecar_no_blocking(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    plan = _plan(env, target_id)

    assert all(a.condition is SidecarCondition.MISSING for a in plan.sidecar_assessments)
    assert len(plan.sidecar_assessments) == len(SIDECAR_SUFFIXES)
    assert plan.sidecars_present == ()
    assert plan.would_proceed is True
    assert not any("sidecar" in issue for issue in plan.blocking_issues)


def test_recovery_plan_wrong_type_sidecar_blocks(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    shm_path = Path(str(env.db_path) + "-shm")
    shm_path.mkdir()
    (shm_path / "stray.txt").write_bytes(b"must never be read")

    plan = _plan(env, target_id)

    shm_assessment = next(a for a in plan.sidecar_assessments if a.suffix == "-shm")
    assert shm_assessment.condition is SidecarCondition.WRONG_TYPE
    assert plan.would_proceed is False
    assert any("sidecar recovery blocked" in issue for issue in plan.blocking_issues)
    # No automatic disposition semantics are invented anywhere in planning --
    # the wrong-type object is left exactly as observed.
    assert shm_path.is_dir()
    assert (shm_path / "stray.txt").read_bytes() == b"must never be read"


def test_recovery_plan_unsafe_sidecar_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    journal_path = Path(str(env.db_path) + "-journal")
    journal_path.write_bytes(b"placeholder")

    monkeypatch.setattr(sc.fsutil, "is_unsafe_link", lambda st: True)

    plan = _plan(env, target_id)

    journal_assessment = next(a for a in plan.sidecar_assessments if a.suffix == "-journal")
    assert journal_assessment.condition is SidecarCondition.UNSAFE
    assert plan.would_proceed is False
    assert any("sidecar recovery blocked" in issue for issue in plan.blocking_issues)


def test_recovery_plan_dangling_unsafe_sidecar_blocks_and_reads_no_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Mandatory Prep2 regression: a dangling unsafe recognized sidecar --
    invisible to Path.exists() -- is still seen by the shared lstat-based
    classifier, is reported UNSAFE, and blocks recovery planning. No
    source bytes are ever read, and no mutation occurs."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    wal_path = Path(str(env.db_path) + "-wal")
    assert not wal_path.exists()

    real_lstat = sc.os.lstat
    sentinel_stat = real_lstat(env.db_path)

    def _fake_lstat(path, *a, **kw):
        if Path(path) == wal_path:
            return sentinel_stat
        return real_lstat(path, *a, **kw)

    real_is_unsafe = sc.fsutil.is_unsafe_link

    def _fake_is_unsafe(st):
        if st is sentinel_stat:
            return True
        return real_is_unsafe(st)

    real_open = Path.open

    def _guarded_open(self, *args, **kwargs):
        if self == wal_path:
            raise AssertionError(f"recovery planning must never open the unsafe sidecar {self}")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(sc.os, "lstat", _fake_lstat)
    monkeypatch.setattr(sc.fsutil, "is_unsafe_link", _fake_is_unsafe)
    monkeypatch.setattr(Path, "open", _guarded_open)

    plan = _plan(env, target_id)

    wal_assessment = next(a for a in plan.sidecar_assessments if a.suffix == "-wal")
    assert wal_assessment.condition is SidecarCondition.UNSAFE
    assert plan.would_proceed is False
    assert any("sidecar recovery blocked" in issue for issue in plan.blocking_issues)
    assert not wal_path.exists()  # never created, proving Path.exists()-style presence would have missed it
    # No mutation: the live database and config are untouched.
    assert env.db_path.exists()
    assert env.config_dir.exists()


def test_recovery_plan_db_missing_plus_unsafe_sidecar_still_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """DB-missing independence, ratified for planning: DB missing +
    unsafe/dangling sidecar must still classify the sidecar as unsafe and
    block recovery -- sidecar classification is never made conditional on
    DB existence."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.db_path.unlink()
    wal_path = Path(str(env.db_path) + "-wal")

    real_lstat = sc.os.lstat
    sentinel_stat = real_lstat(env.config_dir)

    def _fake_lstat(path, *a, **kw):
        if Path(path) == wal_path:
            return sentinel_stat
        return real_lstat(path, *a, **kw)

    real_is_unsafe = sc.fsutil.is_unsafe_link

    def _fake_is_unsafe(st):
        if st is sentinel_stat:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(sc.os, "lstat", _fake_lstat)
    monkeypatch.setattr(sc.fsutil, "is_unsafe_link", _fake_is_unsafe)

    plan = _plan(env, target_id)

    # DB side: architecture-defined MISSING/RECOVERABLE (parent intact) --
    # completely unaffected by the sidecar's own condition.
    assert plan.database.condition is SourceCondition.MISSING
    wal_assessment = next(a for a in plan.sidecar_assessments if a.suffix == "-wal")
    assert wal_assessment.condition is SidecarCondition.UNSAFE
    assert plan.would_proceed is False
    assert any("sidecar recovery blocked" in issue for issue in plan.blocking_issues)


def test_recovery_plan_sidecar_assessments_backward_compatible_shape(tmp_path: Path):
    """sidecars_present is preserved unchanged; sidecar_assessments is
    additive -- existing consumers reading only sidecars_present remain
    valid."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    wal_path = Path(str(env.db_path) + "-wal")
    wal_path.write_bytes(b"content")

    plan = _plan(env, target_id)

    assert isinstance(plan.sidecars_present, tuple)
    assert all(isinstance(p, str) for p in plan.sidecars_present)
    assert isinstance(plan.sidecar_assessments, tuple)
    assert len(plan.sidecar_assessments) == len(SIDECAR_SUFFIXES)


# == A2-2 capture integration: shared classifier reuse, semantics unchanged =


def test_capture_sidecars_wrong_type_directory_recorded(tmp_path: Path):
    """Mandatory Prep2 regression: A2-2 capture must record a wrong-type
    sidecar as WRONG_TYPE_RECORDED via the shared classifier, with no
    recursive traversal of its contents."""
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"
    shm_path = Path(str(env.db_path) + "-shm")
    shm_path.mkdir()
    (shm_path / "stray.txt").write_bytes(b"must never be captured as sidecar bytes")

    records = cp.capture_sidecars(env.db_path, payload_root)

    shm_records = [r for r in records if r.item_key == "sidecar:-shm"]
    assert len(shm_records) == 1
    assert shm_records[0].outcome is CaptureItemOutcome.WRONG_TYPE_RECORDED
    assert shm_records[0].captured_relative_path is None
    assert not (payload_root / "sidecars").exists()
    assert (shm_path / "stray.txt").read_bytes() == b"must never be captured as sidecar bytes"


def test_capture_sidecars_consumes_shared_classifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Proves single-policy-source wiring directly: capture_sidecars()
    dispatches from redline_core.restore.sidecar_classification.
    classify_sidecars()'s own output, not an independent, second copy of
    the lstat/unsafe/type dispatch."""
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"

    calls: list[Path] = []
    real_classify_sidecars = cp.classify_sidecars

    def _spy_classify_sidecars(db_path):
        calls.append(db_path)
        return real_classify_sidecars(db_path)

    monkeypatch.setattr(cp, "classify_sidecars", _spy_classify_sidecars)

    cp.capture_sidecars(env.db_path, payload_root)

    assert calls == [env.db_path]


def test_capture_sidecars_missing_still_produces_no_record(tmp_path: Path):
    """Unchanged A2-2 semantics: a MISSING sidecar (via the shared
    classifier now, not the old inline lstat loop) still produces no
    capture record at all -- exactly the pre-refactor behavior."""
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"

    records = cp.capture_sidecars(env.db_path, payload_root)

    assert records == ()


def test_capture_sidecars_safe_regular_still_captures_verified(tmp_path: Path):
    """Unchanged A2-2 semantics: a SAFE_REGULAR sidecar still goes through
    the existing best-effort capture path and is CAPTURED_VERIFIED --
    proving the shared classifier's SAFE_REGULAR outcome does not by
    itself introduce a new blocking condition or change capture's own
    established behavior."""
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"
    Path(str(env.db_path) + "-wal").write_bytes(b"wal-bytes")

    records = cp.capture_sidecars(env.db_path, payload_root)

    assert len(records) == 1
    assert records[0].outcome is CaptureItemOutcome.CAPTURED_VERIFIED
