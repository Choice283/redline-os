"""Path policy for Persistent Asset Registry V1 declarations."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from redline_core.asset.exceptions import AssetFilesystemError, UnsafeAssetPathError
from redline_core.asset.models import (
    AssetAvailability,
    AssetDiagnosticCode,
    AssetPathObservation,
    AssetPathResolution,
    AssetVerificationState,
)


def validate_declared_asset_path(declared_path: str) -> PurePath:
    """Validate a root-relative asset declaration path."""
    if not isinstance(declared_path, str):
        raise UnsafeAssetPathError("Asset path declaration must be a string.")
    if declared_path.strip() != declared_path:
        raise UnsafeAssetPathError("Asset path declaration must not contain leading or trailing whitespace.")
    if not declared_path:
        raise UnsafeAssetPathError("Asset path declaration must not be empty.")
    if declared_path.startswith(("\\\\", "//")):
        raise UnsafeAssetPathError("Asset path declaration must be relative to the approved assets root.")

    windows_path = PureWindowsPath(declared_path)
    posix_path = PurePosixPath(declared_path)
    if windows_path.drive or windows_path.is_absolute() or posix_path.is_absolute():
        raise UnsafeAssetPathError("Asset path declaration must be relative to the approved assets root.")

    normalized = declared_path.replace("\\", "/")
    parts = tuple(part for part in normalized.split("/") if part)
    if not parts:
        raise UnsafeAssetPathError("Asset path declaration must include at least one path component.")
    if len(parts) != len(normalized.split("/")):
        raise UnsafeAssetPathError("Asset path declaration must not contain empty path components.")
    if any(part in {".", ".."} for part in parts):
        raise UnsafeAssetPathError("Asset path declaration must not traverse outside the approved assets root.")

    return PurePosixPath(*parts)


def normalize_path_key(path: Path) -> str:
    """Return the normalized key used for path equality checks."""
    return os.path.normcase(os.path.normpath(str(Path(path).resolve(strict=False))))


def resolve_asset_path(
    declared_path: str,
    approved_root: Path,
    *,
    approved_root_id: str = "assets_path",
) -> AssetPathResolution:
    """Resolve a declaration beneath the active approved assets root."""
    try:
        root = _resolve_canonical_root(Path(approved_root))
    except OSError as exc:
        raise AssetFilesystemError(
            "Approved assets root could not be resolved.",
            context={"approved_root_id": approved_root_id},
        ) from exc

    candidate = _candidate_for_declared_path(declared_path, root)

    try:
        resolved = _resolve_candidate_safely(candidate)
    except OSError as exc:
        raise AssetFilesystemError(
            "Asset path could not be resolved.",
            context={"approved_root_id": approved_root_id},
        ) from exc

    if not _is_relative_to(resolved, root):
        raise UnsafeAssetPathError(
            "Asset path must remain beneath the active approved assets root.",
            context={"approved_root_id": approved_root_id},
        )

    return AssetPathResolution(
        declared_path=declared_path,
        approved_root=root,
        resolved_path=resolved,
        normalized_path_key=normalize_path_key(resolved),
        approved_root_id=approved_root_id,
    )


def observe_asset_path(resolution: AssetPathResolution) -> AssetPathObservation:
    """Observe normal filesystem availability for a resolved asset path."""
    try:
        root = _resolve_canonical_root(resolution.approved_root)
        candidate = _candidate_for_declared_path(resolution.declared_path, root)
        current_path = _resolve_candidate_safely(candidate)
        if not _is_relative_to(current_path, root):
            raise UnsafeAssetPathError(
                "Asset path must remain beneath the active approved assets root.",
                context={"approved_root_id": resolution.approved_root_id},
            )
        normalized_key = normalize_path_key(current_path)

        # Filesystem state can still change after this point; later verification
        # must repeat the same containment checks before trusting the path.
        if not current_path.exists():
            return AssetPathObservation(
                availability=AssetAvailability.MISSING,
                verification=AssetVerificationState.VERIFIED,
                resolved_path=current_path,
                normalized_path_key=normalized_key,
                file_size_bytes=None,
                file_modified_at=None,
                diagnostic_code=AssetDiagnosticCode.FILE_MISSING,
                diagnostic_message="Asset file is missing.",
            )
        if not current_path.is_file():
            return AssetPathObservation(
                availability=AssetAvailability.NON_FILE,
                verification=AssetVerificationState.VERIFIED,
                resolved_path=current_path,
                normalized_path_key=normalized_key,
                file_size_bytes=None,
                file_modified_at=None,
                diagnostic_code=AssetDiagnosticCode.PATH_IS_NOT_FILE,
                diagnostic_message="Asset path exists but is not a regular file.",
            )

        stat_result = current_path.stat()
        return AssetPathObservation(
            availability=AssetAvailability.AVAILABLE,
            verification=AssetVerificationState.VERIFIED,
            resolved_path=current_path,
            normalized_path_key=normalized_key,
            file_size_bytes=stat_result.st_size,
            file_modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
            diagnostic_code=AssetDiagnosticCode.FILE_AVAILABLE,
            diagnostic_message=None,
        )
    except OSError as exc:
        raise AssetFilesystemError(
            "Asset path observation failed.",
            context={"approved_root_id": resolution.approved_root_id},
        ) from exc


def _resolve_canonical_root(approved_root: Path) -> Path:
    root = approved_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise UnsafeAssetPathError("Approved assets root must be a directory.")
    return root


def _candidate_for_declared_path(declared_path: str, canonical_root: Path) -> Path:
    relative_path = validate_declared_asset_path(declared_path)
    return canonical_root.joinpath(*relative_path.parts)


def _resolve_candidate_safely(candidate: Path) -> Path:
    if os.path.lexists(candidate) and candidate.is_symlink() and not candidate.exists():
        raise UnsafeAssetPathError("Asset path declaration resolves through a broken symbolic link.")
    if candidate.exists():
        return candidate.resolve(strict=True)

    missing_parts: list[str] = []
    probe = candidate
    while not probe.exists():
        if os.path.lexists(probe) and probe.is_symlink():
            raise UnsafeAssetPathError("Asset path declaration resolves through a broken symbolic link.")
        missing_parts.append(probe.name)
        parent = probe.parent
        if parent == probe:
            raise UnsafeAssetPathError("Asset path declaration has no existing approved root ancestor.")
        probe = parent

    resolved_parent = probe.resolve(strict=True)
    return resolved_parent.joinpath(*reversed(missing_parts))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
