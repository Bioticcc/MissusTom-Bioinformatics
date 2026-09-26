from __future__ import annotations

import gzip
import json
import stat
from pathlib import Path

import pytest

from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest
from missus_tom.services.bulk_references import (
    BulkReferenceError,
    BulkReferenceManager,
    KallistoRuntime,
    assess_fasta_gtf_overlap,
    iter_fasta_transcript_ids,
    map_fasta_to_gtf_records,
    parse_gtf_transcript_records,
    read_supplied_transcript_to_gene,
    sha256_file,
    validate_mapping_fasta_overlap,
    write_transcript_to_gene_table,
)


def _write_fasta(path: Path, transcript_ids: list[str]) -> None:
    lines = [f">{transcript_id}\nACGT\n" for transcript_id in transcript_ids]
    path.write_text("".join(lines), encoding="utf-8")


def _write_gtf(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    lines: list[str] = []
    for transcript_id, gene_id, gene_type, gene_name in rows:
        attributes = (
            f'gene_id "{gene_id}"; transcript_id "{transcript_id}"; '
            f'gene_type "{gene_type}"; gene_name "{gene_name}";'
        )
        lines.append(f"chr1\tfixture\texon\t1\t100\t.\t+\t.\t{attributes}\n")
    path.write_text("".join(lines), encoding="utf-8")


def _manifest_payload(
    tmp_path: Path, resources: dict[str, str], **overrides: object
) -> dict[str, object]:
    payload = {
        "schema_version": "1.1.0",
        "reference_mode": "build",
        "project_name": "Reference test",
        "project_identifier": "11111111-2222-4333-8444-555555555555",
        "created_at": "2026-01-15T12:00:00Z",
        "input_directory": str(tmp_path / "inputs"),
        "output_directory": str(tmp_path / "outputs"),
        "pipeline_identifier": "bulk-rnaseq",
        "pipeline_version": "0.5.0",
        "organism": "Mus musculus",
        "reference_genome": "GRCm39",
        "annotation_source": "synthetic",
        "reference_resources": resources,
        "library_type": "total RNA",
        "read_layout": "paired-end",
        "strandedness": "unstranded",
        "samples": [
            {
                "sample_id": "sample_a",
                "r1_files": [str(tmp_path / "inputs" / "a_R1.fastq.gz")],
                "r2_files": [str(tmp_path / "inputs" / "a_R2.fastq.gz")],
                "condition": "control",
                "biological_replicate": "1",
                "batch": None,
                "covariates": {},
                "included": True,
            }
        ],
        "comparisons": [],
        "parameters": {},
        "resource_profile": {"cpus": 2, "memory_gb": 4, "max_parallel_tasks": 1},
        "execution_profile": "local",
        "application_version": "0.1.0",
        "pipeline_status": "draft",
    }
    payload.update(overrides)
    (tmp_path / "inputs").mkdir(parents=True, exist_ok=True)
    for sample in payload["samples"]:  # type: ignore[index]
        for key in ("r1_files", "r2_files"):
            for fastq in sample[key]:
                Path(fastq).touch()
    return payload


def test_gtf_normalization_uses_gencode_gene_type_alias(tmp_path: Path) -> None:
    gtf = tmp_path / "annotation.gtf"
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])

    records = parse_gtf_transcript_records(gtf)

    assert records["ENST000001"].gene_biotype == "protein_coding"
    assert records["ENST000001"].gene_name == "GeneA"


def test_missing_transcript_or_gene_attributes_are_ignored(tmp_path: Path) -> None:
    gtf = tmp_path / "annotation.gtf"
    gtf.write_text(
        'chr1\tfixture\texon\t1\t10\t.\t+\t.\tgene_id "ENSG1";\n'
        'chr1\tfixture\texon\t1\t10\t.\t+\t.\ttranscript_id "ENST1";\n',
        encoding="utf-8",
    )

    records = parse_gtf_transcript_records(gtf)

    assert records == {}


def test_compressed_fasta_and_gtf_are_supported(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa.gz"
    gtf = tmp_path / "annotation.gtf.gz"
    mapping = tmp_path / "tx2gene.tsv.gz"
    with gzip.open(fasta, "wt", encoding="utf-8") as handle:
        handle.write(">TX001\nACGT\n")
    with gzip.open(gtf, "wt", encoding="utf-8") as handle:
        handle.write(
            'chr1\tfixture\ttranscript\t1\t4\t.\t+\t.\tgene_id "GENE001"; transcript_id "TX001";\n'
        )
    with gzip.open(mapping, "wt", encoding="utf-8") as handle:
        handle.write("transcript_id\tgene_id\nTX001\tGENE001\n")

    assert iter_fasta_transcript_ids(fasta) == ["TX001"]
    assert parse_gtf_transcript_records(gtf)["TX001"].gene_id == "GENE001"
    assert read_supplied_transcript_to_gene(mapping) == {"TX001"}


def test_supplied_mapping_is_checked_against_fasta_when_available(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    mapping = tmp_path / "tx2gene.tsv"
    _write_fasta(fasta, ["TX001"])
    mapping.write_text("transcript_id\tgene_id\nTX999\tGENE999\n", encoding="utf-8")

    with pytest.raises(BulkReferenceError, match="only 0.0%"):
        validate_mapping_fasta_overlap(mapping, fasta)


def test_reference_hashing_honors_cancellation(tmp_path: Path) -> None:
    reference = tmp_path / "reference.fa"
    reference.write_bytes(b"A" * (2 * 1024 * 1024))

    with pytest.raises(BulkReferenceError, match="cancelled"):
        sha256_file(reference, cancellation_check=lambda: True)


def test_fasta_gtf_mismatch_reports_actionable_overlap(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001", "ENST000002"])
    _write_gtf(gtf, [("ENST999999", "ENSG000001", "protein_coding", "GeneA")])

    manager = BulkReferenceManager(cache_root=tmp_path / "cache")
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {
                "transcriptome_fasta": str(fasta),
                "annotation_gtf": str(gtf),
            },
        )
    )

    with pytest.raises(BulkReferenceError, match=r"only 0\.0%"):
        manager.prepare(manifest)


def test_exact_id_overlap_is_preferred(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])

    overlap = assess_fasta_gtf_overlap(
        fasta_ids=["ENST000001"],
        gtf_records=parse_gtf_transcript_records(gtf),
    )

    assert overlap.policy == "exact"
    assert overlap.overlap_fraction == 1.0


def test_version_stripped_overlap_when_exact_fails(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001.1"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])

    overlap = assess_fasta_gtf_overlap(
        fasta_ids=["ENST000001.1"],
        gtf_records=parse_gtf_transcript_records(gtf),
    )
    records = map_fasta_to_gtf_records(
        fasta_ids=["ENST000001.1"],
        gtf_records=parse_gtf_transcript_records(gtf),
        policy=overlap.policy,
    )

    assert overlap.policy == "version_stripped"
    assert overlap.overlap_fraction == 1.0
    assert records[0].transcript_id == "ENST000001.1"


def test_version_stripping_is_not_used_for_colliding_annotation_ids(tmp_path: Path) -> None:
    gtf = tmp_path / "annotation.gtf"
    _write_gtf(
        gtf,
        [
            ("TX001.1", "GENE001", "protein_coding", "GeneA"),
            ("TX001.2", "GENE002", "protein_coding", "GeneB"),
        ],
    )

    overlap = assess_fasta_gtf_overlap(
        fasta_ids=["TX001.3"],
        gtf_records=parse_gtf_transcript_records(gtf),
    )

    assert overlap.policy == "exact"
    assert overlap.overlap_fraction == 0


def test_gff3_annotation_reports_required_gtf_format(tmp_path: Path) -> None:
    annotation = tmp_path / "annotation.gff3"
    annotation.write_text(
        "chr1\tfixture\tmRNA\t1\t10\t.\t+\t.\tID=TX001;Parent=GENE001\n",
        encoding="utf-8",
    )

    with pytest.raises(BulkReferenceError, match="GFF3-style"):
        parse_gtf_transcript_records(annotation)


@pytest.mark.parametrize("compressed", [False, True])
def test_kallisto_index_cache_reuse(tmp_path: Path, compressed: bool) -> None:
    fasta = tmp_path / ("transcripts.fa.gz" if compressed else "transcripts.fa")
    gtf = tmp_path / "annotation.gtf"
    if compressed:
        with gzip.open(fasta, "wt", encoding="utf-8") as handle:
            handle.write(">ENST000001\nACGT\n")
    else:
        _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])

    kallisto = tmp_path / "kallisto.sh"
    kallisto.write_text(
        "#!/bin/sh\n"
        'output=""\n'
        'for arg in "$@"; do\n'
        '  if [ "$prev" = "-i" ]; then output="$arg"; fi\n'
        '  prev="$arg"\n'
        "done\n"
        'printf "idx" > "$output"\n',
        encoding="utf-8",
    )
    kallisto.chmod(kallisto.stat().st_mode | stat.S_IXUSR)

    manager = BulkReferenceManager(
        cache_root=tmp_path / "cache",
        kallisto=KallistoRuntime(executable=kallisto, version="0.52.0-test"),
    )
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {
                "transcriptome_fasta": str(fasta),
                "annotation_gtf": str(gtf),
            },
        )
    )

    first = manager.prepare(manifest)
    second = manager.prepare(manifest)

    assert first.kallisto_index == second.kallisto_index
    assert first.index_identity == second.index_identity
    assert Path(first.kallisto_index).read_text(encoding="utf-8") == "idx"


def test_incomplete_cache_is_not_reused(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])

    kallisto = tmp_path / "kallisto.sh"
    kallisto.write_text(
        "#!/bin/sh\n"
        'output=""\n'
        'for arg in "$@"; do\n'
        '  if [ "$prev" = "-i" ]; then output="$arg"; fi\n'
        '  prev="$arg"\n'
        "done\n"
        'printf "idx" > "$output"\n',
        encoding="utf-8",
    )
    kallisto.chmod(kallisto.stat().st_mode | stat.S_IXUSR)
    manager = BulkReferenceManager(
        cache_root=tmp_path / "cache",
        kallisto=KallistoRuntime(executable=kallisto, version="0.52.0-test"),
    )
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {
                "transcriptome_fasta": str(fasta),
                "annotation_gtf": str(gtf),
            },
        )
    )
    prepared = manager.prepare(manifest)
    assert prepared.index_identity is not None
    stale_dir = tmp_path / "cache" / "kallisto_index" / prepared.index_identity
    (stale_dir / "complete.json").unlink()
    (stale_dir / "transcripts.idx").write_text("stale", encoding="utf-8")

    rebuilt = manager.prepare(manifest)

    assert Path(rebuilt.kallisto_index).read_text(encoding="utf-8") == "idx"


def test_failed_build_is_not_reused(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])

    kallisto = tmp_path / "kallisto-fail.sh"
    kallisto.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    kallisto.chmod(kallisto.stat().st_mode | stat.S_IXUSR)
    manager = BulkReferenceManager(
        cache_root=tmp_path / "cache",
        kallisto=KallistoRuntime(executable=kallisto, version="0.52.0-test"),
    )
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {
                "transcriptome_fasta": str(fasta),
                "annotation_gtf": str(gtf),
            },
        )
    )

    with pytest.raises(BulkReferenceError, match="Kallisto index construction failed"):
        manager.prepare(manifest)

    kallisto_ok = tmp_path / "kallisto-ok.sh"
    kallisto_ok.write_text(
        "#!/bin/sh\n"
        'output=""\n'
        'for arg in "$@"; do\n'
        '  if [ "$prev" = "-i" ]; then output="$arg"; fi\n'
        '  prev="$arg"\n'
        "done\n"
        'printf "idx" > "$output"\n',
        encoding="utf-8",
    )
    kallisto_ok.chmod(kallisto_ok.stat().st_mode | stat.S_IXUSR)
    manager_ok = BulkReferenceManager(
        cache_root=tmp_path / "cache",
        kallisto=KallistoRuntime(executable=kallisto_ok, version="0.52.0-test"),
    )

    prepared = manager_ok.prepare(manifest)

    assert Path(prepared.kallisto_index).read_text(encoding="utf-8") == "idx"


def test_existing_index_accepts_supplied_transcript_to_gene(tmp_path: Path) -> None:
    mapping = tmp_path / "transcript_to_gene.tsv"
    write_transcript_to_gene_table(
        mapping,
        [
            parse_gtf_transcript_records(
                _write_gtf_return(
                    tmp_path / "annotation.gtf",
                    [("ENST000001", "ENSG000001", "protein_coding", "GeneA")],
                )
            )["ENST000001"]
        ],
    )
    index = tmp_path / "transcripts.idx"
    index.write_text("idx", encoding="utf-8")

    payload = _manifest_payload(
        tmp_path,
        {
            "kallisto_index": str(index),
            "transcript_to_gene": str(mapping),
        },
        reference_mode=BulkReferenceMode.EXISTING_INDEX.value,
    )
    manifest = ProjectManifest.model_validate(payload)
    prepared = BulkReferenceManager(cache_root=tmp_path / "cache").prepare(manifest)

    assert prepared.kallisto_index == str(index.resolve())
    assert prepared.transcript_to_gene == str(mapping.resolve())
    read_supplied_transcript_to_gene(mapping)


def _write_gtf_return(path: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    _write_gtf(path, rows)
    return path


def test_analysis_only_requires_annotation_not_index(tmp_path: Path) -> None:
    mapping = tmp_path / "transcript_to_gene.tsv"
    write_transcript_to_gene_table(
        mapping,
        [
            parse_gtf_transcript_records(
                _write_gtf_return(
                    tmp_path / "annotation.gtf",
                    [("ENST000001", "ENSG000001", "protein_coding", "GeneA")],
                )
            )["ENST000001"]
        ],
    )
    payload = _manifest_payload(
        tmp_path,
        {"transcript_to_gene": str(mapping)},
        reference_mode=BulkReferenceMode.BUILD.value,
        parameters={"start_stage": "analysis"},
    )
    payload["samples"][0]["r1_files"] = []
    payload["samples"][0]["r2_files"] = []
    payload["samples"][0]["abundance_tsv"] = str(tmp_path / "inputs" / "sample_a" / "abundance.tsv")
    abundance = Path(payload["samples"][0]["abundance_tsv"])
    abundance.parent.mkdir(parents=True, exist_ok=True)
    abundance.write_text(
        "target_id\tlength\teff_length\test_counts\ttpm\nENST000001\t100\t80\t10\t1\n",
        encoding="utf-8",
    )

    manifest = ProjectManifest.model_validate(payload)
    prepared = BulkReferenceManager(cache_root=tmp_path / "cache").prepare(manifest)

    assert prepared.analysis_only is True
    assert prepared.kallisto_index is None


def test_analysis_only_rejects_incompatible_abundance_identifiers(tmp_path: Path) -> None:
    mapping = tmp_path / "transcript_to_gene.tsv"
    mapping.write_text("transcript_id\tgene_id\nTX001\tGENE001\n", encoding="utf-8")
    payload = _manifest_payload(
        tmp_path,
        {"transcript_to_gene": str(mapping)},
        reference_mode=BulkReferenceMode.BUILD.value,
        parameters={"start_stage": "analysis"},
    )
    payload["samples"][0]["r1_files"] = []
    payload["samples"][0]["r2_files"] = []
    abundance = tmp_path / "inputs" / "sample_a" / "abundance.tsv"
    abundance.parent.mkdir(parents=True, exist_ok=True)
    abundance.write_text(
        "target_id\tlength\teff_length\test_counts\ttpm\nTX999\t100\t80\t10\t1\n",
        encoding="utf-8",
    )
    payload["samples"][0]["abundance_tsv"] = str(abundance)

    with pytest.raises(BulkReferenceError, match="only 0.0%"):
        BulkReferenceManager(cache_root=tmp_path / "cache").prepare(
            ProjectManifest.model_validate(payload)
        )


def test_legacy_manifest_without_reference_mode_still_loads(
    manifest_payload: dict[str, object],
) -> None:
    payload = dict(manifest_payload)
    payload["schema_version"] = "1.0.0"
    payload.pop("reference_mode", None)
    manifest = ProjectManifest.model_validate(payload)

    assert manifest.schema_version == "1.0.0"
    assert manifest.reference_mode is None


def test_schema_1_1_requires_reference_mode(tmp_path: Path) -> None:
    payload = _manifest_payload(
        tmp_path,
        {
            "transcriptome_fasta": str(tmp_path / "transcripts.fa"),
            "annotation_gtf": str(tmp_path / "annotation.gtf"),
        },
    )
    payload.pop("reference_mode")

    with pytest.raises(Exception, match="reference_mode"):
        ProjectManifest.model_validate(payload)


def test_prepared_mapping_has_normalized_columns(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "lncRNA", "GeneA")])

    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {
                "transcriptome_fasta": str(fasta),
                "annotation_gtf": str(gtf),
            },
        )
    )
    prepared = BulkReferenceManager(cache_root=tmp_path / "cache").prepare(manifest)
    header = Path(prepared.transcript_to_gene).read_text(encoding="utf-8").splitlines()[0]

    assert header == "\t".join(
        ["transcript_id", "gene_id", "gene_name", "gene_biotype", "transcript_biotype"]
    )


def test_complete_marker_is_written_last(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])

    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {
                "transcriptome_fasta": str(fasta),
                "annotation_gtf": str(gtf),
            },
        )
    )
    prepared = BulkReferenceManager(cache_root=tmp_path / "cache").prepare(manifest)
    assert prepared.annotation_identity is not None
    marker = (
        tmp_path / "cache" / "transcript_to_gene" / prepared.annotation_identity / "complete.json"
    )
    payload = json.loads(marker.read_text(encoding="utf-8"))

    assert payload["artifact"] == "transcript_to_gene.tsv"
    assert payload["metadata"]["normalization_version"] == "1"
    assert payload["metadata"]["overlap"]["policy"] == "exact"

    payload["identity"] = "wrong-cache-identity"
    marker.write_text(json.dumps(payload), encoding="utf-8")
    BulkReferenceManager(cache_root=tmp_path / "cache").prepare(manifest)
    repaired = json.loads(marker.read_text(encoding="utf-8"))
    assert repaired["identity"] == prepared.annotation_identity
