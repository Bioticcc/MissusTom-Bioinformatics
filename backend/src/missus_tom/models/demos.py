from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class DemoPrepareRequest(BaseModel):
    """Explicit acknowledgement before the backend writes a local demo bundle."""

    consent: Literal[True] = Field(
        ..., description="Confirm creation of local synthetic demo files"
    )


class DemoPrepareStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DemoPrepareJob(BaseModel):
    job_identifier: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    pipeline_identifier: str
    status: DemoPrepareStatus
    message: str
    current_stage: str
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_output_at: datetime | None = None
    log_tail: list[str] = Field(default_factory=list)


class DemoIntegrity(BaseModel):
    manifest_path: str
    sha256: str
    file_count: int


class DemoStatus(BaseModel):
    pipeline_identifier: str
    title: str
    available: bool
    bundle_directory: str
    manifest_path: str | None = None
    integrity: DemoIntegrity | None = None
    prepared_at: datetime | None = None
    message: str
    execution_note: str
    job: DemoPrepareJob | None = None
    execution_supported: bool = False
