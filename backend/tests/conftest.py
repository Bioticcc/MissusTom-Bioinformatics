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
    transcriptome = reference_directory / "transcripts.fa"
    annotation = reference_directory / "annotation.gtf"
    biomart = reference_directory / "biomart.tsv"
    for path in (r1, r2, r1_b, r2_b, transcriptome, annotation, biomart):
        path.touch()

    return {
        "schema_version": "1.0.0",
        "project_name": "Synthetic pilot",
        "project_identifier": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "input_directory": str(input_directory),
        "output_directory": str(output_directory),
        "pipeline_identifier": "bulk-rnaseq",
        "pipeline_version": "0.1.0-preview",
        "organism": "Mus musculus",
        "reference_genome": "GRCm39",
        "annotation_source": "GENCODE",
        "reference_resources": {
            "transcriptome_fasta": str(transcriptome),
            "annotation_gtf": str(annotation),
            "biomart": str(biomart),
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
        ],
        "comparisons": [
            {
                "comparison_id": "treatment_vs_control",
                "numerator": "treatment",
                "denominator": "control",
                "label": "Treatment vs control",
            }
        ],
        "parameters": {"minimum_read_length": 20},
        "resource_profile": {"cpus": 4, "memory_gb": 8, "max_parallel_tasks": 1},
        "execution_profile": "local",
        "application_version": "0.1.0",
        "pipeline_status": "draft",
    }
