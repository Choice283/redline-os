"""Scope evaluation for Asset Registry reconciliation planning.

Implements Phase 3 Slice 4 ("Scope evaluation"): deterministic evaluation of
whether one ``AssetRegistryRecord`` was expected to be observable under one
``ObservationScope``.

This module does not resolve raw paths, touch the filesystem, build reusable
indexes across many records, perform matching, classify reconciliation
outcomes, or create findings/actions/plan items. Those responsibilities
belong to later Phase 3 slices (``indexes.py``, ``matching.py``,
``classification.py``, ``findings.py``, ``actions.py``, ``planner.py``).

Model gaps handled conservatively rather than invented:

- ``ObservationFilters.included_media_types`` and ``included_extensions``
  describe fields that exist on ``AssetObservation`` but not on
  ``AssetRegistryRecord``. The approved Phase 1 registry record carries no
  media type or extension field, so these two inclusion dimensions cannot be
  evaluated against a registry record. Non-empty filters therefore fail closed
  for the path channel, rather than deriving an extension from a path string
  (which the approved documents do not define).
- ``ObservationRootScope.access_failures`` is an unstructured
  ``tuple[str, ...]`` with no per-subtree keying in the approved model, so it
  cannot be matched to a specific record's subtree the way
  ``inaccessible_subtrees`` can. Any non-empty ``access_failures`` on the
  selected root conservatively blocks the path channel, consistent with the
  architecture's general bias toward never concluding expected-observability
  when access trouble was reported and cannot be ruled out for this record.
- The approved model has no field representing a per-explicit-Asset-ID
  exclusion distinct from a per-ID access failure, so explicit-channel
  exclusion is not implemented as a separate state.
"""
from __future__ import annotations

from dataclasses import dataclass

from redline_core.asset.models import AssetRegistryRecord
from redline_core.asset.reconciliation.enums import ScopeCompleteness
from redline_core.asset.reconciliation.models import (
    ObservationFilters,
    ObservationRootScope,
    ObservationScope,
)

_PATH_CHANNEL = "path"
_EXPLICIT_CHANNEL = "explicit_asset_id"


@dataclass(frozen=True, slots=True)
class ObservabilityDecision:
    """Immutable per-record observability facts for one declared scope.

    Produced by :func:`evaluate_record_observability`. Carries only bounded,
    already-safe tuples and primitives -- no raw paths, no repository
    handles, no cached filesystem state.
    """

    asset_id: str
    applicable_channels: tuple[str, ...]
    complete_channels: tuple[str, ...]
    blocked_channels: tuple[str, ...]
    exclusion_reasons: tuple[str, ...]
    access_failure_reasons: tuple[str, ...]
    expected_observable: bool
    missing_eligible: bool
    evidence_facts: tuple[str, ...]


def _normalized_key_components(value: str) -> tuple[str, ...]:
    """Return the component tuple for an already-normalized key string.

    Mirrors ``ObservationRootScope.canonical_key()`` exactly so root keys,
    inaccessible/excluded subtree keys, and record paths compare on
    identical, already-normalized terms. Performs no filesystem access, no
    symlink handling, and no raw path resolution.
    """
    return tuple(part for part in value.replace("\\", "/").split("/") if part)


def _is_component_prefix(prefix: tuple[str, ...], components: tuple[str, ...]) -> bool:
    """Return True when ``prefix`` is an exact leading-component match of ``components``.

    Component-based, not a raw string prefix check: ``("assets", "a")`` does
    not match ``("assets", "ab", "file.mov")`` even though the corresponding
    raw strings would share a string prefix.
    """
    return len(prefix) <= len(components) and components[: len(prefix)] == prefix


def _containing_roots(
    record_components: tuple[str, ...],
    scope: ObservationScope,
) -> tuple[ObservationRootScope, ...]:
    """Return every declared root whose normalized key contains the record's path."""
    return tuple(
        root
        for root in scope.roots
        if _is_component_prefix(root.canonical_key(), record_components)
    )


def _most_specific_root(candidates: tuple[ObservationRootScope, ...]) -> ObservationRootScope:
    """Return the candidate root with the greatest normalized component depth.

    Approved validation (``validation.py``) already rejects ambiguous
    equal-depth roots with conflicting declarations before scope evaluation
    ever runs, so a single max reduction is sufficient -- no sort is needed
    merely to pick one root.
    """
    return max(candidates, key=lambda root: len(root.canonical_key()))


@dataclass(frozen=True, slots=True)
class _FilterOutcome:
    """Internal filter evaluation result: exclusion state and inclusion state."""

    excluded: bool
    inclusion_satisfied: bool


def _filter_result(
    record: AssetRegistryRecord,
    inclusion_filters: ObservationFilters,
    exclusion_filters: ObservationFilters,
    record_components: tuple[str, ...],
) -> _FilterOutcome:
    """Evaluate inclusion/exclusion filters for one record against one scope.

    Dimensions AND together; values within one dimension OR together. Only
    dimensions with a corresponding ``AssetRegistryRecord`` field are
    evaluated: ``included_asset_ids`` against ``record.asset_id`` and
    ``included_lifecycle_states`` against ``record.lifecycle``.
    ``included_media_types``/``included_extensions`` have no registry-side
    field to compare against and therefore fail closed for the path channel.
    ``excluded_normalized_subtrees`` is evaluated against the record's
    normalized path via component-prefix match.
    """
    excluded = any(
        _is_component_prefix(_normalized_key_components(subtree), record_components)
        for subtree in exclusion_filters.excluded_normalized_subtrees
    )

    inclusion_satisfied = True
    if inclusion_filters.included_media_types:
        inclusion_satisfied = False
    if inclusion_filters.included_extensions:
        inclusion_satisfied = False
    if inclusion_filters.included_asset_ids:
        inclusion_satisfied = inclusion_satisfied and record.asset_id in inclusion_filters.included_asset_ids
    if inclusion_filters.included_lifecycle_states:
        inclusion_satisfied = (
            inclusion_satisfied and record.lifecycle in inclusion_filters.included_lifecycle_states
        )

    return _FilterOutcome(excluded=excluded, inclusion_satisfied=inclusion_satisfied)


@dataclass(frozen=True, slots=True)
class _ChannelOutcome:
    """Internal per-channel evaluation outcome before assembly into a decision."""

    name: str
    applicable: bool
    complete: bool
    blocked: bool
    excluded: bool
    exclusion_reason: str | None
    access_failure_reason: str | None
    evidence_facts: tuple[str, ...]


_NOT_APPLICABLE_OUTCOME_FIELDS = (False, False, False, False, None, None, ())


def _evaluate_path_channel(record: AssetRegistryRecord, scope: ObservationScope) -> _ChannelOutcome:
    """Evaluate the path channel independently of the explicit-ID channel."""
    path = record.normalized_resolved_path
    if not path:
        return _ChannelOutcome(_PATH_CHANNEL, *_NOT_APPLICABLE_OUTCOME_FIELDS)

    record_components = _normalized_key_components(path)
    candidates = _containing_roots(record_components, scope)
    if not candidates:
        return _ChannelOutcome(_PATH_CHANNEL, *_NOT_APPLICABLE_OUTCOME_FIELDS)

    selected_root = _most_specific_root(candidates)

    inaccessible = any(
        _is_component_prefix(_normalized_key_components(subtree), record_components)
        for subtree in selected_root.inaccessible_subtrees
    )
    root_access_failure = bool(selected_root.access_failures)
    if inaccessible or root_access_failure:
        reason = "path_inaccessible_subtree" if inaccessible else "path_root_access_failure"
        return _ChannelOutcome(
            _PATH_CHANNEL, True, False, True, False, None, reason, ("path:applicable", "path:blocked")
        )

    filter_outcome = _filter_result(
        record, scope.inclusion_filters, scope.exclusion_filters, record_components
    )
    if filter_outcome.excluded:
        return _ChannelOutcome(
            _PATH_CHANNEL,
            True,
            False,
            False,
            True,
            "path_excluded_subtree",
            None,
            ("path:applicable", "path:excluded"),
        )
    if not filter_outcome.inclusion_satisfied:
        return _ChannelOutcome(
            _PATH_CHANNEL, True, False, False, False, None, None, ("path:applicable", "path:filtered_out")
        )

    complete = selected_root.completeness is ScopeCompleteness.COMPLETE
    return _ChannelOutcome(
        _PATH_CHANNEL,
        True,
        complete,
        False,
        False,
        None,
        None,
        ("path:applicable", "path:complete" if complete else "path:incomplete"),
    )


def _evaluate_explicit_channel(record: AssetRegistryRecord, scope: ObservationScope) -> _ChannelOutcome:
    """Evaluate the explicit Asset-ID channel independently of the path channel."""
    if record.asset_id not in scope.explicit_asset_ids:
        return _ChannelOutcome(_EXPLICIT_CHANNEL, *_NOT_APPLICABLE_OUTCOME_FIELDS)

    failure = next(
        (item for item in scope.explicit_asset_id_failures if item.asset_id == record.asset_id),
        None,
    )
    if failure is not None:
        return _ChannelOutcome(
            _EXPLICIT_CHANNEL,
            True,
            False,
            True,
            False,
            None,
            "explicit_access_failure",
            ("explicit_asset_id:applicable", "explicit_asset_id:blocked"),
        )

    complete = scope.explicit_asset_id_completeness is ScopeCompleteness.COMPLETE
    return _ChannelOutcome(
        _EXPLICIT_CHANNEL,
        True,
        complete,
        False,
        False,
        None,
        None,
        (
            "explicit_asset_id:applicable",
            "explicit_asset_id:complete" if complete else "explicit_asset_id:incomplete",
        ),
    )


def evaluate_record_observability(
    record: AssetRegistryRecord,
    scope: ObservationScope,
) -> ObservabilityDecision:
    """Return the deterministic observability decision for one record and scope.

    Combines an independent path channel and explicit-Asset-ID channel. A
    failure, incompleteness, exclusion, or access-failure block in one
    channel never cancels a complete, unblocked, unexcluded result from the
    other. Performs no path resolution, filesystem access, index
    construction, matching, classification, or plan assembly. Does not
    mutate ``record`` or ``scope``.
    """
    channels = (
        _evaluate_path_channel(record, scope),
        _evaluate_explicit_channel(record, scope),
    )

    applicable_channels = tuple(channel.name for channel in channels if channel.applicable)
    complete_channels = tuple(
        channel.name
        for channel in channels
        if channel.applicable and channel.complete and not channel.blocked and not channel.excluded
    )
    blocked_channels = tuple(channel.name for channel in channels if channel.blocked)
    exclusion_reasons = tuple(
        sorted({channel.exclusion_reason for channel in channels if channel.exclusion_reason})
    )
    access_failure_reasons = tuple(
        sorted({channel.access_failure_reason for channel in channels if channel.access_failure_reason})
    )
    evidence_facts = tuple(sorted({fact for channel in channels for fact in channel.evidence_facts}))

    expected_observable = bool(complete_channels)

    return ObservabilityDecision(
        asset_id=record.asset_id,
        applicable_channels=applicable_channels,
        complete_channels=complete_channels,
        blocked_channels=blocked_channels,
        exclusion_reasons=exclusion_reasons,
        access_failure_reasons=access_failure_reasons,
        expected_observable=expected_observable,
        missing_eligible=expected_observable,
        evidence_facts=evidence_facts,
    )
