from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from missus_tom.models.manifest import ProjectManifest
from missus_tom.services.projects import validate_project


def test_valid_manifest_passes_structural_and_project_validation(
    manifest_payload: dict[str, Any],
) -> None:
    manifest = ProjectManifest.model_validate(manifest_payload)
    validation = validate_project(manifest)

    assert validation.valid is True
    assert manifest.input_directory.startswith("/")


def test_duplicate_sample_identifiers_are_rejected(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["samples"][1]["sample_id"] = payload["samples"][0]["sample_id"]

    with pytest.raises(ValidationError, match="sample identifiers must be unique"):
        ProjectManifest.model_validate(payload)


def test_paired_sample_requires_equal_mate_counts(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["samples"][0]["r2_files"] = []

    with pytest.raises(ValidationError, match="has no R2 files"):
        ProjectManifest.model_validate(payload)


def test_contrast_groups_must_differ(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["comparisons"][0]["numerator"] = "control"

    with pytest.raises(ValidationError, match="numerator and denominator must differ"):
        ProjectManifest.model_validate(payload)


def test_unknown_contrast_group_is_blocking(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["comparisons"][0]["numerator"] = "unknown"
    manifest = ProjectManifest.model_validate(payload)

    result = validate_project(manifest)

    assert result.valid is False
    assert any(check.check_id == "comparisons" for check in result.checks)


def test_output_ancestor_of_input_is_blocking(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["output_directory"] = str(Path(payload["input_directory"]).parent)
    manifest = ProjectManifest.model_validate(payload)

    result = validate_project(manifest)

    assert result.valid is False
    separation = next(check for check in result.checks if check.check_id == "path_separation")
    assert separation.status.value == "blocking_failure"


def test_duplicate_fastq_assignment_is_blocking(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["samples"][1]["r1_files"] = payload["samples"][0]["r1_files"]
    manifest = ProjectManifest.model_validate(payload)

    result = validate_project(manifest)

    assert result.valid is False
    fastq_check = next(check for check in result.checks if check.check_id == "fastq_pairing")
    assert fastq_check.details["duplicate_assignment_count"] == 1
