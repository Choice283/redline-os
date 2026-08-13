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

`verify_archive()` (Phase 15 Mission 15F) is the authoritative, read-only
Rev1 verification entry point: it reads the committed `archives` row for
an episode, classifies it (legacy rows fail closed rather than being
verified as if they were Rev1), and delegates the actual filesystem
proof to `package.verify_archive_package()` -- this class owns the DB
read and the DB-vs-filesystem identity cross-check; `package.py` owns
every byte-level/hash-level check and remains entirely unaware of SQLite.
Mutates nothing: no episode-status write, no `archives` row write, no
source-workspace touch, no Resolve.

Mission 15F retired the Mission 15E `archive_episode()` compatibility
wrapper once every transport call site migrated to calling
`create_archive()` directly -- see docs/CHANGELOG.md's Mission 15F entry
for the call-site inventory. `create_archive()`/`verify_archive()`/
`list_archives()` are the only public archive operations now.
"""
from __future__ import annotations

import json
import logging
import re
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
    ArchiveEvidenceConfigurationError,
    ArchiveLegacyRecordError,
    ArchiveManifestMismatchError,
    ArchiveManifestProvenanceError,
    ArchiveNotFoundError,
    ArchivePathError,
    ArchiveRecoveryConflictError,
    ArchiveRecoveryMetadataError,
    ArchiveRecoveryNotFoundError,
    ArchiveRenderSelectionError,
    ArchiveVerifiedUnregisteredError,
    EpisodeAlreadyArchivedError,
)
from redline_core.archive.evidence import EpisodeEvidencePlan, resolve_episode_evidence
from redline_core.archive.integrity import InventoryFile, SourceInventory
from redline_core.archive.metadata_snapshot import (
    build_config_snapshot_bytes,
    build_episode_snapshot_bytes,
    build_render_job_snapshot_bytes,
    build_software_snapshot_bytes,
    resolve_software_identity,
)
from redline_core.archive.supplement import (
    ArchivePackagePlan,
    ArchiveSupplementClassification,
    build_generated_supplement,
    build_package_plan,
)
from redline_core.build.manifest_provenance import map_media_paths_to_approved_roots
from redline_core.config.schema import RedlineConfig
from redline_core.db.database import ArchiveCommitError, Database
from redline_core.db.models import ArchiveRecord, ArchiveState, Episode, EpisodeStatus, RenderJob, RenderJobStatus
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

_METADATA_EPISODE_PATH = "metadata/episode.json"
_METADATA_RENDER_JOB_PATH = "metadata/render_job.json"
_METADATA_CONFIG_PATH = "metadata/config_snapshot.json"
_METADATA_SOFTWARE_PATH = "metadata/software.json"

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


@dataclass(frozen=True, slots=True)
class ArchiveVerificationResult:
    """The result of a successful `ArchiveManager.verify_archive()` call
    (Phase 15 Mission 15F): a committed Rev1 archive record whose
    filesystem package independently re-verified clean. `verified` is
    always `True` on a returned result -- every failure mode (no archive
    record, a legacy record, a corrupt/divergent package, a DB-vs-package
    identity mismatch) raises a typed exception instead of returning a
    result with `verified=False`, matching this module's existing
    fail-closed convention (`create_archive()` never returns a partial/
    degraded `ArchiveResult` either). The field is still carried on the
    result, not implied solely by "no exception was raised," so CLI/MCP
    serialization has one explicit, self-describing field to report.
    Carries no mutable manager/DB/Resolve state."""

    episode_id: str
    archive_id: str
    archive_path: Path
    manifest_sha256: str
    verified: bool
    file_count: int
    directory_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class ArchiveRecoveryResult:
    """The result of a successful `ArchiveManager.recover_archive()` call
    (Phase 15 Mission 15H): either a freshly-registered `VERIFIED_UNREGISTERED`
    -> `REGISTERED COMPLETE` transition, or a deterministic proof that the
    exact matching registration already exists. Carries only immutable
    identity fields the caller needs to report -- no `StagedPackage`, no
    parsed manifest, no mutable manager/DB/Resolve state.

    `classification` is `"recovered"` (this call performed the DB
    registration) or `"already_registered"` (a prior call, or the
    original `create_archive()` attempt in the counterfactual where its
    own commit had actually succeeded, already registered this exact
    package -- recovery is idempotent, never a second row, never an
    error for calling it again)."""

    episode_id: str
    archive_id: str
    archive_path: Path
    manifest_sha256: str
    render_job_id: int
    classification: str


_RECOVERY_CLASSIFICATION_RECOVERED = "recovered"
_RECOVERY_CLASSIFICATION_ALREADY_REGISTERED = "already_registered"

_ARCHIVE_ID_SUFFIX_RE = re.compile(r"^[0-9a-f]{12}$")
_ARCHIVE_ID_SCHEMA_TAG = "a1"


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
        self._reject_existing_final_package(episode_id, archive_id)

        # Snapshotted once, here, from the already-loaded `episode`/
        # `selected_job`/`self.config` -- never re-read from the DB/config
        # a second time during package construction, so a concurrent
        # write cannot be observed mid-build (Mission 15G item 37).
        # `episode` is still the pre-commit 'rendered' record: the DB
        # transition to 'archived' below (via commit_verified_archive())
        # happens strictly after this package is already sealed.
        evidence_plan = self._resolve_configured_evidence(episode_id)
        supplements = (*evidence_plan.supplements, *self._build_metadata_supplements(episode, selected_job))
        package_plan = build_package_plan(plan, supplements, supplement_directories=evidence_plan.directories)

        moment = self._clock()
        verified_at = _format_utc(moment)

        result = package.build_archive_package(
            package_plan,
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

    # -- evidence (Phase 15 Mission 15G.1) -----------------------------------------

    def _resolve_configured_evidence(self, episode_id: str) -> EpisodeEvidencePlan:
        """Resolve `episode_id`'s authoritative evidence scope. Requires
        an evidence-root authority to be configured at all -- a missing
        authority is never treated as an authoritative zero-evidence
        result (Mission 15G.1's narrow correction over the original
        Mission 15G.1 session's more permissive behavior, which this
        method previously implemented and which Control Room rejected as
        the canonical archive-completeness contract).

        Two genuinely different conditions, deliberately not conflated:
        `self.config.paths.evidence_path is None` -- no evidence-root
        authority exists in this configuration at all -- is a
        configuration-completeness failure and raises
        `ArchiveEvidenceConfigurationError` before any
        `ArchivePackagePlan` construction, package staging, publication,
        or database commit; `config.paths.evidence_path` being set but
        `<evidence_path>/<episode_id>/` simply not existing is a valid,
        ordinary zero-evidence result (`resolve_episode_evidence()`'s own
        contract, unchanged) -- evidence generation is not mandatory for
        every episode once an evidence authority *does* exist. Once
        `evidence_path` is configured, every other misconfiguration
        (a missing/unsafe root, an unsafe/identity-conflicting episode
        directory) still fails closed via `resolve_episode_evidence()`'s
        existing `ArchivePathError`/`ArchiveUnsafeFilesystemObjectError`/
        `ArchiveEvidenceIdentityConflictError` contract, unchanged.

        `PathsConfig.evidence_path` itself remains optional at the config-
        schema level (existing `paths.yaml` documents without it still
        load) -- this method, not config parsing, is where the archive-
        completeness requirement is enforced."""
        if self.config.paths.evidence_path is None:
            raise ArchiveEvidenceConfigurationError(
                f"Episode {episode_id}: no evidence-root authority is configured "
                "(config.paths.evidence_path is not set); Archive Rev1 cannot establish "
                "the authoritative evidence source for this episode. Configure "
                "paths.evidence_path to either a valid evidence root (an episode with no "
                f"{episode_id!r} subdirectory under it still archives with zero evidence) "
                "before archiving, or contact Paul if this deployment intentionally has no "
                "evidence authority yet."
            )
        return resolve_episode_evidence(evidence_root=self.config.paths.evidence_path, episode_id=episode_id)

    # -- supplements (Phase 15 Mission 15G) --------------------------------------

    def _build_metadata_supplements(self, episode: Episode, render_job: RenderJob) -> tuple:
        """Build the four Mission 15G generated restore-metadata
        supplements from already-loaded, already-in-memory sources only:
        the `episode`/`render_job` records this call already holds (never
        a second DB read), `self.config` (the effective configuration this
        archive is being built under), and the current process's own
        software identity. No evidence supplement is ever constructed
        here -- Mission 15G's repository investigation found no
        authoritative episode-scoped evidence-source mapping (see
        docs/CHANGELOG.md's Mission 15G entry); inventing one is
        explicitly out of scope, so `ArchiveManager` never resolves or
        archives production evidence."""
        software_identity = resolve_software_identity()
        return (
            build_generated_supplement(
                archive_relative_path=_METADATA_EPISODE_PATH,
                canonical_bytes=build_episode_snapshot_bytes(episode),
                classifications=(
                    ArchiveSupplementClassification.GENERATED_METADATA.value,
                    ArchiveSupplementClassification.EPISODE_SNAPSHOT.value,
                ),
                source_kind="generated_metadata",
            ),
            build_generated_supplement(
                archive_relative_path=_METADATA_RENDER_JOB_PATH,
                canonical_bytes=build_render_job_snapshot_bytes(render_job),
                classifications=(
                    ArchiveSupplementClassification.GENERATED_METADATA.value,
                    ArchiveSupplementClassification.RENDER_JOB_SNAPSHOT.value,
                ),
                source_kind="generated_metadata",
            ),
            build_generated_supplement(
                archive_relative_path=_METADATA_CONFIG_PATH,
                canonical_bytes=build_config_snapshot_bytes(self.config),
                classifications=(
                    ArchiveSupplementClassification.GENERATED_METADATA.value,
                    ArchiveSupplementClassification.CONFIG_SNAPSHOT.value,
                ),
                source_kind="generated_metadata",
            ),
            build_generated_supplement(
                archive_relative_path=_METADATA_SOFTWARE_PATH,
                canonical_bytes=build_software_snapshot_bytes(**software_identity),
                classifications=(
                    ArchiveSupplementClassification.GENERATED_METADATA.value,
                    ArchiveSupplementClassification.SOFTWARE_IDENTITY.value,
                ),
                source_kind="generated_metadata",
            ),
        )

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

    def _reject_existing_final_package(self, episode_id: str, archive_id: str) -> None:
        """Phase 15 Mission 15H: `archive_id` does not incorporate
        supplemental evidence/metadata identity (Mission 15G's frozen
        boundary) -- the *same* `archive_id` (same preservation content)
        can therefore be re-derived by a later `create_archive()` attempt
        whose current evidence/config/software state differs from an
        earlier attempt's. If a final package already exists at the
        canonical path this `archive_id` would publish to, that package
        -- not a freshly-built one -- owns that path permanently. This
        method never lets `create_archive()` reach `package.build_archive_package()`
        in that case: no overwrite, no rebuild, ever.

        A pre-existing package that still independently verifies means
        exactly one thing: a prior attempt already reached
        `VERIFIED_UNREGISTERED` (published, but never registered) --
        raised here as the same `ArchiveVerifiedUnregisteredError` a
        failed DB commit raises, so the operator sees one consistent
        signal regardless of when that state is discovered, always
        pointing at Mission 15H's `recover_archive()`. A pre-existing
        package that fails verification is corrupt or identity-conflicting
        and is never touched -- the verifier's own exception propagates
        unchanged, fail closed; this state requires human investigation,
        not automatic repair (Mission 15H item 26)."""
        final_path = package.derive_final_package_path(self.config.paths.archive_path, episode_id, archive_id)
        if not final_path.exists():
            return

        package_result = package.verify_archive_package(
            final_path, expected_episode_id=episode_id, expected_archive_id=archive_id
        )
        raise ArchiveVerifiedUnregisteredError(
            f"A verified final archive package for episode {episode_id} already exists at "
            f"{package_result.final_path} (archive_id={archive_id}), but no matching database "
            "registration exists. This create attempt was stopped before any new package was built "
            "-- the existing package was not overwritten, rebuilt, or touched. Use "
            "ArchiveManager.recover_archive() with this exact archive_id to register it.",
            episode_id=episode_id,
            archive_id=archive_id,
            archive_path=str(package_result.final_path),
            manifest_path=str(package_result.manifest_path),
            manifest_sha256=package_result.manifest_sha256,
        )

    # -- read-only verification ---------------------------------------------------

    def verify_archive(self, episode_id: str) -> ArchiveVerificationResult:
        """Prove a committed Rev1 archive is still valid (Phase 15
        Mission 15F): a pure, read-only orchestration of the DB record
        lookup and the filesystem package's own independent
        re-verification. Never mutates the episode, the `archives` row,
        the source workspace, or the archive package; never contacts
        Resolve.

        Raises (all `ArchiveError` subclasses, never a partial/degraded
        result):
          - `ArchiveNotFoundError` -- no committed `archives` row exists
            for `episode_id` at all. Mission 15F stays focused on
            committed records; this never scans the archive root
            attempting recovery of an unregistered package (Mission 15H's
            concern) and never repairs or registers anything.
          - `ArchiveLegacyRecordError` -- the row exists but is a pre-Rev1
            legacy record (`archive_schema_version == 0`); it has no Rev1
            manifest/hashes to verify and is never pretended otherwise.
          - Whatever `package.verify_archive_package()` raises for a
            Rev1 record whose filesystem package has diverged (missing/
            unexpected/mismatched control files, payload content, or
            manifest structure) -- propagated unchanged; this method adds
            no second, weaker verification algorithm.
          - `ArchiveManifestMismatchError` -- the filesystem package is
            perfectly self-consistent, but the committed DB row's
            `manifest_sha256`/`manifest_path` disagree with what was
            actually, independently verified on disk.
        """
        record = self.db.get_archive_by_episode_id(episode_id)
        if record is None:
            raise ArchiveNotFoundError(f"No archive record exists for episode {episode_id!r}; nothing to verify.")
        if record.archive_state != ArchiveState.COMPLETE:
            raise ArchiveLegacyRecordError(
                f"Episode {episode_id} has a legacy (pre-Rev1) archive record at {record.archive_path!r} "
                "(archive_schema_version=0); it has no Rev1 manifest/hashes and cannot be verified as one."
            )

        package_result = package.verify_archive_package(
            record.archive_path, expected_episode_id=episode_id, expected_archive_id=record.archive_id
        )

        if record.manifest_sha256 != package_result.manifest_sha256:
            raise ArchiveManifestMismatchError(
                f"Episode {episode_id}: committed archive record manifest_sha256 "
                f"({record.manifest_sha256!r}) does not match the independently verified package "
                f"manifest_sha256 ({package_result.manifest_sha256!r})."
            )
        if Path(record.manifest_path) != package_result.manifest_path:
            raise ArchiveManifestMismatchError(
                f"Episode {episode_id}: committed archive record manifest_path ({record.manifest_path!r}) "
                f"does not match the independently verified package manifest_path ({package_result.manifest_path!r})."
            )

        logger.info(
            "Archive Rev1 verified: episode_id=%s archive_id=%s archive_path=%s manifest_sha256=%s",
            episode_id,
            package_result.archive_id,
            package_result.final_path,
            package_result.manifest_sha256,
        )

        return ArchiveVerificationResult(
            episode_id=episode_id,
            archive_id=package_result.archive_id,
            archive_path=package_result.final_path,
            manifest_sha256=package_result.manifest_sha256,
            verified=True,
            file_count=package_result.file_count,
            directory_count=package_result.directory_count,
            total_bytes=package_result.total_bytes,
        )

    def list_archives(self) -> list[ArchiveRecord]:
        return self.db.list_archives()

    # -- recovery (Phase 15 Mission 15H) -------------------------------------------

    def recover_archive(self, episode_id: str, *, archive_id: str) -> ArchiveRecoveryResult:
        """Register an already-published, independently-verified Rev1
        final package that a prior `create_archive()` attempt left
        `VERIFIED_UNREGISTERED` (a fully verified package on disk, no
        matching `archives` row). Recovery never repairs, rebuilds,
        replaces, or re-seals a package -- it verifies the sealed package
        exactly as it already is and, if every precondition holds,
        performs the same guarded DB transaction `create_archive()`
        itself would have performed.

        `archive_id` is required and explicit -- recovery never scans the
        archive root guessing which package to register (item 6); the
        canonical final path is derived purely from
        `(self.config.paths.archive_path, episode_id, archive_id)`, never
        from an operator-supplied path.

        Recovery deliberately does NOT rebuild `ArchiveContentPlan`,
        re-hash the active workspace, re-read current ingest/assets/
        evidence, or recompute `archive_id` from current source state
        (item 7) -- the sealed package is the authority for what was
        preserved; only its own already-sealed
        `payload/metadata/episode.json`/`payload/metadata/render_job.json`
        are read, and only after the package itself has independently
        verified (item 42/43: never parse unverified package data).

        Idempotent (item 19): a second call after a successful first
        recovery returns `classification="already_registered"` rather
        than raising or creating a second row. A DB commit failure during
        recovery leaves the package exactly `VERIFIED_UNREGISTERED` --
        raised as the same `ArchiveVerifiedUnregisteredError`
        `create_archive()` itself raises, so a later `recover_archive()`
        call remains possible (item 27).

        Raises (all `ArchiveError` subclasses except `EpisodeNotFoundError`):
          - `ArchivePathError` -- `archive_id` is not a well-formed,
            safe Rev1 archive identifier for `episode_id`.
          - `ArchiveRecoveryNotFoundError` -- no final package exists at
            the canonical path at all.
          - `ArchivePathError`/`ArchiveUnsafeFilesystemObjectError`/
            `ArchivePackageVerificationError` -- the package exists but
            fails the published finalized-package verifier (propagated
            unchanged; never repaired, never overwritten -- item 26).
          - `ArchiveRecoveryMetadataError` -- the package verifies, but
            its sealed `episode.json`/`render_job.json` is missing,
            malformed, or internally inconsistent with the package's own
            manifest identity.
          - `EpisodeNotFoundError` -- no current episode row for
            `episode_id`.
          - `ArchiveLegacyRecordError` -- an existing `archives` row for
            this episode is a pre-Rev1 legacy record.
          - `ArchiveRecoveryConflictError` -- current DB state (episode
            status, an existing but non-matching `archives` row, or the
            live `render_jobs` row) disagrees with what recovery
            requires; never overwritten, never repaired.
          - `ArchiveVerifiedUnregisteredError` -- the DB commit itself
            failed; the package remains exactly `VERIFIED_UNREGISTERED`,
            retry remains possible.
        """
        self._validate_recovery_archive_id(episode_id, archive_id)
        final_path = package.derive_final_package_path(self.config.paths.archive_path, episode_id, archive_id)
        if not final_path.exists():
            raise ArchiveRecoveryNotFoundError(
                f"No final archive package exists at the canonical path for episode_id={episode_id!r} "
                f"archive_id={archive_id!r}: {final_path}"
            )

        logger.info("Archive recovery requested: episode_id=%s archive_id=%s", episode_id, archive_id)

        package_result = package.verify_archive_package(
            final_path, expected_episode_id=episode_id, expected_archive_id=archive_id
        )
        logger.info(
            "Archive recovery package verified: episode_id=%s archive_id=%s manifest_sha256=%s",
            episode_id,
            archive_id,
            package_result.manifest_sha256,
        )

        self._read_recovery_episode_snapshot(final_path, expected_episode_id=episode_id)
        render_job_snapshot = self._read_recovery_render_job_snapshot(final_path, expected_episode_id=episode_id)
        render_job_id = render_job_snapshot["render_job_id"]

        episode = self.db.get_episode_by_episode_id(episode_id)
        if episode is None:
            raise EpisodeNotFoundError(f"No episode with episode_id={episode_id}.")

        existing_record = self.db.get_archive_by_episode_id(episode_id)
        if existing_record is not None:
            if (
                existing_record.archive_state == ArchiveState.COMPLETE
                and existing_record.archive_id == archive_id
                and existing_record.archive_path == str(package_result.final_path)
                and existing_record.manifest_sha256 == package_result.manifest_sha256
                and existing_record.render_job_id == render_job_id
                and episode.status == EpisodeStatus.ARCHIVED
            ):
                logger.info(
                    "Archive recovery already registered: episode_id=%s archive_id=%s", episode_id, archive_id
                )
                return ArchiveRecoveryResult(
                    episode_id=episode_id,
                    archive_id=archive_id,
                    archive_path=package_result.final_path,
                    manifest_sha256=package_result.manifest_sha256,
                    render_job_id=render_job_id,
                    classification=_RECOVERY_CLASSIFICATION_ALREADY_REGISTERED,
                )
            if existing_record.archive_state != ArchiveState.COMPLETE:
                raise ArchiveLegacyRecordError(
                    f"Episode {episode_id} has a legacy (pre-Rev1) archive record at "
                    f"{existing_record.archive_path!r}; Mission 15H recovery does not reclassify or "
                    "overwrite a legacy row."
                )
            raise ArchiveRecoveryConflictError(
                f"Episode {episode_id} already has a committed archive record "
                f"(archive_id={existing_record.archive_id!r}, archive_path={existing_record.archive_path!r}) "
                f"that does not exactly match the package being recovered "
                f"(archive_id={archive_id!r}, archive_path={package_result.final_path!r}). Recovery never "
                "overwrites or repairs an existing registration."
            )

        if episode.status != EpisodeStatus.RENDERED:
            raise ArchiveRecoveryConflictError(
                f"Episode {episode_id} has current status {episode.status.value!r}; recovery requires the "
                "episode to still be 'rendered' when no matching archives row exists yet."
            )

        self._validate_current_render_job_for_recovery(episode_id, render_job_id, render_job_snapshot)

        moment = self._clock()
        verified_at = _format_utc(moment)

        try:
            self.db.commit_verified_archive(
                episode_id=episode_id,
                render_job_id=render_job_id,
                archive_id=archive_id,
                archive_path=str(package_result.final_path),
                manifest_path=str(package_result.manifest_path),
                manifest_sha256=package_result.manifest_sha256,
                verified_at=verified_at,
            )
        except ArchiveCommitError as exc:
            raise ArchiveVerifiedUnregisteredError(
                f"Archive package for episode {episode_id} (archive_id={archive_id}) independently verified "
                f"during recovery, but database registration failed: {exc} The package remains exactly as "
                f"it was; episode {episode_id} remains 'rendered'. Recovery may be retried.",
                episode_id=episode_id,
                archive_id=archive_id,
                archive_path=str(package_result.final_path),
                manifest_path=str(package_result.manifest_path),
                manifest_sha256=package_result.manifest_sha256,
            ) from exc

        logger.info(
            "Archive recovery registered: episode_id=%s archive_id=%s render_job_id=%s manifest_sha256=%s",
            episode_id,
            archive_id,
            render_job_id,
            package_result.manifest_sha256,
        )

        return ArchiveRecoveryResult(
            episode_id=episode_id,
            archive_id=archive_id,
            archive_path=package_result.final_path,
            manifest_sha256=package_result.manifest_sha256,
            render_job_id=render_job_id,
            classification=_RECOVERY_CLASSIFICATION_RECOVERED,
        )

    @staticmethod
    def _validate_recovery_archive_id(episode_id: str, archive_id: str) -> None:
        """Item 48: strict Archive Rev1 `archive_id` shape validation for
        caller-supplied (CLI/MCP) input -- rejects any value that could
        not possibly be a real `archive_id` before it ever becomes a
        filesystem path component, closing off path-traversal vectors
        (`..`, separators, an absolute/drive/UNC path) far more strictly
        than the generic path-component safety check
        `package.derive_final_package_path()` already applies defensively
        underneath this."""
        prefix = f"{episode_id}-{_ARCHIVE_ID_SCHEMA_TAG}-"
        suffix = archive_id[len(prefix) :] if isinstance(archive_id, str) and archive_id.startswith(prefix) else None
        if suffix is None or not _ARCHIVE_ID_SUFFIX_RE.match(suffix):
            raise ArchivePathError(
                f"archive_id {archive_id!r} is not a valid Archive Rev1 identifier for episode "
                f"{episode_id!r} (expected the shape {prefix}<12 lowercase hex characters>)."
            )

    def _read_recovery_metadata_json(self, final_path: Path, relative_path: str) -> dict:
        """Read one already-verified package's sealed metadata JSON file
        through the same safe-open primitive every other package read in
        this codebase uses (item 43) -- never a plain, unverified
        `Path.read_bytes()`/`read_text()`. Only ever called after
        `package.verify_archive_package()` has already proven the
        complete payload, including this exact file, matches the sealed
        manifest's own recorded size/SHA-256 -- this function does not
        re-derive that trust on its own; it reads bytes the caller has
        already established are exactly what was sealed."""
        target = final_path / "payload" / relative_path
        with integrity.open_stable_source(target) as (fh, size_bytes):
            data = fh.read()
        if len(data) != size_bytes:
            raise ArchiveRecoveryMetadataError(f"sealed recovery metadata size changed while reading: {target}")
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ArchiveRecoveryMetadataError(f"sealed recovery metadata is not valid JSON: {target}") from exc
        if not isinstance(parsed, dict):
            raise ArchiveRecoveryMetadataError(f"sealed recovery metadata is not a JSON object: {target}")
        return parsed

    def _read_recovery_episode_snapshot(self, final_path: Path, *, expected_episode_id: str) -> dict:
        snapshot = self._read_recovery_metadata_json(final_path, _METADATA_EPISODE_PATH)
        episode_id = snapshot.get("episode_id")
        status = snapshot.get("status")
        if not isinstance(episode_id, str) or not episode_id:
            raise ArchiveRecoveryMetadataError("sealed episode.json is missing a valid episode_id field")
        if episode_id != expected_episode_id:
            raise ArchiveRecoveryMetadataError(
                f"sealed episode.json episode_id {episode_id!r} does not match the package's own "
                f"manifest episode_id {expected_episode_id!r}"
            )
        if status != EpisodeStatus.RENDERED.value:
            raise ArchiveRecoveryMetadataError(
                f"sealed episode.json status {status!r} is not {EpisodeStatus.RENDERED.value!r}; a Rev1 "
                "package is only ever sealed for a pre-archive 'rendered' episode"
            )
        return snapshot

    def _read_recovery_render_job_snapshot(self, final_path: Path, *, expected_episode_id: str) -> dict:
        snapshot = self._read_recovery_metadata_json(final_path, _METADATA_RENDER_JOB_PATH)
        episode_id = snapshot.get("episode_id")
        render_job_id = snapshot.get("render_job_id")
        status = snapshot.get("status")
        if episode_id != expected_episode_id:
            raise ArchiveRecoveryMetadataError(
                f"sealed render_job.json episode_id {episode_id!r} does not match the package's own "
                f"manifest episode_id {expected_episode_id!r}"
            )
        if not isinstance(render_job_id, int) or isinstance(render_job_id, bool):
            raise ArchiveRecoveryMetadataError("sealed render_job.json is missing a valid render_job_id field")
        if status != RenderJobStatus.COMPLETE.value:
            raise ArchiveRecoveryMetadataError(
                f"sealed render_job.json status {status!r} is not {RenderJobStatus.COMPLETE.value!r}; only a "
                "completed render job is ever sealed as the selected render for a Rev1 package"
            )
        return snapshot

    def _validate_current_render_job_for_recovery(
        self, episode_id: str, render_job_id: int, render_job_snapshot: dict
    ) -> None:
        """Item 12: the sealed render-job snapshot is cross-checked
        against the *live* render_jobs row, not trusted alone -- a
        conflict here (the current DB disagreeing with what was sealed)
        fails closed rather than silently registering against a render
        job that no longer matches what the package actually preserved."""
        render_job = self.db.get_render_job_by_id(render_job_id)
        if render_job is None:
            raise ArchiveRecoveryConflictError(
                f"Episode {episode_id}: sealed render_job_id={render_job_id} no longer exists in the database."
            )
        if render_job.episode_id != episode_id:
            raise ArchiveRecoveryConflictError(
                f"Episode {episode_id}: sealed render_job_id={render_job_id} currently belongs to episode "
                f"{render_job.episode_id!r} in the database, not {episode_id!r}."
            )
        if render_job.status != RenderJobStatus.COMPLETE:
            raise ArchiveRecoveryConflictError(
                f"Episode {episode_id}: render job {render_job_id} has current status "
                f"{render_job.status.value!r}, not 'complete'."
            )
        identity_fields = {
            "output_path": render_job.output_path,
            "resolve_job_id": render_job.resolve_job_id,
            "project_name": render_job.project_name,
            "timeline_name": render_job.timeline_name,
            "preset_name": render_job.preset_name,
        }
        for field_name, current_value in identity_fields.items():
            sealed_value = render_job_snapshot.get(field_name)
            if sealed_value != current_value:
                raise ArchiveRecoveryConflictError(
                    f"Episode {episode_id}: render job {render_job_id}'s current {field_name}={current_value!r} "
                    f"does not match the sealed package's {field_name}={sealed_value!r}."
                )


def _find_inventory_file_by_absolute_path(inventory: SourceInventory, absolute_path: Path) -> InventoryFile | None:
    for f in inventory.files:
        if f.absolute_source_path == absolute_path:
            return f
    return None
