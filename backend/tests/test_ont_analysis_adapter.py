from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.preflight import CheckStatus
from missus_tom.pipeline_adapters.ont_analysis import OntAnalysisAdapter


def ont_manifest(tmp_path: Path) -> ProjectManifest:
    inputs = tmp_path / "inputs"
    references = tmp_path / "references"
    inputs.mkdir()
    references.mkdir()
    bam = inputs / "mouse_pass.bam"
    bam.touch()
    resources = {}
    for key in (
        "reference_fasta",
        "reference_fai",
        "minimap2_index",
        "gencode_gff3",
        "cpg_islands",
        "ccre_table",
        "intergenic_bed",
        "ont_instrument_report",
    ):
        path = references / key
        path.touch()
        resources[key] = str(path)
    return ProjectManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "project_name": "Mouse ONT pilot",
            "project_identifier": str(uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "input_directory": str(inputs),
            "output_directory": str(tmp_path / "output"),
            "pipeline_identifier": "ont-analysis",
            "pipeline_version": "0.1.0",
            "organism": "Mus musculus",
            "reference_genome": "GRCm38p6",
            "annotation_source": "GENCODE",
            "reference_resources": resources,
            "library_type": "ONT",
            "read_layout": "single-end",
            "strandedness": "unknown",
            "samples": [
                {
                    "sample_id": "mouse_01",
                    "condition": "single_sample",
                    "biological_replicate": "1",
                    "ont_bam_files": [str(bam)],
                }
            ],
            "comparisons": [],
            "parameters": {"expected_pass_bam_count": 1},
            "resource_profile": {"cpus": 1, "memory_gb": 1, "max_parallel_tasks": 1},
            "execution_profile": "local",
            "application_version": "0.1.0",
            "pipeline_status": "draft",
        }
    )


def test_ont_adapter_accepts_one_contained_mouse_bam(tmp_path: Path) -> None:
    manifest = ont_manifest(tmp_path)
    adapter = OntAnalysisAdapter()

    checks = adapter.validate_project(manifest)
    plan = adapter.construct_run_plan(manifest)

    assert not [check for check in checks if check.status == CheckStatus.BLOCKING]
    assert [stage.stage_id for stage in plan.stages] == [
        "align_modbam",
        "finalize_alignment",
        "ont_qc_coverage",
        "methylation",
        "methylation_exploration",
    ]
    assert plan.command_preview[0] == sys.executable
    assert plan.command_preview[1].endswith("workflows/ont_analysis/run_pipeline.py")
    assert "--manifest" in plan.command_preview
    assert "--outdir" in plan.command_preview


def test_ont_runner_working_directory_remains_its_installed_workflow(tmp_path: Path) -> None:
    adapter = OntAnalysisAdapter()

    assert adapter.runner_working_directory(tmp_path / "project") == adapter.workflow_directory


def test_ont_adapter_uses_packaged_runner_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = tmp_path / "ont-analysis-runner-linux-x86_64"
    monkeypatch.setenv("MISSUS_TOM_ONT_RUNNER", str(runner))

    command = OntAnalysisAdapter().construct_command(ont_manifest(tmp_path))

    assert command[0] == str(runner.resolve())
    assert sys.executable not in command
    assert command[1:] == [
        "--manifest",
        str(tmp_path / "output" / "input_manifest" / "project_manifest.json"),
        "--outdir",
        str(tmp_path / "output" / "results"),
    ]


def test_ont_adapter_accepts_core_references_without_annotation_or_instrument_files(
    tmp_path: Path,
) -> None:
    manifest = ont_manifest(tmp_path)
    payload = manifest.model_dump(mode="json")
    payload["reference_resources"] = {
        key: value
        for key, value in payload["reference_resources"].items()
        if key in {"reference_fasta", "reference_fai", "minimap2_index"}
    }

    checks = OntAnalysisAdapter().validate_project(ProjectManifest.model_validate(payload))
    references = next(check for check in checks if check.check_id == "references")

    assert references.status == CheckStatus.PASSED
    assert "not configured" in references.message


def test_ont_adapter_rejects_partial_annotations_and_invalid_optional_report(
    tmp_path: Path,
) -> None:
    manifest = ont_manifest(tmp_path)
    payload = manifest.model_dump(mode="json")
    payload["reference_resources"] = {
        key: value
        for key, value in payload["reference_resources"].items()
        if key in {"reference_fasta", "reference_fai", "minimap2_index", "gencode_gff3"}
    }
    checks = OntAnalysisAdapter().validate_project(ProjectManifest.model_validate(payload))
    references = next(check for check in checks if check.check_id == "references")
    assert references.status == CheckStatus.BLOCKING
    assert "ccre_table" in references.message

    payload["reference_resources"] = {
        key: value
        for key, value in manifest.model_dump(mode="json")["reference_resources"].items()
        if key in {"reference_fasta", "reference_fai", "minimap2_index"}
    }
    payload["reference_resources"]["ont_instrument_report"] = str(tmp_path / "missing.html")
    checks = OntAnalysisAdapter().validate_project(ProjectManifest.model_validate(payload))
    references = next(check for check in checks if check.check_id == "references")
    assert references.status == CheckStatus.BLOCKING
    assert "ont_instrument_report" in references.message


def test_ont_adapter_rejects_comparisons_and_bam_basename_collisions(tmp_path: Path) -> None:
    manifest = ont_manifest(tmp_path)
    payload = manifest.model_dump(mode="json")
    other = Path(payload["input_directory"]) / "other" / "mouse_pass.bam"
    other.parent.mkdir()
    other.touch()
    payload["samples"][0]["ont_bam_files"].append(str(other))
    payload["comparisons"] = [
        {"comparison_id": "not_allowed", "numerator": "a", "denominator": "b"}
    ]

    checks = OntAnalysisAdapter().validate_project(ProjectManifest.model_validate(payload))
    failures = {
        check.check_id: check.message for check in checks if check.status == CheckStatus.BLOCKING
    }

    assert "comparisons" in failures
    assert "ont_bam_files" in failures
    assert "basename collision" in failures["ont_bam_files"]


def test_ont_adapter_rejects_invalid_window_and_modkit_parameters(tmp_path: Path) -> None:
    manifest = ont_manifest(tmp_path)
    payload = manifest.model_dump(mode="json")
    payload["parameters"] = {
        "coverage_window_size": 0,
        "methylation_window_size": True,
        "modkit_filter_percentile": 1.0,
        "modkit_max_depth": 60_001,
        "exploration_min_valid_coverage": -1,
        "exploration_min_feature_cpgs": 0,
    }

    checks = OntAnalysisAdapter().validate_project(ProjectManifest.model_validate(payload))
    parameters = next(check for check in checks if check.check_id == "pipeline_parameters")

    assert parameters.status == CheckStatus.BLOCKING
    assert "modkit_filter_percentile" in parameters.message
    assert "modkit_max_depth" in parameters.message


def test_ont_adapter_requires_coordinate_aligned_window_sizes(tmp_path: Path) -> None:
    manifest = ont_manifest(tmp_path)
    payload = manifest.model_dump(mode="json")
    payload["parameters"] = {
        "coverage_window_size": 100_000,
        "methylation_window_size": 50_000,
    }

    checks = OntAnalysisAdapter().validate_project(ProjectManifest.model_validate(payload))
    parameters = next(check for check in checks if check.check_id == "pipeline_parameters")

    assert parameters.status == CheckStatus.BLOCKING
    assert "coverage_window_size and methylation_window_size" in parameters.message


def test_ont_adapter_rejects_output_nested_under_inputs(tmp_path: Path) -> None:
    manifest = ont_manifest(tmp_path)
    payload = manifest.model_dump(mode="json")
    payload["output_directory"] = str(Path(payload["input_directory"]) / "results")

    checks = OntAnalysisAdapter().validate_project(ProjectManifest.model_validate(payload))
    separation = next(check for check in checks if check.check_id == "path_separation")

    assert separation.status == CheckStatus.BLOCKING
