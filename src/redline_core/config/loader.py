"""YAML config loader for Redline OS.

Loads the four config files under /config into a single validated
RedlineConfig object. This is the ONLY place in the codebase that should
read these YAML files directly — every other module receives an already-
validated RedlineConfig instance.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)

logger = logging.getLogger(__name__)

REQUIRED_FILES = {
    "naming": "naming.yaml",
    "folder_structure": "folder_structure.yaml",
    "render_presets": "render_presets.yaml",
    "paths": "paths.yaml",
    "assets": "assets.yaml",
    "timeline": "timeline_template.yaml",
}


class ConfigError(Exception):
    """Raised when config files are missing or fail schema validation."""


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing required config file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a YAML mapping at the top level.")
    return data


def load_config(config_dir: str | Path) -> RedlineConfig:
    """Load and validate all Redline OS config files from `config_dir`.

    Raises ConfigError if a file is missing or fails schema validation.
    """
    config_dir = Path(config_dir)
    logger.info("Loading Redline OS config from %s", config_dir)

    try:
        naming = NamingConfig(**_read_yaml(config_dir / REQUIRED_FILES["naming"]))
        folder_structure = FolderStructureConfig(**_read_yaml(config_dir / REQUIRED_FILES["folder_structure"]))
        render_presets = RenderPresetsConfig(**_read_yaml(config_dir / REQUIRED_FILES["render_presets"]))
        paths = PathsConfig(**_read_yaml(config_dir / REQUIRED_FILES["paths"]))
        assets = AssetsConfig(**_read_yaml(config_dir / REQUIRED_FILES["assets"]))
        timeline = TimelineTemplateConfig(**_read_yaml(config_dir / REQUIRED_FILES["timeline"]))
    except ConfigError:
        raise
    except Exception as exc:  # pydantic ValidationError and friends
        raise ConfigError(f"Config validation failed: {exc}") from exc

    config = RedlineConfig(
        naming=naming,
        folder_structure=folder_structure,
        render_presets=render_presets,
        paths=paths,
        assets=assets,
        timeline=timeline,
    )
    logger.info("Redline OS config loaded successfully.")
    return config
