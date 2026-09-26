from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from missus_tom.config import settings
from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest, SampleRecord
from missus_tom.models.preflight import PreflightCheck
from missus_tom.models.run import (
    PipelineStatusResult,
    PlannedStage,
    RunPlan,
    RunStartStage,
)
from missus_tom.pipeline_adapters.base import PipelineAdapter
from missus_tom.services.bulk_references import (
    PRODUCTION_PIPELINE_VERSION,
    SUPPORTED_PIPELINE_VERSIONS,
    BulkReferenceError,
    BulkReferenceManager,
    CancellationCheck,
    KallistoRuntime,
    PreparedBulkReferences,
    ReferenceCommandRunner,
    assess_fasta_gtf_overlap,
    infer_bulk_reference_mode,
    iter_fasta_transcript_ids,
    legacy_biomart_migration_message,
    parse_gtf_transcript_records,
    read_supplied_transcript_to_gene,
)
from missus_tom.services.dependencies import runtime_environment, runtime_tool
from missus_tom.services.preflight import project_preflight
from missus_tom.services.projects import read_project_manifest
from missus_tom.services.resources import execution_resource_checks, validate_execution_resources


def bulk_reference_cache_root() -> Path:
    return settings.state_directory / "references" / "bulk-rnaseq"


def execution_manifest_path(project_root: Path, job_identifier: str) -> Path:
    return project_root / "input_manifest" / f"run-{job_identifier}-manifest.json"


def resolve_kallisto_runtime() -> KallistoRuntime | None:
    executable_path = runtime_tool("kallisto", "bulk-rnaseq")
    if executable_path is None:
        return None
    executable = Path(executable_path)
    try:
        completed = subprocess.run(
            [str(executable), "version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            shell=False,
            env=runtime_environment("bulk-rnaseq"),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = ((completed.stdout or "") + (completed.stderr or "")).strip().splitlines()
    version = output[0][:120] if output else "unknown"
    if completed.returncode != 0:
        return None
    return KallistoRuntime(executable=executable, version=version)


def build_execution_manifest_payload(
    manifest: ProjectManifest,
    prepared: PreparedBulkReferences,
    *,
    job_identifier: str,
    start_stage: RunStartStage | None = None,
) -> dict[str, Any]:
    payload = manifest.model_dump(mode="json")
    effective_start_stage = start_stage or (
        RunStartStage.ANALYSIS if prepared.analysis_only else RunStartStage.QUANTIFICATION
    )
    payload["parameters"] = {
        **dict(payload.get("parameters", {})),
        "start_stage": effective_start_stage.value,
    }
    reference_resources = dict(payload.get("reference_resources", {}))
    reference_resources.pop("biomart", None)
    if prepared.kallisto_index:
        reference_resources["kallisto_index"] = prepared.kallisto_index
    else:
        reference_resources.pop("kallisto_index", None)
    reference_resources["transcript_to_gene"] = prepared.transcript_to_gene
    payload["reference_resources"] = reference_resources
    payload["reference_provenance"] = {
        "job_identifier": job_identifier,
        "reference_mode": prepared.reference_mode.value,
        "analysis_only": prepared.analysis_only,
        "cache_root": prepared.cache_root,
        "kallisto_index": prepared.kallisto_index,
        "transcript_to_gene": prepared.transcript_to_gene,
        "index_identity": prepared.index_identity,
        "annotation_identity": prepared.annotation_identity,
        "fasta_id_policy": prepared.fasta_id_policy,
        "overlap": prepared.overlap.model_dump(mode="json") if prepared.overlap else None,
        "transcriptome_fasta": prepared.transcriptome_fasta,
        "annotation_gtf": prepared.annotation_gtf,
    }
    return payload


def write_execution_manifest(
    manifest: ProjectManifest,
    prepared: PreparedBulkReferences,
    destination: Path,
    *,
    job_identifier: str,
    start_stage: RunStartStage | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = build_execution_manifest_payload(
        manifest,
        prepared,
        job_identifier=job_identifier,
        start_stage=start_stage,
    )
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    temporary.replace(destination)


class BulkRnaSeqAdapter(PipelineAdapter):
    pipeline_identifier = "bulk-rnaseq"
    pipeline_version = PRODUCTION_PIPELINE_VERSION
    supported_pipeline_versions = SUPPORTED_PIPELINE_VERSIONS

    @property
    def execution_enabled(self) -> bool:
        return settings.execution_enabled

    @property
    def repository_root(self) -> Path:
        return settings.resource_root

    @property
    def workflow_directory(self) -> Path:
        return self.repository_root / "workflows" / "bulk_rnaseq"

    def runner_working_directory(self, project_root: Path) -> Path:
        """Keep Nextflow session state in the writable saved project directory."""
        return project_root

    def requires_run_reference_preparation(self, manifest: ProjectManifest) -> bool:
        return manifest.pipeline_version in self.supported_pipeline_versions and bool(
            manifest.reference_resources.get("annotation_gtf")
            or manifest.reference_resources.get("transcript_to_gene")
        )

    def expected_stages(self) -> list[PlannedStage]:
        return [
            PlannedStage(
                stage_id="validate_inputs",
                name="Validate inputs",
                description="Confirm the manifest, FASTQ assignments, references, and resources.",
                source_mapping="New application boundary",
            ),
            PlannedStage(
                stage_id="prepare_references",
                name="Prepare references",
                description=(
                    "Build or reuse a cached Kallisto index and normalized transcript-to-gene "
                    "mapping without changing the saved project manifest."
                ),
                source_mapping="Application-owned preparation boundary",
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
                description="Use the prepared index and quantify with kallisto.",
                source_mapping="QC_n_Quantification_{H,M}.sh stage 4",
            ),
            PlannedStage(
                stage_id="transcript_import",
                name="Transcript import",
                description="Import kallisto estimates and aggregate transcripts by gene.",
                source_mapping="BULK_RNASEQ_ANALYSIS tximport stage",
            ),
            PlannedStage(
                stage_id="differential_expression",
                name="Differential expression",
                description=(
                    "Run all-gene manifest-defined DESeq2 comparisons with optional "
                    "annotation-supported biotype subsets."
                ),
                source_mapping="BULK_RNASEQ_ANALYSIS DESeq2 stage",
            ),
            PlannedStage(
                stage_id="analysis_outputs",
                name="Analysis tables and figures",
                description=(
                    "Write normalized matrices, differential-expression tables, "
                    "and diagnostic plots."
                ),
                source_mapping="BULK_RNASEQ_ANALYSIS reporting stages",
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
                "Paired-end bulk RNA-seq execution is enabled for the 0.5.0 contract."
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
        manifest_path: Path | None = None,
        job_identifier: str | None = None,
    ) -> list[str]:
        workflow = self.repository_root / "workflows" / "bulk_rnaseq" / "main.nf"
        root = Path(manifest.output_directory)
        if manifest_path is None:
            if job_identifier and manifest.pipeline_version == PRODUCTION_PIPELINE_VERSION:
                manifest_path = execution_manifest_path(root, job_identifier)
            else:
                manifest_path = root / "input_manifest" / "project_manifest.json"
        return [
            "nextflow",
            "-log",
            str(root / "logs" / "nextflow-engine.log"),
            "run",
            str(workflow),
            "-profile",
            manifest.execution_profile.value,
            "-resume",
            "-work-dir",
            str(root / "work"),
            "--manifest",
            str(manifest_path),
            "--outdir",
            str(root / "results"),
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
        migration = legacy_biomart_migration_message(manifest)
        supported_version = manifest.pipeline_version in self.supported_pipeline_versions
        supported_project = (
            supported_version
            and not migration
            and manifest.read_layout.value == "paired-end"
            and manifest.execution_profile.value in {"local", "docker"}
            and bool(manifest.comparisons)
        )
        execution_enabled = self.execution_enabled and supported_project
        if not self.execution_enabled:
            warnings.append("Execution is disabled in the backend environment.")
        elif migration:
            warnings.append(migration)
        elif not supported_project:
            warnings.append(
                "Execution supports paired-end projects on pipeline version 0.5.0 (or eligible "
                "legacy versions) using Local tools or Docker with at least one comparison."
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
        if not self.execution_enabled:
            raise ValueError("execution is disabled in the backend environment")

        if manifest.pipeline_identifier != self.pipeline_identifier:
            raise ValueError("unsupported pipeline identifier")
        if manifest.pipeline_version not in self.supported_pipeline_versions:
            raise ValueError("unsupported bulk RNA-seq pipeline version")

        migration = legacy_biomart_migration_message(manifest)
        if migration:
            raise ValueError(migration)

        if manifest.pipeline_version == PRODUCTION_PIPELINE_VERSION:
            self._validate_production_execution(manifest, start_stage=start_stage)
            return
        if manifest.reference_resources.get("annotation_gtf") or manifest.reference_resources.get(
            "transcript_to_gene"
        ):
            self._validate_production_execution(manifest, start_stage=start_stage)
            return

        raise ValueError(
            "This legacy Bulk RNA-seq project must be re-saved with annotation_gtf "
            "or transcript_to_gene before running the generic analysis."
        )

    def _validate_production_execution(
        self,
        manifest: ProjectManifest,
        *,
        start_stage: RunStartStage,
    ) -> None:
        if manifest.execution_profile.value not in {"local", "docker"}:
            raise ValueError("bulk RNA-seq execution supports the local tools or Docker profile")
        if manifest.read_layout.value != "paired-end":
            raise ValueError("this workflow supports paired-end projects only")
        if not manifest.comparisons:
            raise ValueError("at least one differential-expression comparison is required")
        if (
            manifest.pipeline_version == PRODUCTION_PIPELINE_VERSION
            and manifest.reference_mode is None
        ):
            raise ValueError(
                "reference_mode must be set explicitly for pipeline version 0.5.0 projects"
            )

        mode = infer_bulk_reference_mode(
            manifest.reference_resources,
            explicit_mode=manifest.reference_mode,
        )
        if mode is None:
            raise ValueError(
                "reference_mode must be set explicitly for pipeline version 0.5.0 projects"
            )

        included = [sample for sample in manifest.samples if sample.included]
        self._validate_design_and_parameters(manifest, included, start_stage=start_stage)
        if start_stage == RunStartStage.ANALYSIS:
            self._validate_analysis_only_inputs(manifest, included)
        else:
            self._validate_quantification_fastqs(manifest, included)
        self._validate_reference_inputs(manifest, mode=mode, start_stage=start_stage)

        if (
            start_stage == RunStartStage.QUANTIFICATION
            and mode == BulkReferenceMode.BUILD
            and resolve_kallisto_runtime() is None
        ):
            raise ValueError(
                "managed Kallisto is required to build an index for build reference mode"
            )

        self.validate_saved_manifest(manifest)
        validate_execution_resources(manifest, analysis_only=start_stage == RunStartStage.ANALYSIS)
        self._validate_runtime_tools(manifest)

    def _validate_design_and_parameters(
        self,
        manifest: ProjectManifest,
        included: list[SampleRecord],
        *,
        start_stage: RunStartStage,
    ) -> None:
        minimum_group_size = manifest.parameters.get("minimum_group_size", 2)
        if not isinstance(minimum_group_size, int) or isinstance(minimum_group_size, bool):
            raise ValueError("minimum_group_size must be an integer")
        if minimum_group_size < 2:
            raise ValueError("minimum_group_size must be at least 2")
        for comparison in manifest.comparisons:
            for group in (comparison.numerator, comparison.denominator):
                group_samples = [
                    sample
                    for sample in included
                    if sample.condition == group
                    and (
                        not comparison.intervention
                        or sample.covariates.get("intervention") == comparison.intervention
                    )
                ]
                if len(group_samples) < minimum_group_size:
                    raise ValueError(
                        f"comparison {comparison.comparison_id} requires at least "
                        f"{minimum_group_size} biological samples in group {group}"
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

    def _validate_reference_inputs(
        self,
        manifest: ProjectManifest,
        *,
        mode: BulkReferenceMode,
        start_stage: RunStartStage,
    ) -> None:
        resources = manifest.reference_resources
        analysis_only = start_stage == RunStartStage.ANALYSIS

        supplied_mapping = resources.get("transcript_to_gene")
        supplied_gtf = resources.get("annotation_gtf")
        supplied_fasta = resources.get("transcriptome_fasta")
        supplied_index = resources.get("kallisto_index")

        if supplied_mapping:
            try:
                read_supplied_transcript_to_gene(Path(supplied_mapping))
            except BulkReferenceError as exc:
                raise ValueError(str(exc)) from exc
        if supplied_gtf:
            records = parse_gtf_transcript_records(Path(supplied_gtf))
            if not records:
                raise ValueError(
                    "annotation_gtf does not contain usable transcript_id and gene_id attributes"
                )
            if supplied_fasta and Path(supplied_fasta).is_file():
                fasta_ids = iter_fasta_transcript_ids(Path(supplied_fasta))
                overlap = assess_fasta_gtf_overlap(fasta_ids=fasta_ids, gtf_records=records)
                if overlap.overlap_fraction < 0.95:
                    raise ValueError(
                        "transcriptome FASTA and annotation GTF appear incompatible "
                        f"({overlap.overlap_fraction:.1%} identifier overlap)"
                    )

        if analysis_only:
            if not supplied_mapping and not supplied_gtf:
                raise ValueError("analysis-only runs require annotation_gtf or transcript_to_gene")
            return

        if mode == BulkReferenceMode.BUILD:
            for key in ("transcriptome_fasta", "annotation_gtf"):
                path_value = resources.get(key)
                if not path_value or not Path(path_value).resolve(strict=True).is_file():
                    raise ValueError(f"a readable {key} file is required for build reference mode")
            if supplied_index:
                raise ValueError("build reference mode must not include kallisto_index")
            return

        index_path = Path(supplied_index) if supplied_index else None
        if index_path is None or not index_path.resolve(strict=True).is_file():
            raise ValueError("existing-index reference mode requires a readable kallisto_index")
        if not supplied_mapping and not supplied_gtf:
            raise ValueError(
                "existing-index reference mode requires annotation_gtf or transcript_to_gene"
            )

    def _validate_quantification_fastqs(
        self,
        manifest: ProjectManifest,
        included: list[SampleRecord],
    ) -> None:
        input_root = Path(manifest.input_directory).resolve(strict=True)
        assigned_paths: set[Path] = set()
        for sample in included:
            if not sample.r1_files:
                raise ValueError(f"Sample {sample.sample_id} has no R1 file.")
            if not sample.r2_files:
                raise ValueError(
                    f"Sample {sample.sample_id} has an R1 file but no matching R2 file."
                )
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
                if path in assigned_paths:
                    raise ValueError(f"FASTQ is assigned more than once: {path}")
                assigned_paths.add(path)

    def _validate_analysis_only_inputs(
        self,
        manifest: ProjectManifest,
        included: list[SampleRecord],
    ) -> None:
        input_root = Path(manifest.input_directory).resolve(strict=True)
        missing_quantifications: list[str] = []
        for sample in included:
            if not sample.abundance_tsv:
                missing_quantifications.append(sample.sample_id)
                continue
            abundance_path = Path(sample.abundance_tsv)
            try:
                resolved_abundance = abundance_path.resolve(strict=True)
            except OSError:
                missing_quantifications.append(sample.sample_id)
                continue
            if (
                not resolved_abundance.is_file()
                or abundance_path.is_symlink()
                or not resolved_abundance.is_relative_to(input_root)
            ):
                missing_quantifications.append(sample.sample_id)
        if missing_quantifications:
            raise ValueError(
                "analysis-only requires existing kallisto abundance tables for: "
                + ", ".join(sorted(missing_quantifications))
            )

    def _validate_runtime_tools(self, manifest: ProjectManifest) -> None:
        if runtime_tool("nextflow", self.pipeline_identifier) is None:
            if manifest.execution_profile.value == "docker":
                raise ValueError("Nextflow and Docker must be available in PATH")
            raise ValueError("Nextflow must be available in PATH")
        if manifest.execution_profile.value == "docker":
            if runtime_tool("docker", self.pipeline_identifier) is None:
                raise ValueError("Nextflow and Docker must be available in PATH")
            try:
                docker_check = subprocess.run(
                    ["docker", "info", "--format", "{{.ServerVersion}}"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                    env=runtime_environment(self.pipeline_identifier),
                    shell=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ValueError("Docker status could not be checked") from exc
            if docker_check.returncode != 0:
                raise ValueError("Docker is unavailable to the backend process")

    def prepare_run_references(
        self,
        manifest: ProjectManifest,
        *,
        job_identifier: str,
        manager: BulkReferenceManager | None = None,
        log_writer: Callable[[str], None] | None = None,
        command_runner: ReferenceCommandRunner | None = None,
        start_stage: RunStartStage | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> tuple[Path, PreparedBulkReferences]:
        if not self.requires_run_reference_preparation(manifest):
            raise ValueError(
                "reference preparation requires pipeline version 0.5.0 or a compatible "
                "legacy manifest with annotation_gtf or transcript_to_gene"
            )
        project_root = Path(manifest.output_directory)
        destination = execution_manifest_path(project_root, job_identifier)
        reference_manager = manager or BulkReferenceManager(
            cache_root=bulk_reference_cache_root(),
            kallisto=resolve_kallisto_runtime(),
            log_writer=log_writer,
            command_runner=command_runner,
            environment=runtime_environment("bulk-rnaseq"),
            cancellation_check=cancellation_check,
        )
        try:
            effective_start_stage = start_stage or RunStartStage(
                str(manifest.parameters.get("start_stage", "quantification"))
            )
            prepared = reference_manager.prepare(
                manifest,
                analysis_only=effective_start_stage == RunStartStage.ANALYSIS,
            )
        except BulkReferenceError as exc:
            raise ValueError(str(exc)) from exc
        write_execution_manifest(
            manifest,
            prepared,
            destination,
            job_identifier=job_identifier,
            start_stage=effective_start_stage,
        )
        return destination, prepared

    def replace_command_manifest(self, command: list[str], manifest_path: Path) -> list[str]:
        updated = list(command)
        try:
            index = updated.index("--manifest")
        except ValueError as exc:
            raise ValueError("runner command is missing --manifest") from exc
        if index + 1 >= len(updated):
            raise ValueError("runner command is missing a manifest path")
        updated[index + 1] = str(manifest_path)
        return updated

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
