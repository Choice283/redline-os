"""Exceptions raised by the Render Manager."""


class RenderPresetNotFoundError(Exception):
    """No render preset with this name exists in config/render_presets.yaml."""


class RenderJobNotFoundError(Exception):
    """No render job with this ID exists in the database."""
