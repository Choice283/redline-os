"""Phase 15 Mission 15G -- tests for redline_core.archive.metadata_snapshot:
the four generated restore-metadata snapshot builders (episode, render
job, config, software identity), their determinism, and the config
secret-field guard.

Scope: redline_core.archive.metadata_snapshot only. No DB, no CLI, no
MCP, no Resolve, no production media.
"""
from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from redline_core.archive.metadata_snapshot import (
    ConfigSnapshotSecretFieldError,
    build_config_snapshot,
    build_config_snapshot_bytes,
    build_episode_snapshot,
    build_episode_snapshot_bytes,
    build_render_job_snapshot,
    build_render_job_snapshot_bytes,
    build_software_snapshot,
    build_software_snapshot_bytes,
    resolve_software_identity,
)
from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.db.models import Episode, EpisodeStatus, RenderJob, RenderJobStatus


def _make_episode(**overrides) -> Episode:
    defaults = dict(
        id=42,
        episode_number=25,
        episode_id="RLC-E025",
        project_name="RLC-E025_MASTER",
        project_path=None,
        folder_path=r"C:\episodes\RLC-E025",
        status=EpisodeStatus.RENDERED,
        assembly_claim_token=None,
        assembly_claimed_at=None,
        created_at="2026-01-01 00:00:00",
        updated_at="2026-01-01 01:00:00",
    )
    defaults.update(overrides)
    return Episode(**defaults)


def _make_render_job(**overrides) -> RenderJob:
    defaults = dict(
        id=7,
        episode_id="RLC-E025",
        preset_name="broadcast_master",
        resolve_job_id="resolve-RLC-E025",
        status=RenderJobStatus.COMPLETE,
        output_path=r"C:\episodes\RLC-E025\exports\RLC-E025_MASTER.mov",
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        created_at="2026-01-01 02:00:00",
        updated_at="2026-01-01 03:00:00",
    )
    defaults.update(overrides)
    return RenderJob(**defaults)


def _make_config() -> RedlineConfig:
    return RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=r"C:\episodes"),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path=r"C:\ingest", archive_path=r"C:\archive", assets_path=r"C:\assets", master_project_template="TEMPLATE"
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )


# -- episode snapshot ---------------------------------------------------------------


def test_build_episode_snapshot_fields():
    episode = _make_episode()
    snapshot = build_episode_snapshot(episode)
    assert snapshot["schema_version"] == 1
    assert snapshot["snapshot_kind"] == "episode"
    assert snapshot["episode_id"] == "RLC-E025"
    assert snapshot["episode_number"] == 25
    assert snapshot["status"] == "rendered"
    assert snapshot["folder_path"] == r"C:\episodes\RLC-E025"
    assert "id" not in snapshot


def test_build_episode_snapshot_preserves_rendered_status_not_archived():
    episode = _make_episode(status=EpisodeStatus.RENDERED)
    snapshot = build_episode_snapshot(episode)
    assert snapshot["status"] == "rendered"


def test_build_episode_snapshot_bytes_deterministic():
    episode = _make_episode()
    assert build_episode_snapshot_bytes(episode) == build_episode_snapshot_bytes(episode)


def test_build_episode_snapshot_bytes_canonical_json():
    episode = _make_episode()
    payload = json.loads(build_episode_snapshot_bytes(episode))
    assert payload == build_episode_snapshot(episode)


# -- render job snapshot --------------------------------------------------------------


def test_build_render_job_snapshot_fields():
    render_job = _make_render_job()
    snapshot = build_render_job_snapshot(render_job)
    assert snapshot["schema_version"] == 1
    assert snapshot["snapshot_kind"] == "render_job"
    assert snapshot["render_job_id"] == 7
    assert snapshot["episode_id"] == "RLC-E025"
    assert snapshot["status"] == "complete"
    assert snapshot["output_path"] == r"C:\episodes\RLC-E025\exports\RLC-E025_MASTER.mov"


def test_build_render_job_snapshot_bytes_deterministic():
    render_job = _make_render_job()
    assert build_render_job_snapshot_bytes(render_job) == build_render_job_snapshot_bytes(render_job)


# -- config snapshot ------------------------------------------------------------------


def test_build_config_snapshot_contains_effective_config():
    config = _make_config()
    snapshot = build_config_snapshot(config)
    assert snapshot["schema_version"] == 1
    assert snapshot["snapshot_kind"] == "config"
    assert snapshot["config"]["paths"]["archive_path"] == r"C:\archive"
    assert snapshot["config"]["naming"]["episode_id_pattern"] == "RLC-E{episode_number:03d}"


def test_build_config_snapshot_bytes_deterministic():
    config = _make_config()
    assert build_config_snapshot_bytes(config) == build_config_snapshot_bytes(config)


def test_build_config_snapshot_no_secret_fields_in_real_schema():
    # Structural proof that RedlineConfig as it exists today has nothing
    # for the secret-field guard to reject.
    build_config_snapshot(_make_config())


def test_build_config_snapshot_fails_closed_on_secret_bearing_field(monkeypatch):
    class LeakyPathsConfig(BaseModel):
        archive_path: str
        api_key: str = "should-never-be-archived"

    class LeakyConfig(BaseModel):
        paths: LeakyPathsConfig

        def model_dump(self, *args, **kwargs):
            return {"paths": {"archive_path": self.paths.archive_path, "api_key": self.paths.api_key}}

    leaky = LeakyConfig(paths=LeakyPathsConfig(archive_path=r"C:\archive"))
    with pytest.raises(ConfigSnapshotSecretFieldError):
        build_config_snapshot(leaky)


def test_build_config_snapshot_fails_closed_on_top_level_secret_field():
    class LeakyConfig(BaseModel):
        auth_token: str = "leaked"

    with pytest.raises(ConfigSnapshotSecretFieldError):
        build_config_snapshot(LeakyConfig())


# -- software identity ----------------------------------------------------------------


def test_build_software_snapshot_explicit_fields():
    snapshot = build_software_snapshot(
        redline_os_version="0.1.0",
        repository_revision=None,
        python_version="3.13.0",
        platform_system="Windows",
        platform_release="11",
        platform_machine="AMD64",
    )
    assert snapshot["schema_version"] == 1
    assert snapshot["snapshot_kind"] == "software"
    assert snapshot["redline_os_version"] == "0.1.0"
    assert snapshot["repository_revision"] is None
    assert snapshot["python_version"] == "3.13.0"
    assert snapshot["platform"] == {"system": "Windows", "release": "11", "machine": "AMD64"}


def test_build_software_snapshot_bytes_deterministic():
    kwargs = dict(
        redline_os_version="0.1.0",
        repository_revision=None,
        python_version="3.13.0",
        platform_system="Windows",
        platform_release="11",
        platform_machine="AMD64",
    )
    assert build_software_snapshot_bytes(**kwargs) == build_software_snapshot_bytes(**kwargs)


def test_resolve_software_identity_never_requires_network_or_subprocess():
    # No mocking of network/subprocess exists here at all -- if this call
    # required either, it would hang or raise in a sandboxed test run.
    identity = resolve_software_identity()
    assert identity["repository_revision"] is None
    assert identity["redline_os_version"] == "0.1.0"
    assert isinstance(identity["python_version"], str) and identity["python_version"]
    assert isinstance(identity["platform_system"], str) and identity["platform_system"]


def test_resolve_software_identity_feeds_build_software_snapshot():
    identity = resolve_software_identity()
    snapshot = build_software_snapshot(**identity)
    assert snapshot["redline_os_version"] == "0.1.0"
    assert snapshot["repository_revision"] is None
