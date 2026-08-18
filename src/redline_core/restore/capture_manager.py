"""Degraded-source capture orchestration (Mission 1B-A2-2).

``build_degraded_source_capture()`` is the one public entry point this
subsystem exposes: given the live ``db_path``/``config_dir`` and the
Mission 1B-A2-1 ``SourceSideAssessment`` already computed for each side
(reused, never recomputed -- see
``redline_core.restore.recovery_classification``), it resolves the shared
Mission 1A ``paths.backup_path`` root, then stages, seals, and atomically
publishes one whole-system degraded-source capture package.

This module performs **no destructive recovery work of any kind**: no
sidecar disposition, no wrong-type live-object disposition, no staging for
Restore, no database or config replacement, and no Restore/recovery
execution journal integration. It is preservation/evidence infrastructure
only, intended for a future, separately authorized Mission 1B-A2-3 to
orchestrate as one step of an eventual recovery attempt -- deliberately
exposed as a plain, programmatic function rather than a CLI command (see
this module's own docstring note below on that boundary decision).

No CLI command is registered anywhere for this capability. A destructive
CLI command would let an operator trigger evidence preservation activity
disconnected from the escalated-authorization ceremony a real recovery
attempt requires (per the accepted Mission 1B-A2 architecture); the
correct integration point for that ceremony is Mission 1B-A2-3, not this
mission. A future read-only capture-planning CLI, if ever desired, would
need its own separate justification and authorization -- not added here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from redline_core.restore.capture_exceptions import CaptureError, CaptureSystemWriteFailedError
from redline_core.restore.capture_models import CaptureResult
from redline_core.restore.capture_package import (
    STAGING_DIRNAME,
    build_staged_capture,
    publish_staged_capture,
)
from redline_core.restore.capture_paths import require_safe_capture_directory, resolve_capture_root
from redline_core.restore.recovery_models import SourceSideAssessment

Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _assessment_to_dict(assessment: SourceSideAssessment) -> dict:
    return {
        "condition": assessment.condition.value,
        "feasibility": assessment.feasibility.value,
        "blocking_reason": assessment.blocking_reason,
        "capture_required": assessment.capture_required,
        "disposition_required": assessment.disposition_required,
        "disposition_description": assessment.disposition_description,
        "details": list(assessment.details),
    }


def build_degraded_source_capture(
    *,
    db_path: Path,
    config_dir: Path,
    backup_path: str | Path | None,
    database_assessment: SourceSideAssessment,
    config_assessment: SourceSideAssessment,
    reason: str | None = None,
    clock: Clock = _default_clock,
) -> CaptureResult:
    """Build, seal, and atomically publish one whole-system degraded-source
    capture package covering the current live database and configuration
    state.

    Always captures **both** sides, regardless of whether one is
    independently classified ``HEALTHY`` by ``database_assessment``/
    ``config_assessment`` -- Mission 1A remains all-or-nothing, so when the
    normal fresh Mission 1A pre-restore backup cannot be made, this one
    capture package represents the whole observed system, never merely the
    broken component (a healthy surviving side is still capture evidence,
    never a separate, partial Mission 1A backup).

    ``database_assessment``/``config_assessment`` are required, caller-
    supplied ``redline_core.restore.recovery_models.SourceSideAssessment``
    values from Mission 1B-A2-1's own classifier -- this function never
    calls ``classify_database_source()``/``classify_config_source()``
    itself, so there is exactly one real HEALTHY/DEGRADED/MISSING
    classification implementation in this repository. They are recorded
    verbatim in the sealed manifest as reference context; the actual,
    independently fresh per-item outcomes this function itself observes
    during capture (which may legitimately differ, e.g. if the source
    changed between classification and capture -- that drift is exactly
    what ``CHANGED_DURING_CAPTURE`` and the other per-item outcomes exist
    to reveal) are what the manifest's ``database``/``config`` sections
    otherwise describe.

    Every capture-*package*-level failure (destination unsafe/
    unconfigured, collision, write failure, seal failure, publication
    failure) raises a typed ``CaptureError`` subclass -- an unconditional
    hard stop with **no proceed-anyway override**. Per-item read/
    inspection problems are never exceptions; they are truthfully recorded
    ``CaptureItemRecord`` outcomes in the sealed manifest, and a package
    built entirely of ``UNREADABLE``/``MISSING``/``UNSAFE_OBJECT_RECORDED``
    items can still seal successfully.
    """
    db_path = Path(db_path)
    config_dir = Path(config_dir)

    capture_root = resolve_capture_root(backup_path=backup_path, db_path=db_path, config_dir=config_dir)
    require_safe_capture_directory(capture_root, description="configured degraded-source capture root (backup_path)", must_exist=False)

    staging_parent = capture_root / STAGING_DIRNAME
    require_safe_capture_directory(staging_parent, description="capture staging root (.staging_capture)", must_exist=False)

    try:
        staging_parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CaptureSystemWriteFailedError(f"could not create capture staging root {staging_parent}: {exc}") from exc

    # Mission 1B-A2-2 safety correction (Correction 3): immediately
    # revalidate both directories the mkdir() call above just
    # created/confirmed -- Path.mkdir(..., exist_ok=True) accepts an
    # already-existing symlink/junction pointing at a real directory
    # without ever creating anything, silently writing everything that
    # follows into the substituted target. This closes that window
    # immediately before either directory is used for anything further.
    require_safe_capture_directory(capture_root, description="configured degraded-source capture root (backup_path)", must_exist=True)
    require_safe_capture_directory(staging_parent, description="capture staging root (.staging_capture)", must_exist=True)

    try:
        staged = build_staged_capture(
            db_path=db_path,
            config_dir=config_dir,
            staging_parent=staging_parent,
            clock=clock,
            reason=reason,
            database_assessment=_assessment_to_dict(database_assessment),
            config_assessment=_assessment_to_dict(config_assessment),
        )
        final_dir = publish_staged_capture(staged, capture_root=capture_root)
    except CaptureError:
        raise
    except OSError as exc:
        raise CaptureSystemWriteFailedError(f"unexpected filesystem failure building the capture package: {exc}") from exc

    total_bytes = staged.manifest["total_bytes_captured"]
    return CaptureResult(
        capture_id=staged.capture_id,
        capture_path=final_dir,
        manifest_path=final_dir / "capture_manifest.json",
        manifest_sha256=staged.manifest_sha256,
        created_at=staged.manifest["created_at"],
        reason=reason,
        database=staged.database,
        config_directory=staged.config_directory,
        config_files=staged.config_files,
        config_directory_inventory=staged.config_directory_inventory,
        sidecars=staged.sidecars,
        total_bytes_captured=total_bytes,
    )
