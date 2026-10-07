from __future__ import annotations

import gzip
import json
import os
import stat
import threading
from pathlib import Path

import pytest

from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest
from missus_tom.services import bulk_references as references_module
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
    assert read_supplied_transcript_to_gene(mapping)[0].transcript_id == "TX001"


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


@pytest.mark.parametrize("exact_count", [94, 96])
@pytest.mark.parametrize("version_in_gtf", [False, True])
def test_mixed_versions_normalize_before_compatibility(
    tmp_path: Path, exact_count: int, version_in_gtf: bool
) -> None:
    gtf = tmp_path / "annotation.gtf"
    ids = [f"ENST{index:011d}" for index in range(100)]
    versioned = [
        identifier if i < exact_count else f"{identifier}.2" for i, identifier in enumerate(ids)
    ]
    fasta_ids, annotation_ids = (ids, versioned) if version_in_gtf else (versioned, ids)
    _write_gtf(
        gtf,
        [(identifier, "ENSG000001", "protein_coding", "GeneA") for identifier in annotation_ids],
    )
    gtf_records = parse_gtf_transcript_records(gtf)
    overlap = assess_fasta_gtf_overlap(fasta_ids=fasta_ids, gtf_records=gtf_records)
    assert overlap.exact_overlap_fraction == exact_count / 100
    assert overlap.overlap_fraction == 1.0
    assert overlap.policy == "version_stripped"
    mapped = map_fasta_to_gtf_records(
        fasta_ids=fasta_ids, gtf_records=gtf_records, policy=overlap.policy
    )
    assert [record.transcript_id for record in mapped] == fasta_ids


def test_unrelated_collision_does_not_disable_normalization(tmp_path: Path) -> None:
    gtf = tmp_path / "annotation.gtf"
    _write_gtf(
        gtf,
        [
            ("ENST000001", "GENE001", "protein_coding", "GeneA"),
            ("TX001.1", "GENE002", "protein_coding", "GeneB"),
            ("TX001.2", "GENE003", "protein_coding", "GeneC"),
        ],
    )
    gtf_records = parse_gtf_transcript_records(gtf)
    fasta_ids = ["ENST000001.2", "TX001.3", "TX001.1"]
    overlap = assess_fasta_gtf_overlap(fasta_ids=fasta_ids, gtf_records=gtf_records)
    assert overlap.overlap_fraction == 2 / 3
    mapped = map_fasta_to_gtf_records(
        fasta_ids=fasta_ids, gtf_records=gtf_records, policy=overlap.policy
    )
    assert [(record.transcript_id, record.gene_id) for record in mapped] == [
        ("ENST000001.2", "GENE001"),
        ("TX001.1", "GENE002"),
    ]


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


def test_gtf_ignores_blank_lines_and_comments(tmp_path: Path) -> None:
    annotation = tmp_path / "annotation.gtf"
    annotation.write_text(
        "#genebuild\n"
        "\n"
        'chr1\tfixture\ttranscript\t1\t10\t.\t+\t.\tgene_id "GENE1"; transcript_id "TX1";\n',
        encoding="utf-8",
    )

    records = parse_gtf_transcript_records(annotation)

    assert set(records) == {"TX1"}
    assert records["TX1"].gene_id == "GENE1"


def test_gtf_rejects_malformed_feature_row_with_line_number(tmp_path: Path) -> None:
    annotation = tmp_path / "annotation.gtf"
    annotation.write_text(
        'chr1\tfixture\texon\t1\t10\t.\t+\t.\tgene_id "GENE1"; transcript_id "TX1";\n'
        "chr1\tfixture\texon\t1\t10\t.\t+\t.\n",
        encoding="utf-8",
    )

    with pytest.raises(BulkReferenceError, match=r"line 2.*9 tab-separated"):
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


def test_metadata_cache_hit_never_hashes_or_parses_unchanged_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])
    manager = BulkReferenceManager(cache_root=tmp_path / "cache")
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {"transcriptome_fasta": str(fasta), "annotation_gtf": str(gtf)},
        )
    )

    first = manager.prepare(manifest)
    monkeypatch.setattr(
        manager,
        "_sha256_file",
        lambda _path: pytest.fail("cache hit must not hash a source reference"),
    )
    monkeypatch.setattr(
        references_module,
        "parse_gtf_transcript_records",
        lambda *_args, **_kwargs: pytest.fail("cache hit must not parse the GTF"),
    )

    second = manager.prepare(manifest)

    assert second.transcript_to_gene == first.transcript_to_gene
    assert second.annotation_identity == first.annotation_identity


@pytest.mark.parametrize("change", ["size", "mtime", "ctime"])
def test_metadata_cache_invalidates_changed_gtf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])
    manager = BulkReferenceManager(cache_root=tmp_path / "cache")
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {"transcriptome_fasta": str(fasta), "annotation_gtf": str(gtf)},
        )
    )
    manager.prepare(manifest)
    original_hash = manager._sha256_file
    hashes: list[Path] = []

    def record_hash(path: Path) -> str:
        hashes.append(path)
        return original_hash(path)

    monkeypatch.setattr(manager, "_sha256_file", record_hash)
    if change == "size":
        gtf.write_text(gtf.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    elif change == "mtime":
        state = gtf.stat()
        os.utime(gtf, ns=(state.st_atime_ns, state.st_mtime_ns + 1))
    else:
        state = gtf.stat()
        gtf.chmod(state.st_mode | stat.S_IXUSR)
        assert gtf.stat().st_ctime_ns != state.st_ctime_ns
        assert gtf.stat().st_mtime_ns == state.st_mtime_ns
        assert gtf.stat().st_size == state.st_size

    manager.prepare(manifest)

    assert gtf in hashes


def test_concurrent_metadata_cache_miss_prepares_reference_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {"transcriptome_fasta": str(fasta), "annotation_gtf": str(gtf)},
        )
    )
    calls = 0
    calls_lock = threading.Lock()
    original_parse = references_module.parse_gtf_transcript_records

    def count_parse(*args: object, **kwargs: object):
        nonlocal calls
        with calls_lock:
            calls += 1
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(references_module, "parse_gtf_transcript_records", count_parse)
    results: list[str] = []
    failures: list[BaseException] = []

    def prepare() -> None:
        try:
            prepared = BulkReferenceManager(cache_root=tmp_path / "cache").prepare(manifest)
            results.append(prepared.transcript_to_gene)
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    workers = [threading.Thread(target=prepare) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)

    assert not failures
    assert len(results) == 2
    assert calls == 1


def test_corrupt_metadata_index_forces_safe_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])
    manager = BulkReferenceManager(cache_root=tmp_path / "cache")
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {"transcriptome_fasta": str(fasta), "annotation_gtf": str(gtf)},
        )
    )
    manager.prepare(manifest)
    manager._metadata_index_path().write_text("not json\n", encoding="utf-8")
    parses = 0
    original_parse = references_module.parse_gtf_transcript_records

    def count_parse(*args: object, **kwargs: object):
        nonlocal parses
        parses += 1
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(references_module, "parse_gtf_transcript_records", count_parse)

    manager.prepare(manifest)

    assert parses == 1
    assert json.loads(manager._metadata_index_path().read_text(encoding="utf-8"))["entries"]


def test_authoritative_mapping_does_not_hash_optional_gtf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    mapping = tmp_path / "transcript_to_gene.tsv"
    index = tmp_path / "transcripts.idx"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])
    mapping.write_text("transcript_id\tgene_id\nENST000001\tENSG000001\n", encoding="utf-8")
    index.write_text("index", encoding="utf-8")
    manager = BulkReferenceManager(cache_root=tmp_path / "cache")
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {
                "transcriptome_fasta": str(fasta),
                "annotation_gtf": str(gtf),
                "transcript_to_gene": str(mapping),
                "kallisto_index": str(index),
            },
            reference_mode="existing-index",
        )
    )
    original_hash = manager._sha256_file

    def reject_gtf_hash(path: Path) -> str:
        if path.resolve() == gtf.resolve():
            pytest.fail("authoritative mapping path must not hash optional GTF")
        return original_hash(path)

    monkeypatch.setattr(manager, "_sha256_file", reject_gtf_hash)

    prepared = manager.prepare(manifest)

    assert prepared.transcript_to_gene == str(mapping.resolve())


def test_analysis_only_authoritative_mapping_does_not_hash_optional_gtf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gtf = tmp_path / "annotation.gtf"
    mapping = tmp_path / "transcript_to_gene.tsv"
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])
    mapping.write_text("transcript_id\tgene_id\nENST000001\tENSG000001\n", encoding="utf-8")
    abundance = tmp_path / "inputs" / "sample_a" / "abundance.tsv"
    abundance.parent.mkdir(parents=True, exist_ok=True)
    abundance.write_text(
        "target_id\tlength\teff_length\test_counts\ttpm\nENST000001\t100\t80\t10\t1\n",
        encoding="utf-8",
    )
    payload = _manifest_payload(
        tmp_path,
        {"transcript_to_gene": str(mapping), "annotation_gtf": str(gtf)},
        parameters={"start_stage": "analysis"},
    )
    payload["samples"][0]["r1_files"] = []
    payload["samples"][0]["r2_files"] = []
    payload["samples"][0]["abundance_tsv"] = str(abundance)
    manifest = ProjectManifest.model_validate(payload)
    manager = BulkReferenceManager(cache_root=tmp_path / "cache")
    original_hash = manager._sha256_file

    def reject_gtf_hash(path: Path) -> str:
        if path.resolve() == gtf.resolve():
            pytest.fail("analysis-only authoritative mapping must not hash optional GTF")
        return original_hash(path)

    monkeypatch.setattr(manager, "_sha256_file", reject_gtf_hash)
    monkeypatch.setattr(
        references_module,
        "parse_gtf_transcript_records",
        lambda *_args, **_kwargs: pytest.fail(
            "analysis-only authoritative mapping must not parse optional GTF"
        ),
    )

    prepared = manager.prepare(manifest)

    assert prepared.analysis_only is True
    assert prepared.transcript_to_gene == str(mapping.resolve())


def test_stale_metadata_with_missing_artifact_rebuilds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])
    manager = BulkReferenceManager(cache_root=tmp_path / "cache")
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {"transcriptome_fasta": str(fasta), "annotation_gtf": str(gtf)},
        )
    )
    prepared = manager.prepare(manifest)
    mapping_dir = Path(prepared.transcript_to_gene).parent
    for child in mapping_dir.iterdir():
        child.unlink()
    parses = 0
    original_parse = references_module.parse_gtf_transcript_records

    def count_parse(*args: object, **kwargs: object):
        nonlocal parses
        parses += 1
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(references_module, "parse_gtf_transcript_records", count_parse)

    rebuilt = manager.prepare(manifest)

    assert parses == 1
    assert Path(rebuilt.transcript_to_gene).is_file()
    assert Path(rebuilt.transcript_to_gene).stat().st_size > 0


def test_metadata_entry_without_annotation_identity_is_not_a_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])
    manager = BulkReferenceManager(cache_root=tmp_path / "cache")
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {"transcriptome_fasta": str(fasta), "annotation_gtf": str(gtf)},
        )
    )
    manager.prepare(manifest)
    index_path = manager._metadata_index_path()
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["entries"]
    for entry in payload["entries"].values():
        entry.pop("annotation_identity", None)
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    parses = 0
    original_parse = references_module.parse_gtf_transcript_records

    def count_parse(*args: object, **kwargs: object):
        nonlocal parses
        parses += 1
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(references_module, "parse_gtf_transcript_records", count_parse)

    manager.prepare(manifest)

    assert parses == 1


def test_kallisto_version_change_invalidates_metadata_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {"transcriptome_fasta": str(fasta), "annotation_gtf": str(gtf)},
        )
    )
    first = BulkReferenceManager(
        cache_root=tmp_path / "cache",
        kallisto=KallistoRuntime(executable=kallisto, version="0.51.0-test"),
    )
    first.prepare(manifest)
    second = BulkReferenceManager(
        cache_root=tmp_path / "cache",
        kallisto=KallistoRuntime(executable=kallisto, version="0.52.0-test"),
    )
    hashes: list[Path] = []
    original_hash = second._sha256_file

    def record_hash(path: Path) -> str:
        hashes.append(path)
        return original_hash(path)

    monkeypatch.setattr(second, "_sha256_file", record_hash)

    second.prepare(manifest)

    assert gtf in hashes


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


def test_zero_byte_kallisto_index_is_failed_and_not_marked_complete(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["TX001"])
    _write_gtf(gtf, [("TX001", "GENE001", "protein_coding", "GeneA")])

    def empty_index_runner(command: object, _environment: object) -> object:
        arguments = list(command)  # type: ignore[arg-type]
        Path(arguments[arguments.index("-i") + 1]).touch()
        import subprocess

        return subprocess.CompletedProcess(arguments, 0, stdout="fake completed", stderr="")

    manager = BulkReferenceManager(
        cache_root=tmp_path / "cache",
        kallisto=KallistoRuntime(executable=tmp_path / "fake-kallisto", version="0.52.0-test"),
        command_runner=empty_index_runner,  # type: ignore[arg-type]
    )
    manifest = ProjectManifest.model_validate(
        _manifest_payload(
            tmp_path,
            {"transcriptome_fasta": str(fasta), "annotation_gtf": str(gtf)},
        )
    )

    with pytest.raises(BulkReferenceError, match="Kallisto index construction failed"):
        manager.prepare(manifest)

    index_dirs = list((tmp_path / "cache" / "kallisto_index").iterdir())
    assert len(index_dirs) == 1
    assert (index_dirs[0] / "failed.json").is_file()
    assert (index_dirs[0] / "build.log").read_text(encoding="utf-8") == "fake completed"
    assert not (index_dirs[0] / "complete.json").exists()
    assert not (index_dirs[0] / "transcripts.idx").exists()


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
    assert payload["metadata"]["normalization_version"] == "2"
    assert payload["metadata"]["overlap"]["policy"] == "exact"

    payload["identity"] = "wrong-cache-identity"
    marker.write_text(json.dumps(payload), encoding="utf-8")
    BulkReferenceManager(cache_root=tmp_path / "cache").prepare(manifest)
    repaired = json.loads(marker.read_text(encoding="utf-8"))
    assert repaired["identity"] == prepared.annotation_identity


def test_conflicting_mapping_rows_are_rejected(tmp_path: Path) -> None:
    mapping = tmp_path / "tx2gene.tsv"
    mapping.write_text(
        "transcript_id\tgene_id\nTX001\tGENE001\nTX001\tGENE002\n",
        encoding="utf-8",
    )

    with pytest.raises(BulkReferenceError, match="conflicting gene_id"):
        read_supplied_transcript_to_gene(mapping)


def test_identical_duplicate_mapping_rows_are_deduped(tmp_path: Path) -> None:
    mapping = tmp_path / "tx2gene.tsv"
    mapping.write_text(
        "transcript_id\tgene_id\tgene_name\nTX001\tGENE001\tGeneA\nTX001\tGENE001\tGeneA\n",
        encoding="utf-8",
    )

    records = read_supplied_transcript_to_gene(mapping)

    assert len(records) == 1
    assert records[0].transcript_id == "TX001"


def test_empty_mapping_identifiers_are_rejected(tmp_path: Path) -> None:
    mapping = tmp_path / "tx2gene.tsv"
    mapping.write_text("transcript_id\tgene_id\n\tGENE001\n", encoding="utf-8")

    with pytest.raises(BulkReferenceError, match="empty identifier"):
        read_supplied_transcript_to_gene(mapping)


def test_failed_build_retains_build_log_and_failed_marker(tmp_path: Path) -> None:
    fasta = tmp_path / "transcripts.fa"
    gtf = tmp_path / "annotation.gtf"
    _write_fasta(fasta, ["ENST000001"])
    _write_gtf(gtf, [("ENST000001", "ENSG000001", "protein_coding", "GeneA")])

    kallisto = tmp_path / "kallisto-fail.sh"
    kallisto.write_text("#!/bin/sh\necho failure-on-stderr 1>&2\nexit 2\n", encoding="utf-8")
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

    with pytest.raises(BulkReferenceError, match="See .*build.log"):
        manager.prepare(manifest)

    index_identity = None
    for child in (tmp_path / "cache" / "kallisto_index").iterdir():
        if (child / "failed.json").is_file():
            index_identity = child.name
            assert (child / "build.log").is_file()
            assert "failure-on-stderr" in (child / "build.log").read_text(encoding="utf-8")
            break
    assert index_identity is not None

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
    rebuilt = manager_ok.prepare(manifest)

    assert Path(rebuilt.kallisto_index).read_text(encoding="utf-8") == "idx"
    index_dir = Path(rebuilt.kallisto_index).parent
    assert not (index_dir / "failed.json").is_file()


def test_safe_reference_read_maps_io_failures(tmp_path: Path) -> None:
    from missus_tom.services.bulk_references import safe_reference_read

    missing = tmp_path / "missing.fa"
    with pytest.raises(BulkReferenceError, match="missing"):
        safe_reference_read("transcriptome_fasta", lambda: missing.read_text(encoding="utf-8"))

    bad_gzip = tmp_path / "bad.fa.gz"
    bad_gzip.write_bytes(b"not gzip")
    with pytest.raises(BulkReferenceError, match="invalid gzip"):
        safe_reference_read("transcriptome_fasta", lambda: iter_fasta_transcript_ids(bad_gzip))

    invalid_utf8 = tmp_path / "invalid.fa"
    invalid_utf8.write_bytes(b">\xff\xfe\nACGT\n")
    with pytest.raises(BulkReferenceError, match="UTF-8"):
        safe_reference_read("transcriptome_fasta", lambda: iter_fasta_transcript_ids(invalid_utf8))


def test_cache_lock_cancellation_while_waiting(tmp_path: Path) -> None:
    import fcntl
    import threading
    import time

    from missus_tom.services.bulk_references import _cache_lock

    cache_dir = tmp_path / "cache" / "kallisto_index" / "lock-test"
    cache_dir.mkdir(parents=True)
    lock_path = cache_dir / ".prepare.lock"
    lock_path.touch()
    release = threading.Event()

    def hold_lock() -> None:
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            release.set()
            time.sleep(3)

    holder = threading.Thread(target=hold_lock, daemon=True)
    holder.start()
    release.wait(timeout=2)

    cancelled = False

    def cancel_check() -> bool:
        nonlocal cancelled
        cancelled = True
        return True

    with (
        pytest.raises(BulkReferenceError, match="cancelled"),
        _cache_lock(
            cache_dir,
            cancellation_check=cancel_check,
            lock_timeout_seconds=5.0,
        ),
    ):
        pass

    assert cancelled
    holder.join(timeout=5)
