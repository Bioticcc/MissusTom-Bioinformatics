from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from missus_tom.config import settings
from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.preflight import PreflightCheck
from missus_tom.models.run import PipelineStatusResult, PlannedStage, RunPlan, RunStartStage
from missus_tom.pipeline_adapters.base import PipelineAdapter
from missus_tom.services.dependencies import ONT_R_PACKAGES, runtime_environment, runtime_tool
from missus_tom.services.preflight import ont_analysis_preflight
from missus_tom.services.projects import read_project_manifest
from missus_tom.services.resources import execution_resource_checks, validate_execution_resources


class OntAnalysisAdapter(PipelineAdapter):
    """Controlled adapter for the local ONT BAM analysis runner."""

    pipeline_identifier = "ont-analysis"
    pipeline_version = "0.1.0"
    required_reference_resources = {
        "reference_fasta",
        "reference_fai",
        "minimap2_index",
    }

    @property
    def execution_enabled(self) -> bool:
        return settings.execution_enabled

    @property
    def repository_root(self) -> Path:
        return settings.resource_root

    @property
    def workflow_directory(self) -> Path:
        return self.repository_root / "workflows" / "ont_analysis"

    @property
    def runner_path(self) -> Path:
        return self.workflow_directory / "run_pipeline.py"

    @property
    def requires_resume(self) -> bool:
        """The ONT runner reuses validated stages and has no clean-rebuild mode."""
        return True

    def expected_stages(self) -> list[PlannedStage]:
        return [
            PlannedStage(
                stage_id="align_modbam",
                name="Align modBAM",
                description="Prepare ONT modified-base alignment inputs.",
                source_mapping="ONT runner align_modbam",
            ),
            PlannedStage(
                stage_id="finalize_alignment",
                name="Finalize alignment",
                description="Publish the controlled alignment outputs.",
                source_mapping="ONT runner finalize_alignment",
            ),
            PlannedStage(
                stage_id="ont_qc_coverage",
                name="ONT QC and coverage",
                description="Generate ONT quality-control and coverage summaries.",
                source_mapping="ONT runner ont_qc_coverage",
            ),
            PlannedStage(
                stage_id="methylation",
                name="Methylation analysis",
                description="Produce methylation calls and annotations.",
                source_mapping="ONT runner methylation",
            ),
            PlannedStage(
                stage_id="methylation_exploration",
                name="Methylation exploration",
                description="Write exploration tables, figures, and reports.",
                source_mapping="ONT runner methylation_exploration",
            ),
        ]

    def expected_output_categories(self) -> list[str]:
        return [
            "alignment",
            "alignment_qc",
            "qc_coverage",
            "methylation",
            "methylation_exploration",
            "logs",
            "manifests",
            "run_manifest",
            "workflow_configuration",
        ]

    def inspect_availability(self) -> PipelineStatusResult:
        available = self.runner_path.is_file()
        return PipelineStatusResult(
            pipeline_identifier=self.pipeline_identifier,
            pipeline_version=self.pipeline_version,
            available=available,
            execution_enabled=self.execution_enabled and available,
            message=(
                "ONT analysis runner is available."
                if available
                else "ONT analysis runner is not installed."
            ),
            stages=self.expected_stages(),
            output_categories=self.expected_output_categories(),
        )

    def validate_project(self, manifest: ProjectManifest) -> list[PreflightCheck]:
        return ont_analysis_preflight(manifest)

    def construct_command(
        self,
        manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> list[str]:
        del start_stage  # The ONT runner owns its restartable internal stages.
        runner = settings.ont_runner
        command = [str(runner)] if runner is not None else [sys.executable, str(self.runner_path)]
        return [
            *command,
            "--manifest",
            str(Path(manifest.output_directory) / "input_manifest" / "project_manifest.json"),
            "--outdir",
            str(Path(manifest.output_directory) / "results"),
        ]

    def append_run_identifier(self, command: list[str], job_identifier: str) -> list[str]:
        return [*command, "--run-id", job_identifier]

    def construct_run_plan(self, manifest: ProjectManifest) -> RunPlan:
        warnings = [
            check.message
            for check in execution_resource_checks(manifest)
            if check.status.value != "passed"
        ]
        supported = (
            manifest.pipeline_version == self.pipeline_version
            and manifest.organism == "Mus musculus"
            and manifest.reference_genome == "GRCm38p6"
            and manifest.execution_profile.value == "local"
        )
        missing_tools = self.missing_runtime_tools()
        enabled = (
            self.execution_enabled
            and self.runner_path.is_file()
            and supported
            and not missing_tools
        )
        if not self.execution_enabled:
            warnings.append("Execution is disabled in the backend environment.")
        elif not self.runner_path.is_file():
            warnings.append("The ONT analysis runner is not installed.")
        elif not supported:
            warnings.append("Execution supports local Mus musculus projects using GRCm38p6.")
        if missing_tools:
            warnings.append("Required ONT tools are unavailable: " + ", ".join(missing_tools))
        input_bytes = sum(
            path.stat().st_size
            for sample in manifest.samples
            if sample.included
            for path in (Path(value) for value in sample.ont_bam_files)
            if path.is_file()
        )
        root = Path(manifest.output_directory)
        return RunPlan(
            project_identifier=str(manifest.project_identifier),
            pipeline_identifier=self.pipeline_identifier,
            pipeline_version=self.pipeline_version,
            execution_profile=manifest.execution_profile.value,
            execution_enabled=enabled,
            stages=self.expected_stages(),
            command_preview=self.construct_command(manifest),
            estimated_input_bytes=input_bytes,
            log_directory=str(root / "logs"),
            results_directory=str(root / "results"),
            warnings=warnings,
        )

    def validate_execution(
        self,
        manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> None:
        del start_stage
        if not self.execution_enabled:
            raise ValueError("execution is disabled in the backend environment")
        if manifest.pipeline_identifier != self.pipeline_identifier:
            raise ValueError("unsupported pipeline identifier")
        if manifest.pipeline_version != self.pipeline_version:
            raise ValueError("unsupported ONT analysis pipeline version")
        if manifest.organism != "Mus musculus" or manifest.reference_genome != "GRCm38p6":
            raise ValueError("this workflow supports Mus musculus GRCm38p6 projects")
        if manifest.execution_profile.value != "local":
            raise ValueError("ONT analysis requires the local execution profile")
        if not self.runner_path.is_file():
            raise ValueError("ONT analysis runner is not installed")
        if settings.ont_runner is not None and not settings.ont_runner.is_file():
            raise ValueError("the configured ONT runner is unavailable")
        checks = self.validate_project(manifest)
        failures = [check.message for check in checks if check.status.value == "blocking_failure"]
        if failures:
            raise ValueError("ONT project has blocking validation failures: " + "; ".join(failures))
        validate_execution_resources(manifest, analysis_only=False)
        if settings.ont_runner is None and not Path(sys.executable).is_file():
            raise ValueError("the configured Python runner is unavailable")
        missing_tools = self.missing_runtime_tools()
        if missing_tools:
            raise ValueError("Required ONT tools are unavailable: " + ", ".join(missing_tools))
        self.validate_saved_manifest(manifest)

    @staticmethod
    def validate_saved_manifest(manifest: ProjectManifest) -> None:
        path = Path(manifest.output_directory) / "input_manifest" / "project_manifest.json"
        try:
            saved = read_project_manifest(path)
        except (OSError, ValueError) as exc:
            raise ValueError("the saved project manifest is missing or invalid") from exc
        if saved != manifest:
            raise ValueError("the submitted manifest does not match the saved project manifest")

    @staticmethod
    def missing_runtime_tools() -> list[str]:
        missing = [
            tool
            for tool in ("dorado", "samtools", "mosdepth", "modkit", "bgzip", "tabix", "Rscript")
            if runtime_tool(tool, "ont-analysis") is None
        ]
        rscript = runtime_tool("Rscript", "ont-analysis")
        if rscript is not None:
            packages = ",".join(f'"{name}"' for name in ONT_R_PACKAGES)
            expression = (
                f"quit(status=if(all(vapply(c({packages}),requireNamespace,"
                "logical(1),quietly=TRUE))) 0 else 1)"
            )
            try:
                result = subprocess.run(
                    [rscript, "--vanilla", "-e", expression],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                    env=runtime_environment("ont-analysis"),
                )
                if result.returncode != 0:
                    missing.append("required ONT R packages")
            except (OSError, subprocess.TimeoutExpired):
                missing.append("usable ONT R environment")
        return missing

    def artifact_roots(self, project_root: Path) -> dict[str, Path]:
        return {
            "qc": project_root / "results" / "qc",
            "alignment": project_root / "results" / "01_alignment",
            "alignment_qc": project_root / "results" / "02_alignment_qc",
            "qc_coverage": project_root / "results" / "03_ont_qc_coverage",
            "methylation": project_root / "results" / "04_methylation",
            "methylation_exploration": project_root / "results" / "05_methylation_exploration",
            "logs": project_root / "logs",
            "manifests": project_root / "results" / "00_manifests",
            "run_manifest": project_root / "input_manifest",
            "workflow_configuration": project_root / "results" / "config",
        }
