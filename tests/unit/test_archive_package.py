"""Phase 15 Mission 15D -- Archive Rev1 package-builder tests, extended by
Mission 15E.2 to the complete-content-plan contract.

Scope: redline_core.archive.package only (staging, chunked copy, source
re-verification, destination verification, independent completeness
verification, Archive Manifest Rev1 sealing, PACKAGE_COMPLETE, atomic
publication). No DB, no CLI, no MCP, no Resolve, no production media --
every test operates on tmp_path fixtures used as a synthetic
`<archive-root>`; RLC-E9901 and the live redline.db are never referenced.

These workspace-only tests exercise ``package.py`` through
``content.build_content_plan(inventory, ())`` -- a plan with zero explicit
artifacts, matching Mission 15D's original single-root behavior exactly,
now under the canonical ``payload/workspace/`` layout. Complete-content
(workspace + external artifacts) coverage lives in
``test_archive_content_plan.py``.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redline_core.archive import integrity, package
from redline_core.archive.content import build_content_plan
from redline_core.archive.exceptions import (
    ArchiveCopyVerificationError,
    ArchiveDestinationCollisionError,
    ArchivePackageError,
    ArchivePackageVerificationError,
    ArchivePathError,
    ArchiveSourceChangedError,
)
from redline_core.archive.integrity import build_source_inventory

_FIXED_CLOCK = lambda: datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# -- helpers ------------------------------------------------------------------


def _make_tree(root: Path) -> None:
    (root / "exports").mkdir(parents=True)
    (root / "graphics").mkdir()
    (root / "footage" / "nested").mkdir(parents=True)
    (root / "exports" / "master.mov").write_bytes(b"master-content")
    (root / "footage" / "clip1.mov").write_bytes(b"clip-one")
    (root / "footage" / "nested" / "clip2.mov").write_bytes(b"clip-two")


def _build_plan_with_empty_dir(tmp_path: Path, name: str = "source"):
    source_root = tmp_path / name
    _make_tree(source_root)
    (source_root / "empty_dir").mkdir()
    inventory = build_source_inventory(source_root)
    plan = build_content_plan(inventory, ())
    return source_root, plan


def _assert_no_sealed_artifacts_in_staging(archive_root: Path) -> None:
    """Assert that no leftover staging directory under `archive_root`
    contains a manifest, sidecar, or PACKAGE_COMPLETE -- i.e. that a
    failure genuinely happened before sealing, not after."""
    staging_root = archive_root / ".staging"
    if not staging_root.exists():
        return
    for leftover in staging_root.iterdir():
        assert not (leftover / "PACKAGE_COMPLETE").exists()
        assert not (leftover / "archive_manifest.json").exists()
        assert not (leftover / "archive_manifest.sha256").exists()


class _MutatedFstat:
    """Fake fstat() result carrying a deliberately-wrong identity field,
    used to deterministically simulate an opened-handle identity mismatch
    without any real timing/threading. Mirrors
    test_archive_integrity.py's own helper of the same name/shape, since
    these tests exercise the identical Mission 15C fstat-fingerprint
    contract, now reused by the package-builder's copy-read path."""

    def __init__(self, real, *, size_delta: int = 0, mtime_ns_delta: int = 0):
        self.st_mode = real.st_mode
        self.st_size = real.st_size + size_delta
        self.st_mtime_ns = real.st_mtime_ns + mtime_ns_delta
        self.st_ino = getattr(real, "st_ino", 0)
        self.st_dev = getattr(real, "st_dev", 0)
        if hasattr(real, "st_file_attributes"):
            self.st_file_attributes = real.st_file_attributes


def _patch_fstat_for_target(monkeypatch, target: Path, *, mutate_on_call: int, **mutation_kwargs):
    """Patch os.fstat so the call-th fstat() against `target`'s own file
    descriptor (matched by inode/device against a real, pre-patch
    os.stat() of target, not a global call counter, so an unrelated
    os.fstat() elsewhere in the process can never be mistaken for one of
    ours) returns a mutated result. Patches `integrity.os.fstat` -- the
    same singleton `os` module object `redline_core.fsutil` (which now
    actually performs the fstat() call inside `open_stable_source()`)
    also references via its own `import os`, so patching the attribute
    here still intercepts it. This is what lets these tests prove the
    copy read itself is protected, not just hash_stable_file()."""
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


# -- successful build -----------------------------------------------------------


def test_build_archive_package_success(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    result = package.build_archive_package(
        plan, episode_id="EP0001", archive_id="ARC0001", archive_root=archive_root, clock=_FIXED_CLOCK
    )

    # source untouched
    assert source_root.is_dir()
    assert (source_root / "exports" / "master.mov").read_bytes() == b"master-content"
    assert (source_root / "footage" / "clip1.mov").read_bytes() == b"clip-one"
    assert (source_root / "footage" / "nested" / "clip2.mov").read_bytes() == b"clip-two"
    assert (source_root / "empty_dir").is_dir()

    # final package exists; staging no longer holds the published attempt
    expected_final = archive_root / "episodes" / "EP0001" / "ARC0001"
    assert result.final_path == expected_final
    assert expected_final.is_dir()
    staging_root = archive_root / ".staging"
    assert not any(staging_root.iterdir()) if staging_root.exists() else True

    # payload byte/hash identical, empty directory reproduced, under the
    # canonical payload/workspace/ layout (Mission 15E.2)
    workspace_payload = expected_final / "payload" / "workspace"
    assert (workspace_payload / "exports" / "master.mov").read_bytes() == b"master-content"
    assert (workspace_payload / "footage" / "clip1.mov").read_bytes() == b"clip-one"
    assert (workspace_payload / "footage" / "nested" / "clip2.mov").read_bytes() == b"clip-two"
    assert (workspace_payload / "empty_dir").is_dir()
    assert not (expected_final / "payload" / "external").exists()

    # manifest valid
    manifest_path = expected_final / "archive_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["schema_version"] == 1
    assert manifest["archive_id"] == "ARC0001"
    assert manifest["episode_id"] == "EP0001"
    assert manifest["created_at_utc"] == "2026-01-01T12:00:00Z"
    assert manifest["content"]["content_set_digest"] == plan.content_set_digest
    assert manifest["content"]["workspace_source_set_digest"] == plan.workspace_inventory.source_set_digest
    assert {a["archive_relative_path"] for a in manifest["artifacts"]} == {
        "workspace/exports/master.mov",
        "workspace/footage/clip1.mov",
        "workspace/footage/nested/clip2.mov",
    }
    assert all(a["classifications"] == ["workspace"] for a in manifest["artifacts"])
    assert all(a["source_kind"] == "workspace" for a in manifest["artifacts"])
    assert "workspace/empty_dir" in manifest["directories"]
    assert manifest["summary"]["file_count"] == 3
    assert manifest["summary"]["directory_count"] == plan.workspace_inventory.directory_count
    assert manifest["summary"]["total_bytes"] == plan.workspace_inventory.total_bytes
    assert manifest["verification"] == {"algorithm": "sha256", "completeness": "verified"}

    # manifest sidecar valid
    sidecar = (expected_final / "archive_manifest.sha256").read_text(encoding="utf-8").strip()
    assert sidecar == hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    # completion marker present
    assert (expected_final / "PACKAGE_COMPLETE").is_file()

    # result fields correct
    assert result.archive_id == "ARC0001"
    assert result.episode_id == "EP0001"
    assert result.manifest_path == manifest_path
    assert result.manifest_sha256 == sidecar
    assert result.content_set_digest == plan.content_set_digest
    assert result.workspace_source_set_digest == plan.workspace_inventory.source_set_digest
    assert result.file_count == 3
    assert result.directory_count == plan.workspace_inventory.directory_count
    assert result.total_bytes == plan.workspace_inventory.total_bytes


def test_empty_directory_preserved_in_package_and_manifest(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    result = package.build_archive_package(
        plan, episode_id="EP0002", archive_id="ARC0002", archive_root=archive_root, clock=_FIXED_CLOCK
    )

    assert (result.final_path / "payload" / "workspace" / "empty_dir").is_dir()
    manifest = json.loads((result.final_path / "archive_manifest.json").read_bytes())
    assert "workspace/empty_dir" in manifest["directories"]


# -- manifest determinism --------------------------------------------------------


def test_manifest_determinism_internal(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)

    manifest_a = package._build_manifest(
        plan=plan,
        archive_id="ARC0003",
        episode_id="EP0003",
        created_at_utc=package._format_utc(_FIXED_CLOCK()),
    )
    manifest_b = package._build_manifest(
        plan=plan,
        archive_id="ARC0003",
        episode_id="EP0003",
        created_at_utc=package._format_utc(_FIXED_CLOCK()),
    )

    assert package._canonical_json_bytes(manifest_a) == package._canonical_json_bytes(manifest_b)


def test_manifest_bytes_deterministic_across_two_full_builds(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)

    staged_a = package.build_staged_package(
        plan, episode_id="EP0004", archive_id="ARC0004", archive_root=tmp_path / "archive_root_a", clock=_FIXED_CLOCK
    )
    staged_b = package.build_staged_package(
        plan, episode_id="EP0004", archive_id="ARC0004", archive_root=tmp_path / "archive_root_b", clock=_FIXED_CLOCK
    )

    assert staged_a.manifest_path.read_bytes() == staged_b.manifest_path.read_bytes()
    assert staged_a.manifest_sha256 == staged_b.manifest_sha256


# -- destination collision -------------------------------------------------------


def test_destination_collision_before_build_fails_closed(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"
    final_path = archive_root / "episodes" / "EP0005" / "ARC0005"
    final_path.mkdir(parents=True)
    (final_path / "existing.txt").write_text("pre-existing")

    with pytest.raises(ArchiveDestinationCollisionError):
        package.build_archive_package(
            plan, episode_id="EP0005", archive_id="ARC0005", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    # existing destination untouched; nothing was even allocated
    assert (final_path / "existing.txt").read_text() == "pre-existing"
    assert not (archive_root / ".staging").exists()
    assert source_root.is_dir()
    assert (source_root / "footage" / "clip1.mov").read_bytes() == b"clip-one"


def test_atomic_publication_collision_race_fails_closed(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    staged = package.build_staged_package(
        plan, episode_id="EP0006", archive_id="ARC0006", archive_root=archive_root, clock=_FIXED_CLOCK
    )

    # simulate the final destination appearing after staging was sealed
    staged.final_path.parent.mkdir(parents=True, exist_ok=True)
    staged.final_path.mkdir()
    (staged.final_path / "sentinel.txt").write_text("do-not-touch")

    with pytest.raises(ArchiveDestinationCollisionError):
        package.publish_package(staged)

    assert (staged.final_path / "sentinel.txt").read_text() == "do-not-touch"
    assert staged.staging_path.is_dir()
    assert source_root.is_dir()
    assert (source_root / "footage" / "clip1.mov").read_bytes() == b"clip-one"


# -- source stability -------------------------------------------------------------


def test_source_changed_after_inventory_fails_closed(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    (source_root / "footage" / "clip1.mov").write_bytes(b"changed-after-inventory")
    archive_root = tmp_path / "archive_root"

    with pytest.raises(ArchiveSourceChangedError):
        package.build_archive_package(
            plan, episode_id="EP0007", archive_id="ARC0007", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    assert not (archive_root / "episodes").exists()
    assert source_root.is_dir()
    assert (source_root / "footage" / "clip1.mov").read_bytes() == b"changed-after-inventory"


def test_source_changes_during_copy_fails_closed(tmp_path, monkeypatch):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    target = (source_root / "footage" / "clip1.mov").resolve()
    archive_root = tmp_path / "archive_root"

    real_copy = package._copy_file_chunked

    def _copy_then_mutate_source(src: Path, dst: Path) -> None:
        real_copy(src, dst)
        if Path(src).resolve() == target:
            target.write_bytes(b"mutated-mid-copy-window")

    monkeypatch.setattr(package, "_copy_file_chunked", _copy_then_mutate_source)

    with pytest.raises(ArchiveSourceChangedError):
        package.build_archive_package(
            plan, episode_id="EP0008", archive_id="ARC0008", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    assert not (archive_root / "episodes").exists()
    assert source_root.is_dir()
    assert target.read_bytes() == b"mutated-mid-copy-window"
    assert (source_root / "exports" / "master.mov").read_bytes() == b"master-content"


# -- post-copy / pre-publication staging verification --------------------------------


def test_destination_corruption_detected_before_publish(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    staged = package.build_staged_package(
        plan, episode_id="EP0009", archive_id="ARC0009", archive_root=archive_root, clock=_FIXED_CLOCK
    )
    (staged.payload_root / "workspace" / "footage" / "clip1.mov").write_bytes(b"corrupted-destination-bytes")

    with pytest.raises(ArchivePackageVerificationError):
        package.publish_package(staged)

    assert not staged.final_path.exists()
    assert source_root.is_dir()
    assert (source_root / "footage" / "clip1.mov").read_bytes() == b"clip-one"


def test_missing_copied_artifact_detected_before_publish(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    staged = package.build_staged_package(
        plan, episode_id="EP0010", archive_id="ARC0010", archive_root=archive_root, clock=_FIXED_CLOCK
    )
    (staged.payload_root / "workspace" / "footage" / "clip1.mov").unlink()

    with pytest.raises(ArchivePackageVerificationError):
        package.publish_package(staged)

    assert not staged.final_path.exists()
    assert source_root.is_dir()
    assert (source_root / "footage" / "clip1.mov").read_bytes() == b"clip-one"


def test_unexpected_artifact_detected_before_publish(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    staged = package.build_staged_package(
        plan, episode_id="EP0011", archive_id="ARC0011", archive_root=archive_root, clock=_FIXED_CLOCK
    )
    (staged.payload_root / "workspace" / "footage" / "stray.mov").write_bytes(b"stray-file")

    with pytest.raises(ArchivePackageVerificationError):
        package.publish_package(staged)

    assert not staged.final_path.exists()
    assert source_root.is_dir()
    assert (source_root / "footage" / "clip1.mov").read_bytes() == b"clip-one"


def test_manifest_tampering_detected_before_publish(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    staged = package.build_staged_package(
        plan, episode_id="EP0012", archive_id="ARC0012", archive_root=archive_root, clock=_FIXED_CLOCK
    )
    tampered = staged.manifest_path.read_bytes() + b" "
    staged.manifest_path.write_bytes(tampered)

    with pytest.raises(ArchivePackageVerificationError):
        package.publish_package(staged)

    assert not staged.final_path.exists()
    assert source_root.is_dir()


# -- PACKAGE_COMPLETE ordering ------------------------------------------------------


def test_package_complete_marker_absent_before_sealed_state(tmp_path, monkeypatch):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    real_copy = package._copy_file_chunked
    state = {"copied": 0}

    def _corrupt_first_copy(src: Path, dst: Path) -> None:
        real_copy(src, dst)
        state["copied"] += 1
        if state["copied"] == 1:
            dst.write_bytes(b"corrupted-immediately-after-copy")

    monkeypatch.setattr(package, "_copy_file_chunked", _corrupt_first_copy)

    with pytest.raises(ArchiveCopyVerificationError):
        package.build_staged_package(
            plan, episode_id="EP0013", archive_id="ARC0013", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    staging_dirs = list((archive_root / ".staging").iterdir())
    assert len(staging_dirs) == 1
    leftover = staging_dirs[0]
    assert not (leftover / "PACKAGE_COMPLETE").exists()
    assert not (leftover / "archive_manifest.json").exists()
    assert not (leftover / "archive_manifest.sha256").exists()
    assert source_root.is_dir()
    assert (source_root / "footage" / "clip1.mov").read_bytes() == b"clip-one"


# -- identity validation ------------------------------------------------------------


def test_episode_id_with_path_separator_rejected(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    with pytest.raises(ArchivePackageError):
        package.build_archive_package(
            plan, episode_id="EP/0014", archive_id="ARC0014", archive_root=archive_root, clock=_FIXED_CLOCK
        )
    assert not (archive_root / "episodes").exists()


def test_archive_id_with_parent_reference_rejected(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    archive_root = tmp_path / "archive_root"

    with pytest.raises(ArchivePackageError):
        package.build_archive_package(
            plan, episode_id="EP0015", archive_id="..", archive_root=archive_root, clock=_FIXED_CLOCK
        )


# -- Correction 1: safe source descriptor used for the actual copy read ----------------


def test_copy_fails_closed_when_opened_source_handle_does_not_match_pre_open_identity(tmp_path, monkeypatch):
    """Simulates the object represented by the just-opened copy-read
    descriptor not matching the pathname identity observed before
    opening -- the package-builder-copy-path counterpart to Mission 15C's
    own hash_stable_file() test of the same name. Deterministic: patches
    integrity.os.fstat by call count against the target's real inode/dev,
    no thread timing."""
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    target = (source_root / "footage" / "clip1.mov").resolve()
    archive_root = tmp_path / "archive_root"

    _patch_fstat_for_target(monkeypatch, target, mutate_on_call=1, size_delta=1)

    with pytest.raises(ArchiveSourceChangedError):
        package.build_archive_package(
            plan, episode_id="EP0200", archive_id="ARC0200", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    assert not (archive_root / "episodes").exists()
    _assert_no_sealed_artifacts_in_staging(archive_root)
    assert source_root.is_dir()
    assert target.read_bytes() == b"clip-one"


def test_copy_fails_closed_when_opened_source_handle_changes_during_streaming(tmp_path, monkeypatch):
    """Simulates the already-open copy-read descriptor's own fstat()
    reporting a different identity between the pre-streaming and
    post-streaming observation -- the handle-level counterpart to the
    pathname-mismatch test above, mirroring Mission 15C's own
    hash_stable_file() streaming-mutation test."""
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    target = (source_root / "footage" / "clip1.mov").resolve()
    archive_root = tmp_path / "archive_root"

    _patch_fstat_for_target(monkeypatch, target, mutate_on_call=2, mtime_ns_delta=1)

    with pytest.raises(ArchiveSourceChangedError):
        package.build_archive_package(
            plan, episode_id="EP0201", archive_id="ARC0201", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    assert not (archive_root / "episodes").exists()
    _assert_no_sealed_artifacts_in_staging(archive_root)
    assert source_root.is_dir()
    assert target.read_bytes() == b"clip-one"


# -- Correction 2: complete source-set reconciliation before sealing -------------------


def test_new_source_file_added_after_inventory_fails_closed(tmp_path):
    """Per-file post-copy re-hashing alone cannot catch this: the new
    file has no entry in the original inventory to be re-verified
    against, and the payload-completeness check compares staging against
    that same original plan. Only the final whole-tree source-set-digest
    reconciliation, which rebuilds a fresh inventory from the source root
    itself, sees the addition."""
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    (source_root / "footage" / "new_clip.mov").write_bytes(b"new-content")
    archive_root = tmp_path / "archive_root"

    with pytest.raises(ArchiveSourceChangedError):
        package.build_archive_package(
            plan, episode_id="EP0202", archive_id="ARC0202", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    assert not (archive_root / "episodes").exists()
    _assert_no_sealed_artifacts_in_staging(archive_root)
    assert source_root.is_dir()
    # the test's own mutation is preserved -- the builder must not repair it
    assert (source_root / "footage" / "new_clip.mov").read_bytes() == b"new-content"


def test_new_empty_source_directory_added_after_inventory_fails_closed(tmp_path):
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    (source_root / "new_empty_dir").mkdir()
    archive_root = tmp_path / "archive_root"

    with pytest.raises(ArchiveSourceChangedError):
        package.build_archive_package(
            plan, episode_id="EP0203", archive_id="ARC0203", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    assert not (archive_root / "episodes").exists()
    _assert_no_sealed_artifacts_in_staging(archive_root)
    assert source_root.is_dir()
    assert (source_root / "new_empty_dir").is_dir()


def test_source_file_renamed_after_inventory_fails_closed(tmp_path):
    """A rename removes one inventory-known path and introduces an
    unknown one. The now-missing original path is what the copy loop
    hits first (ArchivePathError from open_stable_source's pre-open
    lstat) -- a valid, earlier fail-closed point than the final
    reconciliation step, and still proves the structural-removal/rename
    case fails closed without the builder attempting any repair."""
    source_root, plan = _build_plan_with_empty_dir(tmp_path)
    old_path = source_root / "footage" / "clip1.mov"
    new_path = source_root / "footage" / "clip1_renamed.mov"
    old_path.rename(new_path)
    archive_root = tmp_path / "archive_root"

    with pytest.raises(ArchivePathError):
        package.build_archive_package(
            plan, episode_id="EP0204", archive_id="ARC0204", archive_root=archive_root, clock=_FIXED_CLOCK
        )

    assert not (archive_root / "episodes").exists()
    _assert_no_sealed_artifacts_in_staging(archive_root)
    assert not old_path.exists()
    assert new_path.read_bytes() == b"clip-one"
