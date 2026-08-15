"""Redline OS Control Room V0 — read-only local Projects instrument panel.

Serves a single Projects screen showing Redline OS: live local Git truth
composed with version-controlled semantic project state. No mutation
routes exist. Binds to 127.0.0.1 by default -- not exposed to the LAN.

Run it with:
    python -m control_room.app                  # http://127.0.0.1:8765
    python -m control_room.app --port 9000
    redline-control-room                          # once installed

Requires the optional 'control_room' extra: pip install -e ".[control_room]"
FastAPI/uvicorn are imported lazily (see _import_fastapi()/main()) so that
merely importing this module -- e.g. to read REDLINE_CONTROL_ROOM_ROOT
semantics or resolve paths in a test -- never requires them, and running
the installed `redline-control-room` script without the extra installed
fails with one clear message instead of a raw ModuleNotFoundError
traceback (Codex review Finding 2).
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from redline_core.logging.setup import configure_logging

from control_room.models import ProjectSnapshot
from control_room.project_registry import ProjectRegistry, RegistryError
from control_room.project_status_service import ProjectNotFoundError, ProjectStatusService
from control_room.state_reader import StateReader

logger = logging.getLogger("redline_os.control_room.app")

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765

# src/control_room/app.py -> parents[0]=control_room, [1]=src, [2]=repo root.
# For an editable dev install this *is* the real Redline OS checkout,
# regardless of the process's current working directory. For a
# non-editable (built wheel) install this resolves somewhere inside
# site-packages, which correctly has no config/control_room/projects.yaml
# -- REDLINE_CONTROL_ROOM_ROOT must be set explicitly in that case. Either
# way, the process's CWD is never consulted, so launching the installed
# `redline-control-room` script from an unrelated directory can never
# silently reinterpret that directory as the Redline OS project root
# (Codex review Finding 3).
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_DEFAULT_REGISTRY_RELATIVE_PATH = Path("config") / "control_room" / "projects.yaml"


def _resolve_base_dir(base_dir: str | Path | None) -> Path:
    """The deterministic anchor for registry/repository/state_file
    resolution, in priority order:

      1. an explicit `base_dir` argument (e.g. passed by a test or caller)
      2. the REDLINE_CONTROL_ROOM_ROOT environment variable -- the
         supported override for a real installed (non-editable) deployment,
         or for pointing an editable checkout's Control Room at a
         *different* Redline OS repository than the one it was installed
         from
      3. `_PACKAGE_ROOT` -- where this installed `control_room` package's
         own source lives on disk

    The process's current working directory is never used as a fallback.
    """
    if base_dir is not None:
        return Path(base_dir)
    env_root = os.environ.get("REDLINE_CONTROL_ROOM_ROOT")
    if env_root:
        return Path(env_root)
    return _PACKAGE_ROOT


def _resolve_registry_path(registry_path: str | Path | None, base_dir: Path) -> Path:
    """Resolve the project registry path. An explicit argument or the
    REDLINE_CONTROL_ROOM_REGISTRY environment variable may be absolute (used
    as-is) or relative (resolved against `base_dir`, never against CWD)."""
    if registry_path is not None:
        value = Path(registry_path)
    else:
        env_registry = os.environ.get("REDLINE_CONTROL_ROOM_REGISTRY")
        value = Path(env_registry) if env_registry else _DEFAULT_REGISTRY_RELATIVE_PATH
    return value if value.is_absolute() else (base_dir / value)


def build_service(
    registry_path: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> ProjectStatusService:
    resolved_base_dir = _resolve_base_dir(base_dir)
    registry = ProjectRegistry(_resolve_registry_path(registry_path, resolved_base_dir), base_dir=resolved_base_dir)
    return ProjectStatusService(registry, state_reader=StateReader())


def _import_fastapi():
    """Deferred import of FastAPI/Starlette pieces, so importing
    control_room.app itself never requires the optional 'control_room'
    extra -- only actually building or running the app does."""
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise ImportError(
            "The 'fastapi' package is required to run Control Room. Install it with: "
            "pip install -e '.[control_room]'"
        ) from exc
    return FastAPI, HTTPException, FileResponse, StaticFiles


def create_app(service: ProjectStatusService | None = None):
    FastAPI, HTTPException, FileResponse, StaticFiles = _import_fastapi()

    service = service or build_service()
    app = FastAPI(title="Redline OS Control Room", version="0.1.0")
    app.state.service = service

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/api/projects", response_model=list[ProjectSnapshot])
    def list_projects():
        try:
            return app.state.service.list_snapshots()
        except RegistryError as exc:
            logger.error("control room /api/projects failed: %s", exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}", response_model=ProjectSnapshot)
    def get_project(project_id: str):
        try:
            return app.state.service.get_snapshot(project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RegistryError as exc:
            logger.error("control room /api/projects/%s failed: %s", project_id, exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Redline OS Control Room (read-only, local-only).")
    parser.add_argument("--host", default=_DEFAULT_HOST, help=f"Bind address (default: {_DEFAULT_HOST}).")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help=f"Bind port (default: {_DEFAULT_PORT}).")
    args = parser.parse_args()

    configure_logging(
        log_dir=os.environ.get("REDLINE_LOG_DIR", "./logs"),
        level=os.environ.get("REDLINE_LOG_LEVEL", "INFO"),
    )
    logger.info("Starting Redline OS Control Room on %s:%s", args.host, args.port)

    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "The 'uvicorn' package is required to run Control Room. Install it with: "
            "pip install -e '.[control_room]'"
        ) from exc

    app = create_app()
    _preflight_registry_check(app.state.service)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def _preflight_registry_check(service: ProjectStatusService) -> None:
    """Fail fast, before binding a socket, if the project registry itself
    cannot be loaded -- rather than starting a server that would only
    surface this as a 503 on the first request. Control Room V0 requires
    an existing Redline OS repository checkout (Codex review "Prove the
    path design under an installed wheel", Option A): it is not a
    self-contained package, since its whole purpose is reading a real
    checkout's live Git state, which is never bundled into a wheel. Only
    RegistryError is fatal here -- a missing/invalid PROJECT_STATE.yaml or
    a dirty working tree are normal, displayable degraded states, not
    reasons to refuse to start."""
    try:
        service.list_snapshots()
    except RegistryError as exc:
        message = (
            f"Control Room cannot locate its project registry: {exc}\n"
            "Control Room V0 requires an existing Redline OS repository checkout -- it is "
            "not a self-contained installed package. Set REDLINE_CONTROL_ROOM_ROOT to the "
            "path of a Redline OS repository checkout before launching (required for a "
            "real installed wheel; an editable dev install finds its own checkout "
            "automatically)."
        )
        logger.error(message)
        raise SystemExit(message) from exc


if __name__ == "__main__":
    main()
