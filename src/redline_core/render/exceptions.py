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
