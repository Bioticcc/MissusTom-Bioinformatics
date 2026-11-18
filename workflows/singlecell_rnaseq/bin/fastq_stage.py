#!/usr/bin/env python3
"""Nextflow task helper: fixed STAR argument arrays and lossless matrix packaging."""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import shutil
import subprocess
from pathlib import Path


def star(command: list[str], provenance: str) -> None:
    version = subprocess.run(["STAR", "--version"], check=True, capture_output=True, text=True)
    if version.stdout.strip() != "2.7.11b":
        raise ValueError("STAR 2.7.11b is required for this quantification implementation")
    Path(provenance).write_text(
        json.dumps({"command": command, "star_version": version.stdout.strip()}, indent=2) + "\n"
    )
    subprocess.run(command, check=True)


def index(manifest: dict, cpus: int, memory_gb: int) -> None:
    reference = manifest["reference"]
    Path("star_index").mkdir()
    command = [
        "STAR",
        "--runMode",
        "genomeGenerate",
        "--runThreadN",
        str(cpus),
        "--genomeDir",
        "star_index",
        "--genomeFastaFiles",
        "reference.fa",
        "--sjdbGTFfile",
        "genes.gtf",
        "--sjdbOverhang",
        str(reference["sjdb_overhang"]),
        "--genomeSAindexNbases",
        str(reference["sa_index_n_bases"]),
        "--genomeSAsparseD",
        "3",
        "--limitGenomeGenerateRAM",
        str(memory_gb * 1024**3),
    ]
    star(command, "index_provenance.json")
    for name in ("Genome", "SA", "SAindex", "genomeParameters.txt", "geneInfo.tab"):
        if not (Path("star_index") / name).is_file():
            raise ValueError(f"incomplete STAR index: missing {name}")


def package_matrix(source: Path, destination: Path) -> None:
    destination.mkdir()
    for name in ("features.tsv", "barcodes.tsv", "matrix.mtx"):
        original = source / name
        if not original.is_file() or original.stat().st_size == 0:
            raise ValueError(f"missing/empty called-cell output: {original}")
        # Fixed gzip timestamp prevents packaging time from changing scientific input hashes.
        with (
            (destination / f"{name}.gz").open("wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped,
        ):
            if name == "features.tsv":
                with original.open() as handle, io.TextIOWrapper(zipped) as output:
                    for line in handle:
                        row = line.rstrip("\r\n").split("\t")
                        if len(row) == 2:
                            row.append("Gene Expression")
                        if len(row) != 3 or row[2] != "Gene Expression":
                            raise ValueError("STARsolo features must be gene-expression rows")
                        output.write("\t".join(row) + "\n")
            else:
                with original.open("rb") as handle:
                    shutil.copyfileobj(handle, zipped)


def validate_pairs(sample: dict) -> None:
    records = []
    for lane in sample["lanes"]:
        count = 0
        with gzip.open(lane["staged_r1"], "rt") as r1, gzip.open(lane["staged_r2"], "rt") as r2:
            while True:
                left, right = r1.readline(), r2.readline()
                if not left and not right:
                    break
                if not left or not right:
                    raise ValueError("R1/R2 have different record counts")
                pair = []
                for header, handle in ((left, r1), (right, r2)):
                    sequence, plus, quality = [handle.readline().rstrip("\r\n") for _ in range(3)]
                    if (
                        not header.startswith("@")
                        or not plus.startswith("+")
                        or not sequence
                        or len(sequence) != len(quality)
                        or not re.fullmatch("[ACGTNacgtn]+", sequence)
                        or any(not 33 <= ord(character) <= 126 for character in quality)
                    ):
                        raise ValueError(f"invalid FASTQ record after {count} paired records")
                    pair.append((re.sub(r"/[12]$", "", header.split()[0]), sequence))
                if pair[0][0] != pair[1][0]:
                    raise ValueError(f"R1/R2 read IDs differ at record {count + 1}")
                if len(pair[0][1]) < 16 + sample["umi_length"]:
                    raise ValueError("R1 is shorter than the selected barcode/UMI layout")
                count += 1
        if count == 0:
            raise ValueError("FASTQ lane contains no records")
        records.append({"r1": lane["staged_r1"], "r2": lane["staged_r2"], "paired_records": count})
    Path("fastq_validation.json").write_text(json.dumps(records, indent=2) + "\n")


def quantify(sample: dict, cpus: int) -> None:
    validate_pairs(sample)
    # STAR requires cDNA R2 FIRST, barcode/UMI R1 SECOND for these 3-prime chemistries.
    # Commas join explicitly paired lanes after staging; no user filename enters a shell.
    r2 = ",".join(lane["staged_r2"] for lane in sample["lanes"])
    r1 = ",".join(lane["staged_r1"] for lane in sample["lanes"])
    command = [
        "STAR",
        "--runThreadN",
        str(cpus),
        "--genomeDir",
        "star_index",
        "--genomeLoad",
        "NoSharedMemory",
        "--readFilesIn",
        r2,
        r1,
        "--readFilesCommand",
        "gzip",
        "-cd",
        "--soloType",
        "CB_UMI_Simple",
        "--soloCBstart",
        "1",
        "--soloCBlen",
        "16",
        "--soloUMIstart",
        "17",
        "--soloUMIlen",
        str(sample["umi_length"]),
        "--soloBarcodeReadLength",
        "0",
        "--soloCBwhitelist",
        "whitelist.txt",
        "--soloStrand",
        "Forward",
        "--soloFeatures",
        sample["counting_mode"],
        "--soloCBmatchWLtype",
        "1MM_multi_Nbase_pseudocounts",
        "--soloUMIfiltering",
        "MultiGeneUMI_CR",
        "--soloUMIdedup",
        "1MM_CR",
        "--clipAdapterType",
        "CellRanger4",
        "--outFilterScoreMin",
        "30",
        "--soloCellFilter",
        "EmptyDrops_CR",
        str(sample["expected_cells"]),
        "0.99",
        "10",
        "45000",
        "90000",
        "500",
        "0.01",
        "20000",
        "0.01",
        "10000",
        "--runRNGseed",
        "777",
        "--outSAMtype",
        "None",
    ]
    star(command, "quantification_provenance.json")
    feature_root = Path("Solo.out") / sample["counting_mode"]
    for name in ("raw/matrix.mtx", "Summary.csv"):
        if not (feature_root / name).is_file():
            raise ValueError(f"incomplete STARsolo outputs: missing {name}")
    package_matrix(feature_root / "filtered", Path("matrix"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("index", "quant"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("cpus", type=int)
    parser.add_argument("memory_gb", type=int)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if args.stage == "index":
        index(manifest, args.cpus, args.memory_gb)
    else:
        quantify(manifest, args.cpus)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
