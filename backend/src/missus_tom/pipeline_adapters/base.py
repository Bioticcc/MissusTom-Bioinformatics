from __future__ import annotations

from abc import ABC, abstractmethod

from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.preflight import PreflightCheck
from missus_tom.models.run import PipelineStatusResult, PlannedStage, RunPlan


class PipelineAdapter(ABC):
    @abstractmethod
    def inspect_availability(self) -> PipelineStatusResult:
        raise NotImplementedError

    @abstractmethod
    def validate_project(self, manifest: ProjectManifest) -> list[PreflightCheck]:
        raise NotImplementedError

    @abstractmethod
    def construct_run_plan(self, manifest: ProjectManifest) -> RunPlan:
        raise NotImplementedError

    @abstractmethod
    def construct_command(self, manifest: ProjectManifest) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def expected_stages(self) -> list[PlannedStage]:
        raise NotImplementedError

    @abstractmethod
    def expected_output_categories(self) -> list[str]:
        raise NotImplementedError

    @property
    @abstractmethod
    def execution_enabled(self) -> bool:
        raise NotImplementedError
