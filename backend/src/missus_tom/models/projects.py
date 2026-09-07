from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from missus_tom.models.manifest import (
    ProjectManifest,
    ProjectValidationResult,
    normalize_user_path,
)
from missus_tom.models.run import RunPlan


class ProjectSummary(BaseModel):
    project_identifier: str
    project_name: str
    manifest_path: str
    updated_at: datetime
    available: bool

    @field_validator("updated_at")
    @classmethod
    def history_timestamp_is_utc(cls, value: datetime) -> datetime:
        # SQLite datetime('now') is UTC but omits an offset in its stored text.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class ProjectOpenRequest(BaseModel):
    manifest_path: str = Field(min_length=1)

    @field_validator("manifest_path")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        return normalize_user_path(value)


class ProjectOpenResult(BaseModel):
    manifest: ProjectManifest
    validation: ProjectValidationResult
    plan: RunPlan
