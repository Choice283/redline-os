"""Best-effort, non-fail-closed read/copy primitive for degraded-source
capture (Mission 1B-A2-2).

Deliberately **not** built on ``redline_core.fsutil.open_stable_source()``/
``hash_stable_file()``: those are correctly, permanently fail-closed for
Mission 1A/1B-A1's purposes -- any anomaly (wrong type, unsafe object,
identity change) aborts the whole operation immediately, which is exactly
right when a caller needs a trustworthy backup or restore payload. But
degraded-source capture's entire purpose is to get *something* off a file
that may not pass those checks; a caller that needs "raise on the first
problem" already has ``fsutil``, and this module exists specifically for
the caller that needs "record the problem truthfully and keep going."

This module still reuses the identical stat-fingerprint identity technique
``fsutil.open_stable_source()`` uses internally
(``redline_core.restore.capture_models.StatFingerprint`` -- size, mtime_ns,
inode, device, compared before and after streaming) -- just downgraded
from "raise" to "record the mismatch as a typed
``CaptureItemOutcome.CHANGED_DURING_CAPTURE`` and return it."

Every call here assumes its caller has already independently confirmed
``source_path`` is not an unsafe filesystem object (symlink/junction/
reparse point) and not a directory -- see
``redline_core.restore.capture_package``, which performs exactly that gate
(reusing ``redline_core.fsutil.is_unsafe_link()``) before ever calling into
this module. That caller-side gate and this module's own pre-open
``os.lstat()`` below are both pathname-based checks, though, and a pathname
check can never by itself prove what ``Path.open()`` actually resolves a
moment later -- between either check and the real ``open()`` call, another
process could substitute a symlink/junction/reparse point at
``source_path``. Mission 1B-A2-2's post-implementation safety review (the
"Correction 1" TOCTOU finding) is exactly this gap: this module now closes
it itself, independently of the caller, by proving the *just-opened
handle's own identity* (``os.fstat()``) matches the pre-open pathname
observation before a single byte is ever read from it (see
``best_effort_capture_file()``'s docstring for the exact sequence and its
honestly-stated guarantee). This module still never performs the caller's
own pre-open pathname safety gate itself -- that division of
responsibility is unchanged -- it only adds the opened-handle identity
proof this module's own ``open()`` call needs regardless of what the
caller already checked.
"""
from __future__ import annotations

import hashlib
import os
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path

from redline_core import fsutil
from redline_core.restore.capture_models import CaptureItemOutcome, StatFingerprint

_CHUNK_SIZE = 1024 * 1024  # 1 MiB; matches Mission 1A's own backup copy chunk size.


@dataclass(frozen=True, slots=True)
class BestEffortCaptureOutcome:
    """The raw result of one best-effort capture attempt, before the
    caller wraps it into a full ``CaptureItemRecord`` (adding
    ``item_key``/``source_path``/``unsafe_object``)."""

    outcome: CaptureItemOutcome
    captured_relative_path: str | None
    size_bytes: int | None
    sha256: str | None
    stat_fingerprint: StatFingerprint | None
    detail: str


def _fingerprint(st: os.stat_result) -> StatFingerprint:
    return StatFingerprint(
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        ino=getattr(st, "st_ino", None) or None,
        dev=getattr(st, "st_dev", None) or None,
    )


def _discard_partial(destination_path: Path) -> None:
    try:
        destination_path.unlink()
    except OSError:
        pass


def best_effort_capture_file(source_path: Path, destination_path: Path, *, relative_path: str) -> BestEffortCaptureOutcome:
    """Best-effort, non-fail-closed capture of one regular file's bytes
    from ``source_path`` into ``destination_path``. Never raises for a
    source-side read problem -- every failure mode is represented as a
    typed, returned outcome, so the caller can seal a truthful capture
    package regardless of what happened here.

    Decision sequence: MISSING (source absent) -> UNREADABLE (cannot open,
    or a read fails before any bytes are obtained) -> CHANGED_DURING_CAPTURE
    (either the just-opened handle's own identity does not match the
    pre-open pathname observation -- see the opened-handle identity proof
    below -- or the source's stat fingerprint changed, or it disappeared,
    between the start and end of streaming; checked even for a partial
    read) -> UNREADABLE with partial evidence preserved (a read failed
    partway, but the source was otherwise stable) -> CAPTURED_UNVERIFIED
    (the full stream completed and the source stayed stable, but
    independently re-reading the just-written destination failed or did
    not match) -> CAPTURED_VERIFIED (the full stream completed, the
    source stayed stable, and the destination re-read matches the source
    stream exactly).

    Opened-handle identity proof (Mission 1B-A2-2 safety correction,
    Correction 1): immediately after ``open()`` succeeds, and before a
    single byte is read from the handle, this function ``os.fstat()``s
    the handle itself and requires it to be a safe regular object whose
    identity (size/mtime_ns/inode/device) matches the pre-open pathname
    ``lstat()`` above. If a symlink/junction/reparse point was substituted
    at ``source_path`` between the pre-open safety check and this
    function's own ``open()`` call, ``open()`` may still have resolved and
    opened the substituted target -- Python offers no portable
    no-follow-at-open primitive on Windows (``os.O_NOFOLLOW`` does not
    exist there) -- but no byte of that target is ever read, hashed, or
    written: the mismatch is caught here, the handle is closed
    immediately, and the outcome is truthfully recorded as
    ``CHANGED_DURING_CAPTURE`` with zero captured bytes. This guarantee is
    honestly "the substituted object's bytes are never READ," not "the
    substituted object is never OPENED" -- the latter, stronger claim is
    not something this repository's supported primitives can prove on
    Windows, and this module never claims it.
    """
    try:
        st_before = os.lstat(source_path)
    except FileNotFoundError:
        return BestEffortCaptureOutcome(CaptureItemOutcome.MISSING, None, None, None, None, f"{source_path} does not exist.")
    except OSError as exc:
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.UNREADABLE, None, None, None, None, f"cannot inspect {source_path}: {exc}"
        )

    try:
        source_fh = source_path.open("rb")
    except OSError as exc:
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.UNREADABLE, None, None, None, _fingerprint(st_before),
            f"cannot open {source_path} for reading: {exc}",
        )

    fp_before = _fingerprint(st_before)
    try:
        st_opened = os.fstat(source_fh.fileno())
    except OSError as exc:
        source_fh.close()
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.UNREADABLE, None, None, None, fp_before,
            f"cannot fstat the just-opened handle for {source_path}: {exc}",
        )

    if fsutil.is_unsafe_link(st_opened) or not stat_module.S_ISREG(st_opened.st_mode) or _fingerprint(st_opened) != fp_before:
        source_fh.close()
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.CHANGED_DURING_CAPTURE, None, None, None, fp_before,
            f"opened file handle identity does not match the pre-open pathname observation for {source_path} "
            "(possible substitution between the pre-open safety check and open()); zero bytes were read from "
            "the opened handle, which was closed immediately without ever being streamed.",
        )

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    bytes_written = 0
    read_error: OSError | None = None

    try:
        with source_fh:
            with destination_path.open("wb") as out:
                while True:
                    try:
                        chunk = source_fh.read(_CHUNK_SIZE)
                    except OSError as exc:
                        read_error = exc
                        break
                    if not chunk:
                        break
                    digest.update(chunk)
                    out.write(chunk)
                    bytes_written += len(chunk)
                out.flush()
                os.fsync(out.fileno())
    except OSError as exc:
        _discard_partial(destination_path)
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.UNREADABLE, None, None, None, _fingerprint(st_before),
            f"destination write failure while capturing {source_path}: {exc}",
        )

    if bytes_written == 0 and read_error is not None:
        _discard_partial(destination_path)
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.UNREADABLE, None, None, None, _fingerprint(st_before),
            f"could not read any bytes from {source_path}: {read_error}",
        )

    try:
        st_after = os.lstat(source_path)
    except OSError as exc:
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.CHANGED_DURING_CAPTURE, relative_path, bytes_written, digest.hexdigest(),
            _fingerprint(st_before),
            f"source disappeared or became uninspectable immediately after capture: {exc}",
        )

    fp_after = _fingerprint(st_after)
    if fp_before != fp_after:
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.CHANGED_DURING_CAPTURE, relative_path, bytes_written, digest.hexdigest(), fp_after,
            f"source identity changed during capture (before={fp_before}, after={fp_after}).",
        )

    if read_error is not None:
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.UNREADABLE, relative_path, bytes_written, digest.hexdigest(), fp_after,
            f"partial read ({bytes_written} of {st_before.st_size} expected bytes) before error: {read_error}",
        )

    # Independently re-read the just-written destination and re-hash,
    # mirroring Mission 1A's own _copy_and_verify_config_file()/
    # _copy_and_verify()'s double-check pattern exactly.
    try:
        reread_digest = hashlib.sha256()
        reread_size = 0
        with destination_path.open("rb") as verify_fh:
            while True:
                chunk = verify_fh.read(_CHUNK_SIZE)
                if not chunk:
                    break
                reread_digest.update(chunk)
                reread_size += len(chunk)
    except OSError as exc:
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.CAPTURED_UNVERIFIED, relative_path, bytes_written, digest.hexdigest(), fp_after,
            f"captured, but the destination copy could not be independently re-read to verify: {exc}",
        )

    if reread_digest.hexdigest() != digest.hexdigest() or reread_size != bytes_written:
        return BestEffortCaptureOutcome(
            CaptureItemOutcome.CAPTURED_UNVERIFIED, relative_path, bytes_written, digest.hexdigest(), fp_after,
            "captured, but the destination copy does not match the verified source stream.",
        )

    return BestEffortCaptureOutcome(
        CaptureItemOutcome.CAPTURED_VERIFIED, relative_path, bytes_written, digest.hexdigest(), fp_after,
        "captured and independently verified: the destination copy matches the source stream hash, and the "
        "source's identity was stable throughout capture.",
    )
