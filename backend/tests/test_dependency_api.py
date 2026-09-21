from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from missus_tom.api import routes
from missus_tom.main import app
from missus_tom.models.dependencies import (
    DependencyInstallJob,
    DependencyInstallStatus,
    DependencyRequirement,
    DependencyStatus,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://missus-tom.test"
    ) as test_client:
        yield test_client


class _Registry:
    def get(self, pipeline_identifier: str) -> object:
        if pipeline_identifier != "ont-analysis":
            raise ValueError(f"unsupported pipeline identifier: {pipeline_identifier}")
        return object()


class _Installer:
    def status(self, pipeline_identifier: str) -> DependencyStatus:
        return DependencyStatus(
            pipeline_identifier=pipeline_identifier,
            requirements=[
                DependencyRequirement(
                    name="samtools", installed=True, managed=False, detail="/usr/bin/samtools"
                )
            ],
            installable=True,
        )

    def install(self, pipeline_identifier: str) -> DependencyInstallJob:
        return DependencyInstallJob(
            job_identifier="00000000-0000-0000-0000-000000000123",
            pipeline_identifier=pipeline_identifier,
            status=DependencyInstallStatus.RUNNING,
            message="Preparing local environment",
        )


@pytest.fixture
def dependency_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "pipeline_registry", _Registry())
    monkeypatch.setattr(routes, "dependency_installer", _Installer())


async def test_dependency_get_uses_api_envelope(client: AsyncClient, dependency_api: None) -> None:
    response = await client.get("/api/v1/pipelines/ont-analysis/dependencies")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {
            "pipeline_identifier": "ont-analysis",
            "requirements": [
                {
                    "name": "samtools",
                    "installed": True,
                    "managed": False,
                    "detail": "/usr/bin/samtools",
                }
            ],
            "missing": [],
            "installable": True,
            "manual_requirements": [],
            "job": None,
        },
        "errors": [],
        "meta": {},
    }


async def test_dependency_unknown_pipeline_is_404(
    client: AsyncClient, dependency_api: None
) -> None:
    response = await client.get("/api/v1/pipelines/nope/dependencies")

    assert response.status_code == 404
    assert response.json()["success"] is False


@pytest.mark.parametrize("payload", ({}, {"consent": False}))
async def test_dependency_install_requires_explicit_true_consent(
    client: AsyncClient, dependency_api: None, payload: dict[str, Any]
) -> None:
    response = await client.post(
        "/api/v1/pipelines/ont-analysis/dependencies/install", json=payload
    )

    assert response.status_code == 422


async def test_dependency_install_returns_exact_job_envelope(
    client: AsyncClient, dependency_api: None
) -> None:
    response = await client.post(
        "/api/v1/pipelines/ont-analysis/dependencies/install", json={"consent": True}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["job_identifier"] == "00000000-0000-0000-0000-000000000123"
    assert data["pipeline_identifier"] == "ont-analysis"
    assert data["status"] == "running"
    assert data["message"] == "Preparing local environment"
    assert data["log_tail"] == []
