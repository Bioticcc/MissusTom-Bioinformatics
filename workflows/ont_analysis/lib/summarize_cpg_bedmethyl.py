#!/usr/bin/env python3
"""Validate paired 5mC/5hmC bedMethyl and build Stage 04 summaries."""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


COUNTER_KEYS = (
    "reference_cpg_sites",
    "covered_cpg_sites",
    "valid",
    "canonical",
    "mod_m",
    "mod_h",
    "fail",
    "nocall",
    "delete",
    "diff",
)


def empty_counts() -> dict[str, int]:
    return {key: 0 for key in COUNTER_KEYS}


def fail(message: str) -> "None":
    raise ValueError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fasta", required=True, type=Path)
    parser.add_argument("--fai", required=True, type=Path)
    parser.add_argument("--bedmethyl", required=True, type=Path)
    parser.add_argument("--modkit-stats", required=True, type=Path)
    parser.add_argument("--window-size", required=True, type=int)
    parser.add_argument("--global-out", required=True, type=Path)
    parser.add_argument("--chromosome-out", required=True, type=Path)
    parser.add_argument("--window-out", required=True, type=Path)
    parser.add_argument("--call-coverage-out", required=True, type=Path)
    return parser.parse_args()


def read_fai(path: Path) -> OrderedDict[str, int]:
    contigs: OrderedDict[str, int] = OrderedDict()
    with path.open("rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 2:
                fail(f"{path}:{line_number}: malformed FAI row")
            try:
                length = int(fields[1])
            except ValueError:
                fail(f"{path}:{line_number}: invalid contig length")
            name = fields[0]
            if not name or name in contigs or length <= 0:
                fail(f"{path}:{line_number}: invalid or duplicate contig {name!r}")
            contigs[name] = length
    if not contigs:
        fail(f"{path}: no contigs")
    return contigs


def pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "NA"
    return f"{100.0 * numerator / denominator:.6f}"


def observation_total(counts: dict[str, int]) -> int:
    return counts["valid"] + counts["fail"] + counts["nocall"] + counts["delete"] + counts["diff"]


def add_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key in COUNTER_KEYS:
        target[key] += source[key]


def count_reference_cpgs(
    fasta: Path,
    contigs: OrderedDict[str, int],
    chromosome_counts: dict[str, dict[str, int]],
    window_counts: dict[str, list[dict[str, int]]],
    window_size: int,
) -> None:
    seen: set[str] = set()
    current: str | None = None
    offset = 0
    previous = ""

    def finish_contig() -> None:
        if current is not None and offset != contigs[current]:
            fail(f"FASTA length disagrees with FAI for {current}: {offset} != {contigs[current]}")

    with fasta.open("rt", encoding="ascii") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            if line.startswith(">"):
                finish_contig()
                name = line[1:].split()[0]
                if name not in contigs:
                    fail(f"{fasta}:{line_number}: contig absent from FAI: {name}")
                if name in seen:
                    fail(f"{fasta}:{line_number}: duplicate contig: {name}")
                seen.add(name)
                current = name
                offset = 0
                previous = ""
                continue
            if current is None:
                fail(f"{fasta}:{line_number}: sequence before FASTA header")
            sequence = line.upper()
            joined = previous + sequence
            joined_start = offset - (1 if previous else 0)
            search_from = 0
            while True:
                found = joined.find("CG", search_from)
                if found < 0:
                    break
                c_position = joined_start + found
                chromosome_counts[current]["reference_cpg_sites"] += 1
                window_counts[current][c_position // window_size]["reference_cpg_sites"] += 1
                search_from = found + 1
            offset += len(sequence)
            previous = sequence[-1:]
    finish_contig()
    missing = [name for name in contigs if name not in seen]
    if missing:
        fail(f"FASTA is missing FAI contig: {missing[0]}")


@dataclass(frozen=True)
class BedRow:
    chrom: str
    start: int
    end: int
    code: str
    score: int
    strand: str
    valid: int
    percent_modified: float
    modified: int
    canonical: int
    other_modified: int
    delete: int
    failed: int
    different: int
    nocall: int


def bed_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 18:
                fail(f"{path}:{line_number}: expected 18 tab-delimited bedMethyl columns")
            try:
                row = BedRow(
                    chrom=fields[0],
                    start=int(fields[1]),
                    end=int(fields[2]),
                    code=fields[3],
                    score=int(fields[4]),
                    strand=fields[5],
                    valid=int(fields[9]),
                    percent_modified=float(fields[10]),
                    modified=int(fields[11]),
                    canonical=int(fields[12]),
                    other_modified=int(fields[13]),
                    delete=int(fields[14]),
                    failed=int(fields[15]),
                    different=int(fields[16]),
                    nocall=int(fields[17]),
                )
            except ValueError:
                fail(f"{path}:{line_number}: invalid numeric value")
            yield line_number, row


def validate_single_row(path: Path, line_number: int, row: BedRow) -> None:
    integer_values = (
        row.score,
        row.valid,
        row.modified,
        row.canonical,
        row.other_modified,
        row.delete,
        row.failed,
        row.different,
        row.nocall,
    )
    if any(value < 0 for value in integer_values):
        fail(f"{path}:{line_number}: negative count")
    if row.end != row.start + 1 or row.strand != "." or row.code not in {"m", "h"}:
        fail(f"{path}:{line_number}: expected strand-combined one-base m/h CpG row")
    if row.score != row.valid:
        fail(f"{path}:{line_number}: bedMethyl score disagrees with valid coverage")
    if row.valid == 65535:
        fail(
            f"{path}:{line_number}: valid coverage reached the 65535 saturation sentinel; "
            "rerun Modkit pileup with --high-depth and --max-depth no greater than 60000"
        )
    component_valid = row.modified + row.other_modified + row.canonical
    if row.valid != component_valid:
        fail(f"{path}:{line_number}: invalid valid-coverage identity")
    expected_percent = 100.0 * row.modified / row.valid if row.valid else 0.0
    if not math.isfinite(row.percent_modified) or abs(expected_percent - row.percent_modified) > 0.011:
        fail(f"{path}:{line_number}: percent modified disagrees with counts")


def aggregate_bedmethyl(
    path: Path,
    contigs: OrderedDict[str, int],
    chromosome_counts: dict[str, dict[str, int]],
    window_counts: dict[str, list[dict[str, int]]],
    window_size: int,
) -> int:
    iterator = iter(bed_rows(path))
    contig_order = {name: index for index, name in enumerate(contigs)}
    previous_key: tuple[int, int] | None = None
    site_count = 0

    while True:
        try:
            line_a, row_a = next(iterator)
        except StopIteration:
            break
        try:
            line_b, row_b = next(iterator)
        except StopIteration:
            fail(f"{path}: final CpG position has only one modification row")

        validate_single_row(path, line_a, row_a)
        validate_single_row(path, line_b, row_b)
        if (row_a.chrom, row_a.start, row_a.end) != (row_b.chrom, row_b.start, row_b.end):
            fail(f"{path}:{line_a}: 5mC/5hmC rows are not paired by coordinate")
        rows = {row_a.code: row_a, row_b.code: row_b}
        if set(rows) != {"m", "h"}:
            fail(f"{path}:{line_a}: expected exactly one m row and one h row")
        m_row, h_row = rows["m"], rows["h"]
        if m_row.chrom not in contigs or m_row.start < 0 or m_row.end > contigs[m_row.chrom]:
            fail(f"{path}:{line_a}: coordinate absent from FAI")
        key = (contig_order[m_row.chrom], m_row.start)
        if previous_key is not None and key <= previous_key:
            fail(f"{path}:{line_a}: CpG coordinates are duplicated or unsorted")
        previous_key = key
        shared_a = (m_row.valid, m_row.canonical, m_row.delete, m_row.failed, m_row.different, m_row.nocall)
        shared_b = (h_row.valid, h_row.canonical, h_row.delete, h_row.failed, h_row.different, h_row.nocall)
        if shared_a != shared_b:
            fail(f"{path}:{line_a}: paired m/h rows disagree on shared counts")
        if m_row.other_modified != h_row.modified or h_row.other_modified != m_row.modified:
            fail(f"{path}:{line_a}: paired other-modified counts do not cross-match")

        site = empty_counts()
        site["covered_cpg_sites"] = 1
        site["valid"] = m_row.valid
        site["canonical"] = m_row.canonical
        site["mod_m"] = m_row.modified
        site["mod_h"] = h_row.modified
        site["fail"] = m_row.failed
        site["nocall"] = m_row.nocall
        site["delete"] = m_row.delete
        site["diff"] = m_row.different
        add_counts(chromosome_counts[m_row.chrom], site)
        add_counts(window_counts[m_row.chrom][m_row.start // window_size], site)
        site_count += 1

    if site_count == 0:
        fail(f"{path}: no paired CpG bedMethyl records")
    return site_count


def validate_modkit_stats(
    path: Path,
    contigs: OrderedDict[str, int],
    chromosome_counts: dict[str, dict[str, int]],
) -> None:
    seen: set[str] = set()
    with path.open("rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"#chrom", "start", "end", "count_h", "count_valid_h", "count_m", "count_valid_m"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            fail(f"{path}: unexpected Modkit stats header")
        for row in reader:
            chrom = row["#chrom"]
            if chrom not in contigs or chrom in seen:
                fail(f"{path}: unexpected or duplicate chromosome row: {chrom}")
            seen.add(chrom)
            try:
                start = int(row["start"])
                end = int(row["end"])
                count_h = int(row["count_h"])
                valid_h = int(row["count_valid_h"])
                count_m = int(row["count_m"])
                valid_m = int(row["count_valid_m"])
            except ValueError:
                fail(f"{path}: invalid numeric value for {chrom}")
            counts = chromosome_counts[chrom]
            if (
                start != 0
                or end != contigs[chrom]
                or count_h != counts["mod_h"]
                or count_m != counts["mod_m"]
                or valid_h != counts["valid"]
                or valid_m != counts["valid"]
            ):
                fail(f"{path}: Modkit stats disagree with bedMethyl aggregation for {chrom}")
    missing = [name for name in contigs if name not in seen]
    if missing:
        fail(f"{path}: missing chromosome row: {missing[0]}")


def summary_header() -> list[str]:
    return [
        "chrom",
        "start",
        "end",
        "region_bases",
        "reference_cpg_sites",
        "cpg_sites_with_valid_calls",
        "pct_reference_cpg_sites_with_valid_calls",
        "valid_calls",
        "canonical_calls",
        "modified_5mc_calls",
        "modified_5hmc_calls",
        "total_modified_calls",
        "pct_5mc_of_valid_calls",
        "pct_5hmc_of_valid_calls",
        "pct_total_modified_of_valid_calls",
        "failed_filtered_calls",
        "no_call_calls",
        "deletion_calls",
        "different_base_calls",
        "total_observations",
        "pct_valid_calls_of_observations",
    ]


def summary_row(chrom: str, start: int, end: int, counts: dict[str, int]) -> list[str | int]:
    total_modified = counts["mod_m"] + counts["mod_h"]
    observations = observation_total(counts)
    return [
        chrom,
        start,
        end,
        end - start,
        counts["reference_cpg_sites"],
        counts["covered_cpg_sites"],
        pct(counts["covered_cpg_sites"], counts["reference_cpg_sites"]),
        counts["valid"],
        counts["canonical"],
        counts["mod_m"],
        counts["mod_h"],
        total_modified,
        pct(counts["mod_m"], counts["valid"]),
        pct(counts["mod_h"], counts["valid"]),
        pct(total_modified, counts["valid"]),
        counts["fail"],
        counts["nocall"],
        counts["delete"],
        counts["diff"],
        observations,
        pct(counts["valid"], observations),
    ]


def write_outputs(
    args: argparse.Namespace,
    contigs: OrderedDict[str, int],
    chromosome_counts: dict[str, dict[str, int]],
    window_counts: dict[str, list[dict[str, int]]],
) -> None:
    global_counts = empty_counts()
    for counts in chromosome_counts.values():
        add_counts(global_counts, counts)
    if global_counts["valid"] <= 0:
        fail("global valid CpG call denominator is zero")
    if global_counts["canonical"] + global_counts["mod_m"] + global_counts["mod_h"] != global_counts["valid"]:
        fail("global canonical + 5mC + 5hmC does not equal valid calls")

    total_modified = global_counts["mod_m"] + global_counts["mod_h"]
    with args.global_out.open("wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "context",
                "category",
                "mod_code",
                "call_count",
                "valid_call_denominator",
                "percent_of_valid_calls",
                "modified_call_denominator",
                "percent_of_modified_calls",
            ]
        )
        writer.writerow(["CpG", "5mC", "m", global_counts["mod_m"], global_counts["valid"], pct(global_counts["mod_m"], global_counts["valid"]), total_modified, pct(global_counts["mod_m"], total_modified)])
        writer.writerow(["CpG", "5hmC", "h", global_counts["mod_h"], global_counts["valid"], pct(global_counts["mod_h"], global_counts["valid"]), total_modified, pct(global_counts["mod_h"], total_modified)])
        writer.writerow(["CpG", "total_modified", "m+h", total_modified, global_counts["valid"], pct(total_modified, global_counts["valid"]), total_modified, pct(total_modified, total_modified)])
        writer.writerow(["CpG", "canonical_C", "C", global_counts["canonical"], global_counts["valid"], pct(global_counts["canonical"], global_counts["valid"]), "NA", "NA"])

    with args.chromosome_out.open("wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(summary_header())
        for chrom, length in contigs.items():
            writer.writerow(summary_row(chrom, 0, length, chromosome_counts[chrom]))

    with args.window_out.open("wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        header = summary_header()
        header[0] = "#chrom"
        writer.writerow(header)
        for chrom, length in contigs.items():
            for index, counts in enumerate(window_counts[chrom]):
                start = index * args.window_size
                end = min(start + args.window_size, length)
                writer.writerow(summary_row(chrom, start, end, counts))

    with args.call_coverage_out.open("wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "scope",
                "chrom",
                "start",
                "end",
                "reference_cpg_sites",
                "cpg_sites_with_valid_calls",
                "cpg_sites_without_valid_calls",
                "pct_reference_cpg_sites_with_valid_calls",
                "valid_calls",
                "failed_filtered_calls",
                "no_call_calls",
                "deletion_calls",
                "different_base_calls",
                "total_observations",
                "pct_valid_calls_of_observations",
            ]
        )

        def coverage_row(scope: str, chrom: str, start: int, end: int, counts: dict[str, int]):
            observations = observation_total(counts)
            return [
                scope,
                chrom,
                start,
                end,
                counts["reference_cpg_sites"],
                counts["covered_cpg_sites"],
                counts["reference_cpg_sites"] - counts["covered_cpg_sites"],
                pct(counts["covered_cpg_sites"], counts["reference_cpg_sites"]),
                counts["valid"],
                counts["fail"],
                counts["nocall"],
                counts["delete"],
                counts["diff"],
                observations,
                pct(counts["valid"], observations),
            ]

        writer.writerow(coverage_row("genome", "ALL", 0, sum(contigs.values()), global_counts))
        for chrom, length in contigs.items():
            writer.writerow(coverage_row("chromosome", chrom, 0, length, chromosome_counts[chrom]))


def main() -> int:
    args = parse_args()
    if args.window_size <= 0:
        fail("window size must be positive")
    contigs = read_fai(args.fai)
    chromosome_counts = {name: empty_counts() for name in contigs}
    window_counts = {
        name: [empty_counts() for _ in range((length + args.window_size - 1) // args.window_size)]
        for name, length in contigs.items()
    }
    count_reference_cpgs(args.fasta, contigs, chromosome_counts, window_counts, args.window_size)
    aggregate_bedmethyl(args.bedmethyl, contigs, chromosome_counts, window_counts, args.window_size)
    for chrom in contigs:
        if chromosome_counts[chrom]["covered_cpg_sites"] > chromosome_counts[chrom]["reference_cpg_sites"]:
            fail(f"more covered CpG sites than reference CpGs on {chrom}")
    validate_modkit_stats(args.modkit_stats, contigs, chromosome_counts)
    write_outputs(args, contigs, chromosome_counts, window_counts)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
