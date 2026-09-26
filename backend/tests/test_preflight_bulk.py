from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest
from missus_tom.models.preflight import CheckStatus
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
