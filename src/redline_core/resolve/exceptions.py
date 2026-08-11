"""Exceptions raised by the Resolve adapter layer.

Keeping these separate from generic Python exceptions lets callers (Episode
Manager, MCP tool handlers) catch Resolve-specific failures and turn them
into clean, structured error responses instead of raw stack traces.
"""


class ResolveError(Exception):
    """Base class for all Resolve adapter errors."""


class ResolveConnectionError(ResolveError):
    """Could not connect to a running DaVinci Resolve Studio instance.

    Common causes: Resolve isn't running, it's the free (non-Studio) edition,
    RESOLVE_SCRIPT_API/RESOLVE_SCRIPT_LIB aren't set correctly, or scripting
    access is disabled in Resolve's preferences.
    """


class ProjectNotFoundError(ResolveError):
    """The requested project (e.g. the master template) does not exist."""


class ProjectAlreadyExistsError(ResolveError):
    """A project with this name already exists in the current database."""


class MediaImportError(ResolveError):
    """Raised when media cannot be imported into Resolve."""


class TimelineOperationError(ResolveError):
    """Raised when a Resolve timeline operation fails."""


class RenderJobError(ResolveError):
    """Something went wrong building or queuing a render job."""


class RenderQueueIdentityUnresolvedError(RenderJobError):
    """AddRenderJob() may have succeeded, but Redline could not prove the
    identity of exactly one newly queued Resolve job.

    Raised only for failures that occur after AddRenderJob() has returned
    something other than explicit False and no direct job ID was obtained
    from it — i.e. Resolve's queue state is genuinely uncertain, not just
    unreachable or misconfigured. Manual reconciliation may be required
    before retrying.
    """


class RenderQueueAcceptanceNotObservedError(RenderJobError):
    """AddRenderJob() returned an empty string, and Redline confirmed the
    render queue's job-ID multiset is unchanged: identical job IDs before
    and after, no new candidate, no unidentified item, and the after-phase
    snapshot itself succeeded.

    This is a stronger, more specific claim than
    RenderQueueIdentityUnresolvedError: it states that no evidence of an
    accepted job was found by job-ID comparison, not merely that identity
    is uncertain. Only job IDs are compared — other per-item queue metadata
    (e.g. target directory, custom name) is not inspected. Reserved for
    exactly this evidence shape; every other ambiguous outcome for an
    empty-string result (snapshot failure, unidentified item, multiple
    candidates) still raises RenderQueueIdentityUnresolvedError.
    """


class RenderStartReconciliationRequiredError(RenderJobError):
    """`StartRendering()` was invoked and its final effect on live Resolve
    state could not be proven safe or unsafe from the return value alone.

    Raised only once `ResolveScriptAdapter.start_render()` has actually
    called `StartRendering()` — never before. Covers every outcome where a
    getter-only reconciliation attempt (a bounded, non-mutating poll of
    `GetRenderJobStatus()`, reusing the same postcondition-wait pattern
    already established for the ordinary success path) could not positively
    confirm the target job reached `Rendering`:

    - `StartRendering()` itself raised an exception.
    - `StartRendering()` returned a value that is neither `True` nor `False`
      (a contract violation of the documented `--> Bool` return type).
    - `StartRendering()` returned `True`, but the bounded postcondition poll
      never observed `JobStatus == "Rendering"` within its attempt budget.

    An explicit `False` return is NOT included here — that is Resolve's own
    unambiguous rejection signal per its documented Bool contract, and stays
    a plain `RenderJobError`.

    This exception's live Resolve state is unproven, not merely "failed" —
    callers must never treat it as a safely-retryable ordinary failure.
    `StartRendering()` must not be invoked again for the same job until
    manual, getter-only reconciliation independently establishes the true
    state. `RenderManager.start_render()` deliberately does not catch or
    reword this exception: it propagates unchanged, and specifically
    performs no database write when it is raised, so the Redline render
    job's DB status stays exactly what it was before this call (`QUEUED`).
    """
