"""Archive Rev1 filesystem integrity engine (Phase 15 Mission 15C).

Read-only, transport-neutral primitives for turning a production episode
workspace into a trusted, deterministic source inventory: safe root
validation, recursive enumeration that rejects every unsafe filesystem
object type outright, streaming SHA-256 with before/after stability
proof, and a canonical source-set digest. Nothing here writes, copies, or
moves anything -- Archive Manager Rev1 (a later mission) will orchestrate
these primitives into an actual copy-and-publish pipeline.

Guarantee this module actually provides (read this before relying on it):
a successful file fingerprint (hash_stable_file(), and therefore every
InventoryFile's sha256/size_bytes) validates the pathname before opening,
the identity of the actual opened regular-file handle (via os.fstat() on
the open file descriptor, narrowing the gap between "the pathname looked
safe" and "the object actually opened is that same object" -- open() has
no way to refuse following a symlink that appears at a path after it was
last checked, but a mismatched fstat() is how that swap is caught), the
stability of that same handle while streaming its SHA-256, and the
pathname again afterward. All four observations compare the same stat
fingerprint (size, mtime_ns, and inode/device where the platform reports
them). Additionally, a final structural reconciliation pass re-enumerates
the whole tree and fails closed if any file or directory was added or
removed since the initial walk. This is NOT a filesystem lock and NOT a
full snapshot: a sufficiently adversarial, precisely-timed mutation that
also happens to leave a same-named, same-sized, same-mtime, same-inode
replacement in place at exactly the right instants could theoretically
still evade every one of these checks together. No locking is attempted
(see Mission 15C's governing instructions) -- this module fails closed on
every mutation it is able to observe, which is the practical guarantee a
non-locking design can offer.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Sequence

from redline_core.archive.exceptions import (
    ArchiveInventoryError,
    ArchivePathError,
    ArchiveSourceChangedError,
    ArchiveUnsafeFilesystemObjectError,
)

logger = logging.getLogger(__name__)

_HASH_CHUNK_SIZE = 1024 * 1024  # 1 MiB; suitable for multi-GB rendered masters without loading whole files.
_SOURCE_SET_SCHEMA_VERSION = 1


# -- models -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InventoryDirectory:
    """A directory entry preserved so restore can recreate it, even if empty."""

    relative_path: str
    absolute_source_path: Path


@dataclass(frozen=True, slots=True)
class InventoryFile:
    """A verified regular file: content was hashed while stable (see module docstring)."""

    relative_path: str
    absolute_source_path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceInventory:
    """The complete, verified, deterministically-ordered inventory of one source root."""

    root: Path
    directories: tuple[InventoryDirectory, ...]
    files: tuple[InventoryFile, ...]
    file_count: int
    directory_count: int
    total_bytes: int
    source_set_digest: str


# -- filesystem object safety --------------------------------------------------


def _is_windows() -> bool:
    """Small module-local indirection so tests can patch it, matching the
    existing pattern in redline_core.manifest.validator._is_windows()."""
    return os.name == "nt"


def _is_unsafe_link(st: os.stat_result) -> bool:
    """True if `st` (from os.lstat()) describes a symlink, Windows
    junction, or any other reparse point.

    POSIX symlinks are detected via the standard S_ISLNK mode bit.
    Windows junctions are NOT reported as symlinks by S_ISLNK or by
    pathlib's is_symlink() (confirmed empirically against a real
    New-Item -ItemType Junction on this repository's target Windows
    environment) -- they carry a different reparse tag
    (IO_REPARSE_TAG_MOUNT_POINT vs IO_REPARSE_TAG_SYMLINK) that only a
    generic reparse-point check catches. os.stat_result.st_file_attributes
    (Windows-only, present since Python 3.5, no elevated privileges
    required) reports FILE_ATTRIBUTE_REPARSE_POINT for *any* reparse tag,
    covering symlinks, junctions, and any other current or future reparse
    type uniformly -- this is deliberately used instead of requiring
    Python 3.12's Path.is_junction(), since this repository supports
    Python 3.10+.
    """
    if stat_module.S_ISLNK(st.st_mode):
        return True
    attributes = getattr(st, "st_file_attributes", None)
    if attributes is not None and attributes & stat_module.FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    return False


def _classify_entry(path: Path) -> str:
    """Return "dir" or "file" for a safe filesystem object.

    Raises ArchiveUnsafeFilesystemObjectError for a symlink, junction,
    reparse point, or any object that is neither a regular file nor a
    directory (named pipe, device, socket, etc.) -- these are rejected
    outright, never silently skipped.
    """
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise ArchivePathError(f"cannot inspect filesystem object: {path}") from exc

    if _is_unsafe_link(st):
        raise ArchiveUnsafeFilesystemObjectError(
            f"filesystem object is a symlink, junction, or reparse point and is rejected: {path}"
        )
    if stat_module.S_ISDIR(st.st_mode):
        return "dir"
    if stat_module.S_ISREG(st.st_mode):
        return "file"
    raise ArchiveUnsafeFilesystemObjectError(
        f"filesystem object is neither a regular file nor a directory: {path}"
    )


# -- root validation ------------------------------------------------------------


def validate_source_root(root: str | Path) -> Path:
    """Validate and resolve an Archive Rev1 source root.

    Requires: root is path-like, exists, is a directory, and is not
    itself a symlink/junction/reparse point. Returns the canonically
    resolved Path. Never follows a link to get there -- the safety check
    runs (via os.lstat, which does not follow the final path component)
    before any Path.resolve() call, and resolve() is only reached once
    the root is already proven to be a genuine directory, so nothing here
    can silently escape through a linked root.
    """
    if not isinstance(root, (str, Path)):
        raise ArchivePathError("source root must be a path-like string or Path.")

    candidate = Path(root).expanduser()
    try:
        st = os.lstat(candidate)
    except OSError as exc:
        raise ArchivePathError(f"source root does not exist or cannot be inspected: {candidate}") from exc

    if _is_unsafe_link(st):
        raise ArchiveUnsafeFilesystemObjectError(
            f"source root is a symlink, junction, or reparse point and is rejected: {candidate}"
        )
    if not stat_module.S_ISDIR(st.st_mode):
        raise ArchivePathError(f"source root must be a directory: {candidate}")

    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ArchivePathError(f"source root cannot be resolved: {candidate}") from exc
    return resolved


# -- relative-path identity ------------------------------------------------------


def _normalized_identity_key(relative_path: str) -> str:
    """Case-insensitive collision key for a normalized relative path.

    Applied unconditionally, not only when running on Windows: Archive
    Rev1 packages are built for a Windows production filesystem regardless
    of which OS builds the inventory, so two entries that would collide
    once restored to Windows must be rejected even when the machine
    running this code happens to be case-sensitive.
    """
    return relative_path.casefold()


def _register_relative_identity(seen: dict[str, str], relative_path: str) -> None:
    """Record `relative_path` in `seen`, raising ArchiveInventoryError on a
    normalized-identity collision with an already-registered path.

    Kept as its own small function (rather than inlined in the walk) so
    the collision policy can be exercised directly against synthetic
    input in tests -- a real Windows filesystem cannot itself hold two
    case-only-distinct entries in one directory, so there is no way to
    exercise this failure via a live directory walk alone.
    """
    key = _normalized_identity_key(relative_path)
    existing = seen.get(key)
    if existing is not None:
        raise ArchiveInventoryError(
            f"normalized relative-path identity collision: {relative_path!r} collides with "
            f"{existing!r} once case-insensitively normalized"
        )
    seen[key] = relative_path


# -- streaming hashing / stability ------------------------------------------------


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


def _require_safe_regular_stat(st: os.stat_result, path: Path, *, when: str) -> None:
    """Raise ArchiveUnsafeFilesystemObjectError unless `st` describes a
    plain regular file -- shared by every observation point in
    hash_stable_file() (pre-open pathname, opened handle, post-hash
    pathname) so all three apply the identical safety definition."""
    if _is_unsafe_link(st):
        raise ArchiveUnsafeFilesystemObjectError(
            f"file object is a symlink, junction, or reparse point ({when}): {path}"
        )
    if not stat_module.S_ISREG(st.st_mode):
        raise ArchiveUnsafeFilesystemObjectError(f"file object is not a regular file ({when}): {path}")


def _require_stable_fingerprint(before: os.stat_result, after: os.stat_result, path: Path, *, context: str) -> None:
    if _fingerprint(before) != _fingerprint(after):
        raise ArchiveSourceChangedError(f"{context}: {path}")


def _fstat_opened_handle(fh, path: Path) -> os.stat_result:
    try:
        return os.fstat(fh.fileno())
    except OSError as exc:
        raise ArchiveSourceChangedError(f"cannot fstat opened file handle: {path}") from exc


@contextlib.contextmanager
def open_stable_source(path: str | Path) -> Iterator[tuple[BinaryIO, int]]:
    """Open `path` for streaming binary reads and yield
    `(handle, size_bytes)`, proving the same four-checkpoint identity/
    safety contract `hash_stable_file()` relies on for its own reads.

    This is the shared safe-open primitive behind every streaming read
    Archive Rev1 performs against a source file. `hash_stable_file()`
    streams the yielded handle into a SHA-256 digest; the Archive Rev1
    package builder (Phase 15 Mission 15D) streams the identical yielded
    handle into a copy destination -- the file descriptor actually copied
    from gets exactly the same identity proof a hash does, never a
    second, weaker plain `Path.open()`. See the module docstring for what
    this guarantee does and does not cover.

    Checkpoints, all compared with the same stat-field fingerprint (size,
    mtime_ns, and inode/device where the platform reports them -- see
    _fingerprint()):

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
         opened for, not just that the specific fd behaved consistently.

    Any mismatch at any checkpoint, or the file disappearing, raises
    ArchiveUnsafeFilesystemObjectError (wrong object type) or
    ArchiveSourceChangedError (identity changed) -- a caller must never
    treat an exception here as "proceed with an unverified handle." An
    exception raised by the caller's own body (e.g. a destination write
    failing) propagates unchanged; it is never reinterpreted as a
    source-identity failure. This is a stronger observation contract, not
    filesystem locking: see the module docstring for what remains
    theoretically outside a non-locking design.
    """
    path = Path(path)
    try:
        st_before = os.lstat(path)
    except OSError as exc:
        raise ArchivePathError(f"cannot stat file before opening: {path}") from exc
    _require_safe_regular_stat(st_before, path, when="pre-open pathname check")

    try:
        fh = path.open("rb")
    except OSError as exc:
        raise ArchivePathError(f"cannot open file for streaming: {path}") from exc

    with fh:
        st_opened = _fstat_opened_handle(fh, path)
        _require_safe_regular_stat(st_opened, path, when="opened file handle")
        _require_stable_fingerprint(
            st_before,
            st_opened,
            path,
            context="opened file handle does not match the pathname identity observed before opening",
        )

        yield fh, st_before.st_size

        st_streamed = _fstat_opened_handle(fh, path)
        _require_stable_fingerprint(
            st_opened, st_streamed, path, context="opened file handle changed while being streamed"
        )

    try:
        st_after = os.lstat(path)
    except OSError as exc:
        raise ArchiveSourceChangedError(f"file disappeared or became unreadable during streaming: {path}") from exc

    _require_safe_regular_stat(st_after, path, when="post-stream pathname check")
    _require_stable_fingerprint(st_before, st_after, path, context="source file changed while being streamed")


def hash_stable_file(path: str | Path) -> tuple[str, int]:
    """Stream a regular file's SHA-256 digest via open_stable_source(),
    proving it did not change during observation. Returns
    (sha256_hex, size_bytes).

    All identity/safety verification is open_stable_source()'s -- see its
    docstring for the exact four checkpoints. This function's own
    responsibility is only streaming the yielded handle's chunks (fixed
    size, never loading the whole file into memory) into a SHA-256 digest
    and translating a read failure into ArchivePathError.

    This is a complete, self-contained safety check every time it is
    called -- it does not assume a caller (e.g. the inventory walk, or
    the Mission 15D package builder) has already classified the path, so
    it is safe to call directly on an arbitrary path from any caller.
    """
    path = Path(path)
    digest = hashlib.sha256()
    with open_stable_source(path) as (fh, size_bytes):
        try:
            while True:
                chunk = fh.read(_HASH_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
        except OSError as exc:
            raise ArchivePathError(f"cannot read file while hashing: {path}") from exc

    return digest.hexdigest(), size_bytes


# -- recursive enumeration --------------------------------------------------------


def _enumerate_source_tree(root: Path) -> list[tuple[str, str, Path]]:
    """Recursively enumerate `root`, returning
    [(relative_path, kind, absolute_path), ...] for every safe object
    found, in deterministic order. Does not hash file contents. Raises on
    any unsafe object or normalized-identity collision. Called twice by
    build_source_inventory() -- once to drive hashing, once more,
    cheaply, as the final tree-mutation reconciliation pass -- so it is
    kept independent of hashing and of any mutable state beyond its own
    local collision-tracking dict.
    """
    entries: list[tuple[str, str, Path]] = []
    seen: dict[str, str] = {}

    def _recurse(current_dir: Path) -> None:
        try:
            children = sorted(current_dir.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            raise ArchivePathError(f"cannot list directory: {current_dir}") from exc
        for child in children:
            kind = _classify_entry(child)
            try:
                relative = child.relative_to(root).as_posix()
            except ValueError as exc:
                # Structurally unreachable given the walk never follows a
                # link and always descends from an already-validated
                # ancestor of root -- kept as an explicit safety net
                # rather than a load-bearing check.
                raise ArchivePathError(f"discovered object escaped source root: {child}") from exc
            _register_relative_identity(seen, relative)
            entries.append((relative, kind, child))
            if kind == "dir":
                _recurse(child)

    _recurse(root)
    return entries


def _sort_key(relative_path: str) -> str:
    return _normalized_identity_key(relative_path)


# -- source-set digest --------------------------------------------------------------


def _source_set_digest(directories: Sequence[InventoryDirectory], files: Sequence[InventoryFile]) -> str:
    """Canonical SHA-256 identity of a verified inventory.

    This hashes a canonical logical representation (schema_version +
    sorted directory relative-paths + sorted file
    {path, size_bytes, sha256} objects), NOT the concatenated raw bytes of
    every source file -- that would re-read gigabytes of already-hashed
    content for no additional integrity value. `directories`/`files` are
    expected already sorted by the caller. This is an internal integrity
    primitive, not the future Archive Manifest Rev1 JSON document.
    """
    payload = {
        "schema_version": _SOURCE_SET_SCHEMA_VERSION,
        "directories": [d.relative_path for d in directories],
        "files": [{"path": f.relative_path, "size_bytes": f.size_bytes, "sha256": f.sha256} for f in files],
    }
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


# -- top-level entry point --------------------------------------------------------


def build_source_inventory(root: str | Path) -> SourceInventory:
    """Build a verified, deterministic SourceInventory for `root`.

    No filesystem mutation occurs. See the module docstring for the exact
    stability/race guarantee this provides.
    """
    resolved_root = validate_source_root(root)
    logger.info("Building archive source inventory: root=%s", resolved_root)

    initial_entries = _enumerate_source_tree(resolved_root)

    directories: list[InventoryDirectory] = []
    files: list[InventoryFile] = []
    for relative, kind, absolute in initial_entries:
        if kind == "dir":
            directories.append(InventoryDirectory(relative_path=relative, absolute_source_path=absolute))
        else:
            sha256, size_bytes = hash_stable_file(absolute)
            files.append(
                InventoryFile(relative_path=relative, absolute_source_path=absolute, size_bytes=size_bytes, sha256=sha256)
            )

    directories.sort(key=lambda d: _sort_key(d.relative_path))
    files.sort(key=lambda f: _sort_key(f.relative_path))

    _reconcile_final_tree_state(resolved_root, initial_entries)

    total_bytes = sum(f.size_bytes for f in files)
    digest = _source_set_digest(directories, files)

    logger.info(
        "Archive source inventory complete: root=%s files=%d directories=%d total_bytes=%d source_set_digest=%s",
        resolved_root,
        len(files),
        len(directories),
        total_bytes,
        digest,
    )

    return SourceInventory(
        root=resolved_root,
        directories=tuple(directories),
        files=tuple(files),
        file_count=len(files),
        directory_count=len(directories),
        total_bytes=total_bytes,
        source_set_digest=digest,
    )


def _reconcile_final_tree_state(root: Path, initial_entries: list[tuple[str, str, Path]]) -> None:
    """Re-enumerate `root` (structure only, no re-hash) and fail closed if
    the file/directory set differs from `initial_entries` -- detects a
    file or directory added or removed while the initial pass was
    hashing. See the module docstring for this check's real limits.
    """
    final_entries = _enumerate_source_tree(root)
    initial_identity = {(relative, kind) for relative, kind, _ in initial_entries}
    final_identity = {(relative, kind) for relative, kind, _ in final_entries}
    if initial_identity != final_identity:
        added = sorted(final_identity - initial_identity)
        removed = sorted(initial_identity - final_identity)
        raise ArchiveSourceChangedError(
            f"source tree changed during inventory: root={root} added={added} removed={removed}"
        )
