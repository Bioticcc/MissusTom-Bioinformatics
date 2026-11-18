#!/usr/bin/env python3
"""Validate a standalone SingleCell manifest and launch its local Nextflow graph.

This development runner is deliberately separate from the desktop project model.
Check-only inspects the manifest and the .rds file signature and never runs R.
The R import opens the Seurat object and performs the full count validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
METADATA_ROLES = {"sample_id", "donor_id", "condition", "batch"}
# gzip, bzip2, xz, and uncompressed XDR/ASCII serializations written by saveRDS().
RDS_SIGNATURES = (b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00", b"X\n", b"A\n")


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


def inspect_rds(path: Path) -> None:
    if path.suffix.casefold() != ".rds":
        raise ValueError(f"seurat_rds must be a .rds file: {path}")
    if not path.is_file():
        raise ValueError(f"missing Seurat object: {path}")
    with path.open("rb") as handle:
        signature = handle.read(6)
    if not signature.startswith(RDS_SIGNATURES):
        raise ValueError(f"seurat_rds is not a file written by saveRDS(): {path}")


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
    exact_keys(data, {"schema_version", "input", "reference", "qc", "analysis"}, "manifest")
    if data["schema_version"] != "singlecell-seurat-v1":
        raise ValueError("unsupported schema_version; expected singlecell-seurat-v1")
    source = data["input"]
    exact_keys(source, {"seurat_rds", "assay", "metadata_columns"}, "input")
    text(source["assay"], "assay")
    columns = source["metadata_columns"]
    exact_keys(columns, METADATA_ROLES, "metadata_columns")
    for role, column in columns.items():
        text(column, f"metadata_columns.{role}")
    reference = data["reference"]
    exact_keys(reference, {"species", "genome_build", "mitochondrial_gene_ids"}, "reference")
    text(reference["species"], "species")
    text(reference["genome_build"], "genome_build")
    mito = reference["mitochondrial_gene_ids"]
    if (
        not isinstance(mito, list)
        or not mito
        or any(not isinstance(gene, str) or not gene.strip() for gene in mito)
    ):
        raise ValueError("mitochondrial_gene_ids requires an explicit nonempty gene-ID list")
    if len(set(mito)) != len(mito):
        raise ValueError("mitochondrial_gene_ids must be unique")
    validate_qc(data["qc"])
    validate_analysis(data["analysis"])
    rds = (path.parent / text(source["seurat_rds"], "seurat_rds")).resolve()
    inspect_rds(rds)
    source["seurat_rds"] = str(rds)
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
            print("Manifest and .rds signature valid. Object contents and R not checked.")
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
        source = Path(manifest["input"]["seurat_rds"])
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
