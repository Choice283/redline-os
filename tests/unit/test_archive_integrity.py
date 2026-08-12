"""Phase 15 Mission 15C -- Archive Rev1 filesystem integrity engine tests.

Scope: redline_core.archive.integrity only (safe root validation,
recursive inventory, streaming SHA-256, source stability, source-set
digest). No filesystem copying, no ArchiveManager, no DB, no Resolve, no
production media -- every test operates on tmp_path fixtures.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from redline_core.archive import integrity
from redline_core.archive.exceptions import (
    ArchiveInventoryError,
    ArchivePathError,
    ArchiveSourceChangedError,
    ArchiveUnsafeFilesystemObjectError,
)
from redline_core.archive.integrity import (
    InventoryDirectory,
    InventoryFile,
    build_source_inventory,
    hash_stable_file,
    validate_source_root,
)


# -- helpers ------------------------------------------------------------------


def _make_tree(root: Path) -> None:
    (root / "exports").mkdir(parents=True)
    (root / "graphics").mkdir()
    (root / "footage" / "nested").mkdir(parents=True)
    (root / "exports" / "master.mov").write_bytes(b"master-content")
    (root / "footage" / "clip1.mov").write_bytes(b"clip-one")
    (root / "footage" / "nested" / "clip2.mov").write_bytes(b"clip-two")


def _create_junction(link: Path, target: Path) -> bool:
    """Best-effort, privilege-free Windows junction creation for tests.
    Returns False (never raises) on any platform/failure other than a
    genuine successful junction creation, so callers can skip cleanly."""
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and link.exists()


def _create_symlink(link: Path, target: Path, *, target_is_directory: bool) -> bool:
    """Best-effort symlink creation for tests. Returns False (never
    raises) if this environment cannot create the link (e.g. Windows
    without Developer Mode/admin), so callers can skip cleanly rather than
    hide a real failure under a blanket platform skip."""
    try:
        os.symlink(target, link, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError):
        return False
    return link.is_symlink()


# -- root validation ------------------------------------------------------------


def test_validate_source_root_rejects_missing_path(tmp_path):
    with pytest.raises(ArchivePathError):
        validate_source_root(tmp_path / "does_not_exist")


def test_validate_source_root_rejects_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(ArchivePathError):
        validate_source_root(f)


def test_validate_source_root_accepts_valid_directory(tmp_path):
    d = tmp_path / "root"
    d.mkdir()
    resolved = validate_source_root(d)
    assert resolved == d.resolve()


def test_validate_source_root_rejects_non_path_like_input():
    with pytest.raises(ArchivePathError):
        validate_source_root(12345)  # type: ignore[arg-type]


# -- basic inventory --------------------------------------------------------------


def test_build_source_inventory_finds_all_files_and_directories(tmp_path):
    root = tmp_path / "root"
    _make_tree(root)
    (root / "empty_dir").mkdir()

    inventory = build_source_inventory(root)

    file_paths = {f.relative_path for f in inventory.files}
    dir_paths = {d.relative_path for d in inventory.directories}
    assert file_paths == {"exports/master.mov", "footage/clip1.mov", "footage/nested/clip2.mov"}
    assert dir_paths == {"exports", "graphics", "footage", "footage/nested", "empty_dir"}

    assert inventory.file_count == 3
    assert inventory.directory_count == 5
    assert inventory.total_bytes == len(b"master-content") + len(b"clip-one") + len(b"clip-two")
    assert inventory.root == root.resolve()


def test_build_source_inventory_file_entries_have_correct_hash_and_size(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    content = b"hello archive world"
    (root / "a.bin").write_bytes(content)

    inventory = build_source_inventory(root)

    assert inventory.file_count == 1
    entry = inventory.files[0]
    assert entry.relative_path == "a.bin"
    assert entry.size_bytes == len(content)
    assert entry.sha256 == hashlib.sha256(content).hexdigest()
    assert entry.absolute_source_path == (root / "a.bin").resolve()


def test_build_source_inventory_empty_root_is_valid(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    inventory = build_source_inventory(root)

    assert inventory.file_count == 0
    assert inventory.directory_count == 0
    assert inventory.total_bytes == 0


# -- streaming hash -----------------------------------------------------------------


def test_hash_stable_file_matches_expected_sha256(tmp_path):
    content = b"the quick brown fox jumps over the lazy dog"
    f = tmp_path / "f.bin"
    f.write_bytes(content)

    sha256, size_bytes = hash_stable_file(f)

    assert sha256 == hashlib.sha256(content).hexdigest()
    assert size_bytes == len(content)
    assert len(sha256) == 64
    assert sha256 == sha256.lower()


def test_hash_stable_file_reads_in_bounded_chunks_not_whole_file(tmp_path, monkeypatch):
    """Structural proof of chunked reading: patches the chunk size down to
    a tiny value and counts read() calls against a file that requires
    several chunks, confirming no single read() call consumes the whole
    file at once."""
    content = b"x" * 10_000
    f = tmp_path / "f.bin"
    f.write_bytes(content)

    monkeypatch.setattr(integrity, "_HASH_CHUNK_SIZE", 1000)

    read_sizes: list[int] = []
    real_open = Path.open

    class _CountingFile:
        def __init__(self, fh):
            self._fh = fh

        def read(self, n):
            data = self._fh.read(n)
            read_sizes.append(len(data))
            return data

        def fileno(self):
            return self._fh.fileno()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._fh.close()

    def fake_open(self, mode, *a, **kw):
        fh = real_open(self, mode, *a, **kw)
        if self == f and mode == "rb":
            return _CountingFile(fh)
        return fh

    monkeypatch.setattr(Path, "open", fake_open)

    sha256, size_bytes = hash_stable_file(f)

    assert sha256 == hashlib.sha256(content).hexdigest()
    assert size_bytes == len(content)
    assert len(read_sizes) > 1
    assert all(n <= 1000 for n in read_sizes)


def test_hash_stable_file_rejects_directory(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        hash_stable_file(d)


def test_hash_stable_file_rejects_missing_path(tmp_path):
    with pytest.raises(ArchivePathError):
        hash_stable_file(tmp_path / "missing.bin")


# -- source mutation detection (deterministic monkeypatching) --------------------------


def test_hash_stable_file_fails_closed_when_stat_changes_during_hashing(tmp_path, monkeypatch):
    target = tmp_path / "f.bin"
    target.write_bytes(b"hello world")

    real_lstat = os.lstat
    call_count = {"n": 0}

    class _MutatedStat:
        def __init__(self, real):
            self.st_mode = real.st_mode
            self.st_size = real.st_size
            self.st_mtime_ns = real.st_mtime_ns + 1  # simulate a change
            self.st_ino = getattr(real, "st_ino", 0)
            self.st_dev = getattr(real, "st_dev", 0)
            if hasattr(real, "st_file_attributes"):
                self.st_file_attributes = real.st_file_attributes

    def fake_lstat(path, *a, **kw):
        real = real_lstat(path, *a, **kw)
        if os.fspath(path) == os.fspath(target):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return _MutatedStat(real)
        return real

    monkeypatch.setattr(integrity.os, "lstat", fake_lstat)

    with pytest.raises(ArchiveSourceChangedError):
        hash_stable_file(target)


class _MutatedFstat:
    """Fake fstat() result carrying a deliberately-wrong identity field,
    used to deterministically simulate an opened-handle identity mismatch
    without any real timing/threading."""

    def __init__(self, real, *, size_delta=0, mtime_ns_delta=0):
        self.st_mode = real.st_mode
        self.st_size = real.st_size + size_delta
        self.st_mtime_ns = real.st_mtime_ns + mtime_ns_delta
        self.st_ino = getattr(real, "st_ino", 0)
        self.st_dev = getattr(real, "st_dev", 0)
        if hasattr(real, "st_file_attributes"):
            self.st_file_attributes = real.st_file_attributes


def _patch_fstat_for_target(monkeypatch, target: Path, *, mutate_on_call: int, **mutation_kwargs):
    """Patch os.fstat so the call-th fstat() against `target`'s own file
    descriptor (identified by matching inode/device against a real,
    pre-patch os.stat() of target -- not a global call counter -- so an
    unrelated os.fstat() call elsewhere in the process during the test
    can never be mistaken for one of ours) returns a mutated result."""
    real_fstat = os.fstat
    target_stat = os.stat(target)
    call_count = {"n": 0}

    def fake_fstat(fd, *a, **kw):
        real = real_fstat(fd, *a, **kw)
        if getattr(real, "st_ino", None) == target_stat.st_ino and getattr(real, "st_dev", None) == target_stat.st_dev:
            call_count["n"] += 1
            if call_count["n"] == mutate_on_call:
                return _MutatedFstat(real, **mutation_kwargs)
        return real

    monkeypatch.setattr(integrity.os, "fstat", fake_fstat)


def test_hash_stable_file_fails_closed_when_opened_handle_does_not_match_pre_open_identity(tmp_path, monkeypatch):
    """Simulates the object represented by the just-opened file
    descriptor not matching the pathname identity observed before
    opening -- e.g. the path was swapped for a different object between
    the pre-open lstat and open() succeeding, which open() has no way to
    refuse following. hash_stable_file()'s fstat() taken immediately
    after opening (checkpoint #2) must catch this, before any content is
    streamed."""
    target = tmp_path / "f.bin"
    target.write_bytes(b"hello world")

    _patch_fstat_for_target(monkeypatch, target, mutate_on_call=1, size_delta=1)

    with pytest.raises(ArchiveSourceChangedError):
        hash_stable_file(target)


def test_hash_stable_file_fails_closed_when_opened_handle_changes_during_streaming(tmp_path, monkeypatch):
    """Simulates the already-open descriptor's own fstat() reporting a
    different identity between the pre-streaming and post-streaming
    observation (checkpoints #2 and #3) -- the handle-level counterpart to
    the existing pathname-level mutation test above."""
    target = tmp_path / "f.bin"
    target.write_bytes(b"hello world" * 100)

    _patch_fstat_for_target(monkeypatch, target, mutate_on_call=2, mtime_ns_delta=1)

    with pytest.raises(ArchiveSourceChangedError):
        hash_stable_file(target)


def test_build_source_inventory_fails_closed_on_tree_mutation_added_file(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"hello")

    real_enumerate = integrity._enumerate_source_tree
    call_count = {"n": 0}

    def fake_enumerate(r):
        entries = real_enumerate(r)
        call_count["n"] += 1
        if call_count["n"] == 2:
            phantom = r / "b.txt"
            entries = [*entries, ("b.txt", "file", phantom)]
        return entries

    monkeypatch.setattr(integrity, "_enumerate_source_tree", fake_enumerate)

    with pytest.raises(ArchiveSourceChangedError):
        build_source_inventory(root)


def test_build_source_inventory_fails_closed_on_tree_mutation_removed_file(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"hello")
    (root / "b.txt").write_bytes(b"world")

    real_enumerate = integrity._enumerate_source_tree
    call_count = {"n": 0}

    def fake_enumerate(r):
        entries = real_enumerate(r)
        call_count["n"] += 1
        if call_count["n"] == 2:
            entries = [e for e in entries if e[0] != "b.txt"]
        return entries

    monkeypatch.setattr(integrity, "_enumerate_source_tree", fake_enumerate)

    with pytest.raises(ArchiveSourceChangedError):
        build_source_inventory(root)


# -- symlink / junction rejection -----------------------------------------------------


def test_symlinked_file_inside_root_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "outside.txt"
    target.write_bytes(b"outside")
    link = root / "linked.txt"

    if not _create_symlink(link, target, target_is_directory=False):
        pytest.skip("this environment cannot create symlinks (no admin/Developer Mode)")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        build_source_inventory(root)


def test_symlinked_directory_inside_root_pointing_outside_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "outside_dir"
    target.mkdir()
    (target / "secret.txt").write_bytes(b"should never be reached")
    link = root / "linked_dir"

    if not _create_symlink(link, target, target_is_directory=True):
        pytest.skip("this environment cannot create symlinks (no admin/Developer Mode)")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        build_source_inventory(root)


def test_symlinked_directory_inside_root_pointing_inside_rejected(tmp_path):
    """Policy is reject-all-symlinks regardless of destination -- a link
    that points back inside the same root must fail exactly like one that
    points outside."""
    root = tmp_path / "root"
    root.mkdir()
    real_subdir = root / "real_subdir"
    real_subdir.mkdir()
    link = root / "linked_dir"

    if not _create_symlink(link, real_subdir, target_is_directory=True):
        pytest.skip("this environment cannot create symlinks (no admin/Developer Mode)")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        build_source_inventory(root)


def test_symlink_root_rejected(tmp_path):
    target = tmp_path / "target_dir"
    target.mkdir()
    link = tmp_path / "link_root"

    if not _create_symlink(link, target, target_is_directory=True):
        pytest.skip("this environment cannot create symlinks (no admin/Developer Mode)")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        validate_source_root(link)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-only")
def test_junction_root_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"

    if not _create_junction(link, target):
        pytest.skip("could not create a Windows junction in this environment")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        validate_source_root(link)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-only")
def test_junction_inside_root_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "outside_target"
    target.mkdir()
    link = root / "linked_subdir"

    if not _create_junction(link, target):
        pytest.skip("could not create a Windows junction in this environment")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        build_source_inventory(root)


def test_is_unsafe_link_detects_windows_reparse_attribute_without_creating_a_real_link(tmp_path):
    """Unit-tests the reparse-point detection primitive directly against a
    synthetic stat-like object, independent of whether this environment
    can create real links/junctions -- documents and proves the Windows
    detection mechanism (st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT)
    deterministically, cross-platform."""
    import stat as stat_module

    class _FakeReparseStat:
        st_mode = stat_module.S_IFDIR
        st_file_attributes = stat_module.FILE_ATTRIBUTE_REPARSE_POINT

    class _FakeNormalStat:
        st_mode = stat_module.S_IFDIR
        st_file_attributes = 0

    assert integrity._is_unsafe_link(_FakeReparseStat()) is True
    assert integrity._is_unsafe_link(_FakeNormalStat()) is False


# -- deterministic ordering -----------------------------------------------------------


def test_inventory_ordering_is_deterministic_regardless_of_creation_order(tmp_path):
    root_a = tmp_path / "root_a"
    root_a.mkdir()
    (root_a / "zeta").mkdir()
    (root_a / "alpha").mkdir()
    (root_a / "zeta" / "z.txt").write_bytes(b"z")
    (root_a / "alpha" / "a.txt").write_bytes(b"a")
    (root_a / "top.txt").write_bytes(b"top")

    root_b = tmp_path / "root_b"
    root_b.mkdir()
    (root_b / "alpha").mkdir()
    (root_b / "top.txt").write_bytes(b"top")
    (root_b / "zeta").mkdir()
    (root_b / "alpha" / "a.txt").write_bytes(b"a")
    (root_b / "zeta" / "z.txt").write_bytes(b"z")

    inv_a = build_source_inventory(root_a)
    inv_b = build_source_inventory(root_b)

    a_files = [f.relative_path for f in inv_a.files]
    b_files = [f.relative_path for f in inv_b.files]
    a_dirs = [d.relative_path for d in inv_a.directories]
    b_dirs = [d.relative_path for d in inv_b.directories]

    assert a_files == b_files
    assert a_dirs == b_dirs
    assert a_files == sorted(a_files, key=str.casefold)
    assert a_dirs == sorted(a_dirs, key=str.casefold)


# -- source-set digest: stability and sensitivity ----------------------------------------


def test_source_set_digest_stable_for_unchanged_tree(tmp_path):
    root = tmp_path / "root"
    _make_tree(root)

    digest1 = build_source_inventory(root).source_set_digest
    digest2 = build_source_inventory(root).source_set_digest

    assert digest1 == digest2
    assert len(digest1) == 64
    assert digest1 == digest1.lower()


def test_source_set_digest_changes_on_file_content_change(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    f = root / "a.bin"
    f.write_bytes(b"original")
    digest1 = build_source_inventory(root).source_set_digest

    f.write_bytes(b"changed!")
    digest2 = build_source_inventory(root).source_set_digest

    assert digest1 != digest2


def test_source_set_digest_changes_on_file_rename(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    f = root / "a.bin"
    f.write_bytes(b"content")
    digest1 = build_source_inventory(root).source_set_digest

    f.rename(root / "b.bin")
    digest2 = build_source_inventory(root).source_set_digest

    assert digest1 != digest2


def test_source_set_digest_changes_on_file_addition(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.bin").write_bytes(b"content")
    digest1 = build_source_inventory(root).source_set_digest

    (root / "b.bin").write_bytes(b"more content")
    digest2 = build_source_inventory(root).source_set_digest

    assert digest1 != digest2


def test_source_set_digest_changes_on_file_deletion(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.bin").write_bytes(b"content")
    (root / "b.bin").write_bytes(b"more content")
    digest1 = build_source_inventory(root).source_set_digest

    (root / "b.bin").unlink()
    digest2 = build_source_inventory(root).source_set_digest

    assert digest1 != digest2


def test_source_set_digest_changes_on_empty_directory_addition(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.bin").write_bytes(b"content")
    digest1 = build_source_inventory(root).source_set_digest

    (root / "empty_dir").mkdir()
    digest2 = build_source_inventory(root).source_set_digest

    assert digest1 != digest2


def test_source_set_digest_changes_on_empty_directory_removal(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.bin").write_bytes(b"content")
    (root / "empty_dir").mkdir()
    digest1 = build_source_inventory(root).source_set_digest

    (root / "empty_dir").rmdir()
    digest2 = build_source_inventory(root).source_set_digest

    assert digest1 != digest2


def test_source_set_digest_is_canonical_json_sha256():
    directories = (InventoryDirectory(relative_path="audio", absolute_source_path=Path("/x/audio")),)
    files = (
        InventoryFile(
            relative_path="exports/example.mov",
            absolute_source_path=Path("/x/exports/example.mov"),
            size_bytes=123,
            sha256="a" * 64,
        ),
    )
    expected_payload = {
        "schema_version": 1,
        "directories": ["audio"],
        "files": [{"path": "exports/example.mov", "size_bytes": 123, "sha256": "a" * 64}],
    }
    expected_bytes = json.dumps(expected_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    expected_digest = hashlib.sha256(expected_bytes).hexdigest()

    assert integrity._source_set_digest(directories, files) == expected_digest


# -- normalized identity collision (synthetic, not filesystem-dependent) -----------------


def test_normalized_identity_collision_fails_closed():
    seen: dict[str, str] = {}
    integrity._register_relative_identity(seen, "Footage/clip.mov")

    with pytest.raises(ArchiveInventoryError):
        integrity._register_relative_identity(seen, "footage/CLIP.mov")


def test_normalized_identity_no_collision_for_distinct_paths():
    seen: dict[str, str] = {}
    integrity._register_relative_identity(seen, "footage/clip1.mov")
    integrity._register_relative_identity(seen, "footage/clip2.mov")
    assert len(seen) == 2
