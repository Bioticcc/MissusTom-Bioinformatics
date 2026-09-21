from __future__ import annotations

import re
import subprocess
from pathlib import Path

from missus_tom.config import settings
from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.preflight import PreflightCheck
from missus_tom.models.run import (
    PipelineStatusResult,
    PlannedStage,
    RunPlan,
    RunStartStage,
)
from missus_tom.pipeline_adapters.base import PipelineAdapter
from missus_tom.services.dependencies import runtime_environment, runtime_tool
from missus_tom.services.preflight import project_preflight
from missus_tom.services.projects import read_project_manifest
from missus_tom.services.resources import execution_resource_checks, validate_execution_resources


class BulkRnaSeqAdapter(PipelineAdapter):
    pipeline_identifier = "bulk-rnaseq"
    pipeline_version = "0.4.0"
    supported_pipeline_versions = {pipeline_version, "0.3.0-full-demo"}

    @property
    def execution_enabled(self) -> bool:
        return settings.execution_enabled

    @property
    def repository_root(self) -> Path:
        return settings.resource_root

    @property
    def workflow_directory(self) -> Path:
        return self.repository_root / "workflows" / "bulk_rnaseq"

    def expected_stages(self) -> list[PlannedStage]:
        return [
            PlannedStage(
                stage_id="validate_inputs",
                name="Validate inputs",
                description="Confirm the manifest, FASTQ assignments, references, and resources.",
                source_mapping="New application boundary",
            ),
            PlannedStage(
                stage_id="raw_read_qc",
                name="Raw-read QC",
                description="Run FastQC and aggregate reports with MultiQC.",
                source_mapping="QC_n_Quantification_{H,M}.sh stage 1",
            ),
            PlannedStage(
                stage_id="adapter_trimming",
                name="Adapter trimming",
                description="Trim paired reads with cutadapt.",
                source_mapping="QC_n_Quantification_{H,M}.sh stage 2",
            ),
            PlannedStage(
                stage_id="clean_read_qc",
                name="Clean-read QC",
                description="Run FastQC and MultiQC on trimmed reads.",
                source_mapping="QC_n_Quantification_{H,M}.sh stage 3",
            ),
            PlannedStage(
                stage_id="quantification",
                name="Transcript quantification",
                description="Use the supplied index and quantify with kallisto.",
                source_mapping="QC_n_Quantification_{H,M}.sh stage 4",
            ),
            PlannedStage(
                stage_id="transcript_import",
                name="Transcript import",
                description="Import kallisto estimates and aggregate transcripts by gene.",
                source_mapping="Human_{mRNA,lncRNA}_analysis_pipeline.R tximport stage",
            ),
            PlannedStage(
                stage_id="differential_expression",
                name="Differential expression",
                description="Run manifest-defined DESeq2 comparisons for mRNA and lncRNA.",
                source_mapping="Human_{mRNA,lncRNA}_analysis_pipeline.R DESeq2 stage",
            ),
            PlannedStage(
                stage_id="analysis_outputs",
                name="Analysis tables and figures",
                description=(
                    "Write normalized matrices, differential-expression tables, "
                    "and diagnostic plots."
                ),
                source_mapping="Human_{mRNA,lncRNA}_analysis_pipeline.R reporting stages",
            ),
        ]

    def expected_output_categories(self) -> list[str]:
        return [
            "qc",
            "trimmed_reads",
            "counts",
            "differential_expression",
            "figures",
            "tables",
            "workflow_reports",
            "logs",
            "run_manifest",
        ]

    def inspect_availability(self) -> PipelineStatusResult:
        workflow = self.repository_root / "workflows" / "bulk_rnaseq" / "main.nf"
        return PipelineStatusResult(
            pipeline_identifier=self.pipeline_identifier,
            pipeline_version=self.pipeline_version,
            available=workflow.is_file(),
            execution_enabled=self.execution_enabled,
            message=(
                "Human paired-end bulk RNA-seq execution is enabled."
                if self.execution_enabled
                else "Workflow is installed; execution is disabled in this process."
            ),
            stages=self.expected_stages(),
            output_categories=self.expected_output_categories(),
        )

    def validate_project(self, manifest: ProjectManifest) -> list[PreflightCheck]:
        return project_preflight(manifest)

    def construct_command(
        self,
        manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> list[str]:
        workflow = self.repository_root / "workflows" / "bulk_rnaseq" / "main.nf"
        manifest_path = Path(manifest.output_directory) / "input_manifest" / "project_manifest.json"
        return [
            "nextflow",
            "-log",
            str(Path(manifest.output_directory) / "logs" / "nextflow-engine.log"),
            "run",
            str(workflow),
            "-profile",
            manifest.execution_profile.value,
            "-resume",
            "-work-dir",
            str(Path(manifest.output_directory) / "work"),
            "--manifest",
            str(manifest_path),
            "--outdir",
            str(Path(manifest.output_directory) / "results"),
            "--max_cpus",
            str(manifest.resource_profile.cpus),
            "--max_memory_gb",
            str(manifest.resource_profile.memory_gb),
            "--max_parallel_tasks",
            str(manifest.resource_profile.max_parallel_tasks),
            "--start_stage",
            start_stage.value,
        ]

    def construct_run_plan(self, manifest: ProjectManifest) -> RunPlan:
        estimated_bytes = 0
        warnings = [
            check.message
            for check in execution_resource_checks(manifest)
            if check.status.value != "passed"
        ]
        configured_start_stage = manifest.parameters.get("start_stage", "quantification")
        start_stage = (
            RunStartStage.ANALYSIS
            if configured_start_stage == RunStartStage.ANALYSIS.value
            else RunStartStage.QUANTIFICATION
        )
        supported_project = (
            manifest.pipeline_version in self.supported_pipeline_versions
            and manifest.organism == "Homo sapiens"
            and manifest.read_layout.value == "paired-end"
            and manifest.execution_profile.value == "docker"
            and bool(manifest.comparisons)
        )
        execution_enabled = self.execution_enabled and supported_project
        if not self.execution_enabled:
            warnings.append("Execution is disabled in the backend environment.")
        elif not supported_project:
            warnings.append(
                "Execution currently supports human paired-end projects using Docker "
                "with at least one comparison."
            )
        for sample in manifest.samples:
            if not sample.included:
                continue
            input_files = (
                [sample.abundance_tsv]
                if start_stage == RunStartStage.ANALYSIS and sample.abundance_tsv
                else [*sample.r1_files, *sample.r2_files]
            )
            for filename in input_files:
                path = Path(filename)
                try:
                    if path.is_file():
                        estimated_bytes += path.stat().st_size
                except OSError:
                    warnings.append(f"Could not read size for {path.name}")

        root = Path(manifest.output_directory)
        return RunPlan(
            project_identifier=str(manifest.project_identifier),
            pipeline_identifier=self.pipeline_identifier,
            pipeline_version=self.pipeline_version,
            execution_profile=manifest.execution_profile.value,
            execution_enabled=execution_enabled,
            stages=self.expected_stages(),
            command_preview=self.construct_command(manifest, start_stage=start_stage),
            estimated_input_bytes=estimated_bytes,
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
        """Validate the implemented human paired-end bulk RNA-seq contract."""
        if not self.execution_enabled:
            raise ValueError("execution is disabled in the backend environment")

        output = Path(manifest.output_directory).resolve(strict=False)
        if manifest.pipeline_identifier != self.pipeline_identifier:
            raise ValueError("unsupported pipeline identifier")
        if manifest.pipeline_version not in self.supported_pipeline_versions:
            raise ValueError("unsupported bulk RNA-seq pipeline version")
        if manifest.execution_profile.value != "docker":
            raise ValueError("bulk RNA-seq execution currently requires the Docker profile")
        if manifest.organism != "Homo sapiens" or manifest.read_layout.value != "paired-end":
            raise ValueError("this workflow supports Homo sapiens paired-end projects")
        if not manifest.comparisons:
            raise ValueError("at least one differential-expression comparison is required")

        included = [sample for sample in manifest.samples if sample.included]
        minimum_group_size = manifest.parameters.get("minimum_group_size", 2)
        if not isinstance(minimum_group_size, int) or isinstance(minimum_group_size, bool):
            raise ValueError("minimum_group_size must be an integer")
        if minimum_group_size < 2:
            raise ValueError("minimum_group_size must be at least 2")
        for comparison in manifest.comparisons:
            for group in (comparison.numerator, comparison.denominator):
                group_replicates = {
                    sample.biological_replicate or sample.sample_id
                    for sample in included
                    if sample.condition == group
                    and (
                        not comparison.intervention
                        or sample.covariates.get("intervention") == comparison.intervention
                    )
                }
                if len(group_replicates) < minimum_group_size:
                    raise ValueError(
                        f"comparison {comparison.comparison_id} requires at least "
                        f"{minimum_group_size} samples or replicate groups in group {group}"
                    )

        if manifest.parameters.get("differential_expression", True) is not True:
            raise ValueError("differential_expression must be enabled")

        for key, default, minimum, maximum in (
            ("adjusted_p_value", 0.05, 0, 1),
            ("absolute_log2_fold_change", 0.30, 0, None),
        ):
            value = manifest.parameters.get(key, default)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{key} must be numeric")
            if (
                value < minimum
                or (key == "adjusted_p_value" and value == 0)
                or (maximum is not None and value > maximum)
            ):
                raise ValueError(f"{key} is outside its supported range")

        if start_stage == RunStartStage.ANALYSIS:
            quantification_root = output / "results" / "counts" / "kallisto"
            input_root = Path(manifest.input_directory).resolve(strict=True)
            missing_quantifications: list[str] = []
            for sample in included:
                abundance_path = (
                    Path(sample.abundance_tsv)
                    if sample.abundance_tsv
                    else quantification_root / sample.sample_id / "abundance.tsv"
                )
                try:
                    resolved_abundance = abundance_path.resolve(strict=True)
                except OSError:
                    missing_quantifications.append(sample.sample_id)
                    continue
                external_input = sample.abundance_tsv is not None
                if not resolved_abundance.is_file() or (
                    external_input and not resolved_abundance.is_relative_to(input_root)
                ):
                    missing_quantifications.append(sample.sample_id)
            if missing_quantifications:
                raise ValueError(
                    "analysis-only requires existing kallisto abundance tables for: "
                    + ", ".join(sorted(missing_quantifications))
                )

        if start_stage == RunStartStage.QUANTIFICATION:
            if manifest.strandedness.value not in {"reverse", "forward", "unstranded"}:
                raise ValueError("confirm forward, reverse, or unstranded library orientation")
            for key, default, minimum, maximum in (
                ("trim_quality", 20, 0, 50),
                ("trim_minimum_length", 20, 1, None),
            ):
                value = manifest.parameters.get(key, default)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(f"{key} must be numeric")
                if value < minimum or (maximum is not None and value > maximum):
                    raise ValueError(f"{key} is outside its supported range")

            for key in ("adapter_r1", "adapter_r2"):
                value = manifest.parameters.get(key)
                if not isinstance(value, str) or not re.fullmatch(
                    r"[ACGTRYSWKMBDHVN]+", value.strip(), re.IGNORECASE
                ):
                    raise ValueError(f"{key} must be a non-empty IUPAC nucleotide sequence")

            input_root = Path(manifest.input_directory).resolve(strict=True)
            for sample in included:
                if len(sample.r1_files) != len(sample.r2_files):
                    raise ValueError(f"{sample.sample_id} has unequal R1 and R2 lane counts")
                for filename in [*sample.r1_files, *sample.r2_files]:
                    requested = Path(filename)
                    path = requested.resolve(strict=True)
                    if (
                        not path.is_file()
                        or requested.is_symlink()
                        or not path.is_relative_to(input_root)
                    ):
                        raise ValueError(
                            "FASTQs must be regular files under the selected input directory"
                        )

            index_value = manifest.reference_resources.get("kallisto_index")
            if not index_value or not Path(index_value).resolve(strict=True).is_file():
                raise ValueError("a readable kallisto index is required")
        biomart_value = manifest.reference_resources.get("biomart")
        if not biomart_value or not Path(biomart_value).resolve(strict=True).is_file():
            raise ValueError("a readable human BioMart annotation table is required")

        self.validate_saved_manifest(manifest)

        validate_execution_resources(manifest, analysis_only=start_stage == RunStartStage.ANALYSIS)

        if (
            runtime_tool("nextflow", self.pipeline_identifier) is None
            or runtime_tool("docker", self.pipeline_identifier) is None
        ):
            raise ValueError("Nextflow and Docker must be available in PATH")
        try:
            docker_check = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                env=runtime_environment(self.pipeline_identifier),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("Docker status could not be checked") from exc
        if docker_check.returncode != 0:
            raise ValueError("Docker is unavailable to the backend process")

    @staticmethod
    def validate_saved_manifest(manifest: ProjectManifest) -> None:
        """Recheck the disk contract while the runner holds the project lock."""
        output = Path(manifest.output_directory)
        manifest_path = output / "input_manifest" / "project_manifest.json"
        try:
            saved = read_project_manifest(manifest_path)
        except (OSError, ValueError) as exc:
            raise ValueError("the saved project manifest is missing or invalid") from exc
        if saved != manifest:
            raise ValueError("the submitted manifest does not match the saved project manifest")
