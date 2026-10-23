from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PipelineSourceFile(BaseModel):
    path: str
    description: str = ""
    language: str
    size_bytes: int
    checksum: str


class PipelineSourceStatus(BaseModel):
    pipeline_identifier: str
    display_name: str
    source_type: str
    active_revision_id: str | None = None
    revision_id: str | None = None
    source_version: str
    files: list[PipelineSourceFile]


class PipelineSourceContent(BaseModel):
    pipeline_identifier: str
    path: str
    content: str
    checksum: str
    source_type: str
    revision_id: str | None = None


class SavePipelineSourceRequest(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=2_000_000)
    expected_revision_id: str | None = Field(default=None, max_length=100)


class PipelineRevision(BaseModel):
    revision_id: str
    pipeline_identifier: str
    created_at: datetime
    source_version: str
    files: list[PipelineSourceFile]
    active: bool = False


class PipelineDifference(BaseModel):
    path: str
    diff: str
