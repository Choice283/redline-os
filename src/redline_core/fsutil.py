"""Generic, domain-neutral safe-file primitives (Phase 15 Mission 15E.2).

Extracted from `redline_core.archive.integrity` (Phase 15 Mission 15C):
that module's `open_stable_source()`/`hash_stable_file()` never referenced
anything archive-specific (no `SourceInventory`, no `InventoryFile`, no
source-set digest) -- they are a genuinely generic "prove this path is a
safe regular file, open it, and prove the opened handle's identity stays
stable while a caller streams it" primitive. Phase 15 Mission 15E.2 needs
the identical guarantee from the build layer (`redline_core.build`) to
persist a canonical manifest copy, and importing `redline_core.archive`
directly from `redline_core.build` would introduce a backwards layering
dependency (an earlier-lifecycle module depending on a later,
domain-branded one) that has no counterpart anywhere else in this
repository's module graph. This module is that neutral home; nothing
here is aware of archives, episodes, manifests, or SQLite.

`redline_core.archive.integrity` now delegates to this module (see its
own docstring) rather than duplicating the logic -- there is exactly one
real implementation of this safety contract in the repository.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

_HASH_CHUNK_SIZE = 1024 * 1024  # 1 MiB; suitable for multi-GB files without loading them whole.


# -- neutral exceptions --------------------------------------------------------


class SafeFileError(Exception):
    """Base class for this module's own, domain-neutral failures."""


class PathError(SafeFileError):
    """A path could not be stat'd, opened, or read, or does not resolve to
    a directory/regular file where one was required."""


class UnsafeFilesystemObjectError(SafeFileError):
    """A filesystem object was rejected because it is not a plain regular
    file: a symlink, a Windows junction/reparse point, or any other
    special object."""


class SourceChangedError(SafeFileError):
    """The object at a path did not remain stable during observation --
    identity (size/mtime/inode/device) changed between two checkpoints,
    or the object disappeared."""


@dataclass(frozen=True, slots=True)
class SafeFileExceptions:
    """The three exception types `open_stable_source()`/`hash_stable_file()`
    raise, injectable so a caller (e.g. `redline_core.archive.integrity`)
    can have this shared primitive raise its own domain-specific exception
    subclasses instead of this module's neutral defaults -- without a
    second implementation of the underlying safety logic."""

    path_error: type[Exception] = PathError
    unsafe_object: type[Exception] = UnsafeFilesystemObjectError
    source_changed: type[Exception] = SourceChangedError


_DEFAULT_EXCEPTIONS = SafeFileExceptions()


# -- filesystem object safety --------------------------------------------------


def is_windows() -> bool:
    """Small module-local indirection so tests can patch it, matching the
    existing pattern this was extracted from."""
    return os.name == "nt"


def is_unsafe_link(st: os.stat_result) -> bool:
    """True if `st` (from os.lstat()) describes a symlink, Windows
    junction, or any other reparse point.

    POSIX symlinks are detected via the standard S_ISLNK mode bit.
    Windows junctions are NOT reported as symlinks by S_ISLNK or by
    pathlib's is_symlink() -- they carry a different reparse tag
    (IO_REPARSE_TAG_MOUNT_POINT vs IO_REPARSE_TAG_SYMLINK) that only a
    generic reparse-point check catches. os.stat_result.st_file_attributes
    (Windows-only, present since Python 3.5, no elevated privileges
    required) reports FILE_ATTRIBUTE_REPARSE_POINT for *any* reparse tag,
    covering symlinks, junctions, and any other current or future reparse
    type uniformly.
    """
    if stat_module.S_ISLNK(st.st_mode):
        return True
    attributes = getattr(st, "st_file_attributes", None)
    if attributes is not None and attributes & stat_module.FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    return False


@dataclass(frozen=True, slots=True)
class _StatFingerprint:
    size: int
    mtime_ns: int
    ino: int | None
    dev: int | None


def _fingerprint(st: os.stat_result) -> _StatFingerprint:
    return _StatFingerprint(
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        ino=getattr(st, "st_ino", None) or None,
        dev=getattr(st, "st_dev", None) or None,
    )


def _require_safe_regular_stat(
    st: os.stat_result, path: Path, *, when: str, exceptions: SafeFileExceptions
) -> None:
    if is_unsafe_link(st):
        raise exceptions.unsafe_object(
            f"file object is a symlink, junction, or reparse point ({when}): {path}"
        )
    if not stat_module.S_ISREG(st.st_mode):
        raise exceptions.unsafe_object(f"file object is not a regular file ({when}): {path}")


def _require_stable_fingerprint(
    before: os.stat_result, after: os.stat_result, path: Path, *, context: str, exceptions: SafeFileExceptions
) -> None:
    if _fingerprint(before) != _fingerprint(after):
        raise exceptions.source_changed(f"{context}: {path}")


def _fstat_opened_handle(fh, path: Path, *, exceptions: SafeFileExceptions) -> os.stat_result:
    try:
        return os.fstat(fh.fileno())
    except OSError as exc:
        raise exceptions.source_changed(f"cannot fstat opened file handle: {path}") from exc


# -- safe open / hash -----------------------------------------------------------


@contextlib.contextmanager
def open_stable_source(
    path: str | Path, *, exceptions: SafeFileExceptions = _DEFAULT_EXCEPTIONS
) -> Iterator[tuple[BinaryIO, int]]:
    """Open `path` for streaming binary reads and yield
    `(handle, size_bytes)`, proving a four-checkpoint identity/safety
    contract before, during, and after the caller streams the handle.

    Checkpoints, all compared with the same stat-field fingerprint (size,
    mtime_ns, and inode/device where the platform reports them):

      1. pre-open pathname lstat -- also the safety check (rejects a
         symlink/junction/reparse point or anything that is not a regular
         file) before anything is opened.
      2. the just-opened file descriptor's own fstat, checked for
         regularity and required to match #1 -- narrows the gap between
         "the pathname looked safe" and "the object actually opened is
         that same object" (open() has no way to refuse following a
         symlink that appeared at the path after the lstat in #1; a
         mismatched fstat here is how that swap is caught).
      3. the same descriptor's fstat again once the caller's `with`-block
         body completes *without raising*, required to match #2 --
         proves whatever was streamed came from a file whose identity
         never changed while being read. Deliberately skipped if the
         body raises: that failure is already the reported error, and
         re-verifying an aborted read/write adds nothing.
      4. a final pathname lstat after closing the handle, checked for
         regularity and required to match #1 -- proves the pathname
         still resolves to the same safe regular file the handle was
         opened for.

    Any mismatch at any checkpoint, or the file disappearing, raises
    `exceptions.unsafe_object` (wrong object type) or
    `exceptions.source_changed` (identity changed) -- a caller must never
    treat an exception here as "proceed with an unverified handle." An
    exception raised by the caller's own body (e.g. a destination write
    failing) propagates unchanged; it is never reinterpreted as a
    source-identity failure. This is a stronger observation contract, not
    filesystem locking or a full snapshot: a sufficiently adversarial,
    precisely-timed same-size/same-mtime/same-inode replacement at
    exactly the right instants could theoretically still evade every one
    of these checks together. No locking is attempted.
    """
    path = Path(path)
    try:
        st_before = os.lstat(path)
    except OSError as exc:
        raise exceptions.path_error(f"cannot stat file before opening: {path}") from exc
    _require_safe_regular_stat(st_before, path, when="pre-open pathname check", exceptions=exceptions)

    try:
        fh = path.open("rb")
    except OSError as exc:
        raise exceptions.path_error(f"cannot open file for streaming: {path}") from exc

    with fh:
        st_opened = _fstat_opened_handle(fh, path, exceptions=exceptions)
        _require_safe_regular_stat(st_opened, path, when="opened file handle", exceptions=exceptions)
        _require_stable_fingerprint(
            st_before,
            st_opened,
            path,
            context="opened file handle does not match the pathname identity observed before opening",
            exceptions=exceptions,
        )

        yield fh, st_before.st_size

        st_streamed = _fstat_opened_handle(fh, path, exceptions=exceptions)
        _require_stable_fingerprint(
            st_opened,
            st_streamed,
            path,
            context="opened file handle changed while being streamed",
            exceptions=exceptions,
        )

    try:
        st_after = os.lstat(path)
    except OSError as exc:
        raise exceptions.source_changed(f"file disappeared or became unreadable during streaming: {path}") from exc

    _require_safe_regular_stat(st_after, path, when="post-stream pathname check", exceptions=exceptions)
    _require_stable_fingerprint(
        st_before, st_after, path, context="source file changed while being streamed", exceptions=exceptions
    )


def hash_stable_file(
    path: str | Path, *, exceptions: SafeFileExceptions = _DEFAULT_EXCEPTIONS
) -> tuple[str, int]:
    """Stream a regular file's SHA-256 digest via open_stable_source(),
    proving it did not change during observation. Returns
    (sha256_hex, size_bytes).

    All identity/safety verification is open_stable_source()'s. This
    function's own responsibility is only streaming the yielded handle's
    chunks (fixed size, never loading the whole file into memory) into a
    SHA-256 digest and translating a read failure into
    `exceptions.path_error`.
    """
    path = Path(path)
    digest = hashlib.sha256()
    with open_stable_source(path, exceptions=exceptions) as (fh, size_bytes):
        try:
            while True:
                chunk = fh.read(_HASH_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
        except OSError as exc:
            raise exceptions.path_error(f"cannot read file while hashing: {path}") from exc

    return digest.hexdigest(), size_bytes
