from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DemoPrepareRequest(BaseModel):
    """Explicit acknowledgement before the backend writes a local demo bundle."""

    consent: Literal[True] = Field(
        ..., description="Confirm creation of local synthetic demo files"
    )


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
