"""Tests for redline_core.restore.recovery_stability (Mission 1B-A2-3):
the reusable, read-only target-level stability primitive.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from redline_core.restore.capture_models import CaptureItemOutcome, CaptureItemRecord, StatFingerprint
from redline_core.restore.recovery_stability import (
    check_config_inventory_stability,
    check_target_stability,
    expected_state_from_capture_record,
    expected_state_missing,
)


def _record(outcome: CaptureItemOutcome, *, sha256=None, size_bytes=None, stat_fingerprint=None, item_key="database") -> CaptureItemRecord:
    return CaptureItemRecord(
        item_key=item_key, source_path="/does/not/matter", outcome=outcome, captured_relative_path=None,
        size_bytes=size_bytes, sha256=sha256, stat_fingerprint=stat_fingerprint, unsafe_object=False, detail="",
    )


def _fp(path: Path) -> StatFingerprint:
    import os
    st = os.lstat(path)
    return StatFingerprint(size=st.st_size, mtime_ns=st.st_mtime_ns, ino=getattr(st, "st_ino", None) or None, dev=getattr(st, "st_dev", None) or None)


# -- expected_state_from_capture_record() ------------------------------------------


def test_expected_state_captured_verified_is_hash_kind():
    record = _record(CaptureItemOutcome.CAPTURED_VERIFIED, sha256="a" * 64, size_bytes=10)
    expected = expected_state_from_capture_record(record)
    assert expected.kind == "hash"
    assert expected.expected_sha256 == "a" * 64
    assert expected.expected_size == 10


def test_expected_state_captured_unverified_is_hash_kind():
    record = _record(CaptureItemOutcome.CAPTURED_UNVERIFIED, sha256="b" * 64, size_bytes=20)
    expected = expected_state_from_capture_record(record)
    assert expected.kind == "hash"


def test_expected_state_missing_outcome_is_missing_kind():
    record = _record(CaptureItemOutcome.MISSING)
    expected = expected_state_from_capture_record(record)
    assert expected.kind == "missing"


def test_expected_state_unreadable_with_fingerprint_is_fingerprint_kind():
    fp = StatFingerprint(size=1, mtime_ns=2, ino=3, dev=4)
    record = _record(CaptureItemOutcome.UNREADABLE, stat_fingerprint=fp)
    expected = expected_state_from_capture_record(record)
    assert expected.kind == "fingerprint"
    assert expected.expected_regular is True
    assert expected.expected_unsafe is False


def test_expected_state_unreadable_without_fingerprint_is_insufficient_evidence():
    record = _record(CaptureItemOutcome.UNREADABLE, stat_fingerprint=None)
    expected = expected_state_from_capture_record(record)
    assert expected.kind == "insufficient_evidence"


def test_expected_state_unreadable_partial_sha256_never_used_as_hash():
    """A partial-read UNREADABLE record can carry a partial sha256 --
    never treated as a full-file hash comparison."""
    fp = StatFingerprint(size=5, mtime_ns=6, ino=7, dev=8)
    record = _record(CaptureItemOutcome.UNREADABLE, sha256="c" * 64, size_bytes=3, stat_fingerprint=fp)
    expected = expected_state_from_capture_record(record)
    assert expected.kind == "fingerprint"
    assert expected.expected_sha256 is None


def test_expected_state_wrong_type_recorded_is_fingerprint_kind_not_regular():
    fp = StatFingerprint(size=0, mtime_ns=1, ino=2, dev=3)
    record = _record(CaptureItemOutcome.WRONG_TYPE_RECORDED, stat_fingerprint=fp)
    expected = expected_state_from_capture_record(record)
    assert expected.kind == "fingerprint"
    assert expected.expected_regular is False
    assert expected.expected_unsafe is False


def test_expected_state_unsafe_object_recorded_is_fingerprint_kind_unsafe():
    fp = StatFingerprint(size=0, mtime_ns=1, ino=2, dev=3)
    record = _record(CaptureItemOutcome.UNSAFE_OBJECT_RECORDED, stat_fingerprint=fp)
    expected = expected_state_from_capture_record(record)
    assert expected.kind == "fingerprint"
    assert expected.expected_unsafe is True


def test_expected_state_changed_during_capture_raises_value_error():
    record = _record(CaptureItemOutcome.CHANGED_DURING_CAPTURE)
    with pytest.raises(ValueError):
        expected_state_from_capture_record(record)


# -- check_target_stability(): missing/present drift --------------------------------


def test_stability_missing_still_missing_confirmed(tmp_path: Path):
    target = tmp_path / "gone"
    result = check_target_stability(target, expected_state_missing(detail="was missing"), target_key="t")
    assert result.confirmed is True


def test_stability_missing_but_now_present_is_mismatch(tmp_path: Path):
    target = tmp_path / "now-here"
    target.write_bytes(b"surprise")
    result = check_target_stability(target, expected_state_missing(detail="was missing"), target_key="t")
    assert result.confirmed is False


def test_stability_present_but_now_missing_is_mismatch(tmp_path: Path):
    target = tmp_path / "vanished.db"
    target.write_bytes(b"hello world")
    expected = expected_state_from_capture_record(_record(CaptureItemOutcome.CAPTURED_VERIFIED, sha256="deadbeef", size_bytes=11))
    target.unlink()
    result = check_target_stability(target, expected, target_key="t")
    assert result.confirmed is False


# -- check_target_stability(): hash-based drift --------------------------------------


def test_stability_hash_matches_confirms(tmp_path: Path):
    import hashlib
    target = tmp_path / "db.sqlite"
    content = b"stable content"
    target.write_bytes(content)
    sha256 = hashlib.sha256(content).hexdigest()
    record = _record(CaptureItemOutcome.CAPTURED_VERIFIED, sha256=sha256, size_bytes=len(content))
    result = check_target_stability(target, expected_state_from_capture_record(record), target_key="database")
    assert result.confirmed is True


def test_stability_hash_byte_drift_is_mismatch(tmp_path: Path):
    import hashlib
    target = tmp_path / "db.sqlite"
    original = b"original bytes"
    target.write_bytes(original)
    sha256 = hashlib.sha256(original).hexdigest()
    record = _record(CaptureItemOutcome.CAPTURED_VERIFIED, sha256=sha256, size_bytes=len(original))
    target.write_bytes(b"drifted bytes!!")
    result = check_target_stability(target, expected_state_from_capture_record(record), target_key="database")
    assert result.confirmed is False


def test_stability_hash_type_changed_to_directory_is_mismatch(tmp_path: Path):
    import hashlib
    target = tmp_path / "was-a-file"
    content = b"x"
    target.write_bytes(content)
    sha256 = hashlib.sha256(content).hexdigest()
    record = _record(CaptureItemOutcome.CAPTURED_VERIFIED, sha256=sha256, size_bytes=1)
    target.unlink()
    target.mkdir()
    result = check_target_stability(target, expected_state_from_capture_record(record), target_key="database")
    assert result.confirmed is False


# -- check_target_stability(): fingerprint-only drift --------------------------------


def test_stability_fingerprint_matches_confirms(tmp_path: Path):
    target = tmp_path / "wrong-type-object"
    target.mkdir()
    fp = _fp(target)
    from redline_core.restore.recovery_stability import ExpectedTargetState
    expected = ExpectedTargetState(kind="fingerprint", expected_fingerprint=fp, expected_unsafe=False, expected_regular=False, detail="dir baseline")
    result = check_target_stability(target, expected, target_key="database")
    assert result.confirmed is True


def test_stability_fingerprint_size_drift_is_mismatch(tmp_path: Path):
    target = tmp_path / "unreadable.db"
    target.write_bytes(b"12345")
    fp = _fp(target)
    record = _record(CaptureItemOutcome.UNREADABLE, stat_fingerprint=fp)
    target.write_bytes(b"1234567890")  # size changed
    result = check_target_stability(target, expected_state_from_capture_record(record), target_key="database")
    assert result.confirmed is False


def test_stability_insufficient_evidence_is_always_mismatch(tmp_path: Path):
    target = tmp_path / "whatever"
    target.write_bytes(b"content")
    record = _record(CaptureItemOutcome.UNREADABLE, stat_fingerprint=None)
    result = check_target_stability(target, expected_state_from_capture_record(record), target_key="database")
    assert result.confirmed is False
    assert "insufficient" in result.detail.lower()


def test_stability_never_mutates_the_target(tmp_path: Path):
    import hashlib
    target = tmp_path / "db.sqlite"
    content = b"do not touch me"
    target.write_bytes(content)
    before = target.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    record = _record(CaptureItemOutcome.CAPTURED_VERIFIED, sha256=sha256, size_bytes=len(content))
    check_target_stability(target, expected_state_from_capture_record(record), target_key="database")
    assert target.read_bytes() == before


# -- check_config_inventory_stability(): drift ---------------------------------------


def test_config_inventory_stability_matches_confirms(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "a.yaml").write_text("a")
    (config_dir / "b.yaml").write_text("b")
    result = check_config_inventory_stability(config_dir, ("a.yaml", "b.yaml"))
    assert result.confirmed is True


def test_config_inventory_stability_extra_file_is_mismatch(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "a.yaml").write_text("a")
    (config_dir / "unexpected.yaml").write_text("x")
    result = check_config_inventory_stability(config_dir, ("a.yaml",))
    assert result.confirmed is False


def test_config_inventory_stability_missing_file_is_mismatch(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    result = check_config_inventory_stability(config_dir, ("a.yaml", "b.yaml"))
    assert result.confirmed is False
