from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from missus_tom.api import routes
from missus_tom.models.demos import DemoPrepareRequest, DemoPrepareStatus
from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest
from missus_tom.pipeline_adapters.bulk_rnaseq import BulkRnaSeqAdapter
from missus_tom.services.demos import (
    DemoService,
    lcg_sequence,
    reverse_complement,
    synthetic_read_count,
)


@pytest.fixture
def demos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DemoService:
    state = tmp_path / "state"
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(state))
    service = DemoService(state_directory=state)
    monkeypatch.setattr(routes, "demo_service", service)
    return service


def wait_for_prepare(service: DemoService, job_identifier: str, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.prepare_job(job_identifier)
        if job.status in {DemoPrepareStatus.SUCCEEDED, DemoPrepareStatus.FAILED}:
            if job.status == DemoPrepareStatus.FAILED:
                pytest.fail(job.message)
            worker = service._threads.get(job_identifier)
            if worker is not None:
                worker.join(timeout=1)
                assert not worker.is_alive(), "demo preparation worker did not release its lock"
            return
        time.sleep(0.05)
    pytest.fail("demo preparation timed out")


def test_catalog_has_only_supported_synthetic_demos(demos: DemoService) -> None:
    response = routes.get_demos()

    data = response.data
    assert data is not None
    assert [item.pipeline_identifier for item in data] == [
        "bulk-rnaseq",
        "ont-analysis",
    ]
    assert all(not item.available for item in data)
    assert all(not item.execution_supported for item in data)
    assert all(item.bundle_directory.startswith(str(demos.state_directory)) for item in data)


@pytest.mark.parametrize("payload", ({}, {"consent": False}))
def test_prepare_requires_explicit_true_consent(
    demos: DemoService, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        DemoPrepareRequest.model_validate(payload)


def test_lcg_sequence_matches_smoke_length_and_alphabet() -> None:
    sequence = lcg_sequence(17)
    assert len(sequence) == 220
    assert set(sequence) <= {"A", "C", "G", "T"}
    assert reverse_complement("ACGT") == "ACGT"[::-1].translate(str.maketrans("ACGT", "TGCA"))


def test_synthetic_read_count_is_deterministic() -> None:
    assert synthetic_read_count("H1", 0) == 35 + (-8)
    assert synthetic_read_count("OD1", 0) == 105 + (-12)


@pytest.mark.parametrize("pipeline_identifier", ("bulk-rnaseq", "ont-analysis"))
def test_prepare_writes_regeneratable_synthetic_bundle_with_self_consistency_metadata(
    demos: DemoService,
    pipeline_identifier: str,
) -> None:
    response = routes.post_demo_prepare(pipeline_identifier, DemoPrepareRequest(consent=True))

    job = response.data
    assert job is not None
    wait_for_prepare(demos, job.job_identifier)

    status = routes.get_demo_status(pipeline_identifier).data
    assert status is not None and status.available is True
    bundle = Path(status.bundle_directory)
    metadata = json.loads((bundle / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
    assert metadata["synthetic_only"] is True
    assert metadata["network_downloads"] is False
    assert metadata["fixture_version"] == "4"
    assert metadata["pipeline_identifier"] == pipeline_identifier
    assert set(metadata["files"]) >= {
        "README.txt",
        "fixture_metadata.json",
        "project_manifest.json",
    }
    assert all(
        not Path(relative).is_absolute() and ".." not in Path(relative).parts
        for relative in metadata["files"]
    )
    assert "not" in status.execution_note.lower()
    fixture_metadata = json.loads((bundle / "fixture_metadata.json").read_text(encoding="utf-8"))
    if pipeline_identifier == "ont-analysis":
        assert fixture_metadata["execution_supported"] is False
        assert not status.execution_supported
        assert (bundle / "inputs/synthetic_pass_modbam.bam").read_bytes().startswith(b"NOT_A_BAM")
    else:
        assert fixture_metadata["execution_supported"] is True
        assert status.execution_supported
        assert not (bundle / "references/biomart.tsv").exists()
        assert not (bundle / "references/transcripts.idx").exists()
        manifest = json.loads((bundle / "project_manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["samples"]) == 4
        assert manifest["schema_version"] == "1.1.0"
        assert manifest["reference_mode"] == BulkReferenceMode.BUILD.value
        assert manifest["pipeline_version"] == "0.5.0"
        assert manifest["reference_resources"] == {
            "annotation_gtf": str((bundle / "references/annotation.gtf").resolve()),
            "transcriptome_fasta": str((bundle / "references/transcripts.fa").resolve()),
        }
        assert manifest["parameters"] == {
            "absolute_log2_fold_change": 0.3,
            "adapter_r1": "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA",
            "adapter_r2": "AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT",
            "adjusted_p_value": 0.05,
            "demo_fixture": True,
            "minimum_group_size": 2,
            "scientific_execution_supported": True,
            "synthetic": True,
            "trim_minimum_length": 20,
            "trim_quality": 20,
        }
        gtf_text = (bundle / "references/annotation.gtf").read_text(encoding="utf-8")
        assert 'gene_name "SMOKEPC1"' in gtf_text
        assert 'gene_type "protein_coding"' in gtf_text
        assert 'transcript_type "protein_coding"' in gtf_text
        assert 'gene_name "SMOKELNC1"' in gtf_text
        assert 'gene_type "lncRNA"' in gtf_text
        assert 'transcript_type "lncRNA"' in gtf_text
        fasta_text = (bundle / "references/transcripts.fa").read_text(encoding="utf-8")
        assert "ENST" not in fasta_text and "ENSG" not in fasta_text
        assert ">TX000001|" in fasta_text
        project = routes.get_bulk_rnaseq_demo_project().data
        assert project is not None and project.manifest.pipeline_identifier == "bulk-rnaseq"
        validated = ProjectManifest.model_validate(manifest)
        assert validated.reference_mode == BulkReferenceMode.BUILD
        saved_manifest = bundle / "project-output/input_manifest/project_manifest.json"
        assert saved_manifest.is_file()
        assert json.loads(saved_manifest.read_text(encoding="utf-8")) == manifest
        BulkRnaSeqAdapter.validate_saved_manifest(project.manifest)
        log_text = routes.get_demo_prepare_job_log(
            pipeline_identifier, job.job_identifier, offset=0, limit=100_000
        ).data
        assert log_text is not None
        assert "building_index" not in log_text.text.lower()
        assert "kallisto index" not in log_text.text.lower()


def test_stale_non_executable_bulk_fixture_is_prepared_before_project_load(
    demos: DemoService,
) -> None:
    first = routes.post_demo_prepare("bulk-rnaseq", DemoPrepareRequest(consent=True)).data
    assert first is not None
    wait_for_prepare(demos, first.job_identifier)

    bundle = demos.root / "bulk-rnaseq"
    fixture_path = bundle / "fixture_metadata.json"
    fixture_metadata = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_metadata["execution_supported"] = False
    fixture_path.write_text(json.dumps(fixture_metadata), encoding="utf-8")
    bundle_metadata_path = bundle / "BUNDLE_MANIFEST.json"
    bundle_metadata = json.loads(bundle_metadata_path.read_text(encoding="utf-8"))
    bundle_metadata["files"]["fixture_metadata.json"] = demos._sha256(fixture_path)
    bundle_metadata_path.write_text(json.dumps(bundle_metadata), encoding="utf-8")

    stale = routes.get_demo_status("bulk-rnaseq").data
    assert stale is not None
    assert stale.available is False
    assert stale.execution_supported is False
    with pytest.raises(HTTPException, match="not available"):
        routes.get_bulk_rnaseq_demo_project()

    refreshed = routes.post_demo_prepare("bulk-rnaseq", DemoPrepareRequest(consent=True)).data
    assert refreshed is not None
    wait_for_prepare(demos, refreshed.job_identifier)
    project = routes.get_bulk_rnaseq_demo_project().data
    assert project is not None
    BulkRnaSeqAdapter.validate_saved_manifest(project.manifest)


def test_status_rejects_tampered_fixture_file(demos: DemoService) -> None:
    prepared = routes.post_demo_prepare("bulk-rnaseq", DemoPrepareRequest(consent=True))
    assert prepared.data is not None
    wait_for_prepare(demos, prepared.data.job_identifier)
    status = routes.get_demo_status("bulk-rnaseq")
    assert status.data is not None
    bundle = Path(status.data.bundle_directory)
    (bundle / "README.txt").write_text("tampered", encoding="utf-8")

    response = routes.get_demo_status("bulk-rnaseq")

    assert response.data is not None and response.data.available is False


def test_unknown_demo_is_not_created(demos: DemoService) -> None:
    with pytest.raises(HTTPException) as exc_info:
        routes.post_demo_prepare("unknown", DemoPrepareRequest(consent=True))

    assert exc_info.value.status_code == 404
    assert not (demos.root / "unknown").exists()


def test_prepare_job_log_endpoint(demos: DemoService) -> None:
    prepared = routes.post_demo_prepare("bulk-rnaseq", DemoPrepareRequest(consent=True))
    assert prepared.data is not None
    wait_for_prepare(demos, prepared.data.job_identifier)

    job_response = routes.get_demo_prepare_job("bulk-rnaseq", prepared.data.job_identifier)
    assert job_response.data is not None
    assert job_response.data.status == DemoPrepareStatus.SUCCEEDED

    log_response = routes.get_demo_prepare_job_log(
        "bulk-rnaseq", prepared.data.job_identifier, offset=0, limit=10_000
    )
    assert log_response.data is not None
    assert "Stage: preparing" in log_response.data.text
