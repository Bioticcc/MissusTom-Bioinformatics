from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def normalize_user_path(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("path must not be empty")
    path = Path(stripped).expanduser()
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    return str(path.resolve(strict=False))


class ReadLayout(StrEnum):
    PAIRED_END = "paired-end"
    SINGLE_END = "single-end"


class Strandedness(StrEnum):
    UNSTRANDED = "unstranded"
    FORWARD = "forward"
    REVERSE = "reverse"
    UNKNOWN = "unknown"


class ExecutionProfile(StrEnum):
    LOCAL = "local"
    DOCKER = "docker"
    APPTAINER = "apptainer"


class BulkReferenceMode(StrEnum):
    BUILD = "build"
    EXISTING_INDEX = "existing-index"


class PipelineStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PLANNED = "planned"
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


Scalar = str | int | float | bool | None


class AxisRange(BaseModel):
    """Viewing limits only; these never change DESeq2 calculations."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["automatic", "manual"] = "automatic"
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_manual_range(self) -> AxisRange:
        if self.mode == "automatic":
            if self.minimum is not None or self.maximum is not None:
                raise ValueError("automatic axis ranges cannot contain limits")
            return self
        if self.minimum is None or self.maximum is None or self.minimum >= self.maximum:
            raise ValueError("manual axis range requires finite minimum less than maximum")
        return self


FIGURE_TYPES = {
    "gene_metric_scatter",
    "sample_correlation_heatmap",
    "expression_distribution_boxplot",
    "top_de_genes_bar",
    "estimated_gene_count_bar",
}
GENE_METRICS = {
    "base_mean",
    "log2_fold_change",
    "p_value",
    "adjusted_p_value",
    "minus_log10_p_value",
    "minus_log10_adjusted_p_value",
    "stat",
    "lfc_standard_error",
}


class CustomFigure(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    figure_id: str
    figure_type: str
    title: str = Field(min_length=1, max_length=160)
    x_variable: str | None = None
    y_variable: str | None = None
    x_axis: AxisRange = Field(default_factory=AxisRange)
    y_axis: AxisRange = Field(default_factory=AxisRange)
    x_label: str | None = Field(default=None, max_length=120)
    y_label: str | None = Field(default=None, max_length=120)
    top_n: int | None = Field(default=None, ge=1, le=50)

    @field_validator("figure_id")
    @classmethod
    def validate_figure_id(cls, value: str) -> str:
        if not SAFE_IDENTIFIER.fullmatch(value):
            raise ValueError("figure_id must be a safe identifier")
        return value

    @field_validator("title", "x_label", "y_label")
    @classmethod
    def validate_figure_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or any(character in value for character in "\t\r\n"):
            raise ValueError("figure text must be non-empty and cannot contain line breaks")
        return value

    @model_validator(mode="after")
    def validate_figure_contract(self) -> CustomFigure:
        if self.figure_type not in FIGURE_TYPES:
            raise ValueError("unsupported figure_type")
        if self.figure_type == "gene_metric_scatter":
            if self.x_variable not in GENE_METRICS or self.y_variable not in GENE_METRICS:
                raise ValueError("gene-metric scatter requires supported numeric x and y variables")
        elif self.figure_type == "expression_distribution_boxplot":
            if (
                self.x_variable not in {"sample_id", "condition"}
                or self.y_variable != "rlog_expression"
            ):
                raise ValueError(
                    "expression boxplot requires sample_id or condition and rlog_expression"
                )
        elif self.figure_type == "top_de_genes_bar":
            if self.y_variable not in {None, "log2_fold_change"}:
                raise ValueError("top-DE bar chart uses log2_fold_change")
            if self.top_n is None:
                raise ValueError("top-DE bar chart requires top_n")
        elif self.figure_type in {"sample_correlation_heatmap", "estimated_gene_count_bar"} and (
            self.x_variable is not None or self.y_variable is not None
        ):
            raise ValueError("this figure type has fixed sample axes")
        return self


class FigureConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    version: Literal[1] = 1
    custom_figures: list[CustomFigure] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_figure_ids(self) -> FigureConfiguration:
        ids = [figure.figure_id for figure in self.custom_figures]
        if len(ids) != len(set(ids)):
            raise ValueError("custom figure identifiers must be unique")
        return self


class SampleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    sample_id: str
    r1_files: list[str] = Field(default_factory=list)
    r2_files: list[str] = Field(default_factory=list)
    ont_bam_files: list[str] = Field(default_factory=list)
    abundance_tsv: str | None = None
    condition: str
    biological_replicate: str
    batch: str | None = None
    covariates: dict[str, Scalar] = Field(default_factory=dict)
    included: bool = True

    @field_validator("sample_id")
    @classmethod
    def validate_sample_id(cls, value: str) -> str:
        value = value.strip()
        if not SAFE_IDENTIFIER.fullmatch(value):
            raise ValueError("use letters, numbers, dots, underscores, or hyphens")
        return value

    @field_validator("condition", "biological_replicate")
    @classmethod
    def normalize_design_text(cls, value: str) -> str:
        value = value.strip()
        if any(character in value for character in "\t\r\n"):
            raise ValueError("tabs and line breaks are not allowed")
        return value

    @field_validator("batch")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("covariates")
    @classmethod
    def normalize_covariates(cls, values: dict[str, Scalar]) -> dict[str, Scalar]:
        normalized = dict(values)
        intervention = normalized.get("intervention")
        if intervention is not None and not isinstance(intervention, str):
            raise ValueError("intervention covariate must be text")
        if isinstance(intervention, str):
            intervention = intervention.strip()
            if any(character in intervention for character in "\t\r\n"):
                raise ValueError("intervention cannot contain tabs or line breaks")
            normalized["intervention"] = intervention or None
        return normalized

    @field_validator("r1_files", "r2_files", "ont_bam_files")
    @classmethod
    def normalize_fastq_paths(cls, values: list[str]) -> list[str]:
        return [normalize_user_path(value) for value in values]

    @field_validator("abundance_tsv")
    @classmethod
    def normalize_abundance_path(cls, value: str | None) -> str | None:
        return normalize_user_path(value) if value else None


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    comparison_id: str
    numerator: str
    denominator: str
    label: str | None = None
    intervention: str | None = None

    @field_validator("comparison_id")
    @classmethod
    def validate_comparison_id(cls, value: str) -> str:
        value = value.strip()
        if not SAFE_IDENTIFIER.fullmatch(value):
            raise ValueError("comparison_id must be a safe identifier")
        return value

    @field_validator("numerator", "denominator")
    @classmethod
    def normalize_group(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("comparison group must not be empty")
        if any(character in value for character in "\t\r\n"):
            raise ValueError("comparison groups cannot contain tabs or line breaks")
        return value

    @field_validator("intervention")
    @classmethod
    def normalize_intervention(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if any(character in value for character in "\t\r\n"):
            raise ValueError("intervention cannot contain tabs or line breaks")
        return value or None

    @model_validator(mode="after")
    def groups_must_differ(self) -> Comparison:
        if self.numerator == self.denominator:
            raise ValueError("numerator and denominator must differ")
        return self


class ResourceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    cpus: int = Field(default=4, ge=1, description="Total workflow CPU budget")
    memory_gb: float = Field(default=8, gt=0, description="Total workflow memory budget in GiB")
    max_parallel_tasks: int = Field(
        default=1, ge=1, description="Maximum concurrent tasks across the whole workflow"
    )


class ProjectManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: str = "1.0.0"
    reference_mode: BulkReferenceMode | None = None
    project_name: str = Field(min_length=1, max_length=120)
    project_identifier: UUID
    created_at: datetime
    input_directory: str
    output_directory: str
    pipeline_identifier: Literal["bulk-rnaseq", "ont-analysis"] = "bulk-rnaseq"
    pipeline_version: str = "0.1.0-preview"
    organism: str
    reference_genome: str
    annotation_source: str
    reference_resources: dict[str, str] = Field(default_factory=dict)
    reference_provenance: dict[str, Any] | None = None
    library_type: str
    read_layout: ReadLayout
    strandedness: Strandedness
    samples: list[SampleRecord] = Field(min_length=1)
    comparisons: list[Comparison] = Field(default_factory=list)
    figure_configuration: FigureConfiguration | None = None
    parameters: dict[str, Scalar] = Field(default_factory=dict)
    resource_profile: ResourceProfile = Field(default_factory=ResourceProfile)
    execution_profile: ExecutionProfile = ExecutionProfile.LOCAL
    application_version: str = "0.1.0"
    pipeline_status: PipelineStatus = PipelineStatus.DRAFT

    @field_validator("input_directory", "output_directory")
    @classmethod
    def normalize_project_paths(cls, value: str) -> str:
        return normalize_user_path(value)

    @field_validator("reference_resources")
    @classmethod
    def normalize_reference_paths(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: normalize_user_path(value) for key, value in values.items() if value.strip()}

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        value = value.strip()
        if value not in {"1.0.0", "1.1.0"}:
            raise ValueError("unsupported schema_version")
        return value

    @field_validator(
        "project_name",
        "pipeline_identifier",
        "pipeline_version",
        "organism",
        "reference_genome",
        "annotation_source",
        "library_type",
        "application_version",
    )
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value

    @model_validator(mode="after")
    def validate_manifest_invariants(self) -> ProjectManifest:
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("sample identifiers must be unique")

        comparison_ids = [comparison.comparison_id for comparison in self.comparisons]
        if len(comparison_ids) != len(set(comparison_ids)):
            raise ValueError("comparison identifiers must be unique")

        if self.pipeline_identifier == "bulk-rnaseq":
            self._validate_bulk_reference_contract()

        return self

    def _validate_bulk_reference_contract(self) -> None:
        resources = self.reference_resources
        analysis_only = self.parameters.get("start_stage") == "analysis"
        mode = self.reference_mode
        if mode is None:
            if self.schema_version == "1.1.0":
                raise ValueError("bulk RNA-seq manifests at schema 1.1.0 require reference_mode")
            return

        has_fasta = bool(resources.get("transcriptome_fasta"))
        has_gtf = bool(resources.get("annotation_gtf"))
        has_index = bool(resources.get("kallisto_index"))
        has_mapping = bool(resources.get("transcript_to_gene"))
        has_annotation = has_gtf or has_mapping

        if analysis_only:
            if not has_annotation:
                raise ValueError(
                    "analysis-only bulk projects require annotation_gtf or transcript_to_gene"
                )
            if mode == BulkReferenceMode.BUILD and has_index:
                raise ValueError("analysis-only build mode must not include kallisto_index")
            return

        if mode == BulkReferenceMode.BUILD:
            if not has_fasta or not has_gtf:
                raise ValueError(
                    "build reference mode requires transcriptome_fasta and annotation_gtf"
                )
            if has_index:
                raise ValueError("build reference mode must not include kallisto_index")
            return

        if mode == BulkReferenceMode.EXISTING_INDEX:
            if not has_index:
                raise ValueError("existing-index reference mode requires kallisto_index")
            if not has_annotation:
                raise ValueError(
                    "existing-index reference mode requires annotation_gtf or transcript_to_gene"
                )
            return

        raise ValueError("unsupported bulk reference mode")


class ProjectValidationResult(BaseModel):
    valid: bool
    manifest: ProjectManifest
    checks: list[Any] = Field(default_factory=list)


class ProjectSaveResult(BaseModel):
    project_directory: str
    manifest_path: str
    created_directories: list[str]
    bytes_written: int
