"""Archive CLI commands — the third resource group, same shape as
episode_commands.py and asset_commands.py: `_run_*`/`_print_*` handler
pairs with no argparse/stdout dependency, subparser registration, and a
dispatch entrypoint.

Archive commands are routed through `PersistenceServices`
(redline_core.runtime.composition.build_persistence_services()), not the
full `ApplicationServices` episode commands use, nor the config-only
`CoreServices` asset commands use — `create_archive()`/`verify_archive()`/
`list_archives()` need a connected Database but never touch Resolve. See
composition.py for the rationale.

Mission 7 added `archive list` (read-only). Mission 8 added a mutating
`archive episode <episode_id>` as a thin wrapper over the then-only
`ArchiveManager.archive_episode()`. Phase 15 Mission 15E replaced that
method's internals with the non-destructive Rev1 orchestration path
(`create_archive()`), keeping `archive_episode()` only as a temporary
compatibility bridge. Phase 15 Mission 15F is the migration this module
was always waiting for: `archive create`/`archive verify` now call
`ArchiveManager.create_archive()`/`verify_archive()` directly, and the
legacy `archive episode` command is retired from this parser entirely —
`ArchiveManager.archive_episode()` no longer exists at all (see
docs/CHANGELOG.md's Mission 15F entry for the full call-site inventory).
There is exactly one canonical way to archive an episode from the CLI now,
not two equivalent ones left active side by side.
"""
from __future__ import annotations

import argparse

from redline_core.archive.exceptions import ArchiveError, ArchiveVerifiedUnregisteredError, EpisodeAlreadyArchivedError
from redline_core.archive.manager import ArchiveResult, ArchiveVerificationResult
from redline_core.db.models import ArchiveRecord
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.runtime.composition import PersistenceServices

_BANNER = "=" * 49


def _archive_to_dict(record: ArchiveRecord) -> dict:
    """Used only by `archive list` (`ArchiveManager.list_archives()`
    still returns raw `ArchiveRecord` rows, legacy and Rev1 alike).
    `archive_id`/`archive_state` are included so a legacy row (no Rev1
    identity at all) and a Rev1 `complete` row are distinguishable in the
    listing — Mission 15F extension, additive to the original three
    fields (episode_id/archive_path/archived_at) every existing caller
    already depends on."""
    return {
        "episode_id": record.episode_id,
        "archive_path": record.archive_path,
        "archived_at": record.archived_at,
        "archive_id": record.archive_id,
        "archive_state": record.archive_state.value,
    }


def _archive_result_to_dict(result: ArchiveResult) -> dict:
    """Serialize a successful `create_archive()` result. Sourced from a
    Mission 15E `ArchiveResult`, not a raw `ArchiveRecord` — `archived_at`
    is `result.verified_at`, the same UTC instant recorded as the
    committed archive's `verified_at` in the database."""
    return {
        "episode_id": result.episode_id,
        "archive_id": result.archive_id,
        "archive_path": str(result.archive_path),
        "render_job_id": result.render_job_id,
        "manifest_sha256": result.manifest_sha256,
        "archived_at": result.verified_at,
        "status": "complete",
    }


def _verification_result_to_dict(result: ArchiveVerificationResult) -> dict:
    """Serialize a successful `verify_archive()` result for both CLI and
    (via the same shape) MCP output."""
    return {
        "episode_id": result.episode_id,
        "archive_id": result.archive_id,
        "archive_path": str(result.archive_path),
        "manifest_sha256": result.manifest_sha256,
        "verified": result.verified,
        "file_count": result.file_count,
        "directory_count": result.directory_count,
        "total_bytes": result.total_bytes,
    }


def _run_archive_list(services: PersistenceServices) -> dict:
    """List every archived episode. Read-only, no arguments: a thin
    wrapper over the existing, already-tested ArchiveManager.list_archives(),
    which has no filtering or pagination of its own. Order is whatever the
    manager/DB returns (ORDER BY archived_at, per database.py); this
    command doesn't re-sort it. Database enumeration only — never performs
    package verification (that's `archive verify`, a separate, explicit,
    per-episode operation).
    """
    archives = services.archive_manager.list_archives()
    return {"success": True, "archives": [_archive_to_dict(a) for a in archives]}


def _print_archive_list_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Archives".center(49))
    print(_BANNER)
    print()

    archives = result["archives"]
    if not archives:
        print("No archives found.")
        return

    print(f"{'EPISODE ID':<14}{'STATE':<10}{'ARCHIVE PATH':<40}{'ARCHIVED AT'}")
    for archive in archives:
        print(f"{archive['episode_id']:<14}{archive['archive_state']:<10}{archive['archive_path']:<40}{archive['archived_at']}")
    print()
    print(f"{len(archives)} archive(s).")


def _run_archive_create(
    services: PersistenceServices,
    episode_id: str,
    *,
    render_job_id: int | None = None,
    manifest_path: str | None = None,
) -> dict:
    """Build, verify, and commit a Rev1 archive for `episode_id` — the
    canonical create transport (Phase 15 Mission 15F), calling
    `ArchiveManager.create_archive()` directly (never the retired
    `archive_episode()` bridge). `render_job_id`/`manifest_path` are
    passed through unchanged: this command does not reimplement render
    selection or provenance-fallback policy, both of which remain
    `ArchiveManager`'s alone.

    `ArchiveVerifiedUnregisteredError` is classified distinctly from every
    other failure: it means a fully verified package was published to
    disk but database registration failed afterward. Collapsing that into
    a generic "archive failed, nothing happened" message would hide from
    the operator that a real, verified package now exists at
    `archive_path` even though the episode never transitioned to
    `archived`. Mission 15F does not attempt recovery of that state — see
    the exception's own docstring; that remains Mission 15H's concern.
    """
    try:
        result = services.archive_manager.create_archive(
            episode_id, render_job_id=render_job_id, manifest_path=manifest_path
        )
        return {"success": True, "archive": _archive_result_to_dict(result)}
    except ArchiveVerifiedUnregisteredError as exc:
        return {
            "success": False,
            "classification": "verified_unregistered",
            "error": str(exc),
            "episode_id": exc.episode_id,
            "archive_id": exc.archive_id,
            "archive_path": exc.archive_path,
            "manifest_path": exc.manifest_path,
            "manifest_sha256": exc.manifest_sha256,
        }
    except (EpisodeNotFoundError, EpisodeAlreadyArchivedError, ArchiveError) as exc:
        return {"success": False, "classification": "error", "error": str(exc)}


def _print_archive_create_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Archive Create".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        if result.get("classification") == "verified_unregistered":
            print("Archive package verified and published, but database registration FAILED.")
            print()
            print(f"Episode:          {result['episode_id']}")
            print(f"Archive ID:       {result['archive_id']}")
            print(f"Archive path:     {result['archive_path']}")
            print(f"Manifest SHA-256: {result['manifest_sha256']}")
            print()
            print(f"Details: {result['error']}")
            print()
            print("The verified package was NOT deleted, moved, or overwritten. Registration")
            print("recovery is a later-mission concern, not performed by this command.")
        else:
            print(f"Archive create failed: {result['error']}")
        return

    archive = result["archive"]
    print(f"Episode ID:       {archive['episode_id']}")
    print(f"Archive ID:       {archive['archive_id']}")
    print(f"Archive path:     {archive['archive_path']}")
    print(f"Render job ID:    {archive['render_job_id']}")
    print(f"Manifest SHA-256: {archive['manifest_sha256']}")
    print(f"Status:           {archive['status']}")


def _run_archive_verify(services: PersistenceServices, episode_id: str) -> dict:
    """Verify a committed Rev1 archive is still intact — the canonical
    verify transport (Phase 15 Mission 15F), calling
    `ArchiveManager.verify_archive()` directly. Read-only: never mutates
    the episode, the `archives` row, the source workspace, or the archive
    package."""
    try:
        result = services.archive_manager.verify_archive(episode_id)
        return {"success": True, "verification": _verification_result_to_dict(result)}
    except ArchiveError as exc:
        return {"success": False, "error": str(exc)}


def _print_archive_verify_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Archive Verify".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Archive verify failed: {result['error']}")
        return

    verification = result["verification"]
    print(f"Episode ID:       {verification['episode_id']}")
    print(f"Archive ID:       {verification['archive_id']}")
    print(f"Archive path:     {verification['archive_path']}")
    print(f"Verified:         {'yes' if verification['verified'] else 'no'}")
    print(f"Manifest SHA-256: {verification['manifest_sha256']}")
    print(f"File count:       {verification['file_count']}")
    print(f"Directory count:  {verification['directory_count']}")
    print(f"Total bytes:      {verification['total_bytes']}")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Attach the `archive` resource and its actions to the top-level
    subparsers. Canonical actions only, as of Phase 15 Mission 15F:
    `list`/`create`/`verify`. The legacy `episode` action is not
    registered — running `redline archive episode ...` now produces
    argparse's own standard "invalid choice" error, the same clean,
    unambiguous failure mode as any other never-existed subcommand."""
    archive_parser = subparsers.add_parser("archive", help="Archive commands.")
    archive_subparsers = archive_parser.add_subparsers(dest="action", required=True)

    archive_subparsers.add_parser("list", help="List every archived episode (read-only).")

    create_parser = archive_subparsers.add_parser(
        "create", help="Build, verify, and commit a Rev1 archive package for a rendered episode."
    )
    create_parser.add_argument("episode_id", help="Episode ID to archive, e.g. RLC-E025.")
    create_parser.add_argument(
        "--render-job-id",
        type=int,
        default=None,
        help="Explicit render job ID to archive. Required only when the episode has more than one "
        "completed render job (ArchiveManager never guesses); omit to auto-select the episode's single "
        "completed render job.",
    )
    create_parser.add_argument(
        "--manifest",
        dest="manifest_path",
        default=None,
        help="Legacy fallback only: explicit path to the episode's original manifest, for an episode "
        "built before canonical manifest provenance existed. Not required for normally-built episodes "
        "-- ArchiveManager uses canonical provenance automatically when it is present.",
    )

    verify_parser = archive_subparsers.add_parser(
        "verify", help="Verify a committed Rev1 archive package is still intact (read-only)."
    )
    verify_parser.add_argument("episode_id", help="Episode ID to verify, e.g. RLC-E025.")


def run(args: argparse.Namespace, services: PersistenceServices) -> int | None:
    """Dispatch a parsed `archive ...` command. Returns an exit code, or
    None if args.action isn't one this module handles."""
    if args.action == "list":
        result = _run_archive_list(services)
        _print_archive_list_result(result)
        return 0 if result["success"] else 1

    if args.action == "create":
        result = _run_archive_create(
            services, args.episode_id, render_job_id=args.render_job_id, manifest_path=args.manifest_path
        )
        _print_archive_create_result(result)
        return 0 if result["success"] else 1

    if args.action == "verify":
        result = _run_archive_verify(services, args.episode_id)
        _print_archive_verify_result(result)
        return 0 if result["success"] else 1

    return None
