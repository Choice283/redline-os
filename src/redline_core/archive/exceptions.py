"""Exceptions raised by the Archive Manager and the Rev1 filesystem
integrity engine (redline_core.archive.integrity)."""


class ArchiveError(Exception):
    """Generic archive operation failure (missing folder, bad destination, etc.)."""


class EpisodeAlreadyArchivedError(Exception):
    """This episode already has an archive record."""


class ArchivePathError(ArchiveError):
    """A source root or discovered filesystem object failed path/root
    safety validation: missing, not resolvable, wrong type (e.g. a file
    supplied where a directory root is required), or unreadable."""


class ArchiveUnsafeFilesystemObjectError(ArchiveError):
    """A filesystem object was rejected outright because it is not a plain
    regular file or directory: a symlink, a Windows junction/reparse
    point, or any other special object (named pipe, device, socket, etc.).
    Archive Rev1's policy rejects every one of these unconditionally,
    regardless of what a link points to."""


class ArchiveSourceChangedError(ArchiveError):
    """The source tree or a source file did not remain stable during
    inventory/hashing: a file's stat identity changed between the
    before-hash and after-hash observation, or a final tree-reconciliation
    pass found the file/directory set had changed since the initial walk.
    No trusted hash or inventory is ever returned when this is raised."""


class ArchiveInventoryError(ArchiveError):
    """An inventory-level integrity failure not covered by a more specific
    exception above -- currently: two entries whose relative paths collide
    once normalized (case-insensitive, since Archive Rev1 targets a
    Windows production filesystem regardless of the OS building the
    inventory)."""


class ArchivePackageError(ArchiveError):
    """Base class for Archive Rev1 package-construction failures (Phase 15
    Mission 15D): staging allocation, copy I/O, completeness verification,
    manifest sealing, and atomic publication. Raised directly only for a
    generic/defensive failure that does not fit one of the more specific
    subclasses below; callers should prefer catching a specific subclass
    where one applies."""


class ArchiveDestinationCollisionError(ArchivePackageError):
    """The final archive destination (or, in one defensive case, a staging
    allocation) already exists. Archive Rev1 never overwrites, merges,
    deletes, or repairs an existing destination -- every attempt uses a
    distinct staging identity, and both the pre-copy check and the
    immediately-pre-rename recheck fail closed rather than replace
    anything already there."""


class ArchiveCopyVerificationError(ArchivePackageError):
    """A just-copied file's destination content does not match its
    verified source: destination SHA-256 or size differs from the
    inventory (and re-verified post-copy source) values. No package is
    ever published with a file that failed this check."""


class ArchivePackageVerificationError(ArchivePackageError):
    """An independent re-enumeration of the staging payload -- run once
    right after copying, and again on the fully sealed package immediately
    before publication -- found a discrepancy: a missing or unexpected
    file/directory, a hash/size mismatch, a missing manifest/sidecar/
    completion marker, or a manifest whose sidecar hash no longer matches
    its on-disk bytes (e.g. tampering after sealing)."""


class ArchivePublicationError(ArchivePackageError):
    """Atomic publication (staging directory -> final destination rename)
    failed for a reason other than a destination collision caught by the
    immediately-pre-rename recheck (that raises
    ArchiveDestinationCollisionError instead). Staging is left in place
    for forensic inspection; nothing is overwritten."""


class ArchiveEligibilityError(ArchiveError):
    """The episode is not eligible for Archive Rev1 orchestration (Phase
    15 Mission 15E), for a reason unrelated to render-job selection: the
    episode does not exist in a 'rendered' state, has no working folder
    on disk, has an active assembly claim (Mission 15A's no-active-claim
    invariant), has an active (claiming/queued/rendering) render job, or
    the selected render job's output does not resolve inside the episode
    workspace. Raised before any package staging or copy begins."""


class ArchiveRenderSelectionError(ArchiveError):
    """A render job could not be resolved for archiving: no render job
    for the episode is 'complete', more than one 'complete' render job
    exists and no explicit render_job_id was supplied to resolve the
    ambiguity, an explicitly supplied render_job_id does not exist / does
    not belong to the episode / is not 'complete', or the selected
    render job's recorded output_path is missing on disk. Archive Rev1
    never guesses a render job on the caller's behalf."""


class ArchiveLegacyRecordError(ArchiveError):
    """The episode already has an `archives` row, but it is a pre-Rev1
    legacy record (archive_schema_version == 0 / archive_state ==
    'legacy'), not a verified Rev1 archive. Mission 15E does not
    reclassify a legacy row as Rev1, does not build a new package over
    it, and does not fabricate Rev1 metadata for it -- expanding
    reconciliation behavior for legacy rows is a later mission's
    concern."""


class ArchiveVerifiedUnregisteredError(ArchiveError):
    """A filesystem archive package was built, verified, and atomically
    published successfully, but `Database.commit_verified_archive()`
    subsequently failed -- so no committed `archives` row exists for it.
    The episode remains 'rendered' (never marked 'archived'), the source
    workspace is untouched, and the verified final package is left
    exactly where it was published; nothing is deleted, overwritten, or
    moved to reconcile this state. This is the approved
    'VERIFIED_UNREGISTERED' boundary condition -- not an `archive_state`
    DB value, since no `archives` row exists to hold one. Also raised by
    `create_archive()` itself when a retry attempt finds an
    already-published, still-verifying package at the canonical
    destination its `archive_id` would target (Phase 15 Mission 15H) --
    never overwritten or rebuilt over. Carries the verified package's own
    identity so `ArchiveManager.recover_archive(episode_id,
    archive_id=...)` (Mission 15H) can register it without rediscovering
    it from scratch."""

    def __init__(
        self,
        message: str,
        *,
        episode_id: str,
        archive_id: str,
        archive_path: str,
        manifest_path: str,
        manifest_sha256: str,
    ) -> None:
        super().__init__(message)
        self.episode_id = episode_id
        self.archive_id = archive_id
        self.archive_path = archive_path
        self.manifest_path = manifest_path
        self.manifest_sha256 = manifest_sha256


class ArchiveNotFoundError(ArchiveError):
    """`ArchiveManager.verify_archive()` (Phase 15 Mission 15F) found no
    committed `archives` row for the requested episode_id -- there is
    nothing to verify. Deliberately distinct from `EpisodeNotFoundError`
    (the episode itself may exist and simply have never been archived) and
    from `ArchiveVerifiedUnregisteredError` (a verified package that
    exists on disk with no DB row is a different, Mission 15H recovery
    concern -- `verify_archive()` never scans the archive root looking for
    one; it only ever reads the `archives` table)."""


class ArchiveManifestMismatchError(ArchiveError):
    """`ArchiveManager.verify_archive()` (Phase 15 Mission 15F) found that
    the committed `archives` row and the actually-verified filesystem
    package disagree on identity: the row's `manifest_sha256` does not
    match the package's actual, freshly-verified manifest SHA-256, or the
    row's `manifest_path` does not match the package's actual manifest
    location. The filesystem package itself may be perfectly
    self-consistent (see `ArchivePackageVerificationError` for that
    failure mode) -- this is specifically a DB-vs-filesystem divergence,
    never repaired automatically."""


class ArchiveSupplementCopyError(ArchivePackageError):
    """A Mission 15G package supplement could not be staged: a
    file-backed supplement's source changed since it was planned
    (mirrors `ArchiveSourceChangedError` for ordinary artifacts), a
    just-copied/just-written supplement's destination content does not
    match its planned fingerprint (mirrors `ArchiveCopyVerificationError`),
    or a supplement is otherwise inconsistent with the sealed manifest.
    No package is ever published with a supplement that failed this
    check."""


class ArchiveEvidenceConfigurationError(ArchiveError):
    """Archive Manager Rev1 cannot establish the authoritative evidence
    source for this episode: `config.paths.evidence_path` is not set at
    all (Phase 15 Mission 15G.1 narrow correction). A missing evidence
    authority is not the same thing as an authoritative zero-evidence
    result -- an episode directory that legitimately does not exist
    under a *configured, validated* evidence root is a valid, ordinary
    zero-evidence archive (no exception); the absence of any configured
    root at all is a configuration failure and blocks `create_archive()`
    entirely, before any `ArchivePackagePlan` construction, package
    staging, publication, or database commit. Deliberately not
    `ArchivePathError` -- there is no path to even evaluate yet; this is
    a configuration-completeness failure, not a filesystem-safety one.
    Once `evidence_path` is configured, a missing or unsafe root reuses
    the existing `ArchivePathError`/`ArchiveUnsafeFilesystemObjectError`
    filesystem-safety exceptions unchanged -- this exception exists only
    for the "no authority configured at all" state."""


class ArchiveEvidenceIdentityConflictError(ArchiveError):
    """A JSON evidence file under an episode's authoritative evidence
    directory (Phase 15 Mission 15G.1) carries a top-level `episode_id`
    field that disagrees with the episode the evidence directory itself
    belongs to. The directory boundary is still the authority (see
    `redline_core.archive.evidence`'s module docstring) -- this is not a
    second, competing ownership rule -- but an internally contradictory
    file (correct directory, wrong embedded identity) is never silently
    preserved or rewritten; it fails closed instead. Malformed/unparsable
    JSON, or JSON with no `episode_id` field at all, does not raise this
    -- it is treated as opaque evidence and preserved as-is."""


class ArchiveManifestProvenanceError(ArchiveError):
    """The episode manifest/media content required for a complete archive
    could not be resolved at archive time (Phase 15 Mission 15E.2): the
    workspace has canonical manifest provenance content that is missing,
    malformed, uses an unsupported schema, or whose recorded SHA-256 does
    not match the actual canonical manifest bytes; a validated media entry
    names an unrecognized source_root or resolves outside its approved
    root; a referenced media file is missing or fails Mission 15C's safe
    regular-file checks; there is no canonical provenance and no explicit
    legacy `manifest_path` fallback was supplied; or an explicit legacy
    `manifest_path` fallback was supplied but does not match this
    episode's existing canonical build provenance (the caller cannot
    override an episode's authoritative build provenance). Never guessed
    from the current working directory, episode ID, or either approved
    root -- always resolved from persisted, verifiable evidence, or not
    resolved at all."""


class ArchiveRecoveryError(ArchiveError):
    """Base class for Phase 15 Mission 15H recovery failures --
    `ArchiveManager.recover_archive()` registering an already-published,
    independently-verified final package that a prior `create_archive()`
    call left in the `VERIFIED_UNREGISTERED` state. Raised directly only
    for a generic/defensive failure that does not fit one of the more
    specific subclasses below; callers should prefer catching a specific
    subclass where one applies. Recovery reuses every existing filesystem-
    integrity exception (`ArchivePathError`, `ArchiveUnsafeFilesystemObjectError`,
    `ArchivePackageVerificationError`, `ArchiveManifestMismatchError`,
    `ArchiveLegacyRecordError`) unchanged wherever their existing meaning
    already applies -- this hierarchy exists only for recovery-specific
    failure modes those exceptions cannot precisely describe."""


class ArchiveRecoveryNotFoundError(ArchiveRecoveryError):
    """No final package exists at all at the canonical path
    `<archive_root>/episodes/<episode_id>/<archive_id>/` derived from the
    caller's explicit `episode_id`/`archive_id`. Mission 15H never scans
    the archive root for candidates -- an explicit, wrong, or already-
    consumed `archive_id` simply has nothing to recover."""


class ArchiveRecoveryConflictError(ArchiveRecoveryError):
    """The verified final package's own sealed identity/metadata
    disagrees with current, authoritative database state in a way
    recovery must never silently resolve: an `archives` row already
    exists for the episode but does not exactly correspond to the package
    being recovered (different `archive_id`/`archive_path`/`manifest_sha256`/
    `render_job_id`); the episode's current status is not `'rendered'`
    (the precondition a fresh recovery registration requires -- an
    already-`archived` episode whose existing row *does* exactly match is
    the separate, non-error `already_registered` classification, not this
    exception); or the sealed `render_job.json` snapshot's identity-
    critical fields (episode ownership, status, output path, Resolve job
    ID, project/timeline identity, preset) disagree with the current,
    live `render_jobs` row for that ID. Recovery never overwrites, repairs,
    or reconciles a conflict -- it fails closed and leaves the package and
    every DB row exactly as they were."""


class ArchiveRecoveryMetadataError(ArchiveRecoveryError):
    """The final package independently verified (its bytes/hashes/manifest
    structure are all self-consistent), but its sealed
    `payload/metadata/episode.json`/`render_job.json` restore-metadata
    (Phase 15 Mission 15G) is missing, structurally malformed, or
    internally inconsistent with the package it is sealed inside (e.g. the
    snapshot's own `episode_id` does not match the package's manifest
    `episode_id`, or the packaged pre-archive `status` is not `'rendered'`)
    -- generic package integrity is not the same guarantee as "this
    package's sealed registration context is usable," and recovery
    requires both before any database mutation."""
