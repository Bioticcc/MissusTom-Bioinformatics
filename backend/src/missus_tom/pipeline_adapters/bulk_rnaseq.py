from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from missus_tom.config import settings
from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.preflight import PreflightCheck
from missus_tom.models.run import PipelineStatusResult, PlannedStage, RunPlan
from missus_tom.pipeline_adapters.base import PipelineAdapter
from missus_tom.services.preflight import project_preflight


class BulkRnaSeqAdapter(PipelineAdapter):
    pipeline_identifier = "bulk-rnaseq"
    pipeline_version = "0.3.0-full-demo"

    @property
    def execution_enabled(self) -> bool:
        return settings.execution_enabled

    @property
    def repository_root(self) -> Path:
        return Path(__file__).resolve().parents[4]

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
                description="Build or reuse an index and quantify with kallisto.",
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
                description="Run the OD1 versus H DESeq2 analyses for mRNA and lncRNA.",
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
                "Controlled human demo execution is enabled."
                if self.execution_enabled
                else "Workflow is installed; controlled execution is disabled in this process."
            ),
            stages=self.expected_stages(),
            output_categories=self.expected_output_categories(),
        )

    def validate_project(self, manifest: ProjectManifest) -> list[PreflightCheck]:
        return project_preflight(manifest)

    def construct_command(self, manifest: ProjectManifest) -> list[str]:
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
        ]

    def construct_run_plan(self, manifest: ProjectManifest) -> RunPlan:
        estimated_bytes = 0
        warnings: list[str] = []
        demo_candidate = (
            manifest.pipeline_version == self.pipeline_version
            and manifest.parameters.get("execution_mode") == "human-demo"
            and manifest.parameters.get("differential_expression") is True
        )
        execution_enabled = self.execution_enabled and demo_candidate
        if not self.execution_enabled:
            warnings.append("Controlled execution is disabled in the backend environment.")
        elif not demo_candidate:
            warnings.append("Execution is restricted to the prepared human demo manifest.")
        for sample in manifest.samples:
            if not sample.included:
                continue
            for filename in [*sample.r1_files, *sample.r2_files]:
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
            command_preview=self.construct_command(manifest),
            estimated_input_bytes=estimated_bytes,
            log_directory=str(root / "logs"),
            results_directory=str(root / "results"),
            warnings=warnings,
        )

    def validate_execution(self, manifest: ProjectManifest) -> None:
        """Restrict execution to the prepared, local human demo contract."""
        if not self.execution_enabled:
            raise ValueError("controlled execution is disabled in the backend environment")
        root = settings.execution_root
        if root is None:
            raise ValueError("MISSUS_TOM_EXECUTION_ROOT is not configured")

        output = Path(manifest.output_directory).resolve(strict=False)
        if output != root / "project":
            raise ValueError("the output directory is outside the configured demo project")
        if manifest.pipeline_identifier != self.pipeline_identifier:
            raise ValueError("unsupported pipeline identifier")
        if manifest.pipeline_version != self.pipeline_version:
            raise ValueError("unsupported demo pipeline version")
        if manifest.execution_profile.value != "docker":
            raise ValueError("the human demo requires the Docker execution profile")
        if manifest.organism != "Homo sapiens" or manifest.read_layout.value != "paired-end":
            raise ValueError("the execution adapter accepts only the paired-end human demo")
        if manifest.strandedness.value != "reverse":
            raise ValueError("the human demo requires reverse-stranded libraries")
        if len(manifest.comparisons) != 1:
            raise ValueError("the full human demo requires one comparison")
        comparison = manifest.comparisons[0]
        if comparison.numerator != "OD1" or comparison.denominator != "H":
            raise ValueError("the full human demo comparison must be OD1 versus H")

        required_parameters = {
            "execution_mode": "human-demo",
            "read_pairs_per_sample": 1_000_000,
            "adapter_r1": "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA",
            "adapter_r2": "AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT",
            "trim_quality": 20,
            "trim_minimum_length": 20,
            "kallisto_strandedness": "rf-stranded",
            "differential_expression": True,
            "analysis_gene_classes": "mRNA,lncRNA",
            "minimum_group_size": 4,
            "adjusted_p_value": 0.05,
            "absolute_log2_fold_change": 0.30,
        }
        for key, expected in required_parameters.items():
            if manifest.parameters.get(key) != expected:
                raise ValueError(f"demo parameter does not match the approved value: {key}")

        included = [sample for sample in manifest.samples if sample.included]
        expected_ids = {
            *(f"DEMO_H_{replicate:02d}" for replicate in range(1, 5)),
            *(f"DEMO_OD1_{replicate:02d}" for replicate in range(1, 5)),
        }
        if {sample.sample_id for sample in included} != expected_ids:
            raise ValueError("the full human demo requires the eight prepared samples")
        if Counter(sample.condition for sample in included) != Counter({"H": 4, "OD1": 4}):
            raise ValueError("the full human demo requires four H and four OD1 samples")

        input_root = (root / "inputs").resolve(strict=False)
        for sample in included:
            if len(sample.r1_files) != 1 or len(sample.r2_files) != 1:
                raise ValueError(f"{sample.sample_id} must have exactly one R1 and one R2 file")
            for filename in [*sample.r1_files, *sample.r2_files]:
                path = Path(filename).resolve(strict=True)
                if path.parent != input_root or path.is_symlink():
                    raise ValueError(
                        "demo FASTQs must be regular files in the configured demo input"
                    )

        index_value = manifest.reference_resources.get("kallisto_index")
        if not index_value or not Path(index_value).resolve(strict=True).is_file():
            raise ValueError("a readable kallisto index is required")
        biomart_value = manifest.reference_resources.get("biomart")
        if not biomart_value or not Path(biomart_value).resolve(strict=True).is_file():
            raise ValueError("a readable human BioMart annotation table is required")

        manifest_path = output / "input_manifest" / "project_manifest.json"
        try:
            saved = ProjectManifest.model_validate(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError) as exc:
            raise ValueError("the saved demo manifest is missing or invalid") from exc
        if saved != manifest:
            raise ValueError("the submitted manifest does not match the saved demo manifest")

        if shutil.which("nextflow") is None or shutil.which("docker") is None:
            raise ValueError("Nextflow and Docker must be available in PATH")
        try:
            docker_check = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("Docker status could not be checked") from exc
        if docker_check.returncode != 0:
            raise ValueError("Docker is unavailable to the backend process")
