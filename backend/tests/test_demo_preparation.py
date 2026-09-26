from __future__ import annotations

import gzip
import runpy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest


def _write_fastq(path: Path, mate: int) -> None:
    with gzip.open(path, "wt", encoding="ascii") as handle:
        for index in range(1, 4):
            handle.write(f"@source-{index}/{mate}\nACGT\n+\nIIII\n")


def test_subset_rewrites_headers_and_preserves_sources(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "prepare_human_demo.py"
    module: dict[str, Any] = runpy.run_path(str(script))
    subset_pair = module["_subset_pair"]

    source_r1 = tmp_path / "source_R1.fastq.gz"
    source_r2 = tmp_path / "source_R2.fastq.gz"
    destination_r1 = tmp_path / "derived" / "DEMO_H_01_R1.fastq.gz"
    destination_r2 = tmp_path / "derived" / "DEMO_H_01_R2.fastq.gz"
    _write_fastq(source_r1, 1)
    _write_fastq(source_r2, 2)
    source_hashes = module["_sha256"](source_r1), module["_sha256"](source_r2)

    count, digest_r1, digest_r2 = subset_pair(
        source_r1,
        source_r2,
        destination_r1,
        destination_r2,
        "DEMO_H_01",
        2,
    )

    assert count == 2
    assert digest_r1 == module["_sha256"](destination_r1)
    assert digest_r2 == module["_sha256"](destination_r2)
    assert source_hashes == (module["_sha256"](source_r1), module["_sha256"](source_r2))
    with gzip.open(destination_r1, "rt", encoding="ascii") as handle:
        records = handle.read().splitlines()
    assert records == [
        "@DEMO_H_01:000000001/1",
        "ACGT",
        "+",
        "IIII",
        "@DEMO_H_01:000000002/1",
        "ACGT",
        "+",
        "IIII",
    ]
    assert destination_r1.stat().st_mode & 0o777 == 0o600
    assert destination_r2.stat().st_mode & 0o777 == 0o600


def test_restricted_human_demo_manifest_uses_existing_index_without_biomart(
    tmp_path: Path,
) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "prepare_human_demo.py"
    module: dict[str, Any] = runpy.run_path(str(script))
    manifest_fn = module["_manifest"]
    transcriptome = tmp_path / "transcripts.fa"
    index = tmp_path / "transcripts.idx"
    gtf = tmp_path / "annotation.gtf"
    transcriptome.write_text(">tx1\nACGT\n", encoding="utf-8")
    index.write_bytes(b"idx")
    gtf.write_text("##gff-version 3\n", encoding="utf-8")
    output_root = tmp_path / "demo-out"
    output_root.mkdir()
    (output_root / "inputs").mkdir()
    r1 = output_root / "inputs" / "DEMO_H_01_R1.fastq.gz"
    r2 = output_root / "inputs" / "DEMO_H_01_R2.fastq.gz"
    r1.write_bytes(b"")
    r2.write_bytes(b"")
    payload = manifest_fn(
        output_root,
        transcriptome,
        index,
        gtf,
        [("DEMO_H_01", 1, module["FastqPair"]("src", "H", r1, r2))],
        datetime.now(UTC),
        1000,
    )
    manifest = ProjectManifest.model_validate(payload)
    assert manifest.schema_version == "1.1.0"
    assert manifest.reference_mode == BulkReferenceMode.EXISTING_INDEX
    assert "biomart" not in manifest.reference_resources
    assert manifest.reference_resources["kallisto_index"] == str(index)
    assert manifest.reference_resources["annotation_gtf"] == str(gtf)
    assert manifest.pipeline_version == "0.5.0"
    assert "execution_mode" not in manifest.parameters
