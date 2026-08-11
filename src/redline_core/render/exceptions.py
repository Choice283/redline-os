"""Exceptions raised by the Render Manager."""


class RenderError(Exception):
    """Base class for render-domain failures."""


class RenderPresetNotFoundError(RenderError):
    """No render preset with this name exists in config/render_presets.yaml."""


class RenderConfigurationError(RenderError):
    """A render preset exists but lacks approved data required to queue safely."""


class RenderJobNotFoundError(RenderError):
    """No render job with this ID exists in the database."""


class RenderOutputCollisionError(RenderError):
    """A render queue request would collide with an existing output or active job."""


class RenderPersistenceError(RenderError):
    """Resolve accepted a render job, but Redline could not persist it."""


class RenderReconciliationRequiredError(RenderError):
    """Resolve accepted a render job and compensation failed after DB persistence failed."""


class RenderTimelineNotRenderableError(RenderError):
    """The target timeline does not satisfy the preset's renderability requirements.

    Raised by the renderability preflight before any SQLite output claim or
    Resolve queue mutation (`LoadRenderPreset`, `SetRenderSettings`,
    `AddRenderJob`) is attempted.
    """


class RenderJobMissingResolveIdError(RenderError):
    """The Redline render job row has no `resolve_job_id`.

    Raised by `start_render()` before its start-specific
    `ResolveAdapter.start_render()` call (this does not claim Resolve has
    never been connected to at all -- application composition connects it
    unconditionally before CLI dispatch; it claims only that no
    start-specific mutation call has happened for this job): a job without
    a persisted Resolve job ID was never accepted by Resolve (or its
    acceptance was never confirmed), so there is no Resolve-side job to
    start.
    """


class RenderJobNotStartableError(RenderError):
    """The render job's current status does not permit starting a render.

    Raised by `start_render()` before its start-specific
    `ResolveAdapter.start_render()` call for any status other than
    `RenderJobStatus.QUEUED` — including a job already `RENDERING`, and
    every terminal status (`COMPLETE`, `FAILED`, `CANCELLED`) — and also
    for a `QUEUED` job whose persisted identity is not actually usable to
    start safely: a non-string, blank, or improperly-whitespaced
    `resolve_job_id`/`project_name`/`timeline_name`/`output_path`.
    """


class RenderStartPersistenceReconciliationRequiredError(RenderError):
    """Resolve has positively confirmed (via the adapter's own getter-only
    postcondition check) that the target render job reached `Rendering`,
    but Redline could not durably record that fact afterward: the guarded
    `QUEUED -> RENDERING` database transition raised, affected zero or more
    than one row, or the row could not be reloaded afterward.

    This is a split-brain condition, not an ordinary failure: Resolve may
    already be rendering the job while Redline's own database still shows
    (or no longer reliably shows) `QUEUED`. `RenderManager.start_render()`
    never attempts to compensate by calling `StopRendering()`, deleting the
    Resolve job, or invoking `ResolveAdapter.start_render()` again — doing
    so could affect a render that is already legitimately in progress.
    Manual, getter-only reconciliation of the database against Resolve's
    live queue state is required before this render job is touched again.
    """
