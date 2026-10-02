from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from missus_tom.models.dependencies import DependencyStatus
from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest
from missus_tom.models.preflight import CheckStatus, PreflightCheck
from missus_tom.services import preflight
from missus_tom.services.preflight import project_preflight
from missus_tom.services.resources import GIB, HostResources, StorageInspection


def test_system_preflight_excludes_container_runtime_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight,
        "inspect_host_resources",
        lambda: HostResources(8, 16 * GIB, 8 * GIB),
    )
    monkeypatch.setattr(
        preflight,
        "inspect_storage",
        lambda path: StorageInspection(
            path=str(path),
            filesystem_type="ext4",
            free_bytes=50 * GIB,
            total_bytes=100 * GIB,
            host_free_bytes=None,
            measurement="linux",
            warning=None,
        ),
    )
    monkeypatch.setattr(
        preflight,
        "_version_check",
        lambda check_id, label, *args, **kwargs: PreflightCheck(
            check_id=check_id,
            label=label,
            status=CheckStatus.PASSED,
            message="ok",
        ),
    )
    monkeypatch.setattr(
        preflight.dependency_installer,
        "status",
        lambda pipeline_identifier: DependencyStatus(
            pipeline_identifier=pipeline_identifier,
            requirements=[],
            installable=True,
        ),
    )

    result = preflight.system_preflight()
    check_ids = {check.check_id for check in result.checks}

    assert "docker" not in check_ids
    assert "apptainer" not in check_ids
    assert "disk_state" in check_ids
    assert "disk_home" in check_ids
    disk_home = next(check for check in result.checks if check.check_id == "disk_home")
    assert "measurement=linux" in disk_home.message


def test_production_bulk_preflight_flags_legacy_biomart_only(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.0.0",
        reference_mode=None,
        pipeline_version="0.4.0",
    )
    payload["reference_resources"] = {
        "biomart": payload["reference_resources"]["biomart"],
        "kallisto_index": payload["reference_resources"]["kallisto_index"],
    }
    manifest = ProjectManifest.model_validate(payload)

    checks = project_preflight(manifest)
    migration = next(check for check in checks if check.check_id == "pipeline_version")

    assert migration.status == CheckStatus.BLOCKING
    assert "BioMart-only" in migration.message


def test_production_bulk_preflight_validates_reference_contract(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.1.0",
        reference_mode=BulkReferenceMode.EXISTING_INDEX.value,
        pipeline_version="0.5.0",
    )
    resources = payload["reference_resources"]
    fasta = Path(resources["transcriptome_fasta"])
    gtf = Path(resources["annotation_gtf"])
    mapping = fasta.parent / "transcript_to_gene.tsv"
    fasta.write_text(">ENST000001\nACGT\n", encoding="utf-8")
    gtf.write_text(
        "chr1\tHAVANA\texon\t1\t10\t.\t+\t.\t"
        'gene_id "ENSG1"; transcript_id "ENST000001"; gene_type "protein_coding";\n',
        encoding="utf-8",
    )
    mapping.write_text(
        "transcript_id\tgene_id\tgene_name\tgene_biotype\ttranscript_biotype\n"
        "ENST000001\tENSG1\tGeneA\tprotein_coding\tprotein_coding\n",
        encoding="utf-8",
    )
    resources.pop("biomart", None)
    resources["transcript_to_gene"] = str(mapping)
    manifest = ProjectManifest.model_validate(payload)

    checks = project_preflight(manifest)
    contract = next(check for check in checks if check.check_id == "bulk_reference_contract")

    assert contract.status == CheckStatus.PASSED


def test_fastq_outside_input_directory_is_blocking(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    outside = Path(payload["input_directory"]).parent / "outside_R1.fastq.gz"
    outside.touch()
    payload["samples"][0]["r1_files"] = [str(outside)]
    manifest = ProjectManifest.model_validate(payload)

    checks = project_preflight(manifest)
    fastq = next(check for check in checks if check.check_id == "fastq_pairing")

    assert fastq.status == CheckStatus.BLOCKING
    assert "outside the input directory" in fastq.message
