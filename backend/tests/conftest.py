from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def manifest_payload(tmp_path: Path) -> dict[str, Any]:
    input_directory = tmp_path / "inputs"
    output_directory = tmp_path / "project-output"
    reference_directory = tmp_path / "references"
    input_directory.mkdir()
    reference_directory.mkdir()

    r1 = input_directory / "synthetic_A_R1.fastq.gz"
    r2 = input_directory / "synthetic_A_R2.fastq.gz"
    r1_b = input_directory / "synthetic_B_R1.fastq.gz"
    r2_b = input_directory / "synthetic_B_R2.fastq.gz"
    r1_c = input_directory / "synthetic_C_R1.fastq.gz"
    r2_c = input_directory / "synthetic_C_R2.fastq.gz"
    r1_d = input_directory / "synthetic_D_R1.fastq.gz"
    r2_d = input_directory / "synthetic_D_R2.fastq.gz"
    transcriptome = reference_directory / "transcripts.fa"
    annotation = reference_directory / "annotation.gtf"
    biomart = reference_directory / "biomart.tsv"
    kallisto_index = reference_directory / "transcripts.idx"
    for path in (
        r1,
        r2,
        r1_b,
        r2_b,
        r1_c,
        r2_c,
        r1_d,
        r2_d,
        transcriptome,
        annotation,
        biomart,
        kallisto_index,
    ):
        path.touch()
    transcriptome.write_text(
        ">TX001\nACGTACGTACGT\n>TX002\nTGCATGCATGCA\n",
        encoding="utf-8",
    )
    annotation.write_text(
        'synthetic\tfixture\ttranscript\t1\t12\t.\t+\t.\tgene_id "GENE001"; '
        'transcript_id "TX001"; gene_name "Gene one"; gene_type "protein_coding";\n'
        'synthetic\tfixture\ttranscript\t1\t12\t.\t+\t.\tgene_id "GENE002"; '
        'transcript_id "TX002"; gene_name "Gene two"; gene_type "lncRNA";\n',
        encoding="utf-8",
    )

    return {
        "schema_version": "1.1.0",
        "reference_mode": "existing-index",
        "project_name": "Synthetic pilot",
        "project_identifier": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "input_directory": str(input_directory),
        "output_directory": str(output_directory),
        "pipeline_identifier": "bulk-rnaseq",
        "pipeline_version": "0.5.0",
        "organism": "Synthetic organism",
        "reference_genome": "synthetic-reference",
        "annotation_source": "synthetic-fixture",
        "reference_resources": {
            "transcriptome_fasta": str(transcriptome),
            "annotation_gtf": str(annotation),
            "biomart": str(biomart),
            "kallisto_index": str(kallisto_index),
        },
        "library_type": "total RNA",
        "read_layout": "paired-end",
        "strandedness": "reverse",
        "samples": [
            {
                "sample_id": "synthetic_A",
                "r1_files": [str(r1)],
                "r2_files": [str(r2)],
                "condition": "control",
                "biological_replicate": "1",
                "batch": "batch-1",
                "covariates": {"sex": "not-specified"},
                "included": True,
            },
            {
                "sample_id": "synthetic_B",
                "r1_files": [str(r1_b)],
                "r2_files": [str(r2_b)],
                "condition": "treatment",
                "biological_replicate": "1",
                "batch": "batch-1",
                "covariates": {},
                "included": True,
            },
            {
                "sample_id": "synthetic_C",
                "r1_files": [str(r1_c)],
                "r2_files": [str(r2_c)],
                "condition": "control",
                "biological_replicate": "2",
                "batch": "batch-1",
                "covariates": {},
                "included": True,
            },
            {
                "sample_id": "synthetic_D",
                "r1_files": [str(r1_d)],
                "r2_files": [str(r2_d)],
                "condition": "treatment",
                "biological_replicate": "2",
                "batch": "batch-1",
                "covariates": {},
                "included": True,
            },
        ],
        "comparisons": [
            {
                "comparison_id": "treatment_vs_control",
                "numerator": "treatment",
                "denominator": "control",
                "label": "Treatment vs control",
            }
        ],
        "parameters": {
            "minimum_read_length": 20,
            "adapter_r1": "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA",
            "adapter_r2": "AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT",
            "trim_quality": 20,
            "trim_minimum_length": 20,
            "minimum_group_size": 2,
            "adjusted_p_value": 0.05,
            "absolute_log2_fold_change": 0.3,
        },
        "resource_profile": {"cpus": 4, "memory_gb": 8, "max_parallel_tasks": 1},
        "execution_profile": "local",
        "application_version": "0.1.0",
        "pipeline_status": "draft",
    }
