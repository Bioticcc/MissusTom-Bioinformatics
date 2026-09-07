from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from missus_tom.models.manifest import ProjectManifest


class StageStatus(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlannedStage(BaseModel):
    stage_id: str
    name: str
    description: str
    status: StageStatus = StageStatus.PLANNED
    resumable: bool = True
    source_mapping: str | None = None


class RunPlan(BaseModel):
    project_identifier: str
    pipeline_identifier: str
    pipeline_version: str
    execution_profile: str
    execution_enabled: bool = False
    stages: list[PlannedStage]
    command_preview: list[str]
    estimated_input_bytes: int
    log_directory: str
    results_directory: str
    warnings: list[str] = Field(default_factory=list)


class PipelineStatusResult(BaseModel):
    pipeline_identifier: str
    pipeline_version: str
    available: bool
    execution_enabled: bool
    message: str
    stages: list[PlannedStage]
    output_categories: list[str]


class RunPlanRequest(BaseModel):
    manifest: ProjectManifest


class RunStartStage(StrEnum):
    QUANTIFICATION = "quantification"
    ANALYSIS = "analysis"


class RunStartRequest(BaseModel):
    manifest: ProjectManifest
    resume: bool = True
    start_stage: RunStartStage = RunStartStage.QUANTIFICATION


class RunStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RunRecord(BaseModel):
    job_identifier: str
    project_identifier: str
    project_name: str
    status: RunStatus
    current_stage: str | None = None
    command: list[str]
    log_path: str
    results_directory: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error_message: str | None = None
    resume: bool = True
    nextflow_run_name: str | None = None
    resume_from_run_name: str | None = None
    start_stage: RunStartStage = RunStartStage.QUANTIFICATION
    process_id: int | None = None
    process_group_id: int | None = None
    process_start_ticks: int | None = None
    process_boot_id: str | None = None
    holds_admission: bool = False
    container_cleanup_required: bool = False
    container_cleanup_verified_at: datetime | None = None


class RunLog(BaseModel):
    job_identifier: str
    text: str
    truncated: bool = False


class ResultArtifact(BaseModel):
    category: str
    relative_path: str
    size_bytes: int
    modified_at: datetime


class HumanDemoProject(BaseModel):
    manifest: ProjectManifest
    plan: RunPlan
