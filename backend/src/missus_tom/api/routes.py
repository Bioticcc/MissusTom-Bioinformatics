from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from missus_tom.config import settings
from missus_tom.models.command_log import CommandLogChunk
from missus_tom.models.common import ApiResponse
from missus_tom.models.demos import DemoPrepareJob, DemoPrepareRequest, DemoStatus
from missus_tom.models.dependencies import (
    DependencyInstallJob,
    DependencyInstallRequest,
    DependencyStatus,
)
from missus_tom.models.directories import DirectoryPreview, DirectoryPreviewRequest
from missus_tom.models.discovery import (
    FastqDiscoveryRequest,
    FastqDiscoveryResult,
    QuantificationDiscoveryRequest,
    QuantificationDiscoveryResult,
)
from missus_tom.models.manifest import (
    ProjectManifest,
    ProjectSaveResult,
    ProjectValidationResult,
)
from missus_tom.models.metadata import MetadataCsvRequest, MetadataCsvResult
from missus_tom.models.preflight import SystemPreflightResult
from missus_tom.models.projects import ProjectOpenRequest, ProjectOpenResult, ProjectSummary
from missus_tom.models.run import (
    HumanDemoProject,
    PipelineStatusResult,
    ResultArtifact,
    RunLog,
    RunPlan,
    RunPlanRequest,
    RunRecord,
    RunStartRequest,
)
from missus_tom.pipeline_adapters import default_pipeline_registry
from missus_tom.pipeline_adapters.base import PipelineAdapter
from missus_tom.services.demos import demo_service
from missus_tom.services.dependencies import dependency_installer
from missus_tom.services.directories import preview_directory
from missus_tom.services.fastq import discover_fastqs
from missus_tom.services.metadata import read_metadata_csv
from missus_tom.services.preflight import system_preflight
from missus_tom.services.projects import (
    ProjectHistoryStore,
    open_project,
    save_project,
    validate_project,
)
from missus_tom.services.quantifications import discover_quantifications
from missus_tom.services.runs import RunManager

router = APIRouter()
pipeline_registry = default_pipeline_registry()
run_manager = RunManager(pipeline_registry)


def _adapter_for(manifest: ProjectManifest) -> PipelineAdapter:
    try:
        return pipeline_registry.for_manifest(manifest)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/health", response_model=ApiResponse[dict[str, Any]])
def health() -> ApiResponse[dict[str, Any]]:
    return ApiResponse(
        data={
            "name": settings.app_name,
            "version": settings.app_version,
            "status": "ok",
            "execution_enabled": settings.execution_enabled,
        }
    )


@router.get(
    f"{settings.api_prefix}/system/preflight",
    response_model=ApiResponse[SystemPreflightResult],
)
def get_system_preflight() -> ApiResponse[SystemPreflightResult]:
    return ApiResponse(data=system_preflight())


@router.post(
    f"{settings.api_prefix}/fastq/discover",
    response_model=ApiResponse[FastqDiscoveryResult],
)
def post_fastq_discover(
    request: FastqDiscoveryRequest,
) -> ApiResponse[FastqDiscoveryResult]:
    try:
        result = discover_fastqs(request.directory, request.recursive)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post(
    f"{settings.api_prefix}/quantifications/discover",
    response_model=ApiResponse[QuantificationDiscoveryResult],
)
def post_quantification_discover(
    request: QuantificationDiscoveryRequest,
) -> ApiResponse[QuantificationDiscoveryResult]:
    try:
        result = discover_quantifications(request.directory, request.recursive)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post(
    f"{settings.api_prefix}/metadata/csv",
    response_model=ApiResponse[MetadataCsvResult],
)
def post_metadata_csv(request: MetadataCsvRequest) -> ApiResponse[MetadataCsvResult]:
    try:
        result = read_metadata_csv(request.path, request.sample_ids)
    except (
        FileNotFoundError,
        PermissionError,
        UnicodeError,
        csv.Error,
        OSError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post(
    f"{settings.api_prefix}/directories/preview",
    response_model=ApiResponse[DirectoryPreview],
)
def post_directory_preview(
    request: DirectoryPreviewRequest,
) -> ApiResponse[DirectoryPreview]:
    try:
        result = preview_directory(request.directory)
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post(
    f"{settings.api_prefix}/projects/validate",
    response_model=ApiResponse[ProjectValidationResult],
)
def post_project_validate(
    manifest: ProjectManifest,
) -> ApiResponse[ProjectValidationResult]:
    return ApiResponse(data=validate_project(manifest, adapter=_adapter_for(manifest)))


@router.get(f"{settings.api_prefix}/projects", response_model=ApiResponse[list[ProjectSummary]])
def get_projects() -> ApiResponse[list[ProjectSummary]]:
    try:
        return ApiResponse(data=ProjectHistoryStore().list_projects())
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=409, detail="Project history could not be read") from exc


@router.post(f"{settings.api_prefix}/projects/open", response_model=ApiResponse[ProjectOpenResult])
def post_project_open(request: ProjectOpenRequest) -> ApiResponse[ProjectOpenResult]:
    try:
        manifest = open_project(Path(request.manifest_path))
        adapter = _adapter_for(manifest)
        validation = validate_project(manifest, adapter=adapter)
        plan = adapter.construct_run_plan(manifest)
        if not validation.valid:
            plan.execution_enabled = False
            plan.warnings.extend(
                check.message
                for check in validation.checks
                if check.status.value == "blocking_failure"
            )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="The saved project file is unavailable"
        ) from exc
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data=ProjectOpenResult(manifest=manifest, validation=validation, plan=plan))


@router.post(
    f"{settings.api_prefix}/projects/save",
    response_model=ApiResponse[ProjectSaveResult],
)
def post_project_save(manifest: ProjectManifest) -> ApiResponse[ProjectSaveResult]:
    try:
        result = save_project(manifest, adapter=_adapter_for(manifest))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post(f"{settings.api_prefix}/runs/plan", response_model=ApiResponse[RunPlan])
def post_run_plan(request: RunPlanRequest) -> ApiResponse[RunPlan]:
    adapter = _adapter_for(request.manifest)
    checks = adapter.validate_project(request.manifest)
    blocking = [check.message for check in checks if check.status.value == "blocking_failure"]
    if blocking:
        raise HTTPException(
            status_code=409,
            detail="Run plan has blocking validation failures: " + "; ".join(blocking),
        )
    return ApiResponse(data=adapter.construct_run_plan(request.manifest))


@router.get(
    f"{settings.api_prefix}/demos/human",
    response_model=ApiResponse[HumanDemoProject],
)
def get_human_demo() -> ApiResponse[HumanDemoProject]:
    manifest_path = settings.human_demo_manifest
    if manifest_path is None or not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="The prepared human demo is not available")
    try:
        manifest = ProjectManifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            status_code=409, detail="The prepared demo manifest is invalid"
        ) from exc
    return ApiResponse(
        data=HumanDemoProject(
            manifest=manifest, plan=_adapter_for(manifest).construct_run_plan(manifest)
        )
    )


@router.get(f"{settings.api_prefix}/demos", response_model=ApiResponse[list[DemoStatus]])
def get_demos() -> ApiResponse[list[DemoStatus]]:
    return ApiResponse(data=demo_service.list())


@router.get(
    f"{settings.api_prefix}/demos/{{pipeline_identifier}}/status",
    response_model=ApiResponse[DemoStatus],
)
def get_demo_status(pipeline_identifier: str) -> ApiResponse[DemoStatus]:
    try:
        return ApiResponse(data=demo_service.status(pipeline_identifier))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    f"{settings.api_prefix}/demos/{{pipeline_identifier}}/prepare",
    response_model=ApiResponse[DemoPrepareJob],
)
def post_demo_prepare(
    pipeline_identifier: str, request: DemoPrepareRequest
) -> ApiResponse[DemoPrepareJob]:
    # Typed consent prevents a bodyless cross-site-simple POST from creating files.
    del request
    try:
        return ApiResponse(data=demo_service.prepare(pipeline_identifier))
    except ValueError as exc:
        status_code = 404 if str(exc).startswith("unsupported demo") else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get(
    f"{settings.api_prefix}/demos/{{pipeline_identifier}}/prepare/jobs/{{job_identifier}}",
    response_model=ApiResponse[DemoPrepareJob],
)
def get_demo_prepare_job(
    pipeline_identifier: str, job_identifier: str
) -> ApiResponse[DemoPrepareJob]:
    del pipeline_identifier
    try:
        return ApiResponse(data=demo_service.prepare_job(job_identifier))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    f"{settings.api_prefix}/demos/{{pipeline_identifier}}/prepare/jobs/{{job_identifier}}/logs",
    response_model=ApiResponse[CommandLogChunk],
)
def get_demo_prepare_job_log(
    pipeline_identifier: str,
    job_identifier: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100_000, ge=1_000, le=1_000_000),
) -> ApiResponse[CommandLogChunk]:
    del pipeline_identifier
    try:
        return ApiResponse(data=demo_service.read_log(job_identifier, offset=offset, limit=limit))
    except ValueError as exc:
        status_code = 404 if str(exc).startswith("unknown demo prepare job") else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get(
    f"{settings.api_prefix}/demos/bulk-rnaseq/project",
    response_model=ApiResponse[HumanDemoProject],
)
def get_bulk_rnaseq_demo_project() -> ApiResponse[HumanDemoProject]:
    try:
        manifest = demo_service.load_project("bulk-rnaseq")
    except ValueError as exc:
        message = str(exc)
        if message.startswith("unsupported") or "not available" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=409, detail=message) from exc
    return ApiResponse(
        data=HumanDemoProject(
            manifest=manifest, plan=_adapter_for(manifest).construct_run_plan(manifest)
        )
    )


@router.post(f"{settings.api_prefix}/runs/start", response_model=ApiResponse[RunRecord])
def post_run_start(request: RunStartRequest) -> ApiResponse[RunRecord]:
    adapter = _adapter_for(request.manifest)
    validation_manifest = request.manifest.model_copy(
        update={
            "parameters": {
                **request.manifest.parameters,
                "start_stage": request.start_stage.value,
            }
        }
    )
    checks = adapter.validate_project(validation_manifest)
    blocking = [check.message for check in checks if check.status.value == "blocking_failure"]
    if blocking:
        raise HTTPException(
            status_code=409,
            detail="Run has blocking validation failures: " + "; ".join(blocking),
        )
    try:
        record = run_manager.start(
            request.manifest,
            resume=request.resume,
            start_stage=request.start_stage,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data=record)


@router.get(f"{settings.api_prefix}/runs", response_model=ApiResponse[list[RunRecord]])
def get_runs() -> ApiResponse[list[RunRecord]]:
    return ApiResponse(data=run_manager.list_runs())


@router.get(f"{settings.api_prefix}/runs/{{job_identifier}}", response_model=ApiResponse[RunRecord])
def get_run(job_identifier: str) -> ApiResponse[RunRecord]:
    try:
        record = run_manager.get(job_identifier)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=record)


@router.get(
    f"{settings.api_prefix}/runs/{{job_identifier}}/logs",
    response_model=ApiResponse[RunLog],
)
def get_run_log(
    job_identifier: str,
    offset: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100_000, ge=1_000, le=1_000_000),
) -> ApiResponse[RunLog]:
    try:
        log = run_manager.read_log(job_identifier, offset=offset, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=log)


@router.get(
    f"{settings.api_prefix}/runs/{{job_identifier}}/artifacts",
    response_model=ApiResponse[list[ResultArtifact]],
)
def get_run_artifacts(job_identifier: str) -> ApiResponse[list[ResultArtifact]]:
    try:
        artifacts = run_manager.artifacts(job_identifier)
    except (KeyError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=artifacts)


@router.post(
    f"{settings.api_prefix}/runs/{{job_identifier}}/cancel",
    response_model=ApiResponse[RunRecord],
)
def post_run_cancel(job_identifier: str) -> ApiResponse[RunRecord]:
    try:
        record = run_manager.cancel(job_identifier)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data=record)


@router.get(
    f"{settings.api_prefix}/pipelines",
    response_model=ApiResponse[list[PipelineStatusResult]],
)
def get_pipelines() -> ApiResponse[list[PipelineStatusResult]]:
    return ApiResponse(data=[adapter.inspect_availability() for adapter in pipeline_registry.all()])


@router.get(
    f"{settings.api_prefix}/pipelines/{{pipeline_identifier}}/status",
    response_model=ApiResponse[PipelineStatusResult],
)
def get_pipeline_status(pipeline_identifier: str) -> ApiResponse[PipelineStatusResult]:
    try:
        return ApiResponse(data=pipeline_registry.get(pipeline_identifier).inspect_availability())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    f"{settings.api_prefix}/pipelines/{{pipeline_identifier}}/dependencies",
    response_model=ApiResponse[DependencyStatus],
)
def get_pipeline_dependencies(pipeline_identifier: str) -> ApiResponse[DependencyStatus]:
    try:
        # The registry remains the public authority for supported identifiers.
        pipeline_registry.get(pipeline_identifier)
        return ApiResponse(data=dependency_installer.status(pipeline_identifier))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    f"{settings.api_prefix}/pipelines/{{pipeline_identifier}}/dependencies/install",
    response_model=ApiResponse[DependencyInstallJob],
)
def post_pipeline_dependencies_install(
    pipeline_identifier: str, request: DependencyInstallRequest
) -> ApiResponse[DependencyInstallJob]:
    # Typed consent is intentionally required: bodyless POST is cross-site-simple.
    del request
    try:
        pipeline_registry.get(pipeline_identifier)
        return ApiResponse(data=dependency_installer.install(pipeline_identifier))
    except ValueError as exc:
        message = str(exc)
        if message.startswith("unsupported pipeline identifier"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=409, detail=message) from exc


@router.get(
    f"{settings.api_prefix}/pipelines/{{pipeline_identifier}}/dependencies/jobs/{{job_identifier}}/logs",
    response_model=ApiResponse[CommandLogChunk],
)
def get_dependency_install_log(
    pipeline_identifier: str,
    job_identifier: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100_000, ge=1_000, le=1_000_000),
) -> ApiResponse[CommandLogChunk]:
    try:
        pipeline_registry.get(pipeline_identifier)
        job = dependency_installer.get_job(job_identifier)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job.pipeline_identifier != pipeline_identifier:
        raise HTTPException(status_code=404, detail="dependency job not found for this pipeline")
    return ApiResponse(
        data=dependency_installer.read_log(job_identifier, offset=offset, limit=limit)
    )
