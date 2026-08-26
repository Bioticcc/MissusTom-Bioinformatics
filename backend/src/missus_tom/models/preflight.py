from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CheckStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    BLOCKING = "blocking_failure"
    NOT_CONFIGURED = "not_yet_configured"


class PreflightCheck(BaseModel):
    check_id: str
    label: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class SystemPreflightResult(BaseModel):
    ready_for_framework: bool
    ready_for_real_execution: bool
    checks: list[PreflightCheck]
