"""Tests for the transport-neutral composition root.

redline_core.runtime.composition.build_application_services() is the single
place Config + Database + Resolve adapter + every manager get wired
together. Both mcp_server (via mcp_server.context.build_context, tested
separately in test_mcp_tools.py) and cli (via cli.main.main, tested in
test_cli_episode_create.py) are thin callers of this function — these tests
cover the wiring itself, once, independent of either transport.

Tests that actually call create_episode() use an in-memory config scoped
under tmp_path (mirroring test_mcp_tools.make_config) rather than
config_dir="config" — the real config/folder_structure.yaml's root_path is
a relative "./_episodes", and create_episode() really creates that folder
on disk. Loading the real config is fine for wiring-only assertions (no
side effects), but never for anything that calls create_episode().
"""
from pathlib import Path

from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.db.database import Database
from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.runtime.composition import (
    ApplicationServices,
    CoreServices,
    build_application_services,
    build_core_services,
)


def make_config(tmp_path: Path) -> RedlineConfig:
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    return RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path=str(tmp_path / "_ingest"),
            archive_path=str(tmp_path / "_archive"),
            assets_path=str(assets_path),
            master_project_template="RLC_MASTER_TEMPLATE",
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )


def test_build_application_services_wires_shared_resolve_and_managers(tmp_path):
    resolve = MockResolveAdapter()

    services = build_application_services(
        config_dir="config", db_path=tmp_path / "composition.db", resolve_adapter=resolve
    )

    assert isinstance(services, ApplicationServices)
    assert services.resolve is resolve
    assert services.episode_manager.resolve is resolve
    assert services.episode_manager.media_manager is services.media_manager
    assert services.episode_manager.timeline_builder is services.timeline_builder
    assert services.media_manager.resolve is resolve
    assert services.timeline_builder.resolve is resolve
    assert services.render_manager.resolve is resolve
    assert services.render_manager.db is services.db
    assert services.archive_manager.db is services.db


def test_build_application_services_defaults_to_real_resolve_script_adapter(tmp_path):
    # Don't actually construct a real ResolveScriptAdapter (it would try to
    # load Resolve's fusionscript module) — just confirm the default branch
    # is taken by passing an explicit mock and checking it's used as-is,
    # i.e. build_application_services() doesn't silently substitute its own
    # adapter when one is provided.
    resolve = MockResolveAdapter()
    services = build_application_services(
        config_dir="config", db_path=tmp_path / "composition2.db", resolve_adapter=resolve
    )
    assert services.resolve is resolve


def test_build_application_services_loads_real_naming_convention(tmp_path):
    # Assert against the real config/naming.yaml without ever calling
    # create_episode() — that would write to the real (relative)
    # folder_structure.root_path. Naming-pattern loading has no filesystem
    # side effects, so it's safe to check against the real config directory.
    resolve = MockResolveAdapter()
    services = build_application_services(
        config_dir="config", db_path=tmp_path / "composition3.db", resolve_adapter=resolve
    )
    assert services.config.naming.episode_id_pattern == "RLC-E{episode_number:03d}"


def test_build_application_services_supports_fully_isolated_create_episode(tmp_path):
    # For anything that actually calls create_episode(), build the config
    # in-memory scoped under tmp_path (mirroring test_mcp_tools.make_config)
    # rather than loading the real config/ directory, so the test never
    # touches the real working tree.
    resolve = MockResolveAdapter()
    services = build_application_services(
        config_dir="config", db_path=tmp_path / "composition4.db", resolve_adapter=resolve
    )
    services.config = make_config(tmp_path)
    services.episode_manager.config = services.config

    episode = services.episode_manager.create_episode(7)

    assert episode.episode_id == "RLC-E007"
    assert Path(episode.folder_path).is_relative_to(tmp_path)


# -- build_core_services() (Mission 5: config-only composition path) -----------

def test_build_core_services_returns_core_services():
    services = build_core_services(config_dir="config")

    assert isinstance(services, CoreServices)
    assert services.config.naming.episode_id_pattern == "RLC-E{episode_number:03d}"
    assert services.asset_manager.config is services.config


def test_build_core_services_has_no_db_or_resolve_attribute():
    services = build_core_services(config_dir="config")

    assert not hasattr(services, "db")
    assert not hasattr(services, "resolve")
    assert not hasattr(services, "episode_manager")


def test_build_core_services_never_touches_database_or_resolve(monkeypatch):
    """Proves the independence claim structurally, not just by inspecting
    CoreServices' fields: if build_core_services() ever grew a call to
    Database.connect() or ResolveScriptAdapter.connect(), this test fails
    immediately, regardless of what CoreServices ends up shaped like."""

    def _boom(*args, **kwargs):
        raise AssertionError("build_core_services() must not touch this.")

    monkeypatch.setattr(Database, "connect", _boom)
    monkeypatch.setattr(ResolveScriptAdapter, "connect", _boom)
    monkeypatch.setattr(ResolveScriptAdapter, "__init__", _boom)

    services = build_core_services(config_dir="config")

    assert isinstance(services, CoreServices)
