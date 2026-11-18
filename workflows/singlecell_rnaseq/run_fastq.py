#!/usr/bin/env python3
"""Run explicit droplet FASTQs through STARsolo, then the count-matrix pipeline.

This development entry point owns no desktop state and never installs tools.
Chemistry, paired lanes, reference, whitelist and cell calling are user declarations.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from run_pipeline import ROOT, digest, exact_keys, number, text, validate_analysis, validate_qc

CHEMISTRIES = {"10x_3prime_v2": 10, "10x_3prime_v3": 12}
STAR_VERSION = "2.7.11b"


def local_file(value: object, base: Path, label: str) -> Path:
    path = (base / text(value, label)).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"{label} must name a nonempty local file: {path}")
    return path


def first_read(path: Path) -> tuple[str, str]:
    if not path.name.endswith((".fastq.gz", ".fq.gz")):
        raise ValueError("FASTQs must be gzip-compressed .fastq.gz or .fq.gz")
    with gzip.open(path, "rt") as handle:
        header, sequence, plus, quality = [handle.readline().rstrip("\r\n") for _ in range(4)]
    if (
        not header.startswith("@")
        or not plus.startswith("+")
        or not sequence
        or len(sequence) != len(quality)
        or not re.fullmatch("[ACGTNacgtn]+", sequence)
    ):
        raise ValueError(f"invalid first FASTQ record: {path}")
    identifier = re.sub(r"/[12]$", "", header.split()[0])
    return identifier, sequence


def validate_reference(reference: dict) -> dict:
    """Stream FASTA/GTF to check annotation compatibility without building an index."""
    lengths = {}
    current = None
    with Path(reference["fasta"]).open() as handle:
        for line in handle:
            if line.startswith(">"):
                names = line[1:].split()
                if not names or names[0] in lengths:
                    raise ValueError("FASTA requires unique nonempty contig names")
                current = names[0]
                lengths[current] = 0
            elif line.strip():
                if current is None or not re.fullmatch("[A-Za-z]+", line.strip()):
                    raise ValueError("invalid FASTA sequence/header structure")
                lengths[current] += len(line.strip())
    if not lengths or any(length < 1 for length in lengths.values()):
        raise ValueError("FASTA contains missing/empty sequences")
    maximum_sa = max(1, min(14, int(math.log2(sum(lengths.values())) / 2 - 1)))
    if reference["sa_index_n_bases"] > maximum_sa:
        raise ValueError(f"sa_index_n_bases is too large for this genome; choose <= {maximum_sa}")
    genes, transcripts, exons = set(), {}, 0
    with Path(reference["gtf"]).open() as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 9:
                raise ValueError("GTF requires nine tab-delimited columns")
            if fields[2] != "exon":
                continue
            if fields[0] not in lengths:
                raise ValueError(f"GTF exon contig absent from FASTA: {fields[0]}")
            start, end = int(fields[3]), int(fields[4])
            if not 1 <= start <= end <= lengths[fields[0]] or fields[6] not in ("+", "-"):
                raise ValueError("GTF exon coordinates/strand are incompatible with FASTA")
            gene = re.search(r'(?:^|;)\s*gene_id\s+"([^\"]+)"', fields[8])
            transcript = re.search(r'(?:^|;)\s*transcript_id\s+"([^\"]+)"', fields[8])
            if gene is None or transcript is None:
                raise ValueError("GTF exons require quoted gene_id and transcript_id attributes")
            gene, transcript = gene.group(1), transcript.group(1)
            if re.search(r"[_|\s]", gene):
                raise ValueError(
                    "gene IDs containing whitespace, '_' or '|' need a reversible Seurat mapping"
                )
            if transcript in transcripts and transcripts[transcript] != gene:
                raise ValueError("one GTF transcript_id cannot belong to multiple gene IDs")
            transcripts[transcript] = gene
            genes.add(gene)
            exons += 1
    if not exons or not set(reference["mitochondrial_gene_ids"]).issubset(genes):
        raise ValueError("GTF needs exon annotations for every declared mitochondrial gene ID")
    return {
        "contigs": len(lengths),
        "genome_bases": sum(lengths.values()),
        "genes": len(genes),
        "exons": exons,
        "scope": "contig/coordinate/ID consistency; assembly identity is user-declared",
    }


def load_fastq_manifest(
    path: Path, *, chemistry: str | None = None, material: str | None = None
) -> dict:
    data = json.loads(path.read_text())
    exact_keys(data, {"schema_version", "reference", "samples", "analysis"}, "FASTQ manifest")
    if data["schema_version"] != "singlecell-fastq-v1":
        raise ValueError("expected schema_version=singlecell-fastq-v1")
    reference = data["reference"]
    exact_keys(
        reference,
        {
            "species",
            "genome_build",
            "mitochondrial_gene_ids",
            "fasta",
            "gtf",
            "sjdb_overhang",
            "sa_index_n_bases",
        },
        "FASTQ reference",
    )
    for key in ("species", "genome_build"):
        text(reference[key], key)
    mito = reference["mitochondrial_gene_ids"]
    if not isinstance(mito, list) or not mito or any(not isinstance(g, str) or not g for g in mito):
        raise ValueError("mitochondrial_gene_ids requires explicit reference IDs")
    if len(set(mito)) != len(mito):
        raise ValueError("mitochondrial_gene_ids must be unique")
    for key in ("fasta", "gtf"):
        source = local_file(reference[key], path.parent, key)
        if source.suffix == ".gz":
            raise ValueError("STAR reference FASTA/GTF must be uncompressed local files")
        reference[key] = str(source)
    number(reference["sjdb_overhang"], "sjdb_overhang", 1, 1000, integer=True)
    number(reference["sa_index_n_bases"], "sa_index_n_bases", 1, 14, integer=True)
    samples = data["samples"]
    if not isinstance(samples, list) or not 1 <= len(samples) <= 9999:
        raise ValueError("samples must contain 1..9999 libraries")
    seen_ids, seen_reads, modes, checked_whitelists = set(), set(), set(), set()
    # Share analysis/QC rules with the matrix entry point; validate output matrices later.
    validate_analysis(data["analysis"])
    for index, sample in enumerate(samples, 1):
        exact_keys(
            sample,
            {
                "sample_id",
                "donor_id",
                "condition",
                "batch",
                "qc",
                "chemistry",
                "material",
                "counting_mode",
                "barcode_whitelist",
                "expected_cells",
                "lanes",
            },
            "FASTQ sample",
        )
        if chemistry is not None:
            sample["chemistry"] = chemistry
        if material is not None:
            sample["material"] = material
        identifier = text(sample["sample_id"], "sample_id")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", identifier) or identifier in seen_ids:
            raise ValueError(
                "sample_id must be unique: letter followed by <=63 letters/digits/hyphens"
            )
        seen_ids.add(identifier)
        for key in ("donor_id", "condition", "batch"):
            text(sample[key], key)
        validate_qc(sample["qc"])
        if not isinstance(sample["chemistry"], str) or sample["chemistry"] not in CHEMISTRIES:
            raise ValueError(
                "choose a confirmed chemistry: 10x_3prime_v2 or 10x_3prime_v3; "
                "unknown and other chemistries cannot execute; see --list-chemistries"
            )
        sample["umi_length"] = CHEMISTRIES[sample["chemistry"]]
        if sample["material"] not in ("cells", "nuclei"):
            raise ValueError("material must be cells or nuclei")
        if sample["counting_mode"] not in ("Gene", "GeneFull"):
            raise ValueError("counting_mode must explicitly select Gene or GeneFull")
        modes.add(sample["counting_mode"])
        if len(modes) > 1:
            raise ValueError("samples in one analysis must share the same counting_mode")
        number(sample["expected_cells"], "expected_cells", 1, 1000000, integer=True)
        whitelist = local_file(sample["barcode_whitelist"], path.parent, "barcode_whitelist")
        if whitelist not in checked_whitelists:
            with whitelist.open() as handle:
                barcodes = [line.rstrip("\r\n") for line in handle]
            if not barcodes or any(not re.fullmatch("[ACGT]{16}", barcode) for barcode in barcodes):
                raise ValueError(
                    "barcode whitelist must be uncompressed, one 16-base ACGT barcode per line"
                )
            if len(set(barcodes)) != len(barcodes):
                raise ValueError("duplicate whitelist barcodes")
            checked_whitelists.add(whitelist)
        sample["barcode_whitelist"] = str(whitelist)
        lanes = sample["lanes"]
        if not isinstance(lanes, list) or not 1 <= len(lanes) <= 9999:
            raise ValueError("lanes must contain explicit paired R1/R2 files")
        for lane_index, lane in enumerate(lanes):
            exact_keys(lane, {"r1", "r2"}, "lane")
            reads = []
            for mate in ("r1", "r2"):
                source = local_file(lane[mate], path.parent, mate)
                if source in seen_reads:
                    raise ValueError(
                        "a FASTQ file cannot be reused across lanes, mates or libraries"
                    )
                seen_reads.add(source)
                reads.append(first_read(source))
                lane[mate] = str(source)
            if reads[0][0] != reads[1][0]:
                raise ValueError("first R1/R2 read IDs differ; review paired lane assignments")
            if len(reads[0][1]) < 16 + CHEMISTRIES[sample["chemistry"]]:
                raise ValueError("R1 is shorter than the declared cell-barcode + UMI geometry")
            lane["staged_r1"] = f"read{lane_index * 2 + 1:04d}.fastq.gz"
            lane["staged_r2"] = f"read{lane_index * 2 + 2:04d}.fastq.gz"
        sample["ordinal"] = index
    data["reference_validation"] = validate_reference(reference)
    return data


def source_hashes(manifest: dict) -> dict:
    hashes = {}
    for name in (
        "run_pipeline.py",
        "run_fastq.py",
        "main.nf",
        "fastq.nf",
        "nextflow.config",
        "conf/resources.config",
        "environment.yaml",
        "chemistries.json",
        "bin/fastq_stage.py",
        "bin/check_dependencies.R",
        "bin/import_qc.R",
        "bin/singlecell_analysis.R",
    ):
        source = ROOT / name
        hashes[str(source)] = digest(source)
    for key in ("fasta", "gtf"):
        source = Path(manifest["reference"][key])
        hashes[str(source)] = digest(source)
    for sample in manifest["samples"]:
        sources = [sample["barcode_whitelist"]] + [
            lane[mate] for lane in sample["lanes"] for mate in ("r1", "r2")
        ]
        for name in sources:
            if name not in hashes:
                hashes[name] = digest(Path(name))
    return hashes


def count_manifest(manifest: dict, run_dir: Path) -> dict:
    reference = {
        key: manifest["reference"][key]
        for key in ("species", "genome_build", "mitochondrial_gene_ids")
    }
    samples = []
    for sample in manifest["samples"]:
        converted = {
            key: sample[key] for key in ("sample_id", "donor_id", "condition", "batch", "qc")
        }
        converted.update(
            matrix_kind="filtered",
            matrix_dir=str(run_dir / "quantification" / sample["sample_id"] / "matrix"),
        )
        samples.append(converted)
    return {
        "schema_version": "singlecell-counts-v1",
        "reference": reference,
        "samples": samples,
        "analysis": manifest["analysis"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--list-chemistries", action="store_true")
    parser.add_argument(
        "--chemistry",
        choices=tuple(CHEMISTRIES),
        help="Select chemistry for ALL libraries, overriding manifest choices",
    )
    parser.add_argument(
        "--material",
        choices=("cells", "nuclei"),
        help="Select material for ALL libraries, overriding manifest choices",
    )
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--cpus", type=int, choices=range(1, 65), default=4)
    parser.add_argument("--memory-gb", type=int, choices=range(1, 513), default=32)
    args = parser.parse_args()
    try:
        if args.list_chemistries:
            for entry in json.loads((ROOT / "chemistries.json").read_text()):
                status = (
                    "implemented; validation pending"
                    if entry["execution_supported"]
                    else "unavailable"
                )
                print(f"{entry['id']}: {entry['label']} [{status}]\n  {entry['description']}")
            return 0
        if args.manifest is None:
            raise ValueError("--manifest is required unless listing chemistry choices")
        manifest = load_fastq_manifest(
            args.manifest.resolve(), chemistry=args.chemistry, material=args.material
        )
        if args.check_only:
            print(
                "FASTQ declarations/first records and reference structure valid. "
                "Full pairing, tools and assembly identity not checked."
            )
            return 0
        if args.run_dir is None:
            raise ValueError("execution requires --run-dir naming a new directory")
        for tool in ("STAR", "nextflow", "Rscript", "gzip"):
            if not shutil.which(tool):
                raise ValueError(f"missing {tool}; activate the isolated SingleCell environment")
        result = subprocess.run(["STAR", "--version"], check=True, capture_output=True, text=True)
        if result.stdout.strip() != STAR_VERSION:
            raise ValueError(f"STAR {STAR_VERSION} required, found {result.stdout.strip()!r}")
        subprocess.run(["Rscript", "--vanilla", str(ROOT / "bin/check_dependencies.R")], check=True)
        run_dir = args.run_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=False)
        inputs = run_dir / "input_manifest"
        inputs.mkdir()
        manifest["provenance"] = {
            "sha256": source_hashes(manifest),
            "cpus": args.cpus,
            "memory_gb": args.memory_gb,
            "star_version": STAR_VERSION,
            "input_overrides": {"chemistry": args.chemistry, "material": args.material},
        }
        manifest["provenance"]["sha256"][str(args.manifest.resolve())] = digest(
            args.manifest.resolve()
        )
        shutil.copy2(args.manifest, inputs / "original_fastq_manifest.json")
        prepared = inputs / "prepared_fastq_manifest.json"
        prepared.write_text(json.dumps(manifest, indent=2) + "\n")
        for sample in manifest["samples"]:
            (inputs / f"{sample['sample_id']}.json").write_text(json.dumps(sample, indent=2) + "\n")
        command = [
            "nextflow",
            "-log",
            str(run_dir / "nextflow.log"),
            "run",
            str(ROOT / "fastq.nf"),
            "-offline",
            "-profile",
            "local",
            "-w",
            str(run_dir / "work"),
            "--prepared_manifest",
            str(prepared),
            "--outdir",
            str(run_dir),
            "--reports_dir",
            str(run_dir / "reports"),
            "--max_cpus",
            str(args.cpus),
            "--max_memory_gb",
            str(args.memory_gb),
        ]
        subprocess.run(command, cwd=run_dir, check=True, env={**os.environ, "NXF_OFFLINE": "true"})
        # Validate every produced matrix before starting Seurat; do not relabel raw droplets.
        from run_pipeline import load_manifest

        counts = inputs / "count_manifest.json"
        counts.write_text(json.dumps(count_manifest(manifest, run_dir), indent=2) + "\n")
        load_manifest(counts)
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "run_pipeline.py"),
                "--manifest",
                str(counts),
                "--run-dir",
                str(run_dir / "analysis"),
                "--cpus",
                str(args.cpus),
                "--memory-gb",
                str(args.memory_gb),
            ],
            check=True,
        )
        # Bundle original FASTQ settings/hashes with the final scientific provenance.
        shutil.copy2(prepared, run_dir / "analysis/results/tables/provenance/fastq_manifest.json")
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"SingleCell FASTQ: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
