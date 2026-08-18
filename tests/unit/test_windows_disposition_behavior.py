"""Mission 1B-A2-3-Prep: Windows Filesystem Disposition Behavioral Proof.

Isolated, `tmp_path`-scoped behavioral tests proving actual Windows
`os.rename()` / `os.lstat()` semantics for two disposition cases a
*future*, not-yet-implemented Mission 1B-A2-3 would need before it could
safely move a wrong-type live object aside ahead of DB/config replacement:

  Case A: the database path is occupied by an ordinary directory.
  Case B: the config path is occupied by an ordinary regular file.

This module adds **no production disposition code** anywhere in
`redline_core` or `cli`. Every "gate" exercised below (unsafe-object
rejection, same-volume rejection) is a small, test-local stand-in function
defined in this file only, built solely to prove the underlying OS/Python
primitive behaves the way such a gate would need to rely on -- not a
preview or partial implementation of Mission 1B-A2-3 itself. No live
Redline OS database, config directory, or Resolve process is touched by
anything in this file; every path used is `tmp_path`-scoped.

Unsafe-object simulation uses the established, existing repository
convention (`tests/unit/test_backup_paths.py`): monkeypatching
`redline_core.fsutil.is_unsafe_link()`, never real symlink/junction
creation, which can require elevated privileges on Windows.

Windows-only: skips cleanly on any other platform via `fsutil.is_windows()`
(the same test-patchable indirection `fsutil.py` already exposes for this
purpose), so this file never weakens portability of the general suite.

--------------------------------------------------------------------------
Proposed future disposition contract (evidence-derived, NOT implemented)
--------------------------------------------------------------------------

For DB-path-occupied-by-ordinary-directory and
config-path-occupied-by-ordinary-regular-file alike, the behavioral
evidence in this file supports the following contract for a future
Mission 1B-A2-3 `recovery_disposition.py` (not built here):

1. Required preconditions (checked in this order, all before any mutation):
   a. Fresh `os.lstat()` of the source object.
   b. Unsafe-object gate: `fsutil.is_unsafe_link(st)` -- if true, hard
      refuse (`RECOVERY_BLOCKED`); never dispose of a symlink/junction/
      reparse object under any circumstance (proof: `test_a3_*` below).
   c. Wrong-type confirmation: the object must actually be the expected
      wrong type (ordinary directory for the DB case, ordinary regular
      file for the config case) -- re-derived from the same `lstat()`,
      never assumed from an earlier classification result alone.
   d. Same-volume gate: `same_volume(source.parent, destination.parent)`
      (or an equivalent pre-existing-object comparison) must be true
      before any rename is attempted; fail closed otherwise (proof:
      `test_same_volume_gate_pattern_future_disposition_must_apply`).
   e. Destination non-existence gate: an `os.lstat()` (not `Path.exists()`
      -- exists() is blind to a dangling/unsafe object occupying the
      destination, the same lesson Mission 1B-A2-2's own correction
      history already proved) of the computed restore-ID-scoped
      superseded destination must fail with `FileNotFoundError` before
      attempting the rename.
2. Rename primitive: a single `os.rename(source, destination)` call,
   never `shutil.move` (unused anywhere in this repository) and never
   `os.replace` (which on this platform can silently succeed over an
   existing destination -- the opposite of the required "never overwrite"
   guarantee; proof: `test_collision_*` below all use plain `os.rename`
   deliberately). On Windows, `os.rename()` reliably refuses when the
   destination already exists (proof below) -- this refusal, not a
   separate check-then-act probe, is treated as the authoritative
   collision gate, mirroring Mission 1B-A1's own `RestoreJournal`/backup
   publish precedent of "the rename itself is the collision check."
3. Post-move verification: re-`lstat()` both the now-absent source path
   (must raise `FileNotFoundError`) and the destination (must exist, must
   report the expected object type, and -- for the regular-file case --
   must be byte-identical to the pre-move content). For the directory
   case, verify every contained object is present and byte-identical
   rather than comparing directory-level stat fields, which are not a
   meaningful content proxy on Windows.
4. Failure behavior: any `OSError` from the rename call is a hard stop
   with no partial mutation attempted by the disposition step itself
   (proof: every collision/open-handle test below shows the filesystem
   left exactly as it was before the failed call) -- the caller is
   responsible for recording this as a `DISPOSITION_FAILED` journal
   transition and refusing to proceed to replacement.
5. Journal intent/completion boundary: record a `DISPOSITION_INTENT`
   transition immediately before the `os.rename()` call and a
   `DISPOSITION_COMPLETE`/`DISPOSITION_FAILED` transition immediately
   after it returns/raises -- exactly bracketing the single mutating call,
   mirroring every other intent/completion pair already established in
   `redline_core.restore.journal.RestoreState`.

Open-handle behavior (test_a4_*, test_b3_*) is recorded as observed
evidence, not asserted to a predicted outcome -- see the final report for
the exact result seen on this environment. Cross-volume behavior is not
exercised (no safe second temporary volume exists in this isolated test
environment); a future disposition implementation must fail closed on
`same_volume() == False` before ever attempting a rename, exactly as
Mission 1B-A1's own `stage_database()`/`stage_config()` already do.
"""
from __future__ import annotations

import os
import stat as stat_module
from pathlib import Path

import pytest

from redline_core import fsutil
from redline_core.restore import staging as staging_module
from redline_core.restore.staging import same_volume

pytestmark = pytest.mark.skipif(
    not fsutil.is_windows(),
    reason="Mission 1B-A2-3-Prep behavioral proof is Windows-specific; skips cleanly on other platforms.",
)


# == Proof Case A: DB path occupied by an ordinary directory ================


def test_a1_directory_move_aside_succeeds_and_preserves_contents(tmp_path: Path):
    live_db_path = tmp_path / "redline.db"
    live_db_path.mkdir()
    (live_db_path / "stray.txt").write_bytes(b"stray database-directory contents")
    (live_db_path / "nested").mkdir()
    (live_db_path / "nested" / "deep.txt").write_bytes(b"nested content")

    superseded = tmp_path / "redline.db__superseded-rc1-test"
    assert not superseded.exists()

    st_before = os.lstat(live_db_path)
    assert stat_module.S_ISDIR(st_before.st_mode)

    os.rename(live_db_path, superseded)

    assert not live_db_path.exists()
    assert superseded.exists()
    st_after = os.lstat(superseded)
    assert stat_module.S_ISDIR(st_after.st_mode)
    assert (superseded / "stray.txt").read_bytes() == b"stray database-directory contents"
    assert (superseded / "nested" / "deep.txt").read_bytes() == b"nested content"

    # The original path is now free for a regular database file to occupy.
    live_db_path.write_bytes(b"a fresh sqlite database payload")
    assert live_db_path.is_file()
    assert live_db_path.read_bytes() == b"a fresh sqlite database payload"


def test_a2_directory_move_aside_refuses_existing_destination(tmp_path: Path):
    live_db_path = tmp_path / "redline.db"
    live_db_path.mkdir()
    (live_db_path / "original.txt").write_bytes(b"original live directory contents")

    superseded = tmp_path / "redline.db__superseded-rc1-collide"
    superseded.mkdir()
    (superseded / "preexisting.txt").write_bytes(b"pre-existing superseded contents")

    with pytest.raises(OSError) as excinfo:
        os.rename(live_db_path, superseded)
    print(f"[A2] directory-collision exception: {type(excinfo.value).__name__}: {excinfo.value}")

    # No implicit overwrite/merge -- source and destination both untouched.
    assert live_db_path.exists()
    assert (live_db_path / "original.txt").read_bytes() == b"original live directory contents"
    assert (superseded / "preexisting.txt").read_bytes() == b"pre-existing superseded contents"
    assert not (superseded / "original.txt").exists()


def test_a3_unsafe_source_object_must_be_rejected_before_any_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Proves the gate a future disposition MUST apply: lstat() +
    is_unsafe_link() BEFORE any os.rename() attempt. `_would_be_disposition_gate`
    is a test-local stand-in only -- not production code -- proving the
    check itself is sufficient to prevent a mutation from ever being
    attempted against a reported-unsafe object. Uses the established
    `fsutil.is_unsafe_link` monkeypatch simulation convention rather than
    real symlink/junction creation. This pattern applies identically to
    Case B's source object (the check is on the source itself, independent
    of what object type is expected to occupy it)."""
    live_db_path = tmp_path / "redline.db"
    live_db_path.mkdir()
    superseded = tmp_path / "redline.db__superseded-rc1-unsafe"

    monkeypatch.setattr(fsutil, "is_unsafe_link", lambda st: True)

    def _would_be_disposition_gate(source: Path, destination: Path) -> None:
        st = os.lstat(source)
        if fsutil.is_unsafe_link(st):
            raise fsutil.UnsafeFilesystemObjectError(
                f"refusing to dispose of unsafe filesystem object: {source}"
            )
        os.rename(source, destination)  # pragma: no cover -- never reached in this test

    with pytest.raises(fsutil.UnsafeFilesystemObjectError):
        _would_be_disposition_gate(live_db_path, superseded)

    assert live_db_path.exists()
    assert not superseded.exists()


def test_a4_directory_move_aside_with_open_contained_file_handle(tmp_path: Path):
    live_db_path = tmp_path / "redline.db"
    live_db_path.mkdir()
    contained = live_db_path / "held.txt"
    contained.write_bytes(b"held content")

    superseded = tmp_path / "redline.db__superseded-rc1-openhandle"

    handle = open(contained, "rb")
    try:
        try:
            os.rename(live_db_path, superseded)
            outcome = "succeeded"
        except PermissionError as exc:
            outcome = f"PermissionError: {exc}"
        except OSError as exc:
            outcome = f"OSError ({type(exc).__name__}): {exc}"
    finally:
        handle.close()

    print(f"[A4] directory-move-aside-with-open-contained-read-handle outcome: {outcome}")

    # Truthful observation, not an assumed POSIX-style outcome -- but
    # whichever way it went must be internally consistent (no partial
    # move: either the directory moved wholesale, or it stayed exactly
    # where it was).
    if outcome == "succeeded":
        assert not live_db_path.exists()
        assert superseded.exists()
        assert (superseded / "held.txt").exists()
    else:
        assert live_db_path.exists()
        assert not superseded.exists()
        assert (live_db_path / "held.txt").read_bytes() == b"held content"


# == Proof Case B: config path occupied by an ordinary regular file =========


def test_b1_regular_file_move_aside_succeeds_and_preserves_bytes(tmp_path: Path):
    live_config_path = tmp_path / "config"
    payload = b"naming: {}\nfolder_structure: {}\n"
    live_config_path.write_bytes(payload)

    superseded = tmp_path / "config__superseded-rc1-test"
    assert not superseded.exists()

    st_before = os.lstat(live_config_path)
    assert stat_module.S_ISREG(st_before.st_mode)

    os.rename(live_config_path, superseded)

    assert not live_config_path.exists()
    assert superseded.is_file()
    assert superseded.read_bytes() == payload

    # The original path is now free for a config directory to occupy.
    live_config_path.mkdir()
    assert live_config_path.is_dir()


def test_b2_regular_file_move_aside_refuses_existing_destination(tmp_path: Path):
    live_config_path = tmp_path / "config"
    live_config_path.write_bytes(b"live config bytes")

    superseded = tmp_path / "config__superseded-rc1-collide"
    superseded.write_bytes(b"pre-existing superseded bytes")

    with pytest.raises(OSError) as excinfo:
        os.rename(live_config_path, superseded)
    print(f"[B2] regular-file-collision exception: {type(excinfo.value).__name__}: {excinfo.value}")

    assert live_config_path.exists()
    assert live_config_path.read_bytes() == b"live config bytes"
    assert superseded.read_bytes() == b"pre-existing superseded bytes"


def test_b3_regular_file_move_aside_with_open_read_handle(tmp_path: Path):
    live_config_path = tmp_path / "config"
    live_config_path.write_bytes(b"live config bytes")
    superseded = tmp_path / "config__superseded-rc1-readhandle"

    handle = open(live_config_path, "rb")
    try:
        try:
            os.rename(live_config_path, superseded)
            outcome = "succeeded"
        except PermissionError as exc:
            outcome = f"PermissionError: {exc}"
        except OSError as exc:
            outcome = f"OSError ({type(exc).__name__}): {exc}"
    finally:
        handle.close()

    print(f"[B3-read] regular-file-move-aside-with-open-READ-handle outcome: {outcome}")

    if outcome == "succeeded":
        assert not live_config_path.exists()
        assert superseded.exists()
    else:
        assert live_config_path.exists()
        assert not superseded.exists()
        assert live_config_path.read_bytes() == b"live config bytes"


def test_b3_regular_file_move_aside_with_open_write_handle(tmp_path: Path):
    live_config_path = tmp_path / "config"
    live_config_path.write_bytes(b"live config bytes")
    superseded = tmp_path / "config__superseded-rc1-writehandle"

    handle = open(live_config_path, "r+b")
    try:
        try:
            os.rename(live_config_path, superseded)
            outcome = "succeeded"
        except PermissionError as exc:
            outcome = f"PermissionError: {exc}"
        except OSError as exc:
            outcome = f"OSError ({type(exc).__name__}): {exc}"
    finally:
        handle.close()

    print(f"[B3-write] regular-file-move-aside-with-open-WRITE-handle outcome: {outcome}")

    if outcome == "succeeded":
        assert not live_config_path.exists()
        assert superseded.exists()
    else:
        assert live_config_path.exists()
        assert not superseded.exists()
        assert live_config_path.read_bytes() == b"live config bytes"


# == Same-volume requirement =================================================


def test_same_volume_reports_true_for_normal_tmp_path_source_and_destination(tmp_path: Path):
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    assert same_volume(a, b)


def test_same_volume_gate_pattern_future_disposition_must_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """No safe second Windows volume exists in this isolated test
    environment to exercise a real cross-volume `os.stat().st_dev`
    mismatch. This proves the *gate pattern* a future disposition must
    apply instead: `same_volume()` must be checked and must fail closed
    BEFORE any `os.rename()` attempt -- proven here with `same_volume()`
    itself patched to report a mismatch, never real cross-drive I/O."""
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()

    monkeypatch.setattr(staging_module, "same_volume", lambda x, y: False)

    def _would_be_disposition_gate(source: Path, destination: Path) -> None:
        if not staging_module.same_volume(source, destination):
            raise fsutil.PathError(f"refusing cross-volume disposition: {source} -> {destination}")
        os.rename(source, destination)  # pragma: no cover -- never reached in this test

    with pytest.raises(fsutil.PathError):
        _would_be_disposition_gate(a, b)

    assert a.exists()
    assert b.exists()


# == Identity / byte-preservation evidence ===================================


def test_identity_evidence_directory_move_aside(tmp_path: Path):
    live_db_path = tmp_path / "redline.db"
    live_db_path.mkdir()
    (live_db_path / "f.txt").write_bytes(b"evidence payload")
    superseded = tmp_path / "redline.db__superseded-rc1-evidence"

    st_before_source = os.lstat(live_db_path)
    assert not superseded.exists()

    os.rename(live_db_path, superseded)

    assert not live_db_path.exists()
    st_after_dest = os.lstat(superseded)
    assert stat_module.S_ISDIR(st_after_dest.st_mode)
    # A directory's own size/mtime are not a meaningful content proxy on
    # Windows, so content preservation is proven by reading every
    # contained object, not by comparing directory-level stat fields.
    assert (superseded / "f.txt").read_bytes() == b"evidence payload"

    print(
        "[identity-dir] "
        f"before.st_dev={st_before_source.st_dev} after.st_dev={st_after_dest.st_dev} "
        f"before.st_ino={st_before_source.st_ino} after.st_ino={st_after_dest.st_ino}"
    )


def test_identity_evidence_regular_file_move_aside(tmp_path: Path):
    live_config_path = tmp_path / "config"
    payload = b"identity evidence payload bytes"
    live_config_path.write_bytes(payload)
    superseded = tmp_path / "config__superseded-rc1-evidence"

    st_before = os.lstat(live_config_path)
    os.rename(live_config_path, superseded)
    st_after = os.lstat(superseded)

    assert not live_config_path.exists()
    assert superseded.exists()
    assert stat_module.S_ISREG(st_after.st_mode)
    assert st_after.st_size == st_before.st_size == len(payload)
    assert superseded.read_bytes() == payload

    print(
        "[identity-file] "
        f"before.st_dev={st_before.st_dev} after.st_dev={st_after.st_dev} "
        f"before.st_ino={st_before.st_ino} after.st_ino={st_after.st_ino} "
        f"before.st_mtime_ns={st_before.st_mtime_ns} after.st_mtime_ns={st_after.st_mtime_ns}"
    )
