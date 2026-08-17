"""Tests for BackupManager (Mission 1A: System-of-Record Backup +
Verification) against a real, temporary SQLite database (via
redline_core.db.database.Database, so the exact real schema/migrations
apply) and a real, temporary six-file config directory -- no Resolve
involved anywhere in this file, and no mock of SQLite itself (this
project's own established convention, mirrored from test_archive_manager.py
and test_db.py).
"""
from __future__ import annotations

import ast
import hashlib
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redline_core.backup.exceptions import (
    BackupConfigurationError,
    BackupDatabaseSnapshotError,
    BackupDestinationCollisionError,
    BackupError,
    BackupNotFoundError,
    BackupPathContainmentError,
    BackupSourceUnavailableError,
    BackupUnsafeFilesystemObjectError,
    BackupVerificationFailedError,
)
from redline_core.backup.manager import BackupManager
from redline_core.backup.package import MANIFEST_FILENAME, MANIFEST_SHA256_FILENAME, MARKER_FILENAME
from redline_core.config.loader import REQUIRED_FILES
from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.db.database import Database

_FIXED_MOMENT = datetime(2026, 8, 16, 19, 30, 0, tzinfo=timezone.utc)


# -- environment helpers ------------------------------------------------------


def _write_minimal_config_dir(config_dir: Path, *, omit: str | None = None) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    contents = {
        "naming.yaml": (
            'episode_id_pattern: "RLC-E{episode_number:03d}"\n'
            'project_name_pattern: "{episode_id}_MASTER"\n'
        ),
        "folder_structure.yaml": 'root_path: "./_episodes"\n',
        "render_presets.yaml": "presets: []\n",
        "paths.yaml": (
            'ingest_path: "./_ingest"\n'
            'archive_path: "./_archive"\n'
            'assets_path: "./_assets"\n'
            'master_project_template: "RLC_MASTER_TEMPLATE"\n'
        ),
        "assets.yaml": "assets: []\nrequired_for_episode: []\n",
        "timeline_template.yaml": ('timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n'),
    }
    for filename, text in contents.items():
        if filename == omit:
            continue
        (config_dir / filename).write_text(text, encoding="utf-8")


def _make_redline_config(*, backup_path: str | None) -> RedlineConfig:
    return RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path="./_episodes"),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path="./_ingest",
            archive_path="./_archive",
            assets_path="./_assets",
            master_project_template="RLC_MASTER_TEMPLATE",
            backup_path=backup_path,
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )


def _make_db(db_path: Path, *, with_episode: bool = True) -> None:
    db = Database(db_path).connect()
    db.init_schema()
    if with_episode:
        db.create_episode(1, "RLC-E001", "RLC-E001_MASTER")
    db.close()


def _make_environment(tmp_path: Path, *, configure_backup_path: bool = True, omit_config_file: str | None = None):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    _make_db(db_path)

    config_dir = tmp_path / "config"
    _write_minimal_config_dir(config_dir, omit=omit_config_file)

    backup_root = tmp_path / "backups"
    config = _make_redline_config(backup_path=str(backup_root) if configure_backup_path else None)

    manager = BackupManager(config, config_dir, db_path, clock=lambda: _FIXED_MOMENT)
    return manager, db_path, config_dir, backup_root


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_hashes(config_dir: Path) -> dict[str, str]:
    return {filename: _sha256_bytes(config_dir / filename) for filename in REQUIRED_FILES.values()}


# -- create: happy path + zero source mutation --------------------------------


def test_create_backup_succeeds_and_returns_expected_result(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)

    result = manager.create_backup(reason="unit test")

    assert result.backup_id.startswith("b1-20260816T193000Z-")
    assert result.backup_path == backup_root / "system_backups" / result.backup_id
    assert result.backup_path.is_dir()
    assert (result.backup_path / MARKER_FILENAME).is_file()
    assert result.manifest_path == result.backup_path / MANIFEST_FILENAME
    assert result.manifest_path.is_file()
    assert result.config_file_count == len(REQUIRED_FILES)
    assert result.database_size_bytes > 0
    assert result.total_bytes > result.database_size_bytes
    assert len(result.database_sha256) == 64
    assert len(result.content_set_digest) == 64


def test_create_backup_never_mutates_source_database_or_config(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    db_hash_before = _sha256_bytes(db_path)
    config_hashes_before = _config_hashes(config_dir)

    manager.create_backup()

    assert _sha256_bytes(db_path) == db_hash_before
    assert _config_hashes(config_dir) == config_hashes_before


def test_create_backup_snapshot_passes_integrity_check_and_matches_source_rows(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    snapshot_path = result.backup_path / "payload" / "database" / "redline.db"
    conn = sqlite3.connect(f"{snapshot_path.as_uri()}?mode=ro", uri=True)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = conn.execute("SELECT episode_id, status FROM episodes").fetchall()
        assert rows == [("RLC-E001", "created")]
    finally:
        conn.close()


# -- create: fail-closed preconditions -----------------------------------------


def test_create_backup_fails_closed_when_backup_path_not_configured(tmp_path: Path):
    manager, *_ = _make_environment(tmp_path, configure_backup_path=False)
    with pytest.raises(BackupConfigurationError):
        manager.create_backup()


def test_create_backup_fails_closed_when_required_config_file_missing(tmp_path: Path):
    manager, *_ = _make_environment(tmp_path, omit_config_file="assets.yaml")
    with pytest.raises(BackupSourceUnavailableError):
        manager.create_backup()


def test_create_backup_fails_closed_when_source_database_missing(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    db_path.unlink()
    with pytest.raises(BackupSourceUnavailableError):
        manager.create_backup()


def test_create_backup_fails_closed_on_backup_root_overlapping_db_directory(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    _make_db(db_path)
    config_dir = tmp_path / "config"
    _write_minimal_config_dir(config_dir)

    overlapping_backup_root = runtime_dir / "backups"  # inside the db's own directory
    config = _make_redline_config(backup_path=str(overlapping_backup_root))
    manager = BackupManager(config, config_dir, db_path, clock=lambda: _FIXED_MOMENT)

    with pytest.raises(BackupPathContainmentError):
        manager.create_backup()


def test_create_backup_fails_closed_on_unsafe_database_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    from redline_core import fsutil

    monkeypatch.setattr(fsutil, "is_unsafe_link", lambda st: True)
    with pytest.raises(BackupError):
        manager.create_backup()


# -- create: collision / interruption -------------------------------------------


def test_create_backup_second_identical_call_collides_and_never_overwrites(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    first = manager.create_backup()
    first_manifest_bytes = (first.backup_path / MANIFEST_FILENAME).read_bytes()

    with pytest.raises(BackupDestinationCollisionError):
        manager.create_backup()  # same fixed clock + unchanged source content -> same backup_id

    # the original backup must be completely untouched by the failed second attempt
    assert (first.backup_path / MANIFEST_FILENAME).read_bytes() == first_manifest_bytes


def test_interrupted_staging_never_publishes_a_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)

    def _raise(*args, **kwargs):
        raise BackupDatabaseSnapshotError("simulated mid-staging failure")

    monkeypatch.setattr("redline_core.backup.package.snapshot_database", _raise)

    with pytest.raises(BackupDatabaseSnapshotError):
        manager.create_backup()

    system_backups_dir = backup_root / "system_backups"
    assert not system_backups_dir.exists() or list(system_backups_dir.iterdir()) == []


# -- verify: happy path + repeatability -----------------------------------------


def test_verify_backup_succeeds_and_is_idempotent(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    first = manager.verify_backup(result.backup_id)
    second = manager.verify_backup(result.backup_id)

    assert first.verified is True
    assert second.verified is True
    assert first == second


def test_verify_backup_raises_not_found_for_unknown_id(tmp_path: Path):
    manager, *_ = _make_environment(tmp_path)
    manager.create_backup()  # ensure backup_path exists at all
    with pytest.raises(BackupNotFoundError):
        manager.verify_backup("b1-20260816T193000Z-000000000000")


def test_verify_backup_raises_not_found_when_backup_path_never_configured(tmp_path: Path):
    manager, *_ = _make_environment(tmp_path, configure_backup_path=False)
    with pytest.raises(BackupNotFoundError):
        manager.verify_backup("b1-20260816T193000Z-000000000000")


# -- verify: corruption detection ------------------------------------------------


def test_verify_backup_detects_corrupted_database_snapshot(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    snapshot_path = result.backup_path / "payload" / "database" / "redline.db"
    _flip_one_byte(snapshot_path)

    with pytest.raises(BackupVerificationFailedError):
        manager.verify_backup(result.backup_id)


def test_verify_backup_detects_corrupted_config_file(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    corrupted = result.backup_path / "payload" / "config" / "assets.yaml"
    _flip_one_byte(corrupted)

    with pytest.raises(BackupVerificationFailedError):
        manager.verify_backup(result.backup_id)


def test_verify_backup_detects_manifest_sidecar_mismatch(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    manifest_path = result.backup_path / MANIFEST_FILENAME
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")  # tamper without updating the sidecar

    with pytest.raises(BackupVerificationFailedError):
        manager.verify_backup(result.backup_id)


def test_verify_backup_rejects_package_missing_completion_marker(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    (result.backup_path / MARKER_FILENAME).unlink()

    with pytest.raises(BackupVerificationFailedError):
        manager.verify_backup(result.backup_id)


# -- verify: exact sealed package inventory (Mission 1A correction pass) --------
#
# Independent review found the original unexpected-file check under
# payload/config used non-recursive Path.iterdir(), so a file nested inside
# a subdirectory escaped detection entirely, and no equivalent check
# existed for payload/database at all. These tests lock in the corrected,
# single-level, exhaustive check in both directories (deliberately
# non-recursive -- see package.py's own docstring for why recursing is
# never correct here).


def test_verify_backup_rejects_nested_unexpected_config_file(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    nested_dir = result.backup_path / "payload" / "config" / "existing_looking_subdir"
    nested_dir.mkdir()
    (nested_dir / "injected.yaml").write_text("malicious: true\n", encoding="utf-8")

    with pytest.raises(BackupVerificationFailedError):
        manager.verify_backup(result.backup_id)


def test_verify_backup_rejects_nested_unexpected_config_directory(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    (result.backup_path / "payload" / "config" / "empty_nested_dir").mkdir()

    with pytest.raises(BackupVerificationFailedError):
        manager.verify_backup(result.backup_id)


def test_verify_backup_rejects_unexpected_top_level_config_file(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    (result.backup_path / "payload" / "config" / "rogue.yaml").write_text("x: 1\n", encoding="utf-8")

    with pytest.raises(BackupVerificationFailedError):
        manager.verify_backup(result.backup_id)


def test_verify_backup_rejects_extra_database_file(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    (result.backup_path / "payload" / "database" / "extra.db").write_bytes(b"not a real database")

    with pytest.raises(BackupVerificationFailedError):
        manager.verify_backup(result.backup_id)


def test_verify_backup_rejects_nested_database_file_and_directory(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    nested_dir = result.backup_path / "payload" / "database" / "nested"
    nested_dir.mkdir()
    (nested_dir / "sneaky.db").write_bytes(b"not a real database")

    with pytest.raises(BackupVerificationFailedError):
        manager.verify_backup(result.backup_id)


def test_verify_backup_still_succeeds_for_untampered_package(tmp_path: Path):
    """The corrected recursive/exhaustive inventory check must not produce
    a false positive against a genuinely untampered sealed package -- the
    exact package structure BackupManager itself produces must still be
    exactly what verification expects."""
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    verification = manager.verify_backup(result.backup_id)

    assert verification.verified is True
    assert verification.database_integrity_check == "ok"


def test_verify_backup_fails_through_exact_inventory_unsafe_object_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Direct coverage for `_require_exact_payload_contents()`'s own
    unsafe-object rejection branch specifically -- not merely the earlier,
    separate `require_safe_regular_file()` checks against the six
    manifested config files and the database snapshot (which only ever
    look at those exact files, never at extras).

    An *extra* file -- never part of the manifest, so it can only ever be
    discovered by the exact-inventory scan itself, not by the earlier
    per-manifested-file checks -- is placed in the config payload with a
    distinctive size, and `fsutil.is_unsafe_link` is patched to report
    *only* that size as unsafe (the real check still runs for everything
    else), isolating exactly which branch catches it."""
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    sentinel_size = 424242
    extra_path = result.backup_path / "payload" / "config" / "extra_unsafe_object"
    extra_path.write_bytes(b"x" * sentinel_size)

    from redline_core import fsutil as fsutil_module

    real_is_unsafe_link = fsutil_module.is_unsafe_link

    def _fake_is_unsafe_link(st):
        if st.st_size == sentinel_size:
            return True
        return real_is_unsafe_link(st)

    monkeypatch.setattr(fsutil_module, "is_unsafe_link", _fake_is_unsafe_link)

    with pytest.raises(BackupVerificationFailedError) as exc_info:
        manager.verify_backup(result.backup_id)

    assert isinstance(exc_info.value.__cause__, BackupUnsafeFilesystemObjectError)
    assert "extra_unsafe_object" in str(exc_info.value.__cause__)


def test_verify_backup_rejects_junction_before_enumerating_its_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Correction C requirement: prove an unsafe directory is rejected
    *before* its contents are ever enumerated, not merely that it is
    eventually rejected. Mirrors this project's own established
    unsafe-object test convention (`fsutil.is_unsafe_link` patched to
    report a specific entry as unsafe, rather than creating a real
    Windows junction, which -- as `test_backup_paths.py`'s own docstring
    already documents -- this suite deliberately avoids for portability).

    A real, ordinary directory stands in for the junction's own entry
    (identified precisely by its inode, so only *that* entry is treated as
    unsafe); a second real directory, `target_dir`, stands in for what a
    real junction would point at, containing an observable marker. If the
    corrected single-level scan ever recursed into the "junction" the way
    the old `rglob()`-based version did, `Path.iterdir()` would be called
    on `target_dir` to discover the marker file. It never is."""
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    target_dir = tmp_path / "junction_target"
    target_dir.mkdir()
    (target_dir / "should_never_be_seen.txt").write_text(
        "if this file is ever discovered, the target directory was enumerated", encoding="utf-8"
    )

    fake_junction = result.backup_path / "payload" / "config" / "evil_junction"
    fake_junction.mkdir()

    scanned_paths: list[Path] = []
    real_iterdir = Path.iterdir

    def _tracking_iterdir(self):
        scanned_paths.append(self)
        return real_iterdir(self)

    from redline_core import fsutil as fsutil_module

    real_is_unsafe_link = fsutil_module.is_unsafe_link
    junction_ino_dev = (os.lstat(fake_junction).st_ino, os.lstat(fake_junction).st_dev)

    def _fake_is_unsafe_link(st):
        if (st.st_ino, st.st_dev) == junction_ino_dev:
            return True
        return real_is_unsafe_link(st)

    monkeypatch.setattr(fsutil_module, "is_unsafe_link", _fake_is_unsafe_link)
    monkeypatch.setattr(Path, "iterdir", _tracking_iterdir)

    with pytest.raises(BackupVerificationFailedError) as exc_info:
        manager.verify_backup(result.backup_id)

    assert isinstance(exc_info.value.__cause__, BackupUnsafeFilesystemObjectError)
    assert "evil_junction" in str(exc_info.value.__cause__)
    # The proof: the "junction target" was never scanned at all -- not even
    # the "junction" directory entry itself was ever handed to iterdir(),
    # because this implementation never recurses into any subdirectory,
    # safe or not.
    assert target_dir not in scanned_paths
    assert fake_junction not in scanned_paths


def _flip_one_byte(path: Path) -> None:
    data = bytearray(path.read_bytes())
    assert data, f"expected non-empty file to corrupt: {path}"
    data[0] ^= 0xFF
    path.write_bytes(bytes(data))


# -- list -------------------------------------------------------------------------


def test_list_backups_empty_when_backup_path_not_configured(tmp_path: Path):
    manager, *_ = _make_environment(tmp_path, configure_backup_path=False)
    assert manager.list_backups() == []


def test_list_backups_returns_created_backups_newest_first(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    first = manager.create_backup(reason="first")

    later_manager = BackupManager(
        manager.config, config_dir, db_path, clock=lambda: datetime(2026, 8, 16, 20, 0, 0, tzinfo=timezone.utc)
    )
    # change source content so the second backup gets a genuinely different id
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE episodes SET project_name = 'RLC-E001_MASTER_V2' WHERE episode_id = 'RLC-E001'")
    second = later_manager.create_backup(reason="second")

    records = manager.list_backups()
    assert [r.backup_id for r in records] == [second.backup_id, first.backup_id]
    assert records[0].reason == "second"
    assert records[1].reason == "first"


def test_list_backups_excludes_incomplete_package(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    # a second, incomplete package: directory exists, no completion marker
    fake_dir = backup_root / "system_backups" / "b1-20260816T193000Z-ffffffffffff"
    fake_dir.mkdir(parents=True)
    (fake_dir / "payload").mkdir()

    records = manager.list_backups()
    assert [r.backup_id for r in records] == [result.backup_id]


def test_list_backups_excludes_package_with_tampered_manifest(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    manifest_path = result.backup_path / MANIFEST_FILENAME
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

    assert manager.list_backups() == []


# -- list: backup_id / directory identity (Mission 1A correction pass) ----------
#
# Independent review found list_backups() could report manifest["backup_id"]
# paired with a differently-named package directory, an inconsistency
# verify_backup() (which reconstructs its lookup path purely from the
# requested backup_id) could never actually resolve. These lock in the
# corrected structural identity check.


def test_list_backups_reports_matching_backup_id_for_normal_creation(tmp_path: Path):
    """A backup created and published normally always has a manifest
    backup_id equal to its own directory name -- the common case must keep
    listing correctly after the identity check is added."""
    manager, *_ = _make_environment(tmp_path)
    result = manager.create_backup()

    records = manager.list_backups()

    assert [r.backup_id for r in records] == [result.backup_id]
    assert records[0].backup_path.name == result.backup_id


def test_list_backups_excludes_package_with_renamed_directory(tmp_path: Path):
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    system_backups_dir = backup_root / "system_backups"
    renamed_dir = system_backups_dir / "b1-20260816T193000Z-renamedid01"
    result.backup_path.rename(renamed_dir)

    # The manifest inside still claims the *original* backup_id, but the
    # directory holding it no longer agrees -- must not be listed.
    assert manager.list_backups() == []


def test_list_backups_excludes_copied_package_but_keeps_correctly_named_original(tmp_path: Path):
    """Distinct from the rename test above: here the *original*,
    correctly-named package is left in place (not moved), and a full copy
    of its sealed contents is additionally placed under a second,
    different directory name. Both directories now contain a manifest
    claiming the same original backup_id -- only the one whose directory
    name actually matches that backup_id may be listed; the copy must be
    excluded."""
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    system_backups_dir = backup_root / "system_backups"
    copied_dir = system_backups_dir / "b1-20260816T193000Z-copiedid001"
    shutil.copytree(result.backup_path, copied_dir)

    records = manager.list_backups()

    assert [r.backup_id for r in records] == [result.backup_id]
    assert records[0].backup_path == result.backup_path


def test_verify_backup_unaffected_by_list_identity_check(tmp_path: Path):
    """verify_backup()'s own behavior (reconstructing its lookup path
    purely from the requested backup_id, independent of list_backups())
    must remain unchanged: a renamed package is correctly reported as not
    found by verify_backup() under its original id, exactly as it was
    before this correction -- this is a structural identity check for
    list_backups() only, not a change to verify_backup() itself."""
    manager, db_path, config_dir, backup_root = _make_environment(tmp_path)
    result = manager.create_backup()

    system_backups_dir = backup_root / "system_backups"
    renamed_dir = system_backups_dir / "b1-20260816T193000Z-renamedid01"
    result.backup_path.rename(renamed_dir)

    with pytest.raises(BackupNotFoundError):
        manager.verify_backup(result.backup_id)

    # verify_backup() against a backup that was never renamed still works.
    second = manager.create_backup(reason="second, untouched")
    verification = manager.verify_backup(second.backup_id)
    assert verification.verified is True


# -- zero Resolve dependency (static, AST-based) -----------------------------------


def _imported_module_names(file_path: Path) -> set[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_backup_subsystem_source_never_imports_resolve():
    repo_root = Path(__file__).resolve().parents[2]
    backup_src_dir = repo_root / "src" / "redline_core" / "backup"
    cli_file = repo_root / "src" / "cli" / "backup_commands.py"
    files = sorted(backup_src_dir.glob("*.py")) + [cli_file]
    assert len(files) >= 6, f"expected the full backup module set to exist, found: {files}"

    for file_path in files:
        imported = _imported_module_names(file_path)
        offending = {name for name in imported if "resolve" in name.lower()}
        assert not offending, f"{file_path} imports Resolve-related module(s): {offending}"
