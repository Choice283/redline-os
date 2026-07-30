from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from redline_core.build import BuildTarget, BuildTargetError, parse_build_target
from redline_core.config.schema import NamingConfig


def naming(pattern: str = "RLC-E{episode_number:03d}") -> NamingConfig:
    return NamingConfig(episode_id_pattern=pattern, project_name_pattern="{episode_id}_MASTER")


@pytest.mark.parametrize(
    ("target", "episode_number", "episode_id"),
    [
        ("Episode_0001", 1, "RLC-E001"),
        ("Episode_0009", 9, "RLC-E009"),
        ("Episode_0010", 10, "RLC-E010"),
        ("Episode_0100", 100, "RLC-E100"),
        ("Episode_9999", 9999, "RLC-E9999"),
    ],
)
def test_parse_build_target_accepts_canonical_targets(target, episode_number, episode_id):
    result = parse_build_target(target, naming())

    assert result == BuildTarget(
        original_target=target,
        episode_number=episode_number,
        episode_id=episode_id,
    )


def test_parse_build_target_result_is_immutable():
    result = parse_build_target("Episode_0001", naming())

    with pytest.raises(FrozenInstanceError):
        result.episode_number = 2


@pytest.mark.parametrize(
    "target",
    [
        "",
        "episode_0001",
        "EPISODE_0001",
        "0001",
        "Episode-0001",
        "Episode_1",
        "Episode_001",
        "Episode_00001",
        "Episode_00A1",
        "Episode_0001.yaml",
        " Episode_0001",
        "Episode_0001 ",
        "Episode_0001/manifest.yaml",
        "RLC-E001",
    ],
)
def test_parse_build_target_rejects_noncanonical_targets(target):
    with pytest.raises(BuildTargetError, match="Episode_####"):
        parse_build_target(target, naming())


def test_parse_build_target_rejects_zero_episode_number():
    with pytest.raises(BuildTargetError, match="greater than zero"):
        parse_build_target("Episode_0000", naming())


def test_parse_build_target_requires_string_target():
    with pytest.raises(BuildTargetError, match="must be a string"):
        parse_build_target(1, naming())


def test_parse_build_target_requires_naming_config():
    with pytest.raises(BuildTargetError, match="NamingConfig"):
        parse_build_target("Episode_0001", object())


def test_parse_build_target_uses_supplied_naming_configuration():
    result = parse_build_target("Episode_0007", naming("SHOW-{episode_number:04d}"))

    assert result.episode_id == "SHOW-0007"


def test_parse_build_target_does_not_mutate_naming_configuration():
    config = naming("SHOW-{episode_number:04d}")
    before = config.model_dump()

    parse_build_target("Episode_0007", config)

    assert config.model_dump() == before
