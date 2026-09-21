from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from missus_tom.models.manifest import ProjectManifest, ResourceProfile
from missus_tom.services import resources
from missus_tom.services.resources import GIB, HostResources


@pytest.fixture
def capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        resources, "inspect_host_resources", lambda: HostResources(16, 64 * GIB, 48 * GIB)
    )
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda _: SimpleNamespace(free=1000 * GIB))


def test_headroom_is_reserved() -> None:
    host = HostResources(32, 128 * GIB, 100 * GIB)
    assert host.workflow_cpus == 28
    assert host.workflow_memory_bytes == 100 * GIB - host.reserved_memory_bytes
    assert host.reserved_memory_bytes >= 12 * GIB
    assert HostResources(1, 4 * GIB, GIB).workflow_cpus == 1
    assert HostResources(1, 4 * GIB, GIB).workflow_memory_bytes == 0


def test_safe_profile_is_admitted(capacity: None, manifest_payload: dict[str, Any]) -> None:
    manifest = ProjectManifest.model_validate(manifest_payload)
    resources.validate_execution_resources(manifest, analysis_only=False)


@pytest.mark.parametrize("field,value", [("cpus", 16), ("memory_gb", 64)])
def test_excess_profile_warns_for_setup_but_blocks_launch(
    capacity: None, manifest_payload: dict[str, Any], field: str, value: int
) -> None:
    manifest_payload["resource_profile"][field] = value
    manifest = ProjectManifest.model_validate(manifest_payload)
    assert any(c.status == "warning" for c in resources.execution_resource_checks(manifest))
    with pytest.raises(ValueError, match="Insufficient resources"):
        resources.validate_execution_resources(manifest, analysis_only=False)


def test_memory_must_be_known_for_launch(
    capacity: None, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resources, "inspect_host_resources", lambda: HostResources(16, None, None))
    with pytest.raises(ValueError, match="Cannot determine available RAM"):
        resources.validate_execution_resources(
            ProjectManifest.model_validate(manifest_payload), analysis_only=False
        )


def test_disk_admission_uses_output_filesystem_and_input_copies(
    capacity: None, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = ProjectManifest.model_validate(manifest_payload)
    calls: list[Path] = []

    def disk_usage(path: Path) -> SimpleNamespace:
        calls.append(path)
        return SimpleNamespace(free=12 * GIB)

    monkeypatch.setattr(resources.shutil, "disk_usage", disk_usage)
    monkeypatch.setattr(resources, "estimated_input_bytes", lambda *a, **kw: GIB)
    with pytest.raises(ValueError, match="14.0 GiB"):
        resources.validate_execution_resources(manifest, analysis_only=False)
    assert calls == [Path(manifest.output_directory).parent]
    resources.validate_execution_resources(manifest, analysis_only=True)


def test_analysis_estimate_uses_abundance_tables_not_fastqs(
    manifest_payload: dict[str, Any],
) -> None:
    manifest = ProjectManifest.model_validate(manifest_payload)
    Path(manifest.samples[0].r1_files[0]).write_bytes(b"FASTQ metadata fixture")
    table = Path(manifest.output_directory) / "results/counts/kallisto/synthetic_A/abundance.tsv"
    table.parent.mkdir(parents=True)
    table.write_bytes(b"table")
    assert resources.estimated_input_bytes(manifest, analysis_only=False) == 22
    assert resources.estimated_input_bytes(manifest, analysis_only=True) == 5


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_memory_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        ResourceProfile(memory_gb=value)


def test_estimated_input_bytes_uses_ont_bams_only(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    input_directory = Path(manifest_payload["input_directory"])
    bam = input_directory / "mouse.bam"
    bam.write_bytes(b"bam-data")
    payload = dict(manifest_payload)
    payload.update(
        pipeline_identifier="ont-analysis",
        pipeline_version="0.1.0",
        organism="Mus musculus",
        reference_genome="GRCm38p6",
    )
    samples = list(payload["samples"])
    sample = dict(samples[0])
    sample["ont_bam_files"] = [str(bam)]
    samples[0] = sample
    payload["samples"] = samples

    manifest = ProjectManifest.model_validate(payload)

    assert resources.estimated_input_bytes(manifest) == len(b"bam-data")
