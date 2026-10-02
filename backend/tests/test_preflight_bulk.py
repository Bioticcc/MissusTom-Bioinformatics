from __future__ import annotations

import errno
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest
from missus_tom.models.preflight import CheckStatus
from missus_tom.services import preflight as preflight_module
from missus_tom.services.preflight import project_preflight


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


def test_generalized_bulk_preflight_returns_individual_checks_for_blocking_input(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload["samples"][0]["condition"] = ""
    manifest = ProjectManifest.model_validate(payload)

    checks = {check.check_id: check for check in project_preflight(manifest)}

    assert checks["experimental_groups"].status == CheckStatus.BLOCKING
    assert checks["experimental_groups"].message
    assert "fastq_pairing" in checks
    assert "bulk_reference_contract" in checks


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


def _bulk_contract(manifest: ProjectManifest):
    checks = project_preflight(manifest)
    return next(check for check in checks if check.check_id == "bulk_reference_contract")


def test_preflight_missing_fasta_is_blocking_contract(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.1.0",
        reference_mode=BulkReferenceMode.BUILD.value,
        pipeline_version="0.5.0",
    )
    resources = payload["reference_resources"]
    resources.pop("biomart", None)
    resources.pop("kallisto_index", None)
    gtf = Path(resources["annotation_gtf"])
    gtf.write_text(
        "chr1\tHAVANA\texon\t1\t10\t.\t+\t.\t"
        'gene_id "ENSG1"; transcript_id "ENST000001"; gene_type "protein_coding";\n',
        encoding="utf-8",
    )
    resources["transcriptome_fasta"] = str(tmp_path / "missing.fa")
    manifest = ProjectManifest.model_validate(payload)

    contract = _bulk_contract(manifest)

    assert contract.status == CheckStatus.BLOCKING


def test_preflight_fasta_gtf_overlap_mismatch_is_blocking(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.1.0",
        reference_mode=BulkReferenceMode.BUILD.value,
        pipeline_version="0.5.0",
    )
    resources = payload["reference_resources"]
    resources.pop("biomart", None)
    resources.pop("kallisto_index", None)
    fasta = Path(resources["transcriptome_fasta"])
    gtf = Path(resources["annotation_gtf"])
    fasta.write_text(">ENST000001\nACGT\n", encoding="utf-8")
    gtf.write_text(
        "chr1\tHAVANA\texon\t1\t10\t.\t+\t.\t"
        'gene_id "ENSG1"; transcript_id "ENST999999"; gene_type "protein_coding";\n',
        encoding="utf-8",
    )
    manifest = ProjectManifest.model_validate(payload)

    contract = _bulk_contract(manifest)

    assert contract.status == CheckStatus.BLOCKING
    assert "incompatible" in contract.message


def test_preflight_malformed_gtf_is_blocking_reference_contract(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.1.0",
        reference_mode=BulkReferenceMode.BUILD.value,
        pipeline_version="0.5.0",
    )
    resources = payload["reference_resources"]
    resources.pop("biomart", None)
    resources.pop("kallisto_index", None)
    fasta = Path(resources["transcriptome_fasta"])
    gtf = Path(resources["annotation_gtf"])
    fasta.write_text(">TX001\nACGT\n", encoding="utf-8")
    gtf.write_text("chr1\tfixture\texon\t1\t10\t.\t+\t.\n", encoding="utf-8")
    manifest = ProjectManifest.model_validate(payload)

    contract = _bulk_contract(manifest)

    assert contract.status == CheckStatus.BLOCKING
    assert "malformed feature row" in contract.message


def test_preflight_mixed_valid_and_malformed_gtf_is_blocking(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.1.0",
        reference_mode=BulkReferenceMode.BUILD.value,
        pipeline_version="0.5.0",
    )
    resources = payload["reference_resources"]
    resources.pop("biomart", None)
    resources.pop("kallisto_index", None)
    fasta = Path(resources["transcriptome_fasta"])
    gtf = Path(resources["annotation_gtf"])
    fasta.write_text(">TX001\nACGT\n", encoding="utf-8")
    gtf.write_text(
        'chr1\tfixture\texon\t1\t10\t.\t+\t.\tgene_id "GENE1"; transcript_id "TX001";\n'
        "chr1\tfixture\texon\t11\t20\t.\t+\t.\n",
        encoding="utf-8",
    )
    manifest = ProjectManifest.model_validate(payload)

    contract = _bulk_contract(manifest)

    assert contract.status == CheckStatus.BLOCKING
    assert "line 2" in contract.message


@pytest.mark.parametrize(
    ("contents", "suffix", "expected"),
    [
        (b"\xff\xfe", ".gtf", "invalid UTF-8"),
        (b"not a gzip stream", ".gtf.gz", "invalid gzip"),
    ],
)
def test_preflight_corrupt_gtf_is_a_blocking_reference_contract(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    contents: bytes,
    suffix: str,
    expected: str,
) -> None:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.1.0",
        reference_mode=BulkReferenceMode.BUILD.value,
        pipeline_version="0.5.0",
    )
    resources = payload["reference_resources"]
    resources.pop("biomart", None)
    resources.pop("kallisto_index", None)
    fasta = Path(resources["transcriptome_fasta"])
    fasta.write_text(">TX001\nACGT\n", encoding="utf-8")
    gtf = tmp_path / f"corrupt{suffix}"
    gtf.write_bytes(contents)
    resources["annotation_gtf"] = str(gtf)

    contract = _bulk_contract(ProjectManifest.model_validate(payload))

    assert contract.status == CheckStatus.BLOCKING
    assert expected in contract.message


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PermissionError(errno.EACCES, "denied"), "not readable"),
        (FileNotFoundError(errno.ENOENT, "gone"), "missing or unavailable"),
    ],
)
def test_preflight_reference_read_races_are_blocking_not_server_errors(
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    error: OSError,
    expected: str,
) -> None:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.1.0",
        reference_mode=BulkReferenceMode.BUILD.value,
        pipeline_version="0.5.0",
    )
    resources = payload["reference_resources"]
    resources.pop("biomart", None)
    resources.pop("kallisto_index", None)
    Path(resources["transcriptome_fasta"]).write_text(">TX001\nACGT\n", encoding="utf-8")
    Path(resources["annotation_gtf"]).write_text(
        'chr1\tfixture\texon\t1\t10\t.\t+\t.\tgene_id "G1"; transcript_id "TX001";\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        preflight_module,
        "parse_gtf_transcript_records",
        Mock(side_effect=error),
    )

    contract = _bulk_contract(ProjectManifest.model_validate(payload))

    assert contract.status == CheckStatus.BLOCKING
    assert expected in contract.message


def test_preflight_existing_index_without_fasta_warns_compatibility(
    manifest_payload: dict[str, Any],
) -> None:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.1.0",
        reference_mode=BulkReferenceMode.EXISTING_INDEX.value,
        pipeline_version="0.5.0",
    )
    resources = payload["reference_resources"]
    resources.pop("biomart", None)
    resources.pop("transcriptome_fasta", None)
    gtf = Path(resources["annotation_gtf"])
    gtf.write_text(
        "chr1\tHAVANA\texon\t1\t10\t.\t+\t.\t"
        'gene_id "ENSG1"; transcript_id "ENST000001"; gene_type "protein_coding";\n',
        encoding="utf-8",
    )
    manifest = ProjectManifest.model_validate(payload)

    contract = _bulk_contract(manifest)

    assert contract.status == CheckStatus.WARNING
    assert contract.details is not None
    assert contract.details.get("compatibility_unverified") is True


def test_preflight_existing_index_fasta_mapping_mismatch_is_blocking(
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
    resources.pop("biomart", None)
    fasta = Path(resources["transcriptome_fasta"])
    gtf = Path(resources["annotation_gtf"])
    mapping = fasta.parent / "transcript_to_gene.tsv"
    fasta.write_text(">ENST000001\nACGT\n", encoding="utf-8")
    gtf.write_text(
        "chr1\tHAVANA\texon\t1\t10\t.\t+\t.\t"
        'gene_id "ENSG1"; transcript_id "ENST000001"; gene_type "protein_coding";\n',
        encoding="utf-8",
    )
    mapping.write_text("transcript_id\tgene_id\nENST999999\tGENE999\n", encoding="utf-8")
    resources["transcript_to_gene"] = str(mapping)
    manifest = ProjectManifest.model_validate(payload)

    contract = _bulk_contract(manifest)

    assert contract.status == CheckStatus.BLOCKING
    assert "incompatible" in contract.message.lower() or "0.0%" in contract.message
