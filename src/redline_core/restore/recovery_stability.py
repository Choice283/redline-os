"""Read-only target-level stability checking (Mission 1B-A2-3).

One reusable primitive, used identically by ``PRE_MUTATION_STABILITY``
(before the first disposition), each mutation-bound recheck immediately
before one disposition ``os.rename()``, immediately before
``DB_REPLACE_INTENT``/``CONFIG_RENAME_ASIDE_INTENT``, and
``FINAL_STABILITY`` (after all completed dispositions, before
replacement): prove a live filesystem target still matches either its
fresh, this-attempt capture-derived baseline, or an expected-missing state
a previously verified disposition produced. Strictly read-only -- never
follows an unsafe object, never moves, renames, or deletes anything.

Reuses ``redline_core.restore.capture_models.CaptureItemRecord``/
``StatFingerprint`` directly rather than inventing a second baseline
representation -- an ``ExpectedTargetState`` is built from exactly the
per-item evidence a fresh Mission 1B-A2-2 capture already recorded.

Evidence-strength policy, precisely:

- ``CAPTURED_VERIFIED`` / ``CAPTURED_UNVERIFIED`` (both always carry a
  trustworthy source-observed ``sha256``/``size_bytes`` -- see
  ``capture_io.best_effort_capture_file()``) -- compared by live
  hash+size against the captured hash+size.
- ``UNREADABLE`` -- **never** treated as a byte-hash source (a partial
  read's ``sha256`` is not a full-file hash). If it carries a complete
  ``StatFingerprint``, compared by type/safety/size/mtime_ns/ino/dev only.
  If it carries no fingerprint at all, this is insufficient evidence to
  prove stability at all -- always a mismatch.
- ``UNSAFE_OBJECT_RECORDED`` / ``WRONG_TYPE_RECORDED`` -- compared by
  type/safety/fingerprint only (never a byte hash; none was ever
  attempted for these outcomes).
- ``MISSING`` -- the live target must still be missing.
- ``CHANGED_DURING_CAPTURE`` -- never reaches this module. It is an
  unconditional, earlier terminal hard stop (see
  ``redline_core.restore.recovery_execution``); building an
  ``ExpectedTargetState`` from one is a programming error, not a
  recoverable mismatch.
"""
from __future__ import annotations

import os
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path

from redline_core import fsutil
from redline_core.restore.capture_models import CaptureItemOutcome, CaptureItemRecord, StatFingerprint

_HASH_TRUSTWORTHY_OUTCOMES = (CaptureItemOutcome.CAPTURED_VERIFIED, CaptureItemOutcome.CAPTURED_UNVERIFIED)
_FINGERPRINT_ONLY_OUTCOMES = (CaptureItemOutcome.UNSAFE_OBJECT_RECORDED, CaptureItemOutcome.WRONG_TYPE_RECORDED)


@dataclass(frozen=True, slots=True)
class ExpectedTargetState:
    """What one target's stability check requires to currently be true.

    ``kind``:
      ``"missing"``               -- the live path must not exist.
      ``"hash"``                  -- the live path must be a safe regular
                                      file whose freshly recomputed
                                      sha256/size match exactly.
      ``"fingerprint"``           -- the live path's safety/regular-file
                                      classification and stat fingerprint
                                      (size/mtime_ns/ino/dev) must match
                                      exactly; bytes are never compared.
      ``"insufficient_evidence"`` -- this attempt has no trustworthy
                                      evidence to compare against at all;
                                      always a mismatch.
    """

    kind: str
    expected_sha256: str | None = None
    expected_size: int | None = None
    expected_fingerprint: StatFingerprint | None = None
    expected_unsafe: bool = False
    expected_regular: bool = False
    detail: str = ""


@dataclass(frozen=True, slots=True)
class TargetStabilityResult:
    target_key: str
    path: Path
    confirmed: bool
    detail: str


def expected_state_missing(*, detail: str) -> ExpectedTargetState:
    """The target must currently not exist -- used both for a
    capture-baseline item that was itself ``MISSING``, and for a target a
    previously verified disposition has already moved aside."""
    return ExpectedTargetState(kind="missing", detail=detail)


def expected_state_from_capture_record(record: CaptureItemRecord, *, expected_regular: bool | None = None) -> ExpectedTargetState:
    """Build the expected state for one target directly from its fresh,
    this-attempt ``CaptureItemRecord`` baseline. Never called for a
    ``CHANGED_DURING_CAPTURE`` record -- that outcome is an earlier,
    unconditional terminal hard stop (see ``recovery_execution.py``) and
    never reaches this function.

    ``expected_regular`` only affects the ``WRONG_TYPE_RECORDED``
    fingerprint-only case, where a ``CaptureItemRecord`` alone cannot say
    whether the object occupying the path is a regular file or something
    else -- a database's own WRONG_TYPE_RECORDED always means "not a
    regular file" (the default, ``False``), while a config *container*'s
    WRONG_TYPE_RECORDED means "not a directory", which the Windows
    disposition proof establishes is most commonly a regular file; the
    caller who knows which slot this baseline is for supplies the correct
    value explicitly rather than this function guessing from the outcome
    alone."""
    if record.outcome is CaptureItemOutcome.CHANGED_DURING_CAPTURE:
        raise ValueError(
            f"expected_state_from_capture_record() called for a CHANGED_DURING_CAPTURE record "
            f"({record.item_key!r}); CHANGED_DURING_CAPTURE must be handled as an earlier, unconditional "
            "terminal hard stop, never compared as a stability baseline."
        )

    if record.outcome in _HASH_TRUSTWORTHY_OUTCOMES and record.sha256 is not None:
        return ExpectedTargetState(
            kind="hash",
            expected_sha256=record.sha256,
            expected_size=record.size_bytes,
            detail=f"trustworthy fresh capture hash for {record.item_key!r} ({record.outcome.value})",
        )

    if record.outcome is CaptureItemOutcome.MISSING:
        return expected_state_missing(detail=f"{record.item_key!r} was MISSING at fresh capture time")

    if record.outcome is CaptureItemOutcome.UNREADABLE:
        if record.stat_fingerprint is not None:
            return ExpectedTargetState(
                kind="fingerprint",
                expected_fingerprint=record.stat_fingerprint,
                expected_unsafe=False,
                expected_regular=True,
                detail=f"UNREADABLE {record.item_key!r} with a complete trustworthy fingerprint",
            )
        return ExpectedTargetState(
            kind="insufficient_evidence",
            detail=f"UNREADABLE {record.item_key!r} carries no trustworthy fingerprint evidence at all",
        )

    if record.outcome in _FINGERPRINT_ONLY_OUTCOMES:
        if record.stat_fingerprint is None:
            return ExpectedTargetState(
                kind="insufficient_evidence",
                detail=f"{record.outcome.value} {record.item_key!r} carries no fingerprint evidence",
            )
        return ExpectedTargetState(
            kind="fingerprint",
            expected_fingerprint=record.stat_fingerprint,
            expected_unsafe=(record.outcome is CaptureItemOutcome.UNSAFE_OBJECT_RECORDED),
            expected_regular=expected_regular if expected_regular is not None else False,
            detail=f"{record.outcome.value} {record.item_key!r} fingerprint-only evidence",
        )

    return ExpectedTargetState(
        kind="insufficient_evidence",
        detail=f"{record.item_key!r} outcome {record.outcome.value!r} carries no usable stability evidence",
    )


def _fingerprint(st: os.stat_result) -> StatFingerprint:
    return StatFingerprint(
        size=st.st_size, mtime_ns=st.st_mtime_ns, ino=getattr(st, "st_ino", None) or None, dev=getattr(st, "st_dev", None) or None
    )


def check_target_stability(path: Path, expected: ExpectedTargetState, *, target_key: str) -> TargetStabilityResult:
    """The one reusable, read-only stability primitive. Never mutates
    anything: only ``os.lstat()`` and, for hash-mode evidence, a stable
    streaming re-hash (``redline_core.fsutil.hash_stable_file()``)."""
    path = Path(path)

    if expected.kind == "insufficient_evidence":
        return TargetStabilityResult(
            target_key=target_key, path=path, confirmed=False,
            detail=f"insufficient trustworthy evidence to prove stability: {expected.detail}",
        )

    try:
        st = os.lstat(path)
    except FileNotFoundError:
        if expected.kind == "missing":
            return TargetStabilityResult(target_key=target_key, path=path, confirmed=True, detail=f"still missing: {expected.detail}")
        return TargetStabilityResult(
            target_key=target_key, path=path, confirmed=False,
            detail=f"expected present ({expected.detail}) but {path} is now missing",
        )
    except OSError as exc:
        return TargetStabilityResult(target_key=target_key, path=path, confirmed=False, detail=f"cannot inspect {path}: {exc}")

    if expected.kind == "missing":
        return TargetStabilityResult(
            target_key=target_key, path=path, confirmed=False, detail=f"expected missing ({expected.detail}) but {path} now exists"
        )

    is_unsafe = fsutil.is_unsafe_link(st)
    is_regular = stat_module.S_ISREG(st.st_mode)

    if expected.kind == "hash":
        if is_unsafe or not is_regular:
            return TargetStabilityResult(
                target_key=target_key, path=path, confirmed=False,
                detail=f"expected a safe regular file ({expected.detail}) but type/safety changed at {path}",
            )
        try:
            sha256, size = fsutil.hash_stable_file(path)
        except fsutil.SafeFileError as exc:
            return TargetStabilityResult(
                target_key=target_key, path=path, confirmed=False, detail=f"could not stably re-hash {path} for stability proof: {exc}"
            )
        if sha256 != expected.expected_sha256 or size != expected.expected_size:
            return TargetStabilityResult(
                target_key=target_key, path=path, confirmed=False, detail=f"byte content of {path} drifted from the fresh capture baseline"
            )
        return TargetStabilityResult(target_key=target_key, path=path, confirmed=True, detail=f"hash/size match the fresh capture baseline for {path}")

    # expected.kind == "fingerprint"
    if is_unsafe != expected.expected_unsafe or is_regular != expected.expected_regular:
        return TargetStabilityResult(
            target_key=target_key, path=path, confirmed=False,
            detail=f"safety/type classification of {path} drifted from the capture-era baseline ({expected.detail})",
        )
    live_fp = _fingerprint(st)
    if live_fp != expected.expected_fingerprint:
        return TargetStabilityResult(
            target_key=target_key, path=path, confirmed=False,
            detail=f"fingerprint (size/mtime_ns/ino/dev) of {path} drifted from the capture-era baseline ({expected.detail})",
        )
    return TargetStabilityResult(target_key=target_key, path=path, confirmed=True, detail=f"fingerprint matches the capture-era baseline for {path} ({expected.detail})")


def check_config_inventory_stability(config_dir: Path, expected_inventory: tuple[str, ...]) -> TargetStabilityResult:
    """A fresh, shallow (non-recursive) directory inventory of
    ``config_dir`` must equal ``expected_inventory`` exactly. Only
    meaningful when the capture recorded a real inventory (a normal, safe,
    enumerable config directory at capture time) -- the caller is
    responsible for skipping this check when the capture's own
    ``config_directory_inventory`` is empty because the container itself
    was abnormal (missing/unsafe/wrong-type), never because it was
    genuinely an empty directory versus not inspected at all."""
    config_dir = Path(config_dir)
    try:
        live_inventory = tuple(sorted(p.name for p in config_dir.iterdir()))
    except OSError as exc:
        return TargetStabilityResult(
            target_key="config_directory_inventory", path=config_dir, confirmed=False,
            detail=f"could not enumerate {config_dir} for inventory stability: {exc}",
        )
    if live_inventory != expected_inventory:
        return TargetStabilityResult(
            target_key="config_directory_inventory", path=config_dir, confirmed=False,
            detail=f"config directory inventory drifted: expected {list(expected_inventory)}, got {list(live_inventory)}",
        )
    return TargetStabilityResult(
        target_key="config_directory_inventory", path=config_dir, confirmed=True, detail="config directory inventory matches the fresh capture baseline"
    )
