from __future__ import annotations

import json
import stat
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from missus_tom.api import routes
from missus_tom.models.demos import DemoPrepareRequest, DemoPrepareStatus
from missus_tom.services import demos as demos_module
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


@pytest.fixture
def kallisto_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "kallisto-stub"
    script.write_text(
        """#!/bin/sh
if [ "$1" = "index" ] && [ "$2" = "-i" ] && [ -n "$3" ]; then
  printf 'KALLISTO\\0stub-index' > "$3"
  exit 0
fi
exit 2
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    def runtime_tool(name: str, pipeline_identifier: str) -> str | None:
        if name == "kallisto" and pipeline_identifier == "bulk-rnaseq":
            return str(script)
        return None

    monkeypatch.setattr(demos_module, "runtime_tool", runtime_tool)
    monkeypatch.setattr(demos_module, "runtime_environment", lambda _: {"PATH": str(tmp_path)})
    return script


def wait_for_prepare(
    service: DemoService, job_identifier: str, *, timeout: float = 60.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.prepare_job(job_identifier)
        if job.status in {DemoPrepareStatus.SUCCEEDED, DemoPrepareStatus.FAILED}:
            if job.status == DemoPrepareStatus.FAILED:
                pytest.fail(job.message)
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
    kallisto_stub: Path,
    pipeline_identifier: str,
) -> None:
    del kallisto_stub
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
    assert metadata["fixture_version"] == "2"
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
        index_bytes = (bundle / "references/transcripts.idx").read_bytes()
        assert not index_bytes.startswith(b"NOT_A_KALLISTO")
        manifest = json.loads((bundle / "project_manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["samples"]) == 4
        biomart_lines = (bundle / "references/biomart.tsv").read_text(encoding="utf-8").splitlines()
        biomart_header = biomart_lines[0]
        assert biomart_header == "Gene stable ID version\tGene type\tGene name"
        project = routes.get_bulk_rnaseq_demo_project().data
        assert project is not None and project.manifest.pipeline_identifier == "bulk-rnaseq"


def test_status_rejects_tampered_fixture_file(
    demos: DemoService, kallisto_stub: Path
) -> None:
    del kallisto_stub
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


def test_prepare_job_log_endpoint(
    demos: DemoService, kallisto_stub: Path
) -> None:
    del kallisto_stub
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
