"""Safe YAML loading for Episode Manifest V1."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from redline_core.manifest.exceptions import ManifestLoadError, ManifestParseError
from redline_core.manifest.models import EpisodeManifest, build_manifest_model

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".yaml", ".yml"}


class _ManifestSafeLoader(yaml.SafeLoader):
    """Local SafeLoader subclass with duplicate-key rejection."""


def _construct_mapping(loader: _ManifestSafeLoader, node: yaml.nodes.MappingNode, deep: bool = False) -> dict:
    if not isinstance(node, yaml.nodes.MappingNode):
        raise yaml.constructor.ConstructorError(None, None, "expected a mapping node", node.start_mark)

    mapping: dict[str, Any] = {}
    seen: set[str] = set()
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(
                "while constructing a manifest mapping",
                key_node.start_mark,
                f"found non-string mapping key {key!r}",
                key_node.start_mark,
            )
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a manifest mapping",
                key_node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        seen.add(key)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_ManifestSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def load_manifest(path: str | Path) -> EpisodeManifest:
    """Load a YAML Episode Manifest V1 file into an EpisodeManifest model."""
    manifest_path = Path(path)
    logger.debug("Loading episode manifest: %s", manifest_path)
    if manifest_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ManifestLoadError(
            f"unsupported manifest extension for {manifest_path}; expected .yaml or .yml",
            code="manifest.extension_unsupported",
        )

    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestLoadError(
            f"unable to read manifest file {manifest_path}: {exc}",
            code="manifest.file_unreadable",
        ) from exc
    except UnicodeDecodeError as exc:
        raise ManifestLoadError(
            f"manifest file {manifest_path} must be valid UTF-8",
            code="manifest.encoding_invalid",
        ) from exc

    try:
        documents = list(yaml.load_all(text, Loader=_ManifestSafeLoader))
    except yaml.YAMLError as exc:
        raise ManifestParseError(
            f"manifest YAML parse failed for {manifest_path}: {exc}",
            code="manifest.yaml_invalid",
        ) from exc

    if not documents:
        raise ManifestParseError("manifest document must not be empty", code="manifest.document_empty")
    if len(documents) != 1:
        raise ManifestParseError(
            f"manifest must contain exactly one YAML document; found {len(documents)}",
            code="manifest.document_count_invalid",
        )
    data = documents[0]
    if data is None:
        raise ManifestParseError("manifest document must not be empty or null", code="manifest.document_empty")
    if not isinstance(data, dict):
        raise ManifestParseError("manifest root must be a YAML mapping", code="manifest.root_invalid")

    manifest = build_manifest_model(data)
    logger.debug(
        "Loaded episode manifest schema_version=%s media_count=%d marker_count=%d",
        manifest.schema_version,
        len(manifest.assembly.media),
        len(manifest.assembly.markers),
    )
    return manifest
