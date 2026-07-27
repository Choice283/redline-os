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
