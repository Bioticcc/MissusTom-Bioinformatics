from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from missus_tom.config import settings
from missus_tom.models.common import ApiResponse
from missus_tom.models.directories import DirectoryPreview, DirectoryPreviewRequest
from missus_tom.models.discovery import FastqDiscoveryRequest, FastqDiscoveryResult
from missus_tom.models.manifest import (
    ProjectManifest,
    ProjectSaveResult,
    ProjectValidationResult,
)
from missus_tom.models.preflight import SystemPreflightResult
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
from missus_tom.pipeline_adapters import BulkRnaSeqAdapter
from missus_tom.services.directories import preview_directory
from missus_tom.services.fastq import discover_fastqs
from missus_tom.services.preflight import system_preflight
from missus_tom.services.projects import save_project, validate_project
from missus_tom.services.runs import RunManager

router = APIRouter()
adapter = BulkRnaSeqAdapter()
run_manager = RunManager(adapter)


@router.get("/health", response_model=ApiResponse[dict[str, Any]])
async def health() -> ApiResponse[dict[str, Any]]:
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
async def get_system_preflight() -> ApiResponse[SystemPreflightResult]:
    return ApiResponse(data=system_preflight())


@router.post(
    f"{settings.api_prefix}/fastq/discover",
    response_model=ApiResponse[FastqDiscoveryResult],
)
async def post_fastq_discover(
    request: FastqDiscoveryRequest,
) -> ApiResponse[FastqDiscoveryResult]:
    try:
        result = discover_fastqs(request.directory, request.recursive)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post(
    f"{settings.api_prefix}/directories/preview",
    response_model=ApiResponse[DirectoryPreview],
)
async def post_directory_preview(
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
async def post_project_validate(
    manifest: ProjectManifest,
) -> ApiResponse[ProjectValidationResult]:
    return ApiResponse(data=validate_project(manifest))


@router.post(
    f"{settings.api_prefix}/projects/save",
    response_model=ApiResponse[ProjectSaveResult],
)
async def post_project_save(manifest: ProjectManifest) -> ApiResponse[ProjectSaveResult]:
    try:
        result = save_project(manifest)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post(f"{settings.api_prefix}/runs/plan", response_model=ApiResponse[RunPlan])
async def post_run_plan(request: RunPlanRequest) -> ApiResponse[RunPlan]:
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
async def get_human_demo() -> ApiResponse[HumanDemoProject]:
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
        data=HumanDemoProject(manifest=manifest, plan=adapter.construct_run_plan(manifest))
    )


@router.post(f"{settings.api_prefix}/runs/start", response_model=ApiResponse[RunRecord])
async def post_run_start(request: RunStartRequest) -> ApiResponse[RunRecord]:
    checks = adapter.validate_project(request.manifest)
    blocking = [check.message for check in checks if check.status.value == "blocking_failure"]
    if blocking:
        raise HTTPException(
            status_code=409,
            detail="Run has blocking validation failures: " + "; ".join(blocking),
        )
    try:
        record = run_manager.start(request.manifest, resume=request.resume)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data=record)


@router.get(f"{settings.api_prefix}/runs", response_model=ApiResponse[list[RunRecord]])
async def get_runs() -> ApiResponse[list[RunRecord]]:
    return ApiResponse(data=run_manager.list_runs())


@router.get(f"{settings.api_prefix}/runs/{{job_identifier}}", response_model=ApiResponse[RunRecord])
async def get_run(job_identifier: str) -> ApiResponse[RunRecord]:
    try:
        record = run_manager.get(job_identifier)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=record)


@router.get(
    f"{settings.api_prefix}/runs/{{job_identifier}}/logs",
    response_model=ApiResponse[RunLog],
)
async def get_run_log(
    job_identifier: str,
    limit: int = Query(default=100_000, ge=1_000, le=1_000_000),
) -> ApiResponse[RunLog]:
    try:
        log = run_manager.read_log(job_identifier, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=log)


@router.get(
    f"{settings.api_prefix}/runs/{{job_identifier}}/artifacts",
    response_model=ApiResponse[list[ResultArtifact]],
)
async def get_run_artifacts(job_identifier: str) -> ApiResponse[list[ResultArtifact]]:
    try:
        artifacts = run_manager.artifacts(job_identifier)
    except (KeyError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=artifacts)


@router.post(
    f"{settings.api_prefix}/runs/{{job_identifier}}/cancel",
    response_model=ApiResponse[RunRecord],
)
async def post_run_cancel(job_identifier: str) -> ApiResponse[RunRecord]:
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
async def get_pipelines() -> ApiResponse[list[PipelineStatusResult]]:
    return ApiResponse(data=[adapter.inspect_availability()])


@router.get(
    f"{settings.api_prefix}/pipelines/bulk-rnaseq/status",
    response_model=ApiResponse[PipelineStatusResult],
)
async def get_bulk_pipeline_status() -> ApiResponse[PipelineStatusResult]:
    return ApiResponse(data=adapter.inspect_availability())
