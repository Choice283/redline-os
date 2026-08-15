"""Tests for control_room.app's deferred FastAPI import (Codex review
Finding 2): importing the module must never require the optional
'control_room' extra, and building the app without it must fail with one
clear message instead of a raw ModuleNotFoundError traceback."""
from __future__ import annotations

import builtins
import importlib
import sys

import pytest


@pytest.fixture
def fastapi_unavailable(monkeypatch):
    """Simulates a bare install (no 'control_room' extra): blocks `import
    fastapi`/`fastapi.*` and removes any already-imported fastapi modules
    for the duration of the test, restoring them afterward."""
    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "fastapi" or name.startswith("fastapi."):
            raise ImportError("No module named 'fastapi'")
        return real_import(name, *args, **kwargs)

    saved_modules = {name: mod for name, mod in sys.modules.items() if name == "fastapi" or name.startswith("fastapi.")}
    for name in saved_modules:
        del sys.modules[name]

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    yield
    sys.modules.update(saved_modules)


def test_importing_control_room_app_does_not_require_fastapi(fastapi_unavailable):
    sys.modules.pop("control_room.app", None)
    module = importlib.import_module("control_room.app")
    assert hasattr(module, "create_app")
    assert hasattr(module, "main")


def test_create_app_without_fastapi_raises_friendly_import_error(fastapi_unavailable):
    sys.modules.pop("control_room.app", None)
    module = importlib.import_module("control_room.app")

    with pytest.raises(ImportError, match=r"pip install -e '\.\[control_room\]'"):
        module.create_app()
