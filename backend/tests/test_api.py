from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from missus_tom.main import app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://missus-tom.test"
    ) as test_client:
        yield test_client


async def test_health_reports_execution_disabled(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["execution_enabled"] is False


async def test_tauri_origin_preflight_is_allowed(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/fastq/discover",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


async def test_discovery_endpoint(tmp_path: Path, client: AsyncClient) -> None:
    (tmp_path / "api_R1.fastq.gz").touch()
    (tmp_path / "api_R2.fastq.gz").touch()

    response = await client.post("/api/v1/fastq/discover", json={"directory": str(tmp_path)})

    assert response.status_code == 200
    assert response.json()["data"]["samples"][0]["pairing_status"] == "paired"


async def test_directory_preview_endpoint(tmp_path: Path, client: AsyncClient) -> None:
    (tmp_path / "sample_R1.fastq.gz").write_bytes(b"reads")

    response = await client.post("/api/v1/directories/preview", json={"directory": str(tmp_path)})

    assert response.status_code == 200
    preview = response.json()["data"]
    assert preview["total_entries"] == 1
    assert preview["entries"][0]["file_type"] == "FASTQ.GZ"


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
    assert len(plan_data["stages"]) == 8

    start = await client.post(
        "/api/v1/runs/start", json={"manifest": manifest_payload, "resume": True}
    )
    assert start.status_code == 409
    assert "disabled" in start.json()["errors"][0]["message"]


async def test_pipeline_status_is_preview_only(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pipelines/bulk-rnaseq/status")

    assert response.status_code == 200
    assert response.json()["data"]["available"] is True
    assert response.json()["data"]["execution_enabled"] is False


async def test_pipeline_listing_contains_bulk_adapter(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pipelines")

    assert response.status_code == 200
    assert response.json()["data"][0]["pipeline_identifier"] == "bulk-rnaseq"


async def test_system_preflight_keeps_framework_available(client: AsyncClient) -> None:
    response = await client.get("/api/v1/system/preflight")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["ready_for_framework"] is True
    assert body["ready_for_real_execution"] is False
    assert {check["check_id"] for check in body["checks"]} >= {
        "java",
        "nextflow",
        "docker",
        "apptainer",
        "bulk_adapter",
    }
