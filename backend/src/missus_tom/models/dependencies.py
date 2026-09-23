from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class DependencyInstallStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DependencyRequirement(BaseModel):
    name: str
    installed: bool
    managed: bool = False
    detail: str


class DependencyInstallJob(BaseModel):
    job_identifier: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    pipeline_identifier: str
    status: DependencyInstallStatus
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_output_at: datetime | None = None
    current_stage: str = ""
    log_tail: list[str] = Field(default_factory=list)


class DependencyStatus(BaseModel):
    pipeline_identifier: str
    requirements: list[DependencyRequirement]
    missing: list[str] = Field(default_factory=list)
    installable: bool
    manual_requirements: list[str] = Field(default_factory=list)
    job: DependencyInstallJob | None = None


class DependencyInstallRequest(BaseModel):
    """Explicit acknowledgement prevents a cross-site simple POST from installing tools."""

    consent: Literal[True]
