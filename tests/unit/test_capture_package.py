"""Tests for redline_core.restore.capture_package (Mission 1B-A2-2):
per-slot classify-then-capture dispatch (database, config, sidecars), plus
staging/manifest/seal/publish package mechanics. Reuses
tests/unit/_restore_test_helpers.py's Environment exactly as A2-1's own
test suite does. Unsafe-link cases use the established
fsutil.is_unsafe_link monkeypatch convention (tests/unit/test_backup_paths.py)
rather than real symlink/junction creation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redline_core.config.loader import REQUIRED_FILES
from redline_core.restore import capture_package as cp
from redline_core.restore.capture_exceptions import CapturePackageCollisionError, CaptureSealFailedError
from redline_core.restore.capture_models import CaptureItemOutcome

from tests.unit._restore_test_helpers import make_environment


def _fixed_clock():
    return datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)


# -- capture_database_slot -----------------------------------------------------------


def test_capture_database_slot_healthy_regular_file(tmp_path: Path):
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"

    record = cp.capture_database_slot(env.db_path, payload_root)

    assert record.item_key == "database"
    assert record.outcome is CaptureItemOutcome.CAPTURED_VERIFIED
    assert record.captured_relative_path is not None
    assert (payload_root / "database" / env.db_path.name).exists()


def test_capture_database_slot_missing(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.unlink()
    payload_root = tmp_path / "payload"

    record = cp.capture_database_slot(env.db_path, payload_root)

    assert record.outcome is CaptureItemOutcome.MISSING
    assert record.captured_relative_path is None


def test_capture_database_slot_directory_records_shallow_evidence_only(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.unlink()
    env.db_path.mkdir()
    (env.db_path / "not_a_database.bin").write_bytes(b"should never be treated as candidate DB bytes")
    payload_root = tmp_path / "payload"

    record = cp.capture_database_slot(env.db_path, payload_root)

    assert record.outcome is CaptureItemOutcome.WRONG_TYPE_RECORDED
    assert record.captured_relative_path is None
    assert "not_a_database.bin" in record.detail
    # Never actually copied the directory's contents anywhere.
    assert not (payload_root / "database").exists()


def test_capture_database_slot_unsafe_link_never_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"

    monkeypatch.setattr(cp.fsutil, "is_unsafe_link", lambda st: True)

    record = cp.capture_database_slot(env.db_path, payload_root)

    assert record.outcome is CaptureItemOutcome.UNSAFE_OBJECT_RECORDED
    assert record.unsafe_object is True
    assert record.captured_relative_path is None
    assert not (payload_root / "database").exists()


def test_capture_database_slot_degraded_but_readable_still_captures_bytes(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted, not a real sqlite file, but readable and stable")
    payload_root = tmp_path / "payload"

    record = cp.capture_database_slot(env.db_path, payload_root)

    # Capture is byte-preservation, not content validation -- a corrupt but
    # stable, fully-readable file still verifies.
    assert record.outcome is CaptureItemOutcome.CAPTURED_VERIFIED


# -- capture_config_slot --------------------------------------------------------------


def test_capture_config_slot_six_safe_files(tmp_path: Path):
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"

    directory_record, file_records, inventory = cp.capture_config_slot(env.config_dir, payload_root)

    assert directory_record is None
    assert len(file_records) == 6
    assert all(r.outcome is CaptureItemOutcome.CAPTURED_VERIFIED for r in file_records)
    assert set(inventory) == set(REQUIRED_FILES.values())


def test_capture_config_slot_one_missing_required_file(tmp_path: Path):
    env = make_environment(tmp_path)
    (env.config_dir / "paths.yaml").unlink()
    payload_root = tmp_path / "payload"

    directory_record, file_records, inventory = cp.capture_config_slot(env.config_dir, payload_root)

    missing = [r for r in file_records if r.item_key == "config:paths.yaml"]
    assert missing[0].outcome is CaptureItemOutcome.MISSING
    others = [r for r in file_records if r.item_key != "config:paths.yaml"]
    assert all(r.outcome is CaptureItemOutcome.CAPTURED_VERIFIED for r in others)


def test_capture_config_slot_wrong_type_required_file(tmp_path: Path):
    env = make_environment(tmp_path)
    (env.config_dir / "assets.yaml").unlink()
    (env.config_dir / "assets.yaml").mkdir()
    payload_root = tmp_path / "payload"

    _, file_records, _ = cp.capture_config_slot(env.config_dir, payload_root)

    wrong_type = [r for r in file_records if r.item_key == "config:assets.yaml"][0]
    assert wrong_type.outcome is CaptureItemOutcome.WRONG_TYPE_RECORDED


def test_capture_config_slot_unsafe_link_file_never_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    target_file = env.config_dir / sorted(REQUIRED_FILES.values())[0]
    target_ino_dev = (target_file.stat().st_ino, target_file.stat().st_dev)
    real_is_unsafe = cp.fsutil.is_unsafe_link

    def _fake(st):
        if (st.st_ino, st.st_dev) == target_ino_dev:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(cp.fsutil, "is_unsafe_link", _fake)
    payload_root = tmp_path / "payload"

    _, file_records, _ = cp.capture_config_slot(env.config_dir, payload_root)

    unsafe = [r for r in file_records if r.item_key == f"config:{target_file.name}"][0]
    assert unsafe.outcome is CaptureItemOutcome.UNSAFE_OBJECT_RECORDED
    assert unsafe.unsafe_object is True
    assert not (payload_root / "config" / target_file.name).exists()


def test_capture_config_slot_unsafe_link_directory_itself_never_enumerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"

    monkeypatch.setattr(cp.fsutil, "is_unsafe_link", lambda st: True)

    directory_record, file_records, inventory = cp.capture_config_slot(env.config_dir, payload_root)

    assert directory_record.outcome is CaptureItemOutcome.UNSAFE_OBJECT_RECORDED
    assert len(file_records) == 6
    assert all(r.outcome is CaptureItemOutcome.UNSAFE_OBJECT_RECORDED for r in file_records)
    assert inventory == ()


def test_capture_config_slot_post_enumeration_substitution_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Mission 1B-A2-2 safety correction (Correction 2): exercises the
    POST-ENUMERATION recheck specifically -- distinct from
    test_capture_config_slot_unsafe_link_directory_itself_never_enumerated
    above, whose blanket is_unsafe_link patch trips on the very first
    (pre-enumeration) lstat() and never reaches iterdir() or this recheck
    branch at all.

    config_dir passes the pre-enumeration lstat/safety check (the first
    lstat() call below returns the real, safe stat), a safe non-recursive
    iterdir() enumeration then actually runs, and only the *second*
    lstat() call -- the post-enumeration recheck -- observes the
    container's identity as changed, simulating a substitution landing in
    the exact window between the pre-enumeration check and iterdir()
    itself. Proves: the recheck runs (at least two lstat() calls on
    config_dir), the just-obtained enumeration is discarded (never
    returned as this directory's trustworthy inventory), the container
    result is CHANGED_DURING_CAPTURE, all six required config slots are
    truthfully represented as not individually inspected, and no per-file
    capture was ever attempted from the stale/substituted observation."""
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"

    real_lstat = cp.os.lstat
    call_count = {"n": 0}

    def _fake_lstat(path, *a, **kw):
        if Path(path) == env.config_dir:
            call_count["n"] += 1
            if call_count["n"] >= 2:
                # Simulate the container's identity changing strictly
                # between the pre-enumeration check (call #1) and the
                # post-enumeration recheck (call #2) -- i.e. exactly the
                # iterdir() window this correction closes.
                st = real_lstat(path, *a, **kw)

                class _MutatedStat:
                    def __getattr__(self, name):
                        return getattr(st, name)

                    @property
                    def st_mtime_ns(self):
                        return st.st_mtime_ns + 999999999

                return _MutatedStat()
        return real_lstat(path, *a, **kw)

    monkeypatch.setattr(cp.os, "lstat", _fake_lstat)

    directory_record, file_records, inventory = cp.capture_config_slot(env.config_dir, payload_root)

    # Proves the post-enumeration recheck actually ran (both the
    # pre-enumeration check and the recheck lstat() calls happened, with
    # iterdir() sandwiched between them) -- not just the pre-enumeration
    # branch.
    assert call_count["n"] >= 2
    assert directory_record.outcome is CaptureItemOutcome.CHANGED_DURING_CAPTURE
    assert "identity changed between the pre-enumeration safety check and" in directory_record.detail
    assert len(file_records) == 6
    assert all(r.outcome is CaptureItemOutcome.CHANGED_DURING_CAPTURE for r in file_records)
    assert all(r.captured_relative_path is None for r in file_records)
    assert inventory == ()  # the just-obtained enumeration is discarded, never trusted as this directory's inventory
    assert not (payload_root / "config").exists()  # no per-file capture was ever attempted from the stale observation


def test_capture_config_slot_missing_directory(tmp_path: Path):
    env = make_environment(tmp_path)
    import shutil

    shutil.rmtree(env.config_dir)
    payload_root = tmp_path / "payload"

    directory_record, file_records, inventory = cp.capture_config_slot(env.config_dir, payload_root)

    assert directory_record.outcome is CaptureItemOutcome.MISSING
    assert len(file_records) == 6
    assert all(r.outcome is CaptureItemOutcome.MISSING for r in file_records)
    assert inventory == ()


def test_capture_config_slot_records_unexpected_entry_in_inventory(tmp_path: Path):
    env = make_environment(tmp_path)
    (env.config_dir / "unexpected_leftover.txt").write_text("not a required file")
    payload_root = tmp_path / "payload"

    _, _, inventory = cp.capture_config_slot(env.config_dir, payload_root)

    assert "unexpected_leftover.txt" in inventory
    assert set(REQUIRED_FILES.values()).issubset(set(inventory))


# -- capture_sidecars ------------------------------------------------------------------


def test_capture_sidecars_none_present(tmp_path: Path):
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"

    records = cp.capture_sidecars(env.db_path, payload_root)

    assert records == ()


def test_capture_sidecars_wal_shm_journal(tmp_path: Path):
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"
    for suffix, content in (("-wal", b"wal-bytes"), ("-shm", b"shm-bytes"), ("-journal", b"journal-bytes")):
        Path(str(env.db_path) + suffix).write_bytes(content)

    records = cp.capture_sidecars(env.db_path, payload_root)

    assert len(records) == 3
    keys = {r.item_key for r in records}
    assert keys == {"sidecar:-wal", "sidecar:-shm", "sidecar:-journal"}
    assert all(r.outcome is CaptureItemOutcome.CAPTURED_VERIFIED for r in records)
    # Prove none was moved/deleted/merged -- originals remain untouched.
    assert Path(str(env.db_path) + "-wal").read_bytes() == b"wal-bytes"
    assert Path(str(env.db_path) + "-shm").read_bytes() == b"shm-bytes"
    assert Path(str(env.db_path) + "-journal").read_bytes() == b"journal-bytes"


def test_capture_sidecars_present_when_db_missing(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.unlink()
    Path(str(env.db_path) + "-wal").write_bytes(b"orphaned")
    payload_root = tmp_path / "payload"

    records = cp.capture_sidecars(env.db_path, payload_root)

    assert len(records) == 1
    assert records[0].outcome is CaptureItemOutcome.CAPTURED_VERIFIED


def test_capture_sidecars_unreadable_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    wal_path = Path(str(env.db_path) + "-wal")
    wal_path.write_bytes(b"content")
    payload_root = tmp_path / "payload"

    real_open = Path.open

    def _fake_open(self, *args, **kwargs):
        if self == wal_path and "rb" in args:
            raise PermissionError("simulated")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _fake_open)

    records = cp.capture_sidecars(env.db_path, payload_root)

    assert records[0].outcome is CaptureItemOutcome.UNREADABLE


# -- Mission 1B-A2-2 safety correction: Correction 4 (sidecar discovery TOCTOU) -------


def test_capture_sidecars_dangling_unsafe_wal_recorded_never_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A dangling unsafe WAL sidecar (a symlink/junction/reparse point
    whose target does not exist) is invisible to the locked
    find_present_sidecars() -- Path.exists() follows the link and reports
    False for a broken target -- but must still be captured as
    UNSAFE_OBJECT_RECORDED evidence. Simulated here without a real
    privileged symlink: os.lstat() is faked to succeed for the exact WAL
    sidecar path (nothing is ever actually created on disk there, so
    Path.exists() genuinely reports False throughout, exactly like a real
    dangling reparse point), and that fake stat is flagged unsafe."""
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"
    wal_path = Path(str(env.db_path) + "-wal")
    assert not wal_path.exists()  # nothing real ever created here -- simulating a dangling target

    real_lstat = cp.os.lstat
    sentinel_stat = real_lstat(env.db_path)  # stands in for the dangling object's own (link) metadata

    def _fake_lstat(path, *a, **kw):
        if Path(path) == wal_path:
            return sentinel_stat
        return real_lstat(path, *a, **kw)

    real_is_unsafe = cp.fsutil.is_unsafe_link

    def _fake_is_unsafe(st):
        if st is sentinel_stat:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(cp.os, "lstat", _fake_lstat)
    monkeypatch.setattr(cp.fsutil, "is_unsafe_link", _fake_is_unsafe)

    records = cp.capture_sidecars(env.db_path, payload_root)

    wal_records = [r for r in records if r.item_key == "sidecar:-wal"]
    assert len(wal_records) == 1
    assert wal_records[0].outcome is CaptureItemOutcome.UNSAFE_OBJECT_RECORDED
    assert wal_records[0].unsafe_object is True
    assert wal_records[0].captured_relative_path is None
    assert not wal_path.exists()  # Path.exists() would have reported False throughout -- never followed
    assert not (payload_root / "sidecars").exists()  # never opened, never copied anywhere


def test_capture_sidecars_dangling_unsafe_shm_recorded_never_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Same proof as the WAL case above, for the SHM suffix -- confirms
    the fix applies uniformly across SIDECAR_SUFFIXES, not just one."""
    env = make_environment(tmp_path)
    payload_root = tmp_path / "payload"
    shm_path = Path(str(env.db_path) + "-shm")
    assert not shm_path.exists()

    real_lstat = cp.os.lstat
    sentinel_stat = real_lstat(env.db_path)

    def _fake_lstat(path, *a, **kw):
        if Path(path) == shm_path:
            return sentinel_stat
        return real_lstat(path, *a, **kw)

    real_is_unsafe = cp.fsutil.is_unsafe_link

    def _fake_is_unsafe(st):
        if st is sentinel_stat:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(cp.os, "lstat", _fake_lstat)
    monkeypatch.setattr(cp.fsutil, "is_unsafe_link", _fake_is_unsafe)

    records = cp.capture_sidecars(env.db_path, payload_root)

    shm_records = [r for r in records if r.item_key == "sidecar:-shm"]
    assert len(shm_records) == 1
    assert shm_records[0].outcome is CaptureItemOutcome.UNSAFE_OBJECT_RECORDED
    assert not shm_path.exists()


def test_capture_sidecars_dangling_unsafe_sidecar_recorded_even_when_db_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DB missing + a dangling unsafe sidecar: both facts are recorded
    truthfully and independently -- one does not mask or absorb the
    other."""
    env = make_environment(tmp_path)
    env.db_path.unlink()
    payload_root = tmp_path / "payload"
    wal_path = Path(str(env.db_path) + "-wal")

    real_lstat = cp.os.lstat
    sentinel_stat = real_lstat(env.config_dir)

    def _fake_lstat(path, *a, **kw):
        if Path(path) == wal_path:
            return sentinel_stat
        return real_lstat(path, *a, **kw)

    real_is_unsafe = cp.fsutil.is_unsafe_link

    def _fake_is_unsafe(st):
        if st is sentinel_stat:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(cp.os, "lstat", _fake_lstat)
    monkeypatch.setattr(cp.fsutil, "is_unsafe_link", _fake_is_unsafe)

    db_record = cp.capture_database_slot(env.db_path, payload_root)
    sidecar_records = cp.capture_sidecars(env.db_path, payload_root)

    assert db_record.outcome is CaptureItemOutcome.MISSING
    wal_records = [r for r in sidecar_records if r.item_key == "sidecar:-wal"]
    assert len(wal_records) == 1
    assert wal_records[0].outcome is CaptureItemOutcome.UNSAFE_OBJECT_RECORDED


# -- staging / manifest / seal / publish ----------------------------------------------


def _stage_and_assessments():
    return {"condition": "HEALTHY", "feasibility": "NOT_APPLICABLE", "blocking_reason": None,
            "capture_required": False, "disposition_required": False, "disposition_description": None, "details": []}


def test_build_staged_capture_manifest_shape(tmp_path: Path):
    env = make_environment(tmp_path)
    staging_parent = env.backup_root / ".staging_capture"
    staging_parent.mkdir(parents=True)

    staged = cp.build_staged_capture(
        db_path=env.db_path, config_dir=env.config_dir, staging_parent=staging_parent, clock=_fixed_clock,
        reason="unit test", database_assessment=_stage_and_assessments(), config_assessment=_stage_and_assessments(),
    )

    manifest = json.loads((staged.staging_dir / cp.MANIFEST_FILENAME).read_bytes())
    assert manifest["schema_tag"] == "dsc1"
    assert manifest["capture_id"] == staged.capture_id
    assert manifest["database"]["outcome"] == "CAPTURED_VERIFIED"
    assert len(manifest["config"]["files"]) == 6
    assert manifest["config"]["directory"] is None
    assert manifest["sidecars"] == []
    assert (staged.staging_dir / cp.MARKER_FILENAME).exists()
    assert (staged.staging_dir / cp.MANIFEST_SHA256_FILENAME).exists()


def test_publish_staged_capture_moves_to_final_location(tmp_path: Path):
    env = make_environment(tmp_path)
    staging_parent = env.backup_root / ".staging_capture"
    staging_parent.mkdir(parents=True)
    staged = cp.build_staged_capture(
        db_path=env.db_path, config_dir=env.config_dir, staging_parent=staging_parent, clock=_fixed_clock,
        reason=None, database_assessment=_stage_and_assessments(), config_assessment=_stage_and_assessments(),
    )

    final_dir = cp.publish_staged_capture(staged, capture_root=env.backup_root)

    assert final_dir == env.backup_root / cp.DEGRADED_SOURCE_CAPTURES_DIRNAME / staged.capture_id
    assert final_dir.is_dir()
    assert not staged.staging_dir.exists()
    assert (final_dir / cp.MARKER_FILENAME).exists()


def test_publish_staged_capture_refuses_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    staging_parent = env.backup_root / ".staging_capture"
    staging_parent.mkdir(parents=True)

    fixed_capture_id = "dsc1-20260817T120000Z-aaaaaaaaaaaa"
    monkeypatch.setattr(cp, "build_capture_id", lambda moment: fixed_capture_id)

    def _build():
        return cp.build_staged_capture(
            db_path=env.db_path, config_dir=env.config_dir, staging_parent=staging_parent, clock=_fixed_clock,
            reason=None, database_assessment=_stage_and_assessments(), config_assessment=_stage_and_assessments(),
        )

    staged1 = _build()
    cp.publish_staged_capture(staged1, capture_root=env.backup_root)

    staged2 = _build()
    assert staged2.capture_id == fixed_capture_id
    with pytest.raises(CapturePackageCollisionError):
        cp.publish_staged_capture(staged2, capture_root=env.backup_root)


def _build_real_staged_capture(env, staging_parent: Path):
    staging_parent.mkdir(parents=True, exist_ok=True)
    return cp.build_staged_capture(
        db_path=env.db_path, config_dir=env.config_dir, staging_parent=staging_parent, clock=_fixed_clock,
        reason=None, database_assessment=_stage_and_assessments(), config_assessment=_stage_and_assessments(),
    )


# -- Mission 1B-A2-2 safety correction: Correction 5 (seal-time self-verification) ----


def test_seal_self_consistency_check_catches_size_mismatch(tmp_path: Path):
    """Appending bytes changes both size *and* content, so this exercises
    (and is caught by) the size-mismatch branch specifically -- confirmed
    by asserting on the exact "bytes on disk but the manifest records"
    message that branch alone produces, distinguishing it from the
    separate SHA-256-mismatch branch/test below."""
    env = make_environment(tmp_path)
    staged = _build_real_staged_capture(env, env.backup_root / ".staging_capture")

    db_payload = staged.staging_dir / "payload" / "database" / env.db_path.name
    original = db_payload.read_bytes()
    db_payload.write_bytes(original + b"TAMPERED")
    assert db_payload.stat().st_size != len(original)  # this tamper deliberately changes size

    with pytest.raises(CaptureSealFailedError) as exc_info:
        cp._verify_staged_capture_self_consistency(staged.staging_dir, staged.manifest)

    assert "bytes on disk but the manifest records" in str(exc_info.value)
    assert "sha256 does not match" not in str(exc_info.value)


def test_seal_self_consistency_check_catches_sha256_mismatch(tmp_path: Path):
    """Mission 1B-A2-2 safety-correction gap closure: proves the
    independent SHA-256 re-verification branch specifically, isolated
    from the size check above -- the payload is tampered *in place*
    (one byte flipped) so its length, and therefore the manifest's
    recorded size_bytes, is left completely unchanged; only the content
    (and therefore the hash) differs. If the size check fired instead of
    the SHA-256 check, this tamper would slip through undetected, since
    size alone cannot distinguish "same bytes" from "different bytes of
    the same length." The exception message is asserted to name the
    SHA-256 branch specifically, not the size branch."""
    env = make_environment(tmp_path)
    staged = _build_real_staged_capture(env, env.backup_root / ".staging_capture")

    db_payload = staged.staging_dir / "payload" / "database" / env.db_path.name
    original = db_payload.read_bytes()
    mutated = bytearray(original)
    mutated[0] ^= 0xFF  # flip one byte in place -- content differs, length does not
    db_payload.write_bytes(bytes(mutated))

    assert db_payload.stat().st_size == len(original)  # same-size tamper, proven
    assert bytes(mutated) != original  # content genuinely differs

    with pytest.raises(CaptureSealFailedError) as exc_info:
        cp._verify_staged_capture_self_consistency(staged.staging_dir, staged.manifest)

    # Proves failure occurred specifically because recorded SHA-256 !=
    # actual SHA-256 -- not because of a size mismatch (there is none).
    assert "sha256 does not match" in str(exc_info.value)
    assert "bytes on disk but the manifest records" not in str(exc_info.value)


def test_seal_self_consistency_check_catches_tampered_manifest_sha256_sidecar(tmp_path: Path):
    env = make_environment(tmp_path)
    staged = _build_real_staged_capture(env, env.backup_root / ".staging_capture")

    (staged.staging_dir / cp.MANIFEST_SHA256_FILENAME).write_text("0" * 64, encoding="ascii")

    with pytest.raises(CaptureSealFailedError):
        cp._verify_staged_capture_self_consistency(staged.staging_dir, staged.manifest)


def test_seal_self_consistency_check_catches_tampered_manifest_bytes(tmp_path: Path):
    env = make_environment(tmp_path)
    staged = _build_real_staged_capture(env, env.backup_root / ".staging_capture")

    manifest_path = staged.staging_dir / cp.MANIFEST_FILENAME
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")  # corrupted after the .sha256 sidecar was written

    with pytest.raises(CaptureSealFailedError):
        cp._verify_staged_capture_self_consistency(staged.staging_dir, staged.manifest)


def test_seal_self_consistency_check_catches_stray_payload_for_missing_item(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.unlink()  # the database record will be MISSING -> no captured_relative_path
    staged = _build_real_staged_capture(env, env.backup_root / ".staging_capture")
    assert staged.database.outcome is CaptureItemOutcome.MISSING

    # Plant a stray file at the location the database payload *would* have
    # used had it actually been captured -- this must contradict the
    # manifest's own "nothing was captured" claim and refuse to seal.
    stray_path = staged.staging_dir / "payload" / "database" / env.db_path.name
    stray_path.parent.mkdir(parents=True, exist_ok=True)
    stray_path.write_bytes(b"should never be here")

    with pytest.raises(CaptureSealFailedError):
        cp._verify_staged_capture_self_consistency(staged.staging_dir, staged.manifest)


def test_seal_self_consistency_passes_for_legitimate_missing_no_payload_records(tmp_path: Path):
    """Legitimate MISSING/UNSAFE/WRONG_TYPE no-payload records must still
    seal successfully -- the strengthened checks reject only a genuine
    contradiction between the manifest and the filesystem, never an
    honestly-recorded absence."""
    env = make_environment(tmp_path)
    env.db_path.unlink()
    import shutil

    shutil.rmtree(env.config_dir)

    staged = _build_real_staged_capture(env, env.backup_root / ".staging_capture")  # must not raise

    assert staged.database.outcome is CaptureItemOutcome.MISSING
    assert staged.config_directory.outcome is CaptureItemOutcome.MISSING
    assert (staged.staging_dir / cp.MARKER_FILENAME).exists()


def test_seal_self_consistency_check_catches_missing_captured_file(tmp_path: Path):
    env = make_environment(tmp_path)
    staging_parent = env.backup_root / ".staging_capture"
    staging_parent.mkdir(parents=True)

    manifest = {
        "capture_id": "dsc1-20260817T120000Z-000000000000",
        "database": {"captured_relative_path": "payload/database/redline.db", "size_bytes": 100},
        "config": {"directory": None, "files": []},
        "sidecars": [],
    }
    staging_dir = staging_parent / "fake"
    staging_dir.mkdir()

    with pytest.raises(CaptureSealFailedError):
        cp._verify_staged_capture_self_consistency(staging_dir, manifest)
