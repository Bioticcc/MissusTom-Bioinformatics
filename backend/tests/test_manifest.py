from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest
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


def test_paired_sample_with_unequal_mates_is_blocking(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["samples"][0]["r2_files"] = []
    manifest = ProjectManifest.model_validate(payload)

    result = validate_project(manifest)

    assert result.valid is False
    assert any(check.check_id == "fastq_pairing" for check in result.checks)


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


def test_unknown_intervention_filter_is_blocking(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["comparisons"][0]["intervention"] = "D"
    manifest = ProjectManifest.model_validate(payload)

    result = validate_project(manifest)

    comparison = next(check for check in result.checks if check.check_id == "comparisons")
    assert comparison.status.value == "blocking_failure"
    assert "unknown interventions" in comparison.message


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


def test_condition_allows_human_readable_labels(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["samples"][0]["condition"] = "Drug treated"
    payload["comparisons"][0]["denominator"] = "Drug treated"

    manifest = ProjectManifest.model_validate(payload)

    assert manifest.samples[0].condition == "Drug treated"


def test_design_fields_reject_line_breaks(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["samples"][0]["condition"] = "control\nmalformed"

    with pytest.raises(ValidationError, match="line breaks"):
        ProjectManifest.model_validate(payload)


def test_missing_biological_replicates_are_optional(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    for sample in payload["samples"]:
        sample["biological_replicate"] = ""
    manifest = ProjectManifest.model_validate(payload)

    result = validate_project(manifest)

    replicate_check = next(
        check for check in result.checks if check.check_id == "replicate_assignments"
    )
    assert result.valid is True
    assert replicate_check.status.value == "warning"
    assert "Optional biological replicate IDs" in replicate_check.message


def test_intervention_fields_reject_line_breaks(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["samples"][0]["covariates"]["intervention"] = "D\nmalformed"

    with pytest.raises(ValidationError, match="line breaks"):
        ProjectManifest.model_validate(payload)


def test_invalid_pipeline_threshold_is_blocking(manifest_payload: dict[str, Any]) -> None:
    payload = deepcopy(manifest_payload)
    payload["parameters"]["adjusted_p_value"] = 0
    manifest = ProjectManifest.model_validate(payload)

    result = validate_project(manifest)

    assert result.valid is False
    assert any(check.check_id == "pipeline_parameters" for check in result.checks)


def test_build_reference_mode_rejects_kallisto_index_in_manifest(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload["schema_version"] = "1.1.0"
    payload["reference_mode"] = BulkReferenceMode.BUILD.value

    with pytest.raises(ValidationError, match="build reference mode"):
        ProjectManifest.model_validate(payload)


def test_existing_index_mode_requires_annotation_or_mapping(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload["schema_version"] = "1.1.0"
    payload["reference_mode"] = BulkReferenceMode.EXISTING_INDEX.value
    payload["reference_resources"].pop("annotation_gtf")

    with pytest.raises(ValidationError, match="annotation_gtf or transcript_to_gene"):
        ProjectManifest.model_validate(payload)


def test_analysis_only_uses_kallisto_tables_instead_of_fastqs(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload["parameters"]["start_stage"] = "analysis"
    payload["reference_resources"].pop("kallisto_index")
    for sample in payload["samples"]:
        abundance = Path(payload["input_directory"]) / sample["sample_id"] / "abundance.tsv"
        abundance.parent.mkdir()
        abundance.write_text(
            "target_id\tlength\teff_length\test_counts\ttpm\n",
            encoding="utf-8",
        )
        sample["r1_files"] = []
        sample["r2_files"] = []
        sample["abundance_tsv"] = str(abundance)
    manifest = ProjectManifest.model_validate(payload)

    result = validate_project(manifest)

    assert result.valid is True
    fastq_check = next(check for check in result.checks if check.check_id == "fastq_pairing")
    abundance_check = next(
        check for check in result.checks if check.check_id == "quantification_inputs"
    )
    assert fastq_check.status.value == "not_yet_configured"
    assert abundance_check.status.value == "passed"
