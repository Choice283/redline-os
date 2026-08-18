"""Degraded-source capture package construction: classify, capture, seal,
and atomically publish (Mission 1B-A2-2).

Mirrors ``redline_core.backup.package``'s proven shape deliberately (stage
-> self-verify -> atomic publish; a sealed manifest + SHA-256 sidecar;
never overwrite) rather than inventing a different pipeline for a
structurally similar problem -- but a degraded-source capture package is
never itself a Mission 1A backup, and the two are kept structurally
distinct throughout (see ``redline_core.restore.capture_paths`` for the
namespace/identity guarantees).

Every unsafe filesystem object (symlink, Windows junction, other reparse
point) encountered anywhere in this module is detected via the same
domain-neutral ``redline_core.fsutil.is_unsafe_link()`` Mission 1A and
1B-A1 already use, and is **never followed, never opened, and never
recursively inspected** -- only safe ``os.lstat()`` metadata is ever
recorded for one. This module never parses YAML, never validates config
*content*, and never attempts a SQLite Online Backup API snapshot: the
strong default this mission resolves the accepted architecture's one open
question with is to preserve the original live file's raw bytes as the
primary evidence, unconditionally, without risking a normalized copy
silently losing information about exactly what the damaged bytes were.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat as stat_module
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Callable

from redline_core import fsutil
from redline_core.config.loader import REQUIRED_FILES
from redline_core.restore.capture_exceptions import (
    CapturePackageCollisionError,
    CapturePublicationError,
    CaptureSealFailedError,
)
from redline_core.restore.capture_io import best_effort_capture_file
from redline_core.restore.capture_models import CaptureItemOutcome, CaptureItemRecord, CaptureResult, StatFingerprint
from redline_core.restore.capture_paths import build_capture_id, format_utc_iso, require_safe_capture_directory
from redline_core.restore.sidecar_classification import SidecarCondition, classify_sidecars

Clock = Callable[[], datetime]

MANIFEST_FILENAME = "capture_manifest.json"
MANIFEST_SHA256_FILENAME = "capture_manifest.sha256"
MARKER_FILENAME = "CAPTURE_COMPLETE"
STAGING_DIRNAME = ".staging_capture"
DEGRADED_SOURCE_CAPTURES_DIRNAME = "degraded_source_captures"
_DISTRIBUTION_NAME = "redline-os"

_DATABASE_ITEM_KEY = "database"
_CONFIG_DIRECTORY_ITEM_KEY = "config_directory"
_HASH_CHUNK_SIZE = 1024 * 1024  # 1 MiB; matches capture_io.py's own streaming chunk size.


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_write(path: Path, data: bytes) -> None:
    with path.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def _resolve_redline_os_version() -> str | None:
    try:
        return importlib_metadata.version(_DISTRIBUTION_NAME)
    except importlib_metadata.PackageNotFoundError:
        return None


def _resolve_python_version() -> str:
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


def _fingerprint_dict(fp: StatFingerprint | None) -> dict | None:
    if fp is None:
        return None
    return {"size": fp.size, "mtime_ns": fp.mtime_ns, "ino": fp.ino, "dev": fp.dev}


def _item_record_dict(record: CaptureItemRecord) -> dict:
    return {
        "item_key": record.item_key,
        "source_path": record.source_path,
        "outcome": record.outcome.value,
        "captured_relative_path": record.captured_relative_path,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "stat_fingerprint": _fingerprint_dict(record.stat_fingerprint),
        "unsafe_object": record.unsafe_object,
        "detail": record.detail,
    }


# -- shared classify-then-best-effort-capture dispatch for one expected-file item ---


def _fingerprint(st: os.stat_result) -> StatFingerprint:
    return StatFingerprint(
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        ino=getattr(st, "st_ino", None) or None,
        dev=getattr(st, "st_dev", None) or None,
    )


def _config_container_unusable_records(
    config_dir: Path,
    required_filenames: list[str],
    *,
    outcome: CaptureItemOutcome,
    container_detail: str,
    file_detail: str,
    container_fingerprint: StatFingerprint | None,
    unsafe_object: bool,
) -> tuple[CaptureItemRecord, tuple[CaptureItemRecord, ...]]:
    """Shared record-shape builder for every case where the config
    *container itself* cannot be trusted enough to enumerate or to build
    per-file paths from -- missing, uninspectable, unsafe, wrong type, or
    (Correction 2 below) found to have changed identity immediately after
    being enumerated. One real implementation of this four/five-way
    record shape, not one copy per case."""
    directory_record = CaptureItemRecord(
        item_key=_CONFIG_DIRECTORY_ITEM_KEY, source_path=str(config_dir), outcome=outcome,
        captured_relative_path=None, size_bytes=None, sha256=None, stat_fingerprint=container_fingerprint,
        unsafe_object=unsafe_object, detail=container_detail,
    )
    file_records = tuple(
        CaptureItemRecord(
            item_key=f"config:{filename}", source_path=str(config_dir / filename), outcome=outcome,
            captured_relative_path=None, size_bytes=None, sha256=None, stat_fingerprint=None,
            unsafe_object=unsafe_object, detail=file_detail,
        )
        for filename in required_filenames
    )
    return directory_record, file_records


def _describe_directory_shallow(path: Path) -> str:
    try:
        names = sorted(p.name for p in path.iterdir())
    except OSError as exc:
        return f"directory could not be listed: {exc}"
    return f"directory with {len(names)} entrie(s): {names}" if names else "empty directory"


def capture_regular_file_item(
    *, source_path: Path, destination_path: Path, item_key: str, relative_path: str
) -> CaptureItemRecord:
    """Classify then best-effort capture exactly one expected-regular-file
    item -- shared by the database slot, each of the six required config
    files, and each observed SQLite sidecar. Never follows an unsafe
    filesystem object; never recurses into or treats a directory's
    contents as candidate source bytes."""
    try:
        st = os.lstat(source_path)
    except FileNotFoundError:
        return CaptureItemRecord(
            item_key=item_key, source_path=str(source_path), outcome=CaptureItemOutcome.MISSING,
            captured_relative_path=None, size_bytes=None, sha256=None, stat_fingerprint=None,
            unsafe_object=False, detail=f"{source_path} does not exist.",
        )
    except OSError as exc:
        return CaptureItemRecord(
            item_key=item_key, source_path=str(source_path), outcome=CaptureItemOutcome.UNREADABLE,
            captured_relative_path=None, size_bytes=None, sha256=None, stat_fingerprint=None,
            unsafe_object=False, detail=f"cannot inspect {source_path}: {exc}",
        )

    if fsutil.is_unsafe_link(st):
        return CaptureItemRecord(
            item_key=item_key, source_path=str(source_path), outcome=CaptureItemOutcome.UNSAFE_OBJECT_RECORDED,
            captured_relative_path=None, size_bytes=None, sha256=None, stat_fingerprint=_fingerprint(st),
            unsafe_object=True,
            detail=f"{source_path} is a symlink, junction, or reparse point; never followed, never opened.",
        )

    if not stat_module.S_ISREG(st.st_mode):
        if stat_module.S_ISDIR(st.st_mode):
            detail = f"{source_path} is a directory, not a regular file -- {_describe_directory_shallow(source_path)}"
        else:
            detail = f"{source_path} exists but is neither a regular file nor a directory."
        return CaptureItemRecord(
            item_key=item_key, source_path=str(source_path), outcome=CaptureItemOutcome.WRONG_TYPE_RECORDED,
            captured_relative_path=None, size_bytes=None, sha256=None, stat_fingerprint=_fingerprint(st),
            unsafe_object=False, detail=detail,
        )

    outcome = best_effort_capture_file(source_path, destination_path, relative_path=relative_path)
    return CaptureItemRecord(
        item_key=item_key, source_path=str(source_path), outcome=outcome.outcome,
        captured_relative_path=outcome.captured_relative_path, size_bytes=outcome.size_bytes,
        sha256=outcome.sha256, stat_fingerprint=outcome.stat_fingerprint, unsafe_object=False, detail=outcome.detail,
    )


# -- database slot ------------------------------------------------------------------


def capture_database_slot(db_path: Path, payload_root: Path) -> CaptureItemRecord:
    """Best-effort capture of the live database, unconditionally -- even
    when the database side is independently classified HEALTHY, it is
    still captured as part of the one whole-system capture package (a
    healthy surviving component is still capture evidence, never a
    separate Mission 1A backup)."""
    destination = payload_root / "database" / db_path.name
    return capture_regular_file_item(
        source_path=db_path, destination_path=destination, item_key=_DATABASE_ITEM_KEY,
        relative_path=f"payload/database/{db_path.name}",
    )


# -- config slot --------------------------------------------------------------------


def capture_config_slot(
    config_dir: Path, payload_root: Path
) -> tuple[CaptureItemRecord | None, tuple[CaptureItemRecord, ...], tuple[str, ...]]:
    """Best-effort capture of the whole live config directory:
    unconditionally attempts each of the six required files, plus a safe,
    non-recursive directory inventory covering every entry actually
    present (explaining any unexpected config entry by name, never by
    content). Returns ``(config_directory_record, config_file_records,
    directory_inventory)`` -- ``config_directory_record`` is ``None``
    whenever ``config_dir`` is an ordinary, safe, enumerable directory
    (the normal case); it is populated only when the *container itself* is
    missing, unsafe, or the wrong type, in which case the six per-file
    records are also honestly recorded as unreachable rather than
    individually inspected."""
    required_filenames = sorted(REQUIRED_FILES.values())

    try:
        st = os.lstat(config_dir)
    except FileNotFoundError:
        directory_record, file_records = _config_container_unusable_records(
            config_dir, required_filenames, outcome=CaptureItemOutcome.MISSING,
            container_detail=f"{config_dir} does not exist.",
            file_detail="not individually inspected: the config directory itself does not exist.",
            container_fingerprint=None, unsafe_object=False,
        )
        return directory_record, file_records, ()

    except OSError as exc:
        directory_record, file_records = _config_container_unusable_records(
            config_dir, required_filenames, outcome=CaptureItemOutcome.UNREADABLE,
            container_detail=f"cannot inspect {config_dir}: {exc}",
            file_detail="not individually inspected: the config directory itself could not be inspected.",
            container_fingerprint=None, unsafe_object=False,
        )
        return directory_record, file_records, ()

    if fsutil.is_unsafe_link(st):
        directory_record, file_records = _config_container_unusable_records(
            config_dir, required_filenames, outcome=CaptureItemOutcome.UNSAFE_OBJECT_RECORDED,
            container_detail=f"{config_dir} is a symlink, junction, or reparse point; never followed, contents "
            "never enumerated.",
            file_detail="not individually inspected: the config directory itself is an unsafe filesystem object "
            "and was never enumerated.",
            container_fingerprint=_fingerprint(st), unsafe_object=True,
        )
        return directory_record, file_records, ()

    if not stat_module.S_ISDIR(st.st_mode):
        directory_record, file_records = _config_container_unusable_records(
            config_dir, required_filenames, outcome=CaptureItemOutcome.WRONG_TYPE_RECORDED,
            container_detail=f"{config_dir} exists but is not a directory.",
            file_detail="not individually inspected: the config path is not a directory.",
            container_fingerprint=_fingerprint(st), unsafe_object=False,
        )
        return directory_record, file_records, ()

    # Ordinary, safe, enumerable directory at the pre-enumeration check --
    # the normal case.
    try:
        inventory = tuple(sorted(p.name for p in config_dir.iterdir()))
    except OSError:
        inventory = ()

    # Mission 1B-A2-2 safety correction (Correction 2): re-observe the
    # container itself immediately after enumerating it, before treating
    # that enumeration -- or any per-file path built from config_dir -- as
    # trustworthy. iterdir() is a path-based primitive with no way to
    # refuse following a reparse point substituted at config_dir between
    # the lstat() safety check above and iterdir() actually running: the
    # substituted target's contents would otherwise be silently
    # inventoried as though they were config_dir's own, and each of the
    # six required-file captures below would silently read through the
    # substitution too (every path built as config_dir / filename passes
    # through it as an ordinary intermediate path segment, which no
    # per-file lstat() can detect on its own). This recheck proves the
    # directory iterdir() actually walked is still the same safe object
    # the pre-enumeration lstat() observed before either the inventory or
    # any per-file capture is trusted; on any mismatch, the inventory is
    # discarded and the six file slots are recorded as not individually
    # inspected, exactly like the pre-enumeration failure branches above.
    try:
        st_reobserved = os.lstat(config_dir)
    except FileNotFoundError:
        directory_record, file_records = _config_container_unusable_records(
            config_dir, required_filenames, outcome=CaptureItemOutcome.MISSING,
            container_detail=f"{config_dir} disappeared immediately after being enumerated.",
            file_detail="not individually inspected: the config directory disappeared immediately after being "
            "enumerated.",
            container_fingerprint=None, unsafe_object=False,
        )
        return directory_record, file_records, ()
    except OSError as exc:
        directory_record, file_records = _config_container_unusable_records(
            config_dir, required_filenames, outcome=CaptureItemOutcome.UNREADABLE,
            container_detail=f"cannot re-inspect {config_dir} immediately after enumeration: {exc}",
            file_detail="not individually inspected: the config directory could not be re-inspected immediately "
            "after enumeration.",
            container_fingerprint=None, unsafe_object=False,
        )
        return directory_record, file_records, ()

    if fsutil.is_unsafe_link(st_reobserved):
        directory_record, file_records = _config_container_unusable_records(
            config_dir, required_filenames, outcome=CaptureItemOutcome.UNSAFE_OBJECT_RECORDED,
            container_detail=f"{config_dir} is a symlink, junction, or reparse point observed immediately after "
            "enumeration (possible substitution between the pre-enumeration safety check and iterdir()); the "
            "just-obtained enumeration is discarded and never treated as this directory's inventory.",
            file_detail="not individually inspected: the config directory was found to be an unsafe filesystem "
            "object immediately after enumeration.",
            container_fingerprint=_fingerprint(st_reobserved), unsafe_object=True,
        )
        return directory_record, file_records, ()

    if not stat_module.S_ISDIR(st_reobserved.st_mode) or _fingerprint(st) != _fingerprint(st_reobserved):
        directory_record, file_records = _config_container_unusable_records(
            config_dir, required_filenames, outcome=CaptureItemOutcome.CHANGED_DURING_CAPTURE,
            container_detail=f"{config_dir} identity changed between the pre-enumeration safety check and "
            f"iterdir() (before={_fingerprint(st)}, after={_fingerprint(st_reobserved)}); the just-obtained "
            "enumeration is discarded and never treated as this directory's inventory.",
            file_detail="not individually inspected: the config directory's identity changed during enumeration.",
            container_fingerprint=_fingerprint(st_reobserved), unsafe_object=False,
        )
        return directory_record, file_records, ()

    file_records = tuple(
        capture_regular_file_item(
            source_path=config_dir / filename,
            destination_path=payload_root / "config" / filename,
            item_key=f"config:{filename}",
            relative_path=f"payload/config/{filename}",
        )
        for filename in required_filenames
    )
    return None, file_records, inventory


# -- sidecars ------------------------------------------------------------------------


def capture_sidecars(db_path: Path, payload_root: Path) -> tuple[CaptureItemRecord, ...]:
    """Best-effort capture of every SQLite sidecar observed next to
    ``db_path`` (``-journal``/``-wal``/``-shm``). Sidecars are captured
    purely as evidence: never merged into the database slot, never
    treated as proof of quiescence, and -- like every item in this
    module -- never moved, renamed, or deleted.

    Mission 1B-A2-2 safety correction (Correction 4): presence is
    determined here via the shared, lstat-based
    ``redline_core.restore.sidecar_classification.classify_sidecars()``
    primitive (Mission 1B-A2-3-Prep2) -- never through the locked Mission
    1B-A1 ``redline_core.restore.sidecar.find_present_sidecars()``
    (unmodified, still correct for its own fail-closed "must not proceed"
    purpose). That function's presence check is ``Path.exists()``, which
    follows symlinks/junctions and returns ``False`` for a dangling
    reparse object -- so it cannot even see, let alone truthfully record,
    a substituted/dangling unsafe sidecar. A suffix is skipped here only
    when the shared classifier reports ``SidecarCondition.MISSING`` (the
    exact case ``find_present_sidecars()`` already reported correctly, so
    the ordinary "no sidecars" outcome is unchanged); every other
    condition -- safe regular file, wrong type, unsafe symlink/junction/
    reparse, or a *dangling* unsafe symlink/junction/reparse whose target
    does not even exist -- is still handed to the shared
    ``capture_regular_file_item()`` dispatch, which independently
    re-derives the identical lstat-first classification immediately before
    acting (never follows, never opens, never treats an unsafe/dangling
    sidecar as the database) -- a TOCTOU-safety re-check, not a second,
    divergent source of classification truth: ``classify_sidecars()`` is
    the one place the MISSING/SAFE_REGULAR/WRONG_TYPE/UNSAFE distinction
    is actually decided; Mission 1B-A2-1 recovery planning consumes the
    exact same primitive (``recovery_planning.build_recovery_plan()``)."""
    assessments = classify_sidecars(db_path)
    records = []
    for assessment in assessments:
        if assessment.condition is SidecarCondition.MISSING:
            continue  # genuinely absent -- matches find_present_sidecars()'s own correct behavior
        sidecar_path = Path(str(db_path) + assessment.suffix)
        records.append(
            capture_regular_file_item(
                source_path=sidecar_path,
                destination_path=payload_root / "sidecars" / f"{db_path.name}{assessment.suffix}",
                item_key=f"sidecar:{assessment.suffix}",
                relative_path=f"payload/sidecars/{db_path.name}{assessment.suffix}",
            )
        )
    return tuple(records)


# -- staging / manifest / seal / publish ---------------------------------------------


@dataclass(frozen=True, slots=True)
class StagedCapture:
    """A fully built, sealed, self-consistent degraded-source capture
    package still sitting in ``.staging_capture/`` -- not yet published to
    ``degraded_source_captures/``."""

    staging_dir: Path
    manifest: dict
    manifest_sha256: str
    capture_id: str
    database: CaptureItemRecord
    config_directory: CaptureItemRecord | None
    config_files: tuple[CaptureItemRecord, ...]
    config_directory_inventory: tuple[str, ...]
    sidecars: tuple[CaptureItemRecord, ...]


def _expected_relative_path_for_missing_record(record: dict, manifest: dict) -> str | None:
    """The relative payload path a no-payload record's ``item_key`` *would*
    have used had it been captured. Mirrors exactly the ``relative_path=``
    construction ``capture_database_slot()``/``capture_config_slot()``/
    ``capture_sidecars()`` already use, so a stray payload file left at
    that location (by a prior bug, or a hostile actor) can be caught as
    contradicting a legitimate no-payload outcome even though the
    manifest itself never named it. Returns ``None`` (skip the check)
    for a record shape this cannot resolve -- e.g. the config-directory
    container marker, which is never itself a payload file, or a
    hand-built/malformed record missing the fields this needs."""
    item_key = record.get("item_key")
    if item_key == _DATABASE_ITEM_KEY:
        source_path = record.get("source_path")
        return f"payload/database/{Path(source_path).name}" if source_path else None
    if item_key == _CONFIG_DIRECTORY_ITEM_KEY:
        return None
    if isinstance(item_key, str) and item_key.startswith("config:"):
        return f"payload/config/{item_key.split(':', 1)[1]}"
    if isinstance(item_key, str) and item_key.startswith("sidecar:"):
        db_source = (manifest.get("database") or {}).get("source_path")
        return f"payload/sidecars/{Path(db_source).name}{item_key.split(':', 1)[1]}" if db_source else None
    return None


def _verify_staged_capture_self_consistency(staging_dir: Path, manifest: dict) -> None:
    """The package-level integrity checks this module performs before
    sealing -- a self-consistency check of the staged *package*, never a
    re-proof of source trustworthiness (each item's own outcome already
    carries that). Raises ``CaptureSealFailedError`` -- a hard stop, no
    override -- on any mismatch.

    Mission 1B-A2-2 safety correction (Correction 5) strengthens this
    beyond the original existence/size-only check:

    - a record with a ``captured_relative_path`` must name a payload file
      that actually exists, is a *safe regular* object (lstat-checked --
      never a symlink/junction/reparse point standing in for the payload),
      matches the manifest-recorded size, and -- when the manifest
      recorded one -- matches the manifest-recorded SHA-256 exactly; a
      hash mismatch means the staged payload was tampered with or
      corrupted after capture, and ``CAPTURED_VERIFIED``/
      ``CAPTURED_UNVERIFIED`` payload can never pass sealing in that state.
    - a record with no ``captured_relative_path`` (``MISSING``/
      ``UNSAFE_OBJECT_RECORDED``/``WRONG_TYPE_RECORDED``/an ``UNREADABLE``
      with no partial bytes) must have no filesystem object sitting at the
      location it *would* have used -- a stray payload file there would
      silently contradict the manifest's own "nothing was captured" claim.
    - the manifest sidecar itself is independently re-verified: the
      manifest bytes are re-read from disk, re-hashed, and compared
      against the ``.sha256`` sidecar file also just written, catching a
      filesystem-level corruption or race between the two writes.
    """
    all_records = [manifest["database"]] + (
        [manifest["config"]["directory"]] if manifest["config"]["directory"] is not None else []
    ) + manifest["config"]["files"] + manifest["sidecars"]

    for record in all_records:
        relative = record.get("captured_relative_path")
        if relative is None:
            expected = _expected_relative_path_for_missing_record(record, manifest)
            if expected is not None and os.path.lexists(staging_dir / expected):
                raise CaptureSealFailedError(
                    f"staged capture {manifest.get('capture_id')!r} records {record.get('item_key')!r} as "
                    f"{record.get('outcome')!r} with no captured payload, but a filesystem object unexpectedly "
                    f"exists at the payload location it would have used ({staging_dir / expected}); refusing to "
                    "seal a self-contradictory package."
                )
            continue

        captured_path = staging_dir / relative
        try:
            st = os.lstat(captured_path)
        except FileNotFoundError:
            raise CaptureSealFailedError(
                f"staged capture {manifest['capture_id']!r} manifest names {relative!r} as captured, but no such "
                f"file exists in the staging package: {captured_path}"
            )
        except OSError as exc:
            raise CaptureSealFailedError(
                f"staged capture {manifest.get('capture_id')!r} item {relative!r} could not be inspected while "
                f"sealing ({captured_path}): {exc}"
            ) from exc
        if fsutil.is_unsafe_link(st) or not stat_module.S_ISREG(st.st_mode):
            raise CaptureSealFailedError(
                f"staged capture {manifest.get('capture_id')!r} item {relative!r} is not a safe regular payload "
                f"file ({captured_path}); refusing to seal a package whose own payload is unsafe."
            )
        actual_size = st.st_size
        if record.get("size_bytes") is not None and actual_size != record["size_bytes"]:
            raise CaptureSealFailedError(
                f"staged capture {manifest['capture_id']!r} item {relative!r} is {actual_size} bytes on disk but "
                f"the manifest records {record['size_bytes']}; refusing to seal an inconsistent package."
            )
        if record.get("sha256") is not None:
            actual_sha256 = _sha256_of_file(captured_path)
            if actual_sha256 != record["sha256"]:
                raise CaptureSealFailedError(
                    f"staged capture {manifest.get('capture_id')!r} item {relative!r} sha256 does not match the "
                    f"manifest-recorded hash ({captured_path}); refusing to seal a tampered or corrupted package."
                )

    manifest_path = staging_dir / MANIFEST_FILENAME
    manifest_sha256_path = staging_dir / MANIFEST_SHA256_FILENAME
    if manifest_path.is_file() and manifest_sha256_path.is_file():
        actual_manifest_sha256 = _sha256_of_file(manifest_path)
        recorded_manifest_sha256 = manifest_sha256_path.read_text(encoding="ascii").strip()
        if actual_manifest_sha256 != recorded_manifest_sha256:
            raise CaptureSealFailedError(
                f"staged capture {manifest.get('capture_id')!r} manifest sha256 sidecar does not match the "
                "manifest bytes actually on disk; refusing to seal a tampered or corrupted package."
            )


def build_staged_capture(
    *, db_path: Path, config_dir: Path, staging_parent: Path, clock: Clock, reason: str | None,
    database_assessment: dict, config_assessment: dict,
) -> StagedCapture:
    """Build one complete, sealed, self-consistent degraded-source capture
    package inside a fresh staging directory under ``staging_parent``
    (``<capture_root>/.staging_capture/``). Every capture-*package*-level
    failure (write failure, seal failure) raises a typed
    ``CaptureError``; every per-item outcome is recorded truthfully in the
    manifest instead, regardless of how damaged, unsafe, missing, or
    unstable that one item turned out to be. ``database_assessment``/
    ``config_assessment`` are the caller-supplied Mission 1B-A2-1
    ``SourceSideAssessment`` dicts, recorded verbatim as reference
    context -- this function never calls A2-1's classifier itself, so
    there is exactly one real classification implementation in this
    repository, never a second one drifting alongside it.
    """
    staging_dir = staging_parent / uuid.uuid4().hex
    staging_dir.mkdir(parents=True)  # collision-refusing: exist_ok=False (the default) raises if this exact name exists
    # Mission 1B-A2-2 safety correction (Correction 3): prove the object
    # actually created above is a safe, real directory before writing a
    # single payload byte into it.
    require_safe_capture_directory(staging_dir, description="capture staging attempt directory", must_exist=True)
    payload_root = staging_dir / "payload"

    database_record = capture_database_slot(db_path, payload_root)
    config_directory_record, config_file_records, config_inventory = capture_config_slot(config_dir, payload_root)
    sidecar_records = capture_sidecars(db_path, payload_root)

    total_bytes = sum(r.size_bytes or 0 for r in [database_record, *config_file_records, *sidecar_records])

    moment = clock()
    capture_id = build_capture_id(moment)

    manifest = {
        "schema_tag": "dsc1",
        "capture_id": capture_id,
        "created_at": format_utc_iso(moment),
        "reason": reason,
        "source": {
            "redline_db_path": str(db_path),
            "redline_config_dir": str(config_dir),
            "redline_os_version": _resolve_redline_os_version(),
            "python_version": _resolve_python_version(),
        },
        "database": {**_item_record_dict(database_record), "supplied_assessment": database_assessment},
        "config": {
            "directory": _item_record_dict(config_directory_record) if config_directory_record else None,
            "files": [_item_record_dict(r) for r in config_file_records],
            "directory_inventory": list(config_inventory),
            "supplied_assessment": config_assessment,
        },
        "sidecars": [_item_record_dict(r) for r in sidecar_records],
        "total_bytes_captured": total_bytes,
        "capture_package_status": "SEALED",
    }

    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_path = staging_dir / MANIFEST_FILENAME
    try:
        _fsync_write(manifest_path, manifest_bytes)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        _fsync_write(staging_dir / MANIFEST_SHA256_FILENAME, manifest_sha256.encode("ascii"))
    except OSError as exc:
        raise CaptureSealFailedError(f"could not write capture manifest for {capture_id!r}: {exc}") from exc

    _verify_staged_capture_self_consistency(staging_dir, manifest)

    try:
        (staging_dir / MARKER_FILENAME).write_bytes(b"")
    except OSError as exc:
        raise CaptureSealFailedError(f"could not write completion marker for capture {capture_id!r}: {exc}") from exc

    return StagedCapture(
        staging_dir=staging_dir, manifest=manifest, manifest_sha256=manifest_sha256, capture_id=capture_id,
        database=database_record, config_directory=config_directory_record, config_files=config_file_records,
        config_directory_inventory=config_inventory, sidecars=sidecar_records,
    )


def publish_staged_capture(staged: StagedCapture, *, capture_root: Path) -> Path:
    """Atomically publish the sealed staging package to
    ``<capture_root>/degraded_source_captures/<capture_id>/``. Never
    overwrites: the rename itself fails atomically if the destination
    already exists (``os.rename()`` raises rather than replacing), so
    there is no separate check-then-act race window -- mirrors Mission
    1A's own ``publish_staged_backup()`` exactly."""
    if not (staged.staging_dir / MARKER_FILENAME).is_file():
        raise CaptureSealFailedError(f"staged capture {staged.capture_id!r} has no completion marker; refusing to publish.")

    final_parent = capture_root / DEGRADED_SOURCE_CAPTURES_DIRNAME
    require_safe_capture_directory(final_parent, description="degraded_source_captures root", must_exist=False)
    final_parent.mkdir(parents=True, exist_ok=True)
    # Mission 1B-A2-2 safety correction (Correction 3): revalidate what
    # mkdir(..., exist_ok=True) actually left in place -- it silently
    # accepts an already-existing symlink/junction pointing at a real
    # directory without creating anything.
    require_safe_capture_directory(final_parent, description="degraded_source_captures root", must_exist=True)
    final_dir = final_parent / staged.capture_id

    # Mission 1B-A2-2 safety correction (Correction 3): lstat, not
    # Path.exists() -- exists() follows symlinks and returns False for a
    # dangling/unsafe reparse object at this exact path, silently missing
    # exactly the collision case that matters most: an attacker-planted
    # dangling symlink at the final capture-ID location. lstat() succeeds
    # for that object (proving something already occupies the name)
    # without ever following it.
    try:
        os.lstat(final_dir)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise CapturePublicationError(f"cannot inspect capture destination {final_dir} before publishing: {exc}") from exc
    else:
        raise CapturePackageCollisionError(f"a degraded-source capture already exists at {final_dir}; refusing to overwrite.")

    try:
        os.rename(staged.staging_dir, final_dir)
    except FileExistsError as exc:
        raise CapturePackageCollisionError(f"a degraded-source capture already exists at {final_dir}; refusing to overwrite.") from exc
    except OSError as exc:
        raise CapturePublicationError(f"could not publish staged capture to {final_dir}: {exc}") from exc

    return final_dir
