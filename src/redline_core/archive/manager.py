"""Archive Manager — Phase 15 Rev1 orchestration (Mission 15E), extended
by Mission 15E.2 to the complete-content-plan contract.

Orchestrates the already-published Phase 15 layers into a non-destructive
archive path: Mission 15C's filesystem integrity engine
(`redline_core.archive.integrity`), Mission 15D/15E.2's package builder
(`redline_core.archive.package`, now content-plan-aware), Mission 15E.2's
content-plan model (`redline_core.archive.content`), and Mission 15B's
guarded database commit (`Database.commit_verified_archive()`). This
module owns none of those primitives' mechanics -- it decides *what*
belongs in a complete archive and *when*/*with what identity* to invoke
the lower layers, and translates their outcomes into one Archive Manager
result or a typed failure.

`create_archive()` is the authoritative Rev1 entry point. It never moves,
deletes, or renames the episode's source workspace or any external
source (ingest/assets media, an explicit legacy manifest), never rewrites
`episode.folder_path`, and never contacts DaVinci Resolve -- this class is
constructible from `RedlineConfig` and a connected `Database` alone.

`archive_episode()` remains the Mission 15E-approved temporary
compatibility wrapper: a pure, unconditional delegation to
`create_archive()`, no branching, no destructive fallback. It does not
expose the new `manifest_path` legacy fallback parameter -- that is
Mission 15F transport work.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from redline_core.archive import integrity, package
from redline_core.archive.content import (
    ArchiveArtifact,
    ArchiveClassification,
    ArchiveContentPlan,
    ArchiveSourceKind,
    build_content_plan,
)
from redline_core.archive.exceptions import (
    ArchiveEligibilityError,
    ArchiveLegacyRecordError,
    ArchiveManifestProvenanceError,
    ArchiveRenderSelectionError,
    ArchiveVerifiedUnregisteredError,
    EpisodeAlreadyArchivedError,
)
from redline_core.archive.integrity import InventoryFile, SourceInventory
from redline_core.build.manifest_provenance import map_media_paths_to_approved_roots
from redline_core.config.schema import RedlineConfig
from redline_core.db.database import ArchiveCommitError, Database
from redline_core.db.models import ArchiveRecord, ArchiveState, EpisodeStatus, RenderJob, RenderJobStatus
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.manifest import ManifestError, load_manifest, validate_manifest

logger = logging.getLogger(__name__)

_ACTIVE_RENDER_JOB_STATUSES = (RenderJobStatus.CLAIMING, RenderJobStatus.QUEUED, RenderJobStatus.RENDERING)

_PROJECT_SUBFOLDER_NAME = "project"
_PROVENANCE_RELATIVE_DIR = "project/episode_manifest"
_PROVENANCE_FILENAME = "manifest_provenance.json"
_MANIFEST_SUFFIXES = (".yaml", ".yml")
_SOURCE_ROOT_INGEST = "ingest"
_SOURCE_ROOT_ASSETS = "assets"

Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# -- result model ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    """The result of a successfully committed Archive Rev1 archive: both
    the verified filesystem package's identity and the committed database
    record's identity. Carries no Resolve object and no mutable internal
    state (config/db/managers)."""

    episode_id: str
    archive_id: str
    archive_path: Path
    manifest_path: Path
    manifest_sha256: str
    render_job_id: int
    content_set_digest: str
    workspace_source_set_digest: str
    file_count: int
    directory_count: int
    total_bytes: int
    verified_at: str


def _normalized_media_identity(source_root: str, source_relative_path: str) -> tuple[str, str]:
    """Case-insensitive, root-relative collision key for one provenance
    media entry's `(source_root, source_relative_path)` identity.

    Matches `archive.integrity._normalized_identity_key()`'s
    unconditional-casefold policy (applied regardless of which OS is
    running this code, since Archive Rev1 packages are built for a
    Windows production filesystem) rather than defining a second,
    conflicting normalization scheme -- `source_root` is already a closed
    two-value vocabulary (`"ingest"`/`"assets"`) and needs no folding of
    its own."""
    return (source_root, source_relative_path.casefold())


@dataclass(frozen=True, slots=True)
class _CanonicalProvenance:
    """Discovered, schema-validated canonical build provenance found
    inside the episode workspace (see `_discover_canonical_provenance()`).
    `media_entries` is the raw, already-validated, already-duplicate-checked
    `[{"source_root", "source_relative_path"}, ...]` list read from
    `manifest_provenance.json`."""

    manifest_file: InventoryFile
    provenance_file: InventoryFile
    media_entries: list[dict]


class ArchiveManager:
    def __init__(self, config: RedlineConfig, db: Database, *, clock: Clock = _default_clock):
        self.config = config
        self.db = db
        self._clock = clock

    # -- Rev1 orchestration -----------------------------------------------------

    def create_archive(
        self,
        episode_id: str,
        *,
        render_job_id: int | None = None,
        manifest_path: str | Path | None = None,
    ) -> ArchiveResult:
        """Build, verify, publish, and commit a complete Rev1 archive for
        `episode_id`. See the module docstring for the guarantees this
        provides.

        `manifest_path` is a legacy fallback only, for an episode built
        before canonical manifest provenance existed: it is ignored (other
        than being cross-checked, never silently substituted) when the
        workspace already has canonical provenance, used as the original
        manifest location when it does not, and the eligibility failure is
        explicit (`ArchiveManifestProvenanceError`) when neither is
        available -- never guessed from the working directory, episode ID,
        or either approved root.

        Raises a typed exception (all subclass `ArchiveError`, except
        `EpisodeNotFoundError`) and leaves the source workspace, every
        external source, any existing archive package, and the database
        exactly as they were for every failure short of a fully committed
        archive -- including `ArchiveVerifiedUnregisteredError`, the one
        case where the filesystem package did succeed but the database
        commit did not.
        """
        episode = self.db.get_episode_by_episode_id(episode_id)
        if episode is None:
            raise EpisodeNotFoundError(f"No episode with episode_id={episode_id}.")

        self._reject_existing_archive_record(episode_id)

        if episode.status != EpisodeStatus.RENDERED:
            raise ArchiveEligibilityError(
                f"Episode {episode_id} has status {episode.status.value!r}; only a 'rendered' "
                "episode can be archived."
            )
        if not episode.folder_path:
            raise ArchiveEligibilityError(f"Episode {episode_id} has no working folder to archive.")
        source_root = Path(episode.folder_path)
        if not source_root.is_dir():
            raise ArchiveEligibilityError(f"Episode workspace does not exist: {source_root}")
        if episode.assembly_claim_token is not None:
            raise ArchiveEligibilityError(
                f"Episode {episode_id} has an active assembly claim "
                f"({episode.assembly_claim_token!r}); cannot archive while assembly is in progress."
            )

        selected_job = self._select_render_job(episode_id, render_job_id)
        self._require_output_in_workspace(selected_job, source_root)

        logger.info(
            "Archive Rev1 begin: episode_id=%s render_job_id=%s source_root=%s",
            episode_id,
            selected_job.id,
            source_root,
        )

        workspace_inventory = integrity.build_source_inventory(source_root)
        render_master_file = self._require_render_master_is_inventory_file(selected_job, workspace_inventory)

        plan = self._build_content_plan(
            episode_id=episode_id,
            workspace_inventory=workspace_inventory,
            render_master_file=render_master_file,
            manifest_path=manifest_path,
        )
        archive_id = self._derive_archive_id(episode_id, plan.content_set_digest)

        moment = self._clock()
        verified_at = _format_utc(moment)

        result = package.build_archive_package(
            plan,
            episode_id=episode_id,
            archive_id=archive_id,
            archive_root=self.config.paths.archive_path,
            clock=lambda: moment,
        )

        try:
            self.db.commit_verified_archive(
                episode_id=episode_id,
                render_job_id=selected_job.id,
                archive_id=archive_id,
                archive_path=str(result.final_path),
                manifest_path=str(result.manifest_path),
                manifest_sha256=result.manifest_sha256,
                verified_at=verified_at,
            )
        except ArchiveCommitError as exc:
            raise ArchiveVerifiedUnregisteredError(
                f"Archive package for episode {episode_id} was verified and published to "
                f"{result.final_path}, but database registration failed: {exc} Episode "
                f"{episode_id} remains 'rendered'; the verified package was not deleted, moved, "
                "or overwritten. Recovery/registration retry is a later-mission concern.",
                episode_id=episode_id,
                archive_id=archive_id,
                archive_path=str(result.final_path),
                manifest_path=str(result.manifest_path),
                manifest_sha256=result.manifest_sha256,
            ) from exc

        logger.info(
            "Archive Rev1 committed: episode_id=%s archive_id=%s render_job_id=%s archive_path=%s "
            "content_set_digest=%s manifest_sha256=%s",
            episode_id,
            archive_id,
            selected_job.id,
            result.final_path,
            result.content_set_digest,
            result.manifest_sha256,
        )

        return ArchiveResult(
            episode_id=episode_id,
            archive_id=archive_id,
            archive_path=result.final_path,
            manifest_path=result.manifest_path,
            manifest_sha256=result.manifest_sha256,
            render_job_id=selected_job.id,
            content_set_digest=result.content_set_digest,
            workspace_source_set_digest=result.workspace_source_set_digest,
            file_count=result.file_count,
            directory_count=result.directory_count,
            total_bytes=result.total_bytes,
            verified_at=verified_at,
        )

    def _reject_existing_archive_record(self, episode_id: str) -> None:
        """Checked first, independently of episode status -- see the
        Mission 15E report for why. A committed Rev1 row is an idempotent
        stop (`EpisodeAlreadyArchivedError`); a legacy row is classified
        distinctly and never silently treated as verified Rev1."""
        existing = self.db.get_archive_by_episode_id(episode_id)
        if existing is None:
            return
        if existing.archive_state == ArchiveState.COMPLETE:
            raise EpisodeAlreadyArchivedError(
                f"Episode {episode_id} already has a committed Rev1 archive at {existing.archive_path}."
            )
        raise ArchiveLegacyRecordError(
            f"Episode {episode_id} has a legacy (pre-Rev1) archive record at {existing.archive_path!r} "
            "(archive_schema_version=0). Mission 15E does not reclassify legacy archives as verified "
            "Rev1 or build a new package over them."
        )

    def _select_render_job(self, episode_id: str, render_job_id: int | None) -> RenderJob:
        """Select the one render job this archive will be built from. The
        active-job block applies unconditionally. SQLite
        (`list_render_jobs_for_episode`) is the sole authority -- Resolve
        is never contacted."""
        all_jobs = self.db.list_render_jobs_for_episode(episode_id)
        active = [job for job in all_jobs if job.status in _ACTIVE_RENDER_JOB_STATUSES]
        if active:
            raise ArchiveEligibilityError(
                f"Episode {episode_id} has an active render job (id={active[0].id}, "
                f"status={active[0].status.value!r}); cannot archive while a render is in progress."
            )

        if render_job_id is not None:
            job = self.db.get_render_job_by_id(render_job_id)
            if job is None:
                raise ArchiveRenderSelectionError(f"No render job with id={render_job_id}.")
            if job.episode_id != episode_id:
                raise ArchiveRenderSelectionError(
                    f"Render job {render_job_id} belongs to episode {job.episode_id!r}, not {episode_id!r}."
                )
            if job.status != RenderJobStatus.COMPLETE:
                raise ArchiveRenderSelectionError(
                    f"Render job {render_job_id} has status {job.status.value!r}; only a 'complete' "
                    "render job may be archived."
                )
            selected = job
        else:
            complete_jobs = [job for job in all_jobs if job.status == RenderJobStatus.COMPLETE]
            if not complete_jobs:
                raise ArchiveRenderSelectionError(f"Episode {episode_id} has no completed render job.")
            if len(complete_jobs) > 1:
                job_ids = [job.id for job in complete_jobs]
                raise ArchiveRenderSelectionError(
                    f"Episode {episode_id} has {len(complete_jobs)} completed render jobs {job_ids}; "
                    "an explicit render_job_id is required to resolve the ambiguity. Archive Rev1 "
                    "never guesses the latest/highest/first render job on the caller's behalf."
                )
            selected = complete_jobs[0]

        if not selected.output_path:
            raise ArchiveRenderSelectionError(f"Render job {selected.id} has no recorded output_path.")
        if not Path(selected.output_path).is_file():
            raise ArchiveRenderSelectionError(
                f"Render job {selected.id} output is missing on disk: {selected.output_path}"
            )
        return selected

    def _require_output_in_workspace(self, render_job: RenderJob, source_root: Path) -> None:
        """Cheap, pre-inventory fast-fail: proves the selected render
        job's output resolves inside the episode workspace *before*
        paying for a full `build_source_inventory()` walk. This is
        defense in depth, not the primary safety authority --
        `_require_render_master_is_inventory_file()` (run immediately
        after the inventory is built) is that authority; see its own
        docstring."""
        output_resolved = Path(render_job.output_path).resolve()
        workspace_resolved = source_root.resolve()
        if not output_resolved.is_relative_to(workspace_resolved):
            raise ArchiveEligibilityError(
                f"Render job {render_job.id} output {output_resolved} is outside the episode "
                f"workspace {workspace_resolved}; archiving a render output stored outside the "
                "active workspace is not yet supported (see Phase 15 Mission 15E report, "
                "external-artifact reconciliation)."
            )

    def _require_render_master_is_inventory_file(
        self, render_job: RenderJob, inventory: SourceInventory
    ) -> InventoryFile:
        """Mission 15E.2's render-master correction: proves the selected
        render job's output corresponds to an actual, already
        safety-proven `InventoryFile` in the trusted workspace inventory
        -- not merely that some path exists and resolves inside the
        workspace (`Path.is_file()`/`is_relative_to()` alone would accept
        a symlink pointing at a regular file, which Mission 15C's
        inventory walk would have rejected outright). Runs immediately
        after `build_source_inventory()`, before archive identity or
        package construction."""
        output_resolved = Path(render_job.output_path).resolve()
        match = _find_inventory_file_by_absolute_path(inventory, output_resolved)
        if match is None:
            raise ArchiveRenderSelectionError(
                f"Render job {render_job.id} output {output_resolved} does not correspond to a "
                "verified regular file in the workspace inventory; the render master cannot be "
                "archived until this is resolved."
            )
        return match

    # -- content plan resolution -------------------------------------------------

    def _build_content_plan(
        self,
        *,
        episode_id: str,
        workspace_inventory: SourceInventory,
        render_master_file: InventoryFile,
        manifest_path: str | Path | None,
    ) -> ArchiveContentPlan:
        """Resolve the complete required preservation content -- workspace
        (already captured by `workspace_inventory`) plus the original
        episode manifest and every manifest-referenced source-media file
        -- into one `ArchiveContentPlan`. See the module docstring's
        ownership boundary: this method decides *what* belongs in the
        plan; `package.py` only ever consumes an already-resolved one.
        """
        canonical = self._discover_canonical_provenance(workspace_inventory)

        workspace_overlay: dict[Path, set[str]] = {
            render_master_file.absolute_source_path: {ArchiveClassification.RENDER_MASTER.value}
        }
        external_artifacts: list[ArchiveArtifact] = []
        media_entries: list[dict]

        if canonical is not None:
            if manifest_path is not None:
                self._require_manifest_override_matches_canonical(manifest_path, canonical)
            workspace_overlay.setdefault(canonical.manifest_file.absolute_source_path, set()).add(
                ArchiveClassification.EPISODE_MANIFEST.value
            )
            workspace_overlay.setdefault(canonical.provenance_file.absolute_source_path, set()).add(
                ArchiveClassification.MANIFEST_PROVENANCE.value
            )
            media_entries = canonical.media_entries
        else:
            if manifest_path is None:
                raise ArchiveManifestProvenanceError(
                    f"Episode {episode_id} has no canonical manifest provenance in its workspace "
                    "and no explicit legacy manifest_path was supplied; cannot resolve required "
                    "archive content."
                )
            legacy_artifact, media_entries = self._resolve_legacy_manifest(manifest_path)
            external_artifacts.append(legacy_artifact)

        # Deduplicate by (source_root, source_relative_path) before
        # building artifacts. Canonical provenance can no longer reach this
        # point carrying a duplicate identity --
        # `_discover_canonical_provenance()` already fails closed on that
        # above, since a duplicate there is not legitimate canonical state
        # (it indicates tampering/corruption, never ordinary redundant
        # input) -- so this is a no-op for `canonical.media_entries`. It
        # remains needed for the legacy manifest fallback path: a manifest
        # can legitimately reference the same approved media file from more
        # than one `assembly.media[]` entry, and that ordinary redundancy
        # should not be able to trip build_content_plan()'s defensive
        # uniqueness check (that check exists to catch a genuine
        # ArchiveManager construction bug, not to classify ordinary
        # redundant input data as one).
        deduplicated_media_entries = list(
            {(entry["source_root"], entry["source_relative_path"]): entry for entry in media_entries}.values()
        )

        for entry in deduplicated_media_entries:
            source_root_label = entry["source_root"]
            source_relative_path = entry["source_relative_path"]
            resolved_absolute_path = self._resolve_source_media_absolute_path(source_root_label, source_relative_path)
            workspace_match = _find_inventory_file_by_absolute_path(workspace_inventory, resolved_absolute_path)
            if workspace_match is not None:
                # Physical-path dedup (Mission 15E.2 item 14): the same
                # physical file is already captured by the workspace copy
                # -- classify it, never copy it a second time.
                workspace_overlay.setdefault(workspace_match.absolute_source_path, set()).add(
                    ArchiveClassification.SOURCE_MEDIA.value
                )
            else:
                external_artifacts.append(
                    self._build_source_media_artifact(source_root_label, source_relative_path, resolved_absolute_path)
                )

        artifacts: list[ArchiveArtifact] = []
        for absolute_path, classifications in workspace_overlay.items():
            inv_file = _find_inventory_file_by_absolute_path(workspace_inventory, absolute_path)
            artifacts.append(
                ArchiveArtifact(
                    absolute_source_path=absolute_path,
                    archive_relative_path=f"workspace/{inv_file.relative_path}",
                    size_bytes=inv_file.size_bytes,
                    sha256=inv_file.sha256,
                    classifications=(ArchiveClassification.WORKSPACE.value, *sorted(classifications)),
                    source_kind=ArchiveSourceKind.WORKSPACE,
                )
            )
        artifacts.extend(external_artifacts)

        return build_content_plan(workspace_inventory, tuple(artifacts))

    def _discover_canonical_provenance(self, workspace_inventory: SourceInventory) -> _CanonicalProvenance | None:
        """Look for canonical build provenance
        (`project/episode_manifest/`) among the already-verified workspace
        inventory's own files -- never a second, independent filesystem
        walk. Returns `None` (a legacy episode) if nothing is there at
        all; fails closed (`ArchiveManifestProvenanceError`) for anything
        present but incomplete/malformed/inconsistent."""
        prefix = f"{_PROVENANCE_RELATIVE_DIR}/"
        entries_by_name: dict[str, InventoryFile] = {}
        for f in workspace_inventory.files:
            if not f.relative_path.startswith(prefix):
                continue
            remainder = f.relative_path[len(prefix) :]
            if "/" in remainder:
                raise ArchiveManifestProvenanceError(
                    f"unexpected nested content under canonical manifest provenance directory: {f.relative_path}"
                )
            entries_by_name[remainder] = f

        if not entries_by_name:
            return None

        provenance_file = entries_by_name.pop(_PROVENANCE_FILENAME, None)
        if provenance_file is None:
            raise ArchiveManifestProvenanceError(
                f"episode workspace has content under {prefix!r} but is missing {_PROVENANCE_FILENAME!r}"
            )

        manifest_candidates = {
            name: f for name, f in entries_by_name.items() if Path(name).suffix.lower() in _MANIFEST_SUFFIXES
        }
        if not manifest_candidates:
            raise ArchiveManifestProvenanceError(f"no canonical manifest YAML/YML file found under {prefix!r}")
        if len(manifest_candidates) > 1:
            raise ArchiveManifestProvenanceError(
                f"multiple canonical manifest files found under {prefix!r}: {sorted(manifest_candidates)}"
            )
        unexpected = sorted(set(entries_by_name) - set(manifest_candidates))
        if unexpected:
            raise ArchiveManifestProvenanceError(f"unexpected file(s) under {prefix!r}: {unexpected}")

        (manifest_file,) = manifest_candidates.values()

        try:
            provenance_data = json.loads(provenance_file.absolute_source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArchiveManifestProvenanceError(
                f"manifest provenance record is unreadable or malformed: {provenance_file.absolute_source_path}"
            ) from exc

        if not isinstance(provenance_data, dict) or provenance_data.get("schema_version") != 1:
            raise ArchiveManifestProvenanceError(
                f"unsupported or malformed manifest provenance schema: {provenance_file.absolute_source_path}"
            )
        if provenance_data.get("manifest_sha256") != manifest_file.sha256:
            raise ArchiveManifestProvenanceError(
                "manifest provenance SHA-256 does not match the canonical manifest's actual content: "
                f"{provenance_file.absolute_source_path}"
            )
        media = provenance_data.get("media")
        if not isinstance(media, list):
            raise ArchiveManifestProvenanceError(
                f"manifest provenance 'media' must be a list: {provenance_file.absolute_source_path}"
            )
        seen_media_identities: dict[tuple[str, str], str] = {}
        for entry in media:
            if (
                not isinstance(entry, dict)
                or entry.get("source_root") not in (_SOURCE_ROOT_INGEST, _SOURCE_ROOT_ASSETS)
                or not isinstance(entry.get("source_relative_path"), str)
                or not entry["source_relative_path"]
            ):
                raise ArchiveManifestProvenanceError(f"malformed manifest provenance media entry: {entry!r}")
            source_root_label = entry["source_root"]
            source_relative_path = entry["source_relative_path"]
            identity = _normalized_media_identity(source_root_label, source_relative_path)
            existing = seen_media_identities.get(identity)
            if existing is not None:
                # Canonical provenance is generated once, by a single
                # already-validated build, from an upstream media list that
                # is itself already unique (see
                # `manifest_provenance.map_media_paths_to_approved_roots()`'s
                # own duplicate-identity guard). A duplicate normalized
                # identity surviving into this file is therefore not
                # legitimate canonical state -- it indicates tampering,
                # corruption, or a manual/unsupported edit -- and must fail
                # closed here, before any content plan, package staging,
                # publication, DB commit, or episode status transition is
                # attempted. Never deduplicated, merged, or silently
                # accepted.
                raise ArchiveManifestProvenanceError(
                    "duplicate media identity in canonical manifest provenance: "
                    f"source_root={source_root_label!r} source_relative_path={source_relative_path!r} "
                    f"collides with {existing!r} once normalized "
                    f"(case-insensitive, per archive.integrity's identity policy): "
                    f"{provenance_file.absolute_source_path}"
                )
            seen_media_identities[identity] = source_relative_path

        return _CanonicalProvenance(manifest_file=manifest_file, provenance_file=provenance_file, media_entries=media)

    def _require_manifest_override_matches_canonical(
        self, manifest_path: str | Path, canonical: _CanonicalProvenance
    ) -> None:
        """Canonical provenance is authority; an explicit legacy
        `manifest_path` supplied alongside it is accepted only if it is
        demonstrably the *same* manifest (matching SHA-256) -- otherwise
        rejected outright. The caller can never substitute a different
        manifest for an episode's already-recorded build provenance."""
        try:
            override_sha256, _ = integrity.hash_stable_file(manifest_path)
        except Exception as exc:  # noqa: BLE001 -- any failure means "cannot confirm match"
            raise ArchiveManifestProvenanceError(
                f"supplied manifest_path override could not be verified: {manifest_path}: {exc}"
            ) from exc
        if override_sha256 != canonical.manifest_file.sha256:
            raise ArchiveManifestProvenanceError(
                f"supplied manifest_path ({manifest_path}) does not match episode {canonical.manifest_file.relative_path!r}'s "
                "canonical build provenance; the caller cannot override an episode's authoritative build provenance."
            )

    def _resolve_legacy_manifest(self, manifest_path: str | Path) -> tuple[ArchiveArtifact, list[dict]]:
        """Legacy fallback: load and validate the manifest at its actual
        original location using the existing, unmodified manifest loader/
        validator (relative media paths resolved against *that*
        directory, exactly as the build layer itself would have done --
        never against the episode workspace). The manifest itself becomes
        an explicit `EPISODE_MANIFEST` external artifact; there is no
        canonical in-workspace copy for a legacy episode by definition.
        """
        resolved_path = Path(manifest_path).resolve()
        try:
            manifest_model = load_manifest(resolved_path)
            plan = validate_manifest(manifest_model, manifest_path=resolved_path, config=self.config)
        except ManifestError as exc:
            raise ArchiveManifestProvenanceError(
                f"legacy manifest could not be loaded/validated: {resolved_path}: {exc}"
            ) from exc

        sha256, size_bytes = integrity.hash_stable_file(resolved_path)
        artifact = ArchiveArtifact(
            absolute_source_path=resolved_path,
            archive_relative_path=f"external/episode_manifest/{resolved_path.name}",
            size_bytes=size_bytes,
            sha256=sha256,
            classifications=(ArchiveClassification.EPISODE_MANIFEST.value,),
            source_kind=ArchiveSourceKind.EPISODE_MANIFEST,
        )
        media_entries = map_media_paths_to_approved_roots(plan.media_paths, self.config)
        return artifact, media_entries

    def _resolve_source_media_absolute_path(self, source_root_label: str, source_relative_path: str) -> Path:
        root = self._approved_source_root(source_root_label)
        candidate = (root / source_relative_path).resolve()
        if not candidate.is_relative_to(root):
            raise ArchiveManifestProvenanceError(
                f"provenance media path escapes its approved root: {source_root_label}/{source_relative_path}"
            )
        return candidate

    def _approved_source_root(self, source_root_label: str) -> Path:
        if source_root_label == _SOURCE_ROOT_INGEST:
            configured = self.config.paths.ingest_path
        elif source_root_label == _SOURCE_ROOT_ASSETS:
            configured = self.config.paths.assets_path
        else:
            raise ArchiveManifestProvenanceError(f"invalid provenance source_root: {source_root_label!r}")
        try:
            return Path(configured).expanduser().resolve(strict=True)
        except OSError as exc:
            raise ArchiveManifestProvenanceError(
                f"approved {source_root_label} root cannot be resolved: {configured}"
            ) from exc

    def _build_source_media_artifact(
        self, source_root_label: str, source_relative_path: str, resolved_absolute_path: Path
    ) -> ArchiveArtifact:
        """Mission 15C safe regular-file verification on the actual
        candidate path used for archival -- never trust the manifest
        validator's own `Path.resolve(strict=True)` (which follows links)
        as the final filesystem-safety authority. `integrity.hash_stable_file()`
        raises its own typed `ArchiveError` subclasses (already accurate)
        for a missing/unsafe file; not re-wrapped here."""
        sha256, size_bytes = integrity.hash_stable_file(resolved_absolute_path)
        root_classification = (
            ArchiveClassification.INGEST_MEDIA if source_root_label == _SOURCE_ROOT_INGEST else ArchiveClassification.ASSET_MEDIA
        )
        return ArchiveArtifact(
            absolute_source_path=resolved_absolute_path,
            archive_relative_path=f"external/source_media/{source_root_label}/{source_relative_path}",
            size_bytes=size_bytes,
            sha256=sha256,
            classifications=(ArchiveClassification.SOURCE_MEDIA.value, root_classification.value),
            source_kind=ArchiveSourceKind.SOURCE_MEDIA,
            source_root=source_root_label,
            source_relative_path=source_relative_path,
        )

    @staticmethod
    def _derive_archive_id(episode_id: str, content_set_digest: str) -> str:
        """Deterministic, timestamp-independent Rev1 archive identity,
        now derived from the *complete* content-set digest (Mission
        15E.2), not the workspace-only source_set_digest: stable for the
        same complete preservation payload, safe as a directory-name
        component, never derived from a clock. The same complete content
        plan always yields the same archive_id; any change to required
        preservation content (workspace, external media, or the manifest)
        yields a different one."""
        return f"{episode_id}-a1-{content_set_digest[:12].lower()}"

    # -- legacy compatibility (temporary; Mission 15F retires this) -------------

    def archive_episode(self, episode_id: str) -> ArchiveResult:
        """Temporary Rev1-safe compatibility wrapper for the existing CLI
        (`archive episode`) and MCP (`archive_episode`) entry points,
        which still call this method by name. Delegates entirely to
        `create_archive()` -- no branching, no destructive fallback, no
        `shutil.move()`, no `folder_path` rewrite, and no exposure of the
        legacy `manifest_path` fallback (Mission 15F transport work).
        Mission 15F owns migrating those transports to call
        `create_archive()` directly and retiring this wrapper."""
        return self.create_archive(episode_id)

    def list_archives(self) -> list[ArchiveRecord]:
        return self.db.list_archives()


def _find_inventory_file_by_absolute_path(inventory: SourceInventory, absolute_path: Path) -> InventoryFile | None:
    for f in inventory.files:
        if f.absolute_source_path == absolute_path:
            return f
    return None
