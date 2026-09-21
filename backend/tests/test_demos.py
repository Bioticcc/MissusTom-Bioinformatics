from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from missus_tom.api import routes
from missus_tom.models.demos import DemoPrepareRequest
from missus_tom.services.demos import DemoService


@pytest.fixture
def demos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DemoService:
    service = DemoService(state_directory=tmp_path / "state")
    monkeypatch.setattr(routes, "demo_service", service)
    return service


def test_catalog_has_only_supported_synthetic_demos(demos: DemoService) -> None:
    response = routes.get_demos()

    data = response.data
    assert data is not None
    assert [item.pipeline_identifier for item in data] == [
        "bulk-rnaseq",
        "ont-analysis",
    ]
    assert all(not item.available for item in data)
    assert all(item.bundle_directory.startswith(str(demos.state_directory)) for item in data)


@pytest.mark.parametrize("payload", ({}, {"consent": False}))
def test_prepare_requires_explicit_true_consent(
    demos: DemoService, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        DemoPrepareRequest.model_validate(payload)


@pytest.mark.parametrize("pipeline_identifier", ("bulk-rnaseq", "ont-analysis"))
def test_prepare_writes_regeneratable_synthetic_bundle_with_self_consistency_metadata(
    demos: DemoService, pipeline_identifier: str
) -> None:
    response = routes.post_demo_prepare(pipeline_identifier, DemoPrepareRequest(consent=True))

    data = response.data
    assert data is not None and data.available is True
    bundle = Path(data.bundle_directory)
    metadata = json.loads((bundle / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
    assert metadata["synthetic_only"] is True
    assert metadata["network_downloads"] is False
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
    assert "not" in data.execution_note.lower()
    if pipeline_identifier == "ont-analysis":
        assert (bundle / "inputs/synthetic_pass_modbam.bam").read_bytes().startswith(b"NOT_A_BAM")
    else:
        assert (bundle / "references/transcripts.idx").read_bytes().startswith(b"NOT_A_KALLISTO")


def test_status_rejects_tampered_fixture_file(demos: DemoService) -> None:
    prepared = routes.post_demo_prepare("bulk-rnaseq", DemoPrepareRequest(consent=True))
    assert prepared.data is not None
    bundle = Path(prepared.data.bundle_directory)
    (bundle / "README.txt").write_text("tampered", encoding="utf-8")

    response = routes.get_demo_status("bulk-rnaseq")

    assert response.data is not None and response.data.available is False


def test_unknown_demo_is_not_created(demos: DemoService) -> None:
    with pytest.raises(HTTPException) as exc_info:
        routes.post_demo_prepare("unknown", DemoPrepareRequest(consent=True))

    assert exc_info.value.status_code == 404
    assert not (demos.root / "unknown").exists()
