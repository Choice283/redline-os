from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from redline_core.build import (
    BuildOrchestrator,
    BuildResult,
    BuildStage,
    BuildTarget,
    ManifestIdentityMismatchError,
    ManifestResolution,
    PreparedBuildRequest,
)
from redline_core.config.schema import (
    NamingConfig,
)
from redline_core.db.models import Episode, EpisodeStatus
from redline_core.episode.exceptions import EpisodeBuildError, EpisodeNotFoundError
from redline_core.episode.models import EpisodeBuildDefinition, EpisodeBuildResult
from redline_core.manifest import ManifestLoadError, ManifestValidationError


def config() -> SimpleNamespace:
    return SimpleNamespace(
        naming=NamingConfig(
            episode_id_pattern="RLC-E{episode_number:03d}",
            project_name_pattern="{episode_id}_MASTER",
        ),
    )


def target() -> BuildTarget:
    return BuildTarget(original_target="Episode_0001", episode_number=1, episode_id="RLC-E001")


def assembly_result() -> EpisodeBuildResult:
    return EpisodeBuildResult(
        episode_id="RLC-E001",
        project_name="RLC-E001_MASTER",
        timeline_id="timeline-1",
        timeline_name="RLC-E001_TIMELINE",
        media_paths=["C:/media/a.wav", "C:/media/b.wav"],
        media_ids=["media-1", "media-2"],
        markers_applied=3,
        timeline_item_ids=["item-1", "item-2"],
    )


class FakePlan:
    def __init__(self, calls: list[str], *, episode_id: str = "RLC-E001"):
        self.calls = calls
        self.episode_id = episode_id
        self.media_paths = ("C:/media/a.wav", "C:/media/b.wav")
        self.markers = ()
        self.bin_name = "footage"

    def to_build_definition(self) -> EpisodeBuildDefinition:
        self.calls.append("to_build_definition")
        return EpisodeBuildDefinition(
            episode_id=self.episode_id,
            media_paths=list(self.media_paths),
            markers=[],
            bin_name=self.bin_name,
        )


class FakeEpisodeManager:
    def __init__(self, calls: list[str], *, existing: bool):
        self.calls = calls
        self.existing = existing
        self.created_numbers: list[int] = []
        self.build_calls: list[tuple[EpisodeBuildDefinition, bool]] = []

    def get_episode_status(self, episode_number: int) -> Episode:
        self.calls.append("get_episode_status")
        if not self.existing:
            raise EpisodeNotFoundError(f"No episode with episode_number={episode_number}.")
        return Episode(
            episode_number=episode_number,
            episode_id="RLC-E001",
            project_name="RLC-E001_MASTER",
            status=EpisodeStatus.CREATED,
        )

    def create_episode(self, episode_number: int) -> Episode:
        self.calls.append("create_episode")
        self.created_numbers.append(episode_number)
        return Episode(
            episode_number=episode_number,
            episode_id="RLC-E001",
            project_name="RLC-E001_MASTER",
            status=EpisodeStatus.CREATED,
        )

    def build_episode(self, definition: EpisodeBuildDefinition, *, allow_unsafe_retry: bool = False) -> EpisodeBuildResult:
        self.calls.append("build_episode")
        self.build_calls.append((definition, allow_unsafe_retry))
        return assembly_result()


def orchestrator_with_fakes(
    *,
    calls: list[str],
    episode_manager: FakeEpisodeManager | None = None,
    plan: FakePlan | None = None,
    loader_failure: Exception | None = None,
    validator_failure: Exception | None = None,
) -> BuildOrchestrator:
    cfg = config()
    manager = episode_manager or FakeEpisodeManager(calls, existing=False)
    selected_target = target()
    selected_plan = plan or FakePlan(calls)

    def parse(raw_target: str, naming: NamingConfig) -> BuildTarget:
        calls.append("parse")
        assert raw_target == "Episode_0001"
        assert naming is cfg.naming
        return selected_target

    def resolve(parsed_target: BuildTarget, *, manifest_path: Path | str | None, working_directory: Path | str):
        calls.append("resolve")
        assert parsed_target is selected_target
        assert working_directory == Path("C:/work")
        return ManifestResolution(path=Path("C:/resolved/episode.yaml"), source="explicit")

    def load(path: Path):
        calls.append("load")
        assert path == Path("C:/resolved/episode.yaml")
        if loader_failure is not None:
            raise loader_failure
        return object()

    def validate(manifest, *, manifest_path: Path, config):
        calls.append("validate")
        assert manifest is not None
        assert manifest_path == Path("C:/resolved/episode.yaml")
        assert config is cfg
        if validator_failure is not None:
            raise validator_failure
        return selected_plan

    return BuildOrchestrator(
        config=cfg,
        episode_manager=manager,
        target_parser=parse,
        manifest_resolver=resolve,
        manifest_loader=load,
        manifest_validator=validate,
    )


def test_build_orchestrator_builds_new_episode_in_approved_order(tmp_path):
    calls: list[str] = []
    manager = FakeEpisodeManager(calls, existing=False)
    orchestrator = orchestrator_with_fakes(calls=calls, episode_manager=manager)

    result = orchestrator.build("Episode_0001", working_directory=Path("C:/work"), allow_unsafe_retry=False)

    assert calls == [
        "parse",
        "resolve",
        "load",
        "validate",
        "get_episode_status",
        "create_episode",
        "to_build_definition",
        "build_episode",
    ]
    assert manager.created_numbers == [1]
    definition, allow_unsafe_retry = manager.build_calls[0]
    assert definition.episode_id == "RLC-E001"
    assert allow_unsafe_retry is False
    assert result == BuildResult(
        target=target(),
        manifest_path=Path("C:/resolved/episode.yaml"),
        completed_stages=(
            BuildStage.TARGET_PARSED,
            BuildStage.MANIFEST_RESOLVED,
            BuildStage.MANIFEST_LOADED,
            BuildStage.MANIFEST_VALIDATED,
            BuildStage.IDENTITY_CONFIRMED,
            BuildStage.EPISODE_RESOLVED,
            BuildStage.EPISODE_CREATED,
            BuildStage.EPISODE_ASSEMBLED,
        ),
        final_state=EpisodeStatus.ASSEMBLED,
        project_name="RLC-E001_MASTER",
        timeline_name="RLC-E001_TIMELINE",
        media_count=2,
        markers_applied=3,
        clips_placed=2,
        warnings=(),
        episode_created=True,
    )


def test_build_orchestrator_reuses_existing_episode_without_create(tmp_path):
    calls: list[str] = []
    manager = FakeEpisodeManager(calls, existing=True)
    orchestrator = orchestrator_with_fakes(calls=calls, episode_manager=manager)

    result = orchestrator.build("Episode_0001", working_directory=Path("C:/work"))

    assert "create_episode" not in calls
    assert calls == [
        "parse",
        "resolve",
        "load",
        "validate",
        "get_episode_status",
        "to_build_definition",
        "build_episode",
    ]
    assert result.episode_created is False
    assert result.completed_stages == (
        BuildStage.TARGET_PARSED,
        BuildStage.MANIFEST_RESOLVED,
        BuildStage.MANIFEST_LOADED,
        BuildStage.MANIFEST_VALIDATED,
        BuildStage.IDENTITY_CONFIRMED,
        BuildStage.EPISODE_RESOLVED,
        BuildStage.EPISODE_ASSEMBLED,
    )


def test_build_orchestrator_passes_explicit_manifest_path_to_resolver(tmp_path):
    calls: list[str] = []
    cfg = config()
    manager = FakeEpisodeManager(calls, existing=False)
    explicit_path = Path("manifests/custom.yaml")

    def resolve(parsed_target: BuildTarget, *, manifest_path: Path | str | None, working_directory: Path | str):
        calls.append(f"manifest_path={manifest_path}")
        return ManifestResolution(path=tmp_path / "resolved.yaml", source="explicit")

    orchestrator = BuildOrchestrator(
        config=cfg,
        episode_manager=manager,
        target_parser=lambda raw_target, naming: target(),
        manifest_resolver=resolve,
        manifest_loader=lambda path: object(),
        manifest_validator=lambda manifest, *, manifest_path, config: FakePlan(calls),
    )

    orchestrator.build("Episode_0001", working_directory=tmp_path, manifest_path=explicit_path)

    assert calls[0] == f"manifest_path={explicit_path}"


def test_build_prepared_uses_preflighted_manifest_without_loading_or_validating_again(tmp_path):
    calls: list[str] = []
    manager = FakeEpisodeManager(calls, existing=True)
    plan = FakePlan(calls)
    prepared_request = PreparedBuildRequest(
        target=target(),
        manifest_resolution=ManifestResolution(path=Path("C:/resolved/episode.yaml"), source="explicit"),
        manifest=object(),
        plan=plan,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("prepared build must not run preflight-owned work again")

    orchestrator = BuildOrchestrator(
        config=config(),
        episode_manager=manager,
        target_parser=forbidden,
        manifest_resolver=forbidden,
        manifest_loader=forbidden,
        manifest_validator=forbidden,
    )

    result = orchestrator.build_prepared(prepared_request, allow_unsafe_retry=True)

    assert calls == ["get_episode_status", "to_build_definition", "build_episode"]
    _, allow_unsafe_retry = manager.build_calls[0]
    assert allow_unsafe_retry is True
    assert result.manifest_path == Path("C:/resolved/episode.yaml")
    assert result.completed_stages == (
        BuildStage.TARGET_PARSED,
        BuildStage.MANIFEST_RESOLVED,
        BuildStage.MANIFEST_LOADED,
        BuildStage.MANIFEST_VALIDATED,
        BuildStage.IDENTITY_CONFIRMED,
        BuildStage.EPISODE_RESOLVED,
        BuildStage.EPISODE_ASSEMBLED,
    )


def test_build_orchestrator_rejects_manifest_identity_mismatch_before_mutation(tmp_path):
    calls: list[str] = []
    manager = FakeEpisodeManager(calls, existing=False)
    orchestrator = orchestrator_with_fakes(
        calls=calls,
        episode_manager=manager,
        plan=FakePlan(calls, episode_id="RLC-E999"),
    )

    with pytest.raises(ManifestIdentityMismatchError) as error_info:
        orchestrator.build("Episode_0001", working_directory=Path("C:/work"))

    assert error_info.value.target_episode_id == "RLC-E001"
    assert error_info.value.manifest_episode_id == "RLC-E999"
    assert "get_episode_status" not in calls
    assert "create_episode" not in calls
    assert "build_episode" not in calls


def test_build_orchestrator_propagates_manifest_loading_failure_before_mutation(tmp_path):
    calls: list[str] = []
    manager = FakeEpisodeManager(calls, existing=False)
    failure = ManifestLoadError("load failed")
    orchestrator = orchestrator_with_fakes(
        calls=calls,
        episode_manager=manager,
        loader_failure=failure,
    )

    with pytest.raises(ManifestLoadError, match="load failed"):
        orchestrator.build("Episode_0001", working_directory=Path("C:/work"))

    assert calls == ["parse", "resolve", "load"]
    assert manager.created_numbers == []
    assert manager.build_calls == []


def test_build_orchestrator_propagates_manifest_validation_failure_before_mutation(tmp_path):
    calls: list[str] = []
    manager = FakeEpisodeManager(calls, existing=False)
    failure = ManifestValidationError("validation failed")
    orchestrator = orchestrator_with_fakes(
        calls=calls,
        episode_manager=manager,
        validator_failure=failure,
    )

    with pytest.raises(ManifestValidationError, match="validation failed"):
        orchestrator.build("Episode_0001", working_directory=Path("C:/work"))

    assert calls == ["parse", "resolve", "load", "validate"]
    assert manager.created_numbers == []
    assert manager.build_calls == []


def test_build_orchestrator_does_not_assemble_when_episode_creation_fails(tmp_path):
    calls: list[str] = []

    class FailingCreateManager(FakeEpisodeManager):
        def create_episode(self, episode_number: int) -> Episode:
            super().create_episode(episode_number)
            raise RuntimeError("create failed")

    manager = FailingCreateManager(calls, existing=False)
    orchestrator = orchestrator_with_fakes(calls=calls, episode_manager=manager)

    with pytest.raises(RuntimeError, match="create failed"):
        orchestrator.build("Episode_0001", working_directory=Path("C:/work"))

    assert "create_episode" in calls
    assert "build_episode" not in calls
    assert manager.build_calls == []


def test_build_orchestrator_preserves_existing_manager_policy_failures(tmp_path):
    calls: list[str] = []

    class PolicyFailureManager(FakeEpisodeManager):
        def build_episode(
            self, definition: EpisodeBuildDefinition, *, allow_unsafe_retry: bool = False
        ) -> EpisodeBuildResult:
            self.calls.append("build_episode")
            raise EpisodeBuildError("already assembled", stage="episode_lookup", episode_id="RLC-E001")

    manager = PolicyFailureManager(calls, existing=True)
    orchestrator = orchestrator_with_fakes(calls=calls, episode_manager=manager)

    with pytest.raises(EpisodeBuildError, match="already assembled"):
        orchestrator.build("Episode_0001", working_directory=Path("C:/work"))

    assert calls.count("build_episode") == 1
    assert "create_episode" not in calls


def test_build_orchestrator_does_not_retry_assembly_failures(tmp_path):
    calls: list[str] = []

    class AssemblyFailureManager(FakeEpisodeManager):
        def build_episode(
            self, definition: EpisodeBuildDefinition, *, allow_unsafe_retry: bool = False
        ) -> EpisodeBuildResult:
            self.calls.append("build_episode")
            raise RuntimeError("adapter failure")

    manager = AssemblyFailureManager(calls, existing=True)
    orchestrator = orchestrator_with_fakes(calls=calls, episode_manager=manager)

    with pytest.raises(RuntimeError, match="adapter failure"):
        orchestrator.build("Episode_0001", working_directory=Path("C:/work"))

    assert calls.count("build_episode") == 1


def test_build_orchestrator_passes_allow_unsafe_retry_through(tmp_path):
    calls: list[str] = []
    manager = FakeEpisodeManager(calls, existing=True)
    orchestrator = orchestrator_with_fakes(calls=calls, episode_manager=manager)

    orchestrator.build("Episode_0001", working_directory=Path("C:/work"), allow_unsafe_retry=True)

    _, allow_unsafe_retry = manager.build_calls[0]
    assert allow_unsafe_retry is True


def test_build_result_is_immutable(tmp_path):
    calls: list[str] = []
    orchestrator = orchestrator_with_fakes(calls=calls)

    result = orchestrator.build("Episode_0001", working_directory=Path("C:/work"))

    with pytest.raises(FrozenInstanceError):
        result.final_state = EpisodeStatus.FAILED
