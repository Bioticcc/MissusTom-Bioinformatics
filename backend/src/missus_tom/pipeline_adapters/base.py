from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.preflight import PreflightCheck
from missus_tom.models.run import PipelineStatusResult, PlannedStage, RunPlan, RunStartStage


class PipelineAdapter(ABC):
    pipeline_identifier: str

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
    def construct_command(
        self,
        manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def validate_execution(
        self,
        manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> None:
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

    @property
    @abstractmethod
    def workflow_directory(self) -> Path:
        """Directory containing the installed workflow assets."""
        raise NotImplementedError

    def runner_working_directory(self, project_root: Path) -> Path:
        """Return the controlled process working directory for a project.

        Adapters that need project-local engine state may override this to return
        ``project_root``. The default preserves runners that execute beside their
        installed workflow assets.
        """
        del project_root
        return self.workflow_directory

    def append_run_identifier(self, command: list[str], job_identifier: str) -> list[str]:
        """Add the runner-specific job identifier without invoking a shell."""
        return [*command, "--run_id", job_identifier]

    def artifact_roots(self, project_root: Path) -> dict[str, Path]:
        """Return the published artifact roots for this pipeline."""
        return {
            "qc": project_root / "results" / "qc",
            "trimmed_reads": project_root / "results" / "trimmed",
            "counts": project_root / "results" / "counts",
            "differential_expression": project_root / "results" / "differential_expression",
            "figures": project_root / "results" / "figures",
            "tables": project_root / "results" / "tables",
            "workflow_reports": project_root / "reports",
            "logs": project_root / "logs",
            "run_manifest": project_root / "input_manifest",
        }

    @property
    def requires_resume(self) -> bool:
        """Whether this runner supports only restartable execution semantics."""
        return False

    def requires_run_reference_preparation(self, manifest: ProjectManifest) -> bool:
        """Whether the runner performs application-owned reference preparation before launch."""
        del manifest
        return False
