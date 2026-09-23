from __future__ import annotations

import asyncio
import stat
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from missus_tom.api import routes
from missus_tom.main import app
from missus_tom.models.demos import DemoPrepareStatus
from missus_tom.services import demos as demos_module
from missus_tom.services.demos import DemoService

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://missus-tom.test"
    ) as test_client:
        yield test_client


@pytest.fixture
def isolated_demo_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DemoService:
    service = DemoService(state_directory=tmp_path / "state")
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


async def test_health_reports_execution_enabled(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["execution_enabled"] is True


@pytest.mark.parametrize("origin", ("tauri://localhost", "http://tauri.localhost"))
async def test_tauri_origin_preflight_is_allowed(client: AsyncClient, origin: str) -> None:
    response = await client.options(
        "/api/v1/fastq/discover",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


async def test_discovery_endpoint(tmp_path: Path, client: AsyncClient) -> None:
    (tmp_path / "api_R1.fastq.gz").touch()
    (tmp_path / "api_R2.fastq.gz").touch()

    response = await client.post("/api/v1/fastq/discover", json={"directory": str(tmp_path)})

    assert response.status_code == 200
    assert response.json()["data"]["samples"][0]["pairing_status"] == "paired"


async def test_quantification_discovery_endpoint(tmp_path: Path, client: AsyncClient) -> None:
    abundance = tmp_path / "sample_A" / "abundance.tsv"
    abundance.parent.mkdir()
    abundance.write_text(
        "target_id\tlength\teff_length\test_counts\ttpm\n",
        encoding="utf-8",
    )

    response = await client.post(
        "/api/v1/quantifications/discover",
        json={"directory": str(tmp_path)},
    )

    assert response.status_code == 200
    assert response.json()["data"]["samples"][0]["abundance_tsv"] == str(abundance)


async def test_demo_status_endpoint_uses_isolated_service(
    client: AsyncClient, isolated_demo_service: DemoService
) -> None:
    response = await client.get("/api/v1/demos/bulk-rnaseq/status")

    assert response.status_code == 200
    assert response.json()["data"]["available"] is False
    assert response.json()["data"]["bundle_directory"].startswith(
        str(isolated_demo_service.state_directory)
    )


async def test_demo_prepare_endpoint_accepts_explicit_consent(
    client: AsyncClient,
    isolated_demo_service: DemoService,
    kallisto_stub: Path,
) -> None:
    del kallisto_stub
    response = await client.post("/api/v1/demos/bulk-rnaseq/prepare", json={"consent": True})

    assert response.status_code == 200
    job = response.json()["data"]
    assert job["job_identifier"]
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if job["status"] != DemoPrepareStatus.RUNNING:
            break
        await asyncio.sleep(0.05)
        poll = await client.get(f"/api/v1/demos/bulk-rnaseq/prepare/jobs/{job['job_identifier']}")
        assert poll.status_code == 200
        job = poll.json()["data"]
    assert job["status"] == DemoPrepareStatus.SUCCEEDED

    status_response = await client.get("/api/v1/demos/bulk-rnaseq/status")
    assert status_response.status_code == 200
    status = status_response.json()["data"]
    assert status["available"] is True
    assert status["bundle_directory"].startswith(str(isolated_demo_service.state_directory))


@pytest.mark.parametrize("payload", ({}, {"consent": False}))
async def test_demo_prepare_endpoint_requires_true_consent(
    client: AsyncClient, isolated_demo_service: DemoService, payload: dict[str, bool]
) -> None:
    response = await client.post("/api/v1/demos/bulk-rnaseq/prepare", json=payload)

    assert response.status_code == 422
    assert not (isolated_demo_service.root / "bulk-rnaseq").exists()


async def test_demo_endpoint_rejects_unknown_pipeline(
    client: AsyncClient, isolated_demo_service: DemoService
) -> None:
    response = await client.get("/api/v1/demos/unknown/status")

    assert response.status_code == 404
    assert not (isolated_demo_service.root / "unknown").exists()


async def test_directory_preview_endpoint(tmp_path: Path, client: AsyncClient) -> None:
    (tmp_path / "sample_R1.fastq.gz").write_bytes(b"reads")

    response = await client.post("/api/v1/directories/preview", json={"directory": str(tmp_path)})

    assert response.status_code == 200
    preview = response.json()["data"]
    assert preview["total_entries"] == 1
    assert preview["entries"][0]["file_type"] == "FASTQ.GZ"


async def test_metadata_csv_endpoint(tmp_path: Path, client: AsyncClient) -> None:
    metadata = tmp_path / "metadata.csv"
    metadata.write_text("SampleID,condition,batch\nsample_01,HFD,run_1\n", encoding="utf-8")

    response = await client.post("/api/v1/metadata/csv", json={"path": str(metadata)})

    assert response.status_code == 200
    row = response.json()["data"]["rows"][0]
    assert row == {
        "sample_id": "sample_01",
        "condition": "HFD",
        "batch": "run_1",
        "biological_replicate": None,
        "intervention": None,
        "matched_sample_id": None,
    }


async def test_discovery_error_has_structured_envelope(tmp_path: Path, client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/fastq/discover",
        json={"directory": str(tmp_path / "missing")},
    )

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert response.json()["errors"][0]["code"] == "http_400"


async def test_validate_save_and_plan_endpoints(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: Any,
    client: AsyncClient,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path / "state"))

    validation = await client.post("/api/v1/projects/validate", json=manifest_payload)
    assert validation.status_code == 200
    assert validation.json()["data"]["valid"] is True

    saved = await client.post("/api/v1/projects/save", json=manifest_payload)
    assert saved.status_code == 200
    manifest_path = Path(saved.json()["data"]["manifest_path"])
    assert manifest_path.is_file()
    assert not any(
        path.suffix in {".fastq", ".fq", ".gz"} for path in manifest_path.parents[1].rglob("*")
    )

    plan = await client.post("/api/v1/runs/plan", json={"manifest": manifest_payload})
    assert plan.status_code == 200
    plan_data = plan.json()["data"]
    assert plan_data["execution_enabled"] is False
    assert plan_data["command_preview"][0] == "nextflow"
    assert "run" in plan_data["command_preview"]
    assert plan_data["command_preview"][-2:] == ["--start_stage", "quantification"]
    assert len(plan_data["stages"]) == 8

    start = await client.post(
        "/api/v1/runs/start", json={"manifest": manifest_payload, "resume": True}
    )
    assert start.status_code == 409
    assert "unsupported" in start.json()["errors"][0]["message"]


async def test_run_start_rejects_unknown_start_stage(
    manifest_payload: dict[str, Any], client: AsyncClient
) -> None:
    response = await client.post(
        "/api/v1/runs/start",
        json={"manifest": manifest_payload, "start_stage": "alignment"},
    )

    assert response.status_code == 422


async def test_repeated_structural_errors_are_grouped(
    manifest_payload: dict[str, Any], client: AsyncClient
) -> None:
    payload = deepcopy(manifest_payload)
    for sample in payload["samples"]:
        sample["sample_id"] = "invalid sample id"

    response = await client.post("/api/v1/projects/validate", json=payload)

    assert response.status_code == 422
    matching = [
        error for error in response.json()["errors"] if "letters, numbers" in error["message"]
    ]
    assert len(matching) == 1
    assert "2 fields" in matching[0]["message"]


async def test_pipeline_status_allows_execution(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pipelines/bulk-rnaseq/status")

    assert response.status_code == 200
    assert response.json()["data"]["available"] is True
    assert response.json()["data"]["execution_enabled"] is True


async def test_pipeline_listing_contains_bulk_adapter(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pipelines")

    assert response.status_code == 200
    assert response.json()["data"][0]["pipeline_identifier"] == "bulk-rnaseq"


async def test_ont_pipeline_validation_and_plan_dispatch(
    tmp_path: Path, manifest_payload: dict[str, Any], client: AsyncClient
) -> None:
    payload = deepcopy(manifest_payload)
    inputs = Path(payload["input_directory"])
    bam = inputs / "mouse_pass.bam"
    bam.touch()
    references = Path(payload["reference_resources"]["biomart"]).parent
    ont_resources = {}
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
        ont_resources[key] = str(path)
    payload.update(
        pipeline_identifier="ont-analysis",
        pipeline_version="0.1.0",
        organism="Mus musculus",
        reference_genome="GRCm38p6",
        reference_resources=ont_resources,
        read_layout="single-end",
        strandedness="unknown",
        comparisons=[],
        parameters={"expected_pass_bam_count": 1},
    )
    payload["samples"] = [
        {
            "sample_id": "mouse_01",
            "r1_files": [],
            "r2_files": [],
            "ont_bam_files": [str(bam)],
            "condition": "single_sample",
            "biological_replicate": "1",
            "batch": None,
            "covariates": {},
            "included": True,
        }
    ]

    validation = await client.post("/api/v1/projects/validate", json=payload)
    plan = await client.post("/api/v1/runs/plan", json={"manifest": payload})

    assert validation.status_code == 200
    assert validation.json()["data"]["valid"] is True
    assert plan.status_code == 200
    assert plan.json()["data"]["pipeline_identifier"] == "ont-analysis"
    assert plan.json()["data"]["stages"][0]["stage_id"] == "align_modbam"


async def test_system_preflight_keeps_framework_available(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from missus_tom.models.preflight import CheckStatus, PreflightCheck
    from missus_tom.services import preflight

    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "0")
    monkeypatch.setattr(
        preflight,
        "_version_check",
        lambda check_id, label, *args, **kwargs: PreflightCheck(
            check_id=check_id, label=label, status=CheckStatus.PASSED, message="fixture version"
        ),
    )
    response = await client.get("/api/v1/system/preflight")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["ready_for_framework"] is True
    assert body["ready_for_real_execution"] is False
    assert {check["check_id"] for check in body["checks"]} >= {
        "java",
        "nextflow",
        "disk_state",
        "disk_home",
        "managed_dependencies_bulk_rnaseq",
        "bulk_adapter",
    }
    assert "docker" not in {check["check_id"] for check in body["checks"]}
    assert "apptainer" not in {check["check_id"] for check in body["checks"]}
