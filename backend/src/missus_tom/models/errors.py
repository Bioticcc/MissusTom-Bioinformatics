"""Stable API error codes for Setup and other operator-facing failures."""

from __future__ import annotations

DEPENDENCY_INSTALL_IN_PROGRESS = "dependency_install_in_progress"
WORKFLOW_ADMISSION_LOCKED = "workflow_admission_locked"
UNSUPPORTED_PIPELINE = "unsupported_pipeline"
DEPENDENCY_PREREQUISITE_FAILED = "dependency_prerequisite_failed"
DEPENDENCY_VERIFICATION_FAILED = "dependency_verification_failed"


class ApiCodedError(Exception):
    """HTTP error that preserves a stable machine-readable code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
