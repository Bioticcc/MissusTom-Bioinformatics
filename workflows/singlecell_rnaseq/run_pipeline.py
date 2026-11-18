#!/usr/bin/env python3
"""Validate a standalone SingleCell manifest and launch its local Nextflow graph.

This development runner is deliberately separate from the desktop project model.
Check-only reads the small feature/barcode tables and matrix header, never runs R.
The R import performs the full sparse-count validation before analysis.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = ("matrix.mtx.gz", "features.tsv.gz", "barcodes.tsv.gz")


def exact_keys(value: dict, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} requires exactly: {', '.join(sorted(expected))}")


def text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be nonempty text without control characters")
    return value


def number(value: object, label: str, low: float, high: float, *, integer=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
        or (integer and not isinstance(value, int))
    ):
        raise ValueError(
            f"{label} must be {'an integer' if integer else 'a number'} in [{low}, {high}]"
        )
    return value


def inspect_matrix(directory: Path) -> tuple[list[str], int]:
    for name in FILES:
        if not (directory / name).is_file():
            raise ValueError(f"missing 10x v3 input: {directory / name}")
    with gzip.open(directory / FILES[1], "rt") as handle:
        features = [line.rstrip("\n").split("\t") for line in handle]
    if not features or any(len(row) != 3 or row[2] != "Gene Expression" for row in features):
        raise ValueError("features.tsv.gz must contain only three-column Gene Expression rows")
    ids = [row[0] for row in features]
    if len(set(ids)) != len(ids) or any(not gene or re.search(r"[_|\s]", gene) for gene in ids):
        raise ValueError(
            "feature IDs must be unique, nonempty, and free of whitespace, '_' and '|'"
        )
    with gzip.open(directory / FILES[2], "rt") as handle:
        barcodes = [line.rstrip("\n") for line in handle]
    if (
        not barcodes
        or len(set(barcodes)) != len(barcodes)
        or any(not re.fullmatch(r"[A-Za-z0-9.-]+", barcode) for barcode in barcodes)
    ):
        raise ValueError("barcodes must be unique and contain only letters, digits, '.' and '-'")
    with gzip.open(directory / FILES[0], "rt") as handle:
        header = handle.readline().strip()
        if header not in {
            "%%MatrixMarket matrix coordinate integer general",
            "%%MatrixMarket matrix coordinate real general",
        }:
            raise ValueError("matrix must be a general coordinate Matrix Market count matrix")
        line = handle.readline()
        while line.startswith("%"):
            line = handle.readline()
        dimensions = [int(v) for v in line.split()]
    if len(dimensions) != 3 or dimensions[:2] != [len(ids), len(barcodes)] or dimensions[2] < 1:
        raise ValueError("matrix dimensions must match features/barcodes and include counts")
    return ids, len(barcodes)


def validate_analysis(analysis: dict) -> None:
    exact_keys(
        analysis,
        {
            "normalization",
            "integration",
            "variable_features",
            "pcs",
            "resolution",
            "seed",
            "cluster_markers",
        },
        "analysis",
    )
    if analysis["normalization"] != "log_normalize" or analysis["integration"] != "none":
        raise ValueError("v1 supports normalization=log_normalize and integration=none")
    for key, low, high in (
        ("variable_features", 20, 10000),
        ("pcs", 2, 100),
        ("seed", 1, 2147483647),
    ):
        number(analysis[key], key, low, high, integer=True)
    number(analysis["resolution"], "resolution", 0.01, 5)
    if not isinstance(analysis["cluster_markers"], bool):
        raise ValueError("cluster_markers must be boolean")


def validate_qc(qc: dict) -> None:
    exact_keys(qc, {"min_counts", "min_features", "max_features", "max_mito_percent"}, "qc")
    for key in ("min_counts", "min_features", "max_features"):
        number(qc[key], key, 1, 100000000, integer=True)
    number(qc["max_mito_percent"], "max_mito_percent", 0, 100)
    if qc["max_features"] < qc["min_features"]:
        raise ValueError("max_features must be >= min_features")


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text())
    exact_keys(data, {"schema_version", "reference", "samples", "analysis"}, "manifest")
    if data["schema_version"] != "singlecell-counts-v1":
        raise ValueError("unsupported schema_version; expected singlecell-counts-v1")
    reference = data["reference"]
    exact_keys(reference, {"species", "genome_build", "mitochondrial_gene_ids"}, "reference")
    text(reference["species"], "species")
    text(reference["genome_build"], "genome_build")
    mito = reference["mitochondrial_gene_ids"]
    if not isinstance(mito, list) or not mito or any(not isinstance(g, str) for g in mito):
        raise ValueError("mitochondrial_gene_ids requires an explicit nonempty gene-ID list")
    if len(set(mito)) != len(mito):
        raise ValueError("mitochondrial_gene_ids must be unique")
    validate_analysis(data["analysis"])
    samples = data["samples"]
    if not isinstance(samples, list) or not 1 <= len(samples) <= 9999:
        raise ValueError("samples must contain 1..9999 entries")
    seen_ids, seen_paths, expected_genes = set(), set(), None
    for index, sample in enumerate(samples, 1):
        exact_keys(
            sample,
            {"sample_id", "donor_id", "condition", "batch", "matrix_dir", "matrix_kind", "qc"},
            "sample",
        )
        identifier = text(sample["sample_id"], "sample_id")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", identifier) or identifier in seen_ids:
            raise ValueError(
                "sample_id must be unique: letter followed by up to 63 letters/digits/hyphens"
            )
        seen_ids.add(identifier)
        for key in ("donor_id", "condition", "batch"):
            text(sample[key], key)
        if sample["matrix_kind"] != "filtered":
            raise ValueError(
                "v1 requires filtered matrices; raw droplets need a cell-calling stage"
            )
        validate_qc(sample["qc"])
        directory = Path(text(sample["matrix_dir"], "matrix_dir"))
        directory = (path.parent / directory).resolve()
        if directory in seen_paths:
            raise ValueError("the same matrix directory cannot represent two samples")
        seen_paths.add(directory)
        genes, _ = inspect_matrix(directory)
        if expected_genes is not None and genes != expected_genes:
            raise ValueError(
                "all samples must have identical ordered feature IDs from one reference"
            )
        expected_genes = genes
        if not set(mito).issubset(genes):
            raise ValueError("every declared mitochondrial gene ID must occur in the feature table")
        sample["matrix_dir"] = str(directory)
        sample["staged_dir"] = f"matrix{index:04d}"
    return data


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_outputs(run_dir: Path, *, markers: bool) -> None:
    required = [
        "qc/cell_qc.tsv",
        "qc/sample_qc.tsv",
        "tables/features.tsv",
        "tables/cell_metadata.tsv",
        "tables/marker_status.tsv",
        "objects/singlecell.rds",
        "tables/provenance/prepared_manifest.json",
        "tables/provenance/sessionInfo.txt",
        "tables/provenance/installed_packages.txt",
        "tables/provenance/analysis_notes.txt",
        "figures/qc_retained_cells.pdf",
        "figures/pca_elbow.pdf",
        *[
            f"figures/umap_{group}.pdf"
            for group in ("seurat_clusters", "sample_id", "condition", "batch")
        ],
    ]
    if markers:
        required.append("tables/exploratory_cluster_markers.tsv")
    missing = [
        name
        for name in required
        if not (run_dir / "results" / name).is_file()
        or (run_dir / "results" / name).stat().st_size == 0
    ]
    if missing:
        raise ValueError("incomplete SingleCell outputs: " + ", ".join(missing))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--cpus", type=int, default=2, choices=range(1, 65))
    parser.add_argument("--memory-gb", type=int, default=8, choices=range(1, 513))
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest.resolve())
        if args.check_only:
            print(
                f"Input structure valid: {len(manifest['samples'])} sample(s). "
                "Counts and R not checked."
            )
            return 0
        if args.run_dir is None:
            raise ValueError(
                "--run-dir is required for execution; use a new directory for every run"
            )
        if not shutil.which("nextflow") or not shutil.which("Rscript"):
            raise ValueError(
                "activate the isolated SingleCell environment containing Nextflow and Rscript"
            )
        # Check R packages before creating run state. No package installs during analysis.
        subprocess.run(["Rscript", "--vanilla", str(ROOT / "bin/check_dependencies.R")], check=True)
        run_dir = args.run_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=False)
        inputs = run_dir / "input_manifest"
        inputs.mkdir()
        hashes = {
            str(ROOT / name): digest(ROOT / name)
            for name in (
                "run_pipeline.py",
                "main.nf",
                "nextflow.config",
                "conf/resources.config",
                "bin/singlecell_analysis.R",
                "bin/import_qc.R",
                "bin/check_dependencies.R",
            )
        }
        for sample in manifest["samples"]:
            for name in FILES:
                source = Path(sample["matrix_dir"]) / name
                hashes[str(source)] = digest(source)
        manifest["provenance"] = {"sha256": hashes, "cpus": args.cpus, "memory_gb": args.memory_gb}
        prepared = inputs / "prepared_manifest.json"
        prepared.write_text(json.dumps(manifest, indent=2) + "\n")
        command = [
            "nextflow",
            "-log",
            str(run_dir / "nextflow.log"),
            "run",
            str(ROOT / "main.nf"),
            "-offline",
            "-profile",
            "local",
            "-w",
            str(run_dir / "work"),
            "--prepared_manifest",
            str(prepared),
            "--outdir",
            str(run_dir / "results"),
            "--reports_dir",
            str(run_dir / "reports"),
            "--max_cpus",
            str(args.cpus),
            "--max_memory_gb",
            str(args.memory_gb),
        ]
        subprocess.run(command, cwd=run_dir, check=True, env={**os.environ, "NXF_OFFLINE": "true"})
        verify_outputs(run_dir, markers=manifest["analysis"]["cluster_markers"])
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"SingleCell: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
