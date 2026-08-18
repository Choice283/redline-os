"""Tests for redline_core.restore.capture_io.best_effort_capture_file()
(Mission 1B-A2-2): the non-fail-closed, best-effort byte-preservation
primitive. Every failure mode must be represented as a typed, returned
outcome -- this module never raises for a source-side problem.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from redline_core.restore import capture_io
from redline_core.restore.capture_models import CaptureItemOutcome


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _ReadTrackingHandle:
    """Wraps a real file handle, proxying fileno() (required by the
    Correction 1 opened-handle identity check) while counting read()
    calls, so a test can assert zero bytes were ever read from the
    opened handle -- not just that the final outcome looks right."""

    def __init__(self, fh, read_calls: dict):
        self._fh = fh
        self._read_calls = read_calls

    def fileno(self):
        return self._fh.fileno()

    def read(self, size):
        self._read_calls["n"] += 1
        return self._fh.read(size)

    def close(self):
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._fh.close()


def test_captures_and_verifies_a_healthy_file(tmp_path: Path):
    source = tmp_path / "source.bin"
    content = b"stable, readable content" * 100
    source.write_bytes(content)
    destination = tmp_path / "staged" / "source.bin"

    result = capture_io.best_effort_capture_file(source, destination, relative_path="payload/x")

    assert result.outcome is CaptureItemOutcome.CAPTURED_VERIFIED
    assert result.sha256 == _sha256(content)
    assert result.size_bytes == len(content)
    assert result.captured_relative_path == "payload/x"
    assert destination.read_bytes() == content


def test_missing_source_reports_missing(tmp_path: Path):
    source = tmp_path / "does_not_exist.bin"
    destination = tmp_path / "staged" / "x.bin"

    result = capture_io.best_effort_capture_file(source, destination, relative_path="payload/x")

    assert result.outcome is CaptureItemOutcome.MISSING
    assert result.captured_relative_path is None
    assert not destination.exists()


def test_source_cannot_be_opened_reports_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"content")
    destination = tmp_path / "staged" / "x.bin"

    real_open = Path.open

    def _fake_open(self, *args, **kwargs):
        if self == source and "rb" in args:
            raise PermissionError("simulated permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _fake_open)

    result = capture_io.best_effort_capture_file(source, destination, relative_path="payload/x")

    assert result.outcome is CaptureItemOutcome.UNREADABLE
    assert result.captured_relative_path is None
    assert not destination.exists()


def test_read_error_partway_preserves_partial_evidence_as_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.bin"
    content = b"A" * (2 * 1024 * 1024)  # 2 chunks at the module's 1 MiB chunk size
    source.write_bytes(content)
    destination = tmp_path / "staged" / "x.bin"

    real_open = Path.open
    call_count = {"reads": 0}

    class _FlakyHandle:
        def __init__(self, fh):
            self._fh = fh

        def fileno(self):
            # Mission 1B-A2-2 safety correction (Correction 1): production
            # code now fstat()s the just-opened handle before reading a
            # single byte, so this wrapper must proxy fileno() to the real
            # underlying handle exactly like a genuine file object would.
            return self._fh.fileno()

        def read(self, size):
            call_count["reads"] += 1
            if call_count["reads"] == 2:
                raise OSError("simulated mid-read I/O error")
            return self._fh.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self._fh.close()

    def _fake_open(self, *args, **kwargs):
        if self == source and "rb" in args:
            return _FlakyHandle(real_open(self, *args, **kwargs))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _fake_open)

    result = capture_io.best_effort_capture_file(source, destination, relative_path="payload/x")

    assert result.outcome is CaptureItemOutcome.UNREADABLE
    assert result.captured_relative_path == "payload/x"  # partial evidence preserved
    assert destination.exists()
    assert 0 < destination.stat().st_size < len(content)
    assert "partial read" in result.detail


def test_source_changed_during_capture_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original content")
    destination = tmp_path / "staged" / "x.bin"

    import os as os_module

    real_lstat = os_module.lstat
    call_count = {"n": 0}

    def _fake_lstat(path, *a, **kw):
        st = real_lstat(path, *a, **kw)
        if str(path) == str(source):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                # Simulate a changed mtime_ns on every lstat after the first (pre-open) one.
                class _MutatedStat:
                    def __getattr__(self, name):
                        return getattr(st, name)

                    @property
                    def st_mtime_ns(self):
                        return st.st_mtime_ns + 999999999

                return _MutatedStat()
        return st

    monkeypatch.setattr(capture_io.os, "lstat", _fake_lstat)

    result = capture_io.best_effort_capture_file(source, destination, relative_path="payload/x")

    assert result.outcome is CaptureItemOutcome.CHANGED_DURING_CAPTURE
    assert "identity changed" in result.detail


def test_destination_reverify_mismatch_is_captured_unverified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"trustworthy source bytes")
    destination = tmp_path / "staged" / "x.bin"

    real_open = Path.open

    def _fake_open(self, *args, **kwargs):
        fh = real_open(self, *args, **kwargs)
        if self == destination and "rb" in args:
            # Simulate the destination re-read returning corrupted content.
            class _CorruptHandle:
                def read(self, size):
                    data = fh.read(size)
                    return data.replace(b"trustworthy", b"CORRUPTED!!!") if data else data

                def close(self):
                    fh.close()

                def __enter__(self):
                    return self

                def __exit__(self, *exc_info):
                    self.close()

            return _CorruptHandle()
        return fh

    monkeypatch.setattr(Path, "open", _fake_open)

    result = capture_io.best_effort_capture_file(source, destination, relative_path="payload/x")

    assert result.outcome is CaptureItemOutcome.CAPTURED_UNVERIFIED
    assert destination.exists()


# -- Mission 1B-A2-2 safety correction: Correction 1 (source TOCTOU) ------------------


def test_opened_handle_identity_mismatch_detected_before_any_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Simulates a substitution occurring between the pre-open lstat()
    safety observation and open() actually resolving a filesystem object:
    the just-opened handle's own fstat() no longer matches the pre-open
    identity. open() may still have followed a substituted target (Windows
    offers no portable no-follow-at-open primitive), but this proves the
    substituted bytes are never read, hashed, or written -- the mismatch
    is caught, and read() is never called, before a single byte crosses
    the boundary."""
    source = tmp_path / "source.bin"
    source.write_bytes(b"trustworthy original content")
    destination = tmp_path / "staged" / "x.bin"

    real_open = Path.open
    real_fstat = capture_io.os.fstat
    read_calls = {"n": 0}

    def _fake_open(self, *args, **kwargs):
        if self == source and "rb" in args:
            return _ReadTrackingHandle(real_open(self, *args, **kwargs), read_calls)
        return real_open(self, *args, **kwargs)

    def _fake_fstat(fd, *a, **kw):
        st = real_fstat(fd, *a, **kw)

        class _MutatedStat:
            def __getattr__(self, name):
                return getattr(st, name)

            @property
            def st_size(self):
                # Simulate the opened object being a different size than
                # the pathname observed before open() -- e.g. a
                # substituted target file.
                return st.st_size + 999999

        return _MutatedStat()

    monkeypatch.setattr(Path, "open", _fake_open)
    monkeypatch.setattr(capture_io.os, "fstat", _fake_fstat)

    result = capture_io.best_effort_capture_file(source, destination, relative_path="payload/x")

    assert result.outcome is CaptureItemOutcome.CHANGED_DURING_CAPTURE
    assert result.captured_relative_path is None
    assert result.size_bytes is None
    assert result.sha256 is None
    assert "opened file handle identity does not match" in result.detail
    assert read_calls["n"] == 0  # zero bytes were ever read from the opened handle
    assert not destination.exists()  # zero bytes captured -- destination never created


def test_opened_handle_flagged_unsafe_detected_before_any_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Simulates the just-opened handle itself resolving to an unsafe
    filesystem object (e.g. the reparse point survived resolution in a way
    fstat() can still detect) -- proves this is caught, and zero bytes are
    ever read, exactly like the identity-mismatch case above."""
    source = tmp_path / "source.bin"
    source.write_bytes(b"trustworthy original content")
    destination = tmp_path / "staged" / "x.bin"

    real_open = Path.open
    read_calls = {"n": 0}

    def _fake_open(self, *args, **kwargs):
        if self == source and "rb" in args:
            return _ReadTrackingHandle(real_open(self, *args, **kwargs), read_calls)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _fake_open)
    monkeypatch.setattr(capture_io.fsutil, "is_unsafe_link", lambda st: True)

    result = capture_io.best_effort_capture_file(source, destination, relative_path="payload/x")

    assert result.outcome is CaptureItemOutcome.CHANGED_DURING_CAPTURE
    assert result.captured_relative_path is None
    assert read_calls["n"] == 0
    assert not destination.exists()
