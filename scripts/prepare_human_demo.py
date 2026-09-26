#!/usr/bin/env python3
"""Create a restricted, pseudonymized FASTQ subset for the human demo.

The source tree is opened read-only. Derived files are written below the
requested output root with restrictive permissions and pseudonymous headers.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, TextIO
from uuid import NAMESPACE_URL, uuid5

FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz")
READ_PATTERN = re.compile(r"^(?P<sample>.+?)[_-]R(?P<read>[12])(?:[_-].*)?$", re.IGNORECASE)
NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
CONDITIONS = ("H", "OD1")
SAMPLES_PER_CONDITION = 4


@dataclass(frozen=True)
class FastqPair:
    metadata_sample_id: str
    condition: str
    r1: Path
    r2: Path

    @property
    def total_bytes(self) -> int:
        return self.r1.stat().st_size + self.r2.stat().st_size


def _normalize_sample_id(value: str) -> str:
    return NON_ALNUM.sub("", value).upper()


def _strip_fastq_suffix(filename: str) -> str | None:
    lower = filename.lower()
    for suffix in FASTQ_SUFFIXES:
        if lower.endswith(suffix):
            return filename[: -len(suffix)]
    return None


def _metadata_rows(metadata_path: Path) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    with metadata_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"SampleID", "Condition"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("metadata must contain SampleID and Condition columns")
        for row in reader:
            sample_id = (row.get("SampleID") or "").strip()
            condition = (row.get("Condition") or "").strip()
            if not sample_id or condition not in CONDITIONS:
                continue
            normalized = _normalize_sample_id(sample_id)
            if normalized in rows and rows[normalized] != (sample_id, condition):
                raise ValueError(f"ambiguous normalized metadata identifier: {sample_id}")
            rows[normalized] = (sample_id, condition)
    return rows


def _discover_pairs(fastq_root: Path, metadata_path: Path) -> list[FastqPair]:
    metadata = _metadata_rows(metadata_path)
    discovered: dict[str, tuple[str, dict[int, Path]]] = {}

    for path in sorted(fastq_root.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        stem = _strip_fastq_suffix(path.name)
        if stem is None:
            continue
        match = READ_PATTERN.match(stem)
        if not match:
            continue
        discovery_key = match.group("sample")
        sample_stem = re.sub(r"^P50Large[_-]", "", discovery_key, flags=re.IGNORECASE)
        normalized = _normalize_sample_id(sample_stem)
        if normalized not in metadata:
            continue
        read = int(match.group("read"))
        metadata_key, slot = discovered.setdefault(discovery_key, (normalized, {}))
        if metadata_key != normalized:
            raise ValueError(f"inconsistent sample normalization for {sample_stem}")
        if read in slot:
            raise ValueError(
                "multiple FASTQ files have the same sample/read assignment; resolve the "
                f"duplicate before preparing the demo ({path.name})"
            )
        slot[read] = path

    pairs: list[FastqPair] = []
    for normalized, reads in (entry for entry in discovered.values()):
        if set(reads) != {1, 2}:
            continue
        sample_id, condition = metadata[normalized]
        pairs.append(FastqPair(sample_id, condition, reads[1], reads[2]))
    return pairs


def _select_pairs(pairs: list[FastqPair]) -> list[tuple[str, int, FastqPair]]:
    selected: list[tuple[str, int, FastqPair]] = []
    for condition in CONDITIONS:
        candidates = sorted(
            (pair for pair in pairs if pair.condition == condition),
            key=lambda pair: (pair.total_bytes, pair.metadata_sample_id),
        )
        unique_candidates: list[FastqPair] = []
        used_sample_ids: set[str] = set()
        for candidate in candidates:
            if candidate.metadata_sample_id in used_sample_ids:
                continue
            unique_candidates.append(candidate)
            used_sample_ids.add(candidate.metadata_sample_id)
        if len(unique_candidates) < SAMPLES_PER_CONDITION:
            raise ValueError(
                f"fewer than {SAMPLES_PER_CONDITION} complete metadata-matched "
                f"{condition} FASTQ pairs"
            )
        for replicate, pair in enumerate(unique_candidates[:SAMPLES_PER_CONDITION], start=1):
            alias = f"DEMO_{condition}_{replicate:02d}"
            selected.append((alias, replicate, pair))
    return selected


def _read_record(handle: TextIO) -> tuple[str, str, str, str] | None:
    lines = tuple(handle.readline() for _ in range(4))
    if lines[0] == "":
        if any(lines[1:]):
            raise ValueError("truncated FASTQ record")
        return None
    if any(line == "" for line in lines[1:]):
        raise ValueError("truncated FASTQ record")
    header, sequence, separator, quality = lines
    if not header.startswith("@") or not separator.startswith("+"):
        raise ValueError("invalid FASTQ record structure")
    if len(sequence.rstrip("\r\n")) != len(quality.rstrip("\r\n")):
        raise ValueError("FASTQ sequence and quality lengths differ")
    return header, sequence, separator, quality


def _read_name(header: str) -> str:
    name = header[1:].split()[0]
    return re.sub(r"/[12]$", "", name)


def _deterministic_gzip_writer(raw: BinaryIO) -> TextIO:
    compressed = gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=1, mtime=0)
    return io.TextIOWrapper(compressed, encoding="ascii", newline="\n")


def _subset_pair(
    source_r1: Path,
    source_r2: Path,
    destination_r1: Path,
    destination_r2: Path,
    alias: str,
    pair_limit: int,
) -> tuple[int, str, str]:
    destination_r1.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary_paths: list[Path] = []
    try:
        descriptors: list[tuple[int, str]] = []
        for destination in (destination_r1, destination_r2):
            descriptor, name = tempfile.mkstemp(
                prefix=f".{destination.name}.", dir=destination.parent
            )
            os.fchmod(descriptor, 0o600)
            descriptors.append((descriptor, name))
            temporary_paths.append(Path(name))

        count = 0
        with (
            gzip.open(source_r1, "rt", encoding="ascii", newline="") as input_r1,
            gzip.open(source_r2, "rt", encoding="ascii", newline="") as input_r2,
            os.fdopen(descriptors[0][0], "wb") as raw_r1,
            os.fdopen(descriptors[1][0], "wb") as raw_r2,
            _deterministic_gzip_writer(raw_r1) as output_r1,
            _deterministic_gzip_writer(raw_r2) as output_r2,
        ):
            while count < pair_limit:
                record_r1 = _read_record(input_r1)
                record_r2 = _read_record(input_r2)
                if record_r1 is None or record_r2 is None:
                    if record_r1 is not record_r2:
                        raise ValueError("mate FASTQ files contain different record counts")
                    raise ValueError(f"source contains fewer than {pair_limit:,} read pairs")
                if _read_name(record_r1[0]) != _read_name(record_r2[0]):
                    raise ValueError(f"mate headers differ at pair {count + 1:,}")
                count += 1
                output_r1.write(f"@{alias}:{count:09d}/1\n")
                output_r1.write(record_r1[1].rstrip("\r\n") + "\n+\n")
                output_r1.write(record_r1[3].rstrip("\r\n") + "\n")
                output_r2.write(f"@{alias}:{count:09d}/2\n")
                output_r2.write(record_r2[1].rstrip("\r\n") + "\n+\n")
                output_r2.write(record_r2[3].rstrip("\r\n") + "\n")

        os.replace(temporary_paths[0], destination_r1)
        os.replace(temporary_paths[1], destination_r2)
        os.chmod(destination_r1, 0o600)
        os.chmod(destination_r2, 0o600)
        temporary_paths.clear()
        return count, _sha256(destination_r1), _sha256(destination_r2)
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest(
    output_root: Path,
    transcriptome: Path,
    kallisto_index: Path,
    annotation_gtf: Path,
    selected: list[tuple[str, int, FastqPair]],
    created_at: datetime,
    pair_limit: int,
) -> dict[str, object]:
    input_directory = output_root / "inputs"
    project_directory = output_root / "project"
    samples = []
    for alias, replicate, pair in selected:
        samples.append(
            {
                "sample_id": alias,
                "r1_files": [str(input_directory / f"{alias}_R1.fastq.gz")],
                "r2_files": [str(input_directory / f"{alias}_R2.fastq.gz")],
                "condition": pair.condition,
                "biological_replicate": str(replicate),
                "batch": "demo",
                "covariates": {},
                "included": True,
            }
        )
    return {
        "schema_version": "1.1.0",
        "reference_mode": "existing-index",
        "project_name": "Human bulk RNA-seq demo",
        "project_identifier": str(uuid5(NAMESPACE_URL, str(output_root.resolve()))),
        "created_at": created_at.isoformat(),
        "input_directory": str(input_directory),
        "output_directory": str(project_directory),
        "pipeline_identifier": "bulk-rnaseq",
        "pipeline_version": "0.5.0",
        "organism": "Homo sapiens",
        "reference_genome": "GRCh38",
        "annotation_source": "GENCODE v49",
        "reference_resources": {
            "transcriptome_fasta": str(transcriptome),
            "kallisto_index": str(kallisto_index),
            "annotation_gtf": str(annotation_gtf),
        },
        "library_type": "large RNA",
        "read_layout": "paired-end",
        "strandedness": "reverse",
        "samples": samples,
        "comparisons": [
            {
                "comparison_id": "OD1_vs_H",
                "numerator": "OD1",
                "denominator": "H",
                "label": "OD1 (test) vs H (reference)",
            }
        ],
        "parameters": {
            "read_pairs_per_sample": pair_limit,
            "adapter_r1": "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA",
            "adapter_r2": "AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT",
            "trim_quality": 20,
            "trim_minimum_length": 20,
            "kallisto_strandedness": "rf-stranded",
            "differential_expression": True,
            "analysis_gene_classes": "mRNA,lncRNA",
            "minimum_group_size": 4,
            "adjusted_p_value": 0.05,
            "absolute_log2_fold_change": 0.30,
        },
        "resource_profile": {"cpus": 8, "memory_gb": 16, "max_parallel_tasks": 2},
        "execution_profile": "local",
        "application_version": "0.3.0",
        "pipeline_status": "validated",
    }


def prepare(args: argparse.Namespace) -> None:
    fastq_root = args.fastq_root.resolve(strict=True)
    metadata = args.metadata.resolve(strict=True)
    transcriptome = args.transcriptome.resolve(strict=True)
    kallisto_index = args.kallisto_index.resolve(strict=True)
    annotation_gtf = args.annotation_gtf.resolve(strict=True)
    biomart = args.biomart.resolve(strict=True) if args.biomart is not None else None
    output_root = args.output_root.resolve(strict=False)

    if output_root == fastq_root or fastq_root in output_root.parents:
        raise ValueError("the demo output root must be separate from the source FASTQ tree")
    if args.pairs_per_sample < 1:
        raise ValueError("pairs-per-sample must be positive")
    if output_root.exists() and any(output_root.iterdir()) and not args.force:
        raise FileExistsError(f"output root is not empty: {output_root}; use --force to rebuild")

    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_root, 0o700)
    for relative in (
        "inputs",
        "project/input_manifest",
        "project/configuration",
        "project/work",
        "project/results/qc",
        "project/results/trimmed",
        "project/results/counts",
        "project/results/differential_expression",
        "project/results/figures",
        "project/results/tables",
        "project/reports",
        "project/logs",
        "provenance",
    ):
        directory = output_root / relative
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)

    selected = _select_pairs(_discover_pairs(fastq_root, metadata))
    created_at = datetime.now(UTC)
    previous_by_alias: dict[str, dict[str, object]] = {}
    previous_map = output_root / "provenance" / "source_map.json"
    if args.force and previous_map.is_file():
        try:
            previous_payload = json.loads(previous_map.read_text(encoding="utf-8"))
            previous_by_alias = {
                str(sample["alias"]): sample
                for sample in previous_payload.get("samples", [])
                if isinstance(sample, dict) and sample.get("alias")
            }
        except (OSError, ValueError, TypeError):
            previous_by_alias = {}
    provenance_samples = []
    for alias, replicate, pair in selected:
        destination_r1 = output_root / "inputs" / f"{alias}_R1.fastq.gz"
        destination_r2 = output_root / "inputs" / f"{alias}_R2.fastq.gz"
        previous = previous_by_alias.get(alias)
        can_reuse = (
            args.force
            and previous is not None
            and destination_r1.is_file()
            and destination_r2.is_file()
            and previous.get("source_r1") == str(pair.r1)
            and previous.get("source_r2") == str(pair.r2)
            and previous.get("read_pairs") == args.pairs_per_sample
            and previous.get("derived_r1_sha256") == _sha256(destination_r1)
            and previous.get("derived_r2_sha256") == _sha256(destination_r2)
        )
        if can_reuse:
            print(f"Reusing {alias}: verified existing subset", flush=True)
            provenance_samples.append(previous)
            continue
        if destination_r1.exists() or destination_r2.exists():
            if not args.force:
                raise FileExistsError(f"derived FASTQ already exists for {alias}")
            destination_r1.unlink(missing_ok=True)
            destination_r2.unlink(missing_ok=True)
        print(f"Preparing {alias}: {args.pairs_per_sample:,} read pairs", flush=True)
        count, sha_r1, sha_r2 = _subset_pair(
            pair.r1,
            pair.r2,
            destination_r1,
            destination_r2,
            alias,
            args.pairs_per_sample,
        )
        provenance_samples.append(
            {
                "alias": alias,
                "condition": pair.condition,
                "biological_replicate": replicate,
                "source_sample_id": pair.metadata_sample_id,
                "source_r1": str(pair.r1),
                "source_r2": str(pair.r2),
                "source_r1_bytes": pair.r1.stat().st_size,
                "source_r2_bytes": pair.r2.stat().st_size,
                "derived_r1": str(destination_r1),
                "derived_r2": str(destination_r2),
                "derived_r1_sha256": sha_r1,
                "derived_r2_sha256": sha_r2,
                "read_pairs": count,
            }
        )

    provenance = {
        "created_at": created_at.isoformat(),
        "classification": "restricted human sequence data; pseudonymized, not anonymized",
        "selection": (
            f"{SAMPLES_PER_CONDITION} smallest complete metadata-matched FASTQ pairs per condition"
        ),
        "source_tree_modified": False,
        "metadata_path": str(metadata),
        "transcriptome_fasta": str(transcriptome),
        "kallisto_index": str(kallisto_index),
        "kallisto_index_sha256": _sha256(kallisto_index),
        "annotation_gtf": str(annotation_gtf),
        "samples": provenance_samples,
    }
    if biomart is not None:
        provenance["biomart"] = str(biomart)
    _write_json(output_root / "provenance" / "source_map.json", provenance)
    manifest = _manifest(
        output_root,
        transcriptome,
        kallisto_index,
        annotation_gtf,
        selected,
        created_at,
        args.pairs_per_sample,
    )
    _write_json(output_root / "project" / "input_manifest" / "project_manifest.json", manifest)
    print(
        "Demo manifest: "
        + str(output_root / "project" / "input_manifest" / "project_manifest.json"),
        flush=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fastq-root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--transcriptome", type=Path, required=True)
    parser.add_argument("--kallisto-index", type=Path, required=True)
    parser.add_argument("--annotation-gtf", type=Path, required=True)
    parser.add_argument(
        "--biomart",
        type=Path,
        default=None,
        help="Optional legacy BioMart table path recorded in provenance only",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--pairs-per-sample", type=int, default=1_000_000)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    prepare(parse_args())
