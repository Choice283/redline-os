"""Phase 15 Mission 15G.1 -- tests for redline_core.archive.evidence:
the episode-scoped evidence authority resolver.

Scope: redline_core.archive.evidence only. No DB, no CLI, no MCP, no
Resolve, no production filesystem, no RLC-E9901.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from redline_core.archive.evidence import EpisodeEvidencePlan, resolve_episode_evidence
from redline_core.archive.exceptions import (
    ArchiveEvidenceIdentityConflictError,
    ArchiveInventoryError,
    ArchivePathError,
    ArchiveUnsafeFilesystemObjectError,
)


def _create_symlink(link_path: Path, target: Path, *, target_is_directory: bool) -> bool:
    try:
        link_path.symlink_to(target, target_is_directory=target_is_directory)
        return True
    except (OSError, NotImplementedError):
        return False


def _create_junction(link_path: Path, target: Path) -> bool:
    if os.name != "nt":
        return False
    import subprocess

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
        capture_output=True,
    )
    return result.returncode == 0 and link_path.exists()


# -- ownership / containment -------------------------------------------------------


def test_zero_evidence_when_episode_directory_absent(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    assert plan == EpisodeEvidencePlan(supplements=(), directories=())


def test_evidence_root_missing_fails_closed(tmp_path):
    with pytest.raises(ArchivePathError):
        resolve_episode_evidence(evidence_root=tmp_path / "does_not_exist", episode_id="RLC-E001")


def test_episode_directory_maps_ownership(tmp_path):
    root = tmp_path / "evidence"
    (root / "RLC-E001").mkdir(parents=True)
    (root / "RLC-E001" / "start.json").write_bytes(b'{"ok": true}')

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    assert len(plan.supplements) == 1
    assert plan.supplements[0].archive_relative_path == "external/evidence/start.json"


def test_other_episode_evidence_excluded(tmp_path):
    root = tmp_path / "evidence"
    (root / "RLC-E001").mkdir(parents=True)
    (root / "RLC-E001" / "a.json").write_bytes(b"{}")
    (root / "RLC-E002").mkdir(parents=True)
    (root / "RLC-E002" / "b.json").write_bytes(b"{}")

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    paths = {s.archive_relative_path for s in plan.supplements}
    assert paths == {"external/evidence/a.json"}


def test_filename_matching_episode_outside_episode_directory_excluded(tmp_path):
    """The directory boundary is the authority -- a filename containing
    the target episode ID, sitting outside <evidence_root>/<episode_id>/,
    is never evidence for that episode."""
    root = tmp_path / "evidence"
    (root / "RLC-E001").mkdir(parents=True)
    (root / "misc").mkdir(parents=True)
    (root / "misc" / "RLC-E001_result.json").write_bytes(b"{}")

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    assert plan.supplements == ()


def test_nested_paths_preserved(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    (ep / "render" / "queue").mkdir(parents=True)
    (ep / "render" / "completion").mkdir(parents=True)
    (ep / "render" / "queue" / "attempt.json").write_bytes(b"{}")
    (ep / "render" / "completion" / "result.json").write_bytes(b"{}")

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    paths = {s.archive_relative_path for s in plan.supplements}
    assert paths == {
        "external/evidence/render/queue/attempt.json",
        "external/evidence/render/completion/result.json",
    }
    assert "external/evidence/render" in plan.directories


def test_same_basename_in_separate_directories_preserved(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    (ep / "a").mkdir(parents=True)
    (ep / "b").mkdir(parents=True)
    (ep / "a" / "result.json").write_bytes(b"1")
    (ep / "b" / "result.json").write_bytes(b"2")

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    paths = {s.archive_relative_path for s in plan.supplements}
    assert paths == {"external/evidence/a/result.json", "external/evidence/b/result.json"}


def test_empty_evidence_subdirectory_preserved_as_directory(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    (ep / "empty").mkdir(parents=True)

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    assert plan.supplements == ()
    assert plan.directories == ("external/evidence/empty",)


def test_supplement_fields_use_stable_hashing(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    ep.mkdir(parents=True)
    content = b"queue-attempt-evidence-bytes"
    (ep / "attempt.json").write_bytes(content)

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    import hashlib

    supplement = plan.supplements[0]
    assert supplement.sha256 == hashlib.sha256(content).hexdigest()
    assert supplement.size_bytes == len(content)
    assert supplement.classifications == ("production_evidence",)
    assert supplement.source_kind == "production_evidence"
    assert supplement.absolute_source_path == (ep / "attempt.json").resolve()


# -- unsafe conditions ---------------------------------------------------------------


def test_episode_path_is_file_fails_closed(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "RLC-E001").write_bytes(b"not a directory")

    with pytest.raises(ArchivePathError):
        resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")


def test_episode_path_is_symlink_fails_closed(tmp_path):
    root = tmp_path / "evidence"
    real_dir = tmp_path / "outside" / "real"
    real_dir.mkdir(parents=True)
    root.mkdir()
    link_path = root / "RLC-E001"
    if not _create_symlink(link_path, real_dir, target_is_directory=True):
        pytest.skip("this environment cannot create symlinks (no admin/Developer Mode)")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")


def test_episode_path_is_junction_fails_closed(tmp_path):
    root = tmp_path / "evidence"
    real_dir = tmp_path / "outside" / "real"
    real_dir.mkdir(parents=True)
    root.mkdir()
    link_path = root / "RLC-E001"
    if not _create_junction(link_path, real_dir):
        pytest.skip("this environment cannot create junctions")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")


def test_nested_symlink_inside_episode_directory_fails_closed(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    ep.mkdir(parents=True)
    real_file = tmp_path / "outside_file.json"
    real_file.write_bytes(b"{}")
    link_path = ep / "linked.json"
    if not _create_symlink(link_path, real_file, target_is_directory=False):
        pytest.skip("this environment cannot create symlinks (no admin/Developer Mode)")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")


def test_case_colliding_evidence_paths_fail_closed(tmp_path, monkeypatch):
    """A real Windows filesystem cannot itself hold two case-only-
    distinct entries in one directory (NTFS is case-preserving but
    case-insensitive for lookups), so this collision cannot be
    constructed via real files -- matching the same limitation
    test_archive_integrity.py's own case-collision tests document and
    work around by exercising the detection primitive directly. What
    *is* directly provable here: resolve_episode_evidence() does not
    swallow or downgrade an ArchiveInventoryError raised by the
    Mission 15C walk it delegates to -- it propagates unchanged."""
    from redline_core.archive import evidence as evidence_module

    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    ep.mkdir(parents=True)
    (ep / "result.json").write_bytes(b"1")

    def _raise_collision(_root):
        raise ArchiveInventoryError("normalized relative-path identity collision (synthetic)")

    monkeypatch.setattr(evidence_module.integrity, "build_source_inventory", _raise_collision)

    with pytest.raises(ArchiveInventoryError):
        resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")


@pytest.mark.parametrize("bad_episode_id", ["", "..", ".", "a/b", "a\\b"])
def test_unsafe_episode_id_rejected(tmp_path, bad_episode_id):
    root = tmp_path / "evidence"
    root.mkdir()

    with pytest.raises(ArchivePathError):
        resolve_episode_evidence(evidence_root=root, episode_id=bad_episode_id)


def test_evidence_root_that_is_a_file_fails_closed(tmp_path):
    root = tmp_path / "evidence_file"
    root.write_bytes(b"not a directory")

    with pytest.raises(ArchivePathError):
        resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")


def test_evidence_root_that_is_a_symlink_fails_closed(tmp_path):
    real_dir = tmp_path / "outside" / "real_root"
    real_dir.mkdir(parents=True)
    link_path = tmp_path / "evidence_link"
    if not _create_symlink(link_path, real_dir, target_is_directory=True):
        pytest.skip("this environment cannot create symlinks (no admin/Developer Mode)")

    with pytest.raises(ArchiveUnsafeFilesystemObjectError):
        resolve_episode_evidence(evidence_root=link_path, episode_id="RLC-E001")


# -- structured JSON identity validation ----------------------------------------------


def test_json_evidence_with_matching_episode_id_accepted(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    ep.mkdir(parents=True)
    (ep / "start.json").write_bytes(json.dumps({"episode_id": "RLC-E001", "event": "start"}).encode())

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    assert len(plan.supplements) == 1


def test_json_evidence_with_conflicting_episode_id_rejected(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    ep.mkdir(parents=True)
    (ep / "start.json").write_bytes(json.dumps({"episode_id": "RLC-E999"}).encode())

    with pytest.raises(ArchiveEvidenceIdentityConflictError):
        resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")


def test_opaque_json_without_episode_id_field_accepted(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    ep.mkdir(parents=True)
    (ep / "opaque.json").write_bytes(json.dumps({"queue_state": "observed"}).encode())

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    assert len(plan.supplements) == 1


def test_malformed_json_evidence_accepted_as_opaque(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    ep.mkdir(parents=True)
    (ep / "broken.json").write_bytes(b"{not valid json")

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    assert len(plan.supplements) == 1
    assert plan.supplements[0].archive_relative_path == "external/evidence/broken.json"


def test_non_json_evidence_never_parsed(tmp_path):
    root = tmp_path / "evidence"
    ep = root / "RLC-E001"
    ep.mkdir(parents=True)
    (ep / "clip.mov").write_bytes(b"binary-not-json-content")

    plan = resolve_episode_evidence(evidence_root=root, episode_id="RLC-E001")

    assert len(plan.supplements) == 1
