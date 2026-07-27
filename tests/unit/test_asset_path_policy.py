"""Tests for Persistent Asset Registry V1 path policy."""
from __future__ import annotations

import os

import pytest

from redline_core.asset.exceptions import UnsafeAssetPathError
from redline_core.asset.models import AssetAvailability, AssetDiagnosticCode, AssetVerificationState
from redline_core.asset import path_policy as asset_path_policy
from redline_core.asset.path_policy import (
    normalize_path_key,
    observe_asset_path,
    resolve_asset_path,
    validate_declared_asset_path,
)


@pytest.mark.parametrize(
    "declared_path",
    [
        "",
        " ",
        " logos/lower_third.png",
        "logos/lower_third.png ",
        "/logos/lower_third.png",
        "C:/assets/logos/lower_third.png",
        "C:logos/lower_third.png",
        "\\\\server\\share\\clip.mov",
        "//server/share/clip.mov",
        "../outside.mov",
        "logos/../outside.mov",
        "logos//lower_third.png",
        ".",
        "logos/./lower_third.png",
    ],
)
def test_validate_declared_asset_path_rejects_unsafe_declarations(declared_path):
    with pytest.raises(UnsafeAssetPathError):
        validate_declared_asset_path(declared_path)


def test_validate_declared_asset_path_accepts_root_relative_components():
    path = validate_declared_asset_path("logos\\lower_third.png")

    assert path.parts == ("logos", "lower_third.png")


def test_resolve_asset_path_accepts_missing_target_under_root(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()

    resolution = resolve_asset_path("logos/missing.png", root)

    assert resolution.resolved_path == root.resolve() / "logos" / "missing.png"
    assert resolution.normalized_path_key == normalize_path_key(resolution.resolved_path)


def test_observe_asset_path_reports_missing_as_verified(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    resolution = resolve_asset_path("logos/missing.png", root)

    observation = observe_asset_path(resolution)

    assert observation.availability is AssetAvailability.MISSING
    assert observation.verification is AssetVerificationState.VERIFIED
    assert observation.diagnostic_code is AssetDiagnosticCode.FILE_MISSING
    assert observation.file_size_bytes is None
    assert observation.file_modified_at is None


def test_observe_asset_path_reports_file_as_available(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    asset = root / "logos" / "lower_third.png"
    asset.parent.mkdir()
    asset.write_bytes(b"asset")
    resolution = resolve_asset_path("logos/lower_third.png", root)

    observation = observe_asset_path(resolution)

    assert observation.availability is AssetAvailability.AVAILABLE
    assert observation.verification is AssetVerificationState.VERIFIED
    assert observation.diagnostic_code is AssetDiagnosticCode.FILE_AVAILABLE
    assert observation.file_size_bytes == 5
    assert observation.file_modified_at is not None


def test_observe_asset_path_reports_directory_as_non_file(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    directory = root / "logos"
    directory.mkdir()
    resolution = resolve_asset_path("logos", root)

    observation = observe_asset_path(resolution)

    assert observation.availability is AssetAvailability.NON_FILE
    assert observation.verification is AssetVerificationState.VERIFIED
    assert observation.diagnostic_code is AssetDiagnosticCode.PATH_IS_NOT_FILE


def test_observe_asset_path_reports_file_introduced_after_missing_resolution(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    resolution = resolve_asset_path("logos/lower_third.png", root)
    asset = root / "logos" / "lower_third.png"
    asset.parent.mkdir()
    asset.write_bytes(b"asset")

    observation = observe_asset_path(resolution)

    assert observation.availability is AssetAvailability.AVAILABLE
    assert observation.normalized_path_key == normalize_path_key(asset.resolve())


def test_observe_asset_path_reports_directory_introduced_after_missing_resolution(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    resolution = resolve_asset_path("logos/lower_third.png", root)
    (root / "logos" / "lower_third.png").mkdir(parents=True)

    observation = observe_asset_path(resolution)

    assert observation.availability is AssetAvailability.NON_FILE
    assert observation.diagnostic_code is AssetDiagnosticCode.PATH_IS_NOT_FILE


def test_observe_asset_path_reports_target_removed_after_initial_resolution(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    asset = root / "logos" / "lower_third.png"
    asset.parent.mkdir()
    asset.write_bytes(b"asset")
    resolution = resolve_asset_path("logos/lower_third.png", root)
    asset.unlink()

    observation = observe_asset_path(resolution)

    assert observation.availability is AssetAvailability.MISSING
    assert observation.diagnostic_code is AssetDiagnosticCode.FILE_MISSING


def test_observe_asset_path_rechecks_containment_without_symlink_privileges(tmp_path, monkeypatch):
    root = tmp_path / "assets"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    outside_file = outside / "clip.mov"
    outside_file.write_bytes(b"x")
    resolution = resolve_asset_path("logos/missing.mov", root)

    def fake_resolve_candidate_safely(candidate):
        return outside_file.resolve()

    monkeypatch.setattr(asset_path_policy, "_resolve_candidate_safely", fake_resolve_candidate_safely)

    with pytest.raises(UnsafeAssetPathError):
        observe_asset_path(resolution)


def test_observe_asset_path_refreshes_normalized_key_from_current_target(tmp_path, monkeypatch):
    root = tmp_path / "assets"
    root.mkdir()
    current_target = root / "canonical" / "clip.mov"
    current_target.parent.mkdir()
    current_target.write_bytes(b"x")
    resolution = resolve_asset_path("logos/missing.mov", root)

    def fake_resolve_candidate_safely(candidate):
        return current_target.resolve()

    monkeypatch.setattr(asset_path_policy, "_resolve_candidate_safely", fake_resolve_candidate_safely)

    observation = observe_asset_path(resolution)

    assert observation.availability is AssetAvailability.AVAILABLE
    assert observation.normalized_path_key == normalize_path_key(current_target.resolve())
    assert observation.normalized_path_key != resolution.normalized_path_key


def test_resolve_asset_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "assets"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "clip.mov").write_bytes(b"x")
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(UnsafeAssetPathError):
        resolve_asset_path("linked/clip.mov", root)


def test_resolve_asset_path_accepts_symlink_contained_under_root(tmp_path):
    root = tmp_path / "assets"
    target = root / "targets"
    root.mkdir()
    target.mkdir()
    (target / "clip.mov").write_bytes(b"x")
    link = root / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    resolution = resolve_asset_path("linked/clip.mov", root)

    assert resolution.resolved_path == (target / "clip.mov").resolve()


def test_resolve_asset_path_rejects_broken_symlink(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    link = root / "missing-link"
    try:
        link.symlink_to(root / "missing-target")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(UnsafeAssetPathError):
        resolve_asset_path("missing-link", root)


def test_observe_asset_path_rejects_symlink_escape_introduced_after_resolution(tmp_path):
    root = tmp_path / "assets"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "clip.mov").write_bytes(b"x")
    resolution = resolve_asset_path("linked/clip.mov", root)
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(UnsafeAssetPathError):
        observe_asset_path(resolution)


def test_observe_asset_path_accepts_inside_symlink_introduced_after_resolution(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    target = root / "targets"
    target.mkdir()
    (target / "clip.mov").write_bytes(b"x")
    resolution = resolve_asset_path("linked/clip.mov", root)
    link = root / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    observation = observe_asset_path(resolution)

    assert observation.availability is AssetAvailability.AVAILABLE
    assert observation.resolved_path == (target / "clip.mov").resolve()
    assert observation.normalized_path_key == normalize_path_key(target / "clip.mov")


def test_observe_asset_path_rejects_broken_symlink_introduced_after_resolution(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    resolution = resolve_asset_path("missing-link", root)
    link = root / "missing-link"
    try:
        link.symlink_to(root / "missing-target")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(UnsafeAssetPathError):
        observe_asset_path(resolution)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior is Windows-only")
def test_observe_asset_path_rejects_junction_escape_guarded():
    pytest.skip("junction creation is environment-dependent; canonical observation recheck is covered directly")


def test_unc_declaration_is_invalid_without_implying_unc_roots_are_invalid():
    with pytest.raises(UnsafeAssetPathError, match="relative to the approved assets root"):
        validate_declared_asset_path("\\\\unapproved-server\\share\\clip.mov")
