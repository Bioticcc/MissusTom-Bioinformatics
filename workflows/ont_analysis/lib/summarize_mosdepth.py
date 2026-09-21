#!/usr/bin/env python3
"""Validate Mosdepth output and build Stage 03 coverage tables.

All genomic coordinates written by this helper are zero-based, half-open.
Only the Python standard library is used so the pipeline has no hidden package
dependency.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import sys
from collections import OrderedDict
from itertools import zip_longest
from pathlib import Path


def fail(message: str) -> "None":
    raise ValueError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fai", required=True, type=Path)
    parser.add_argument("--regions", required=True, type=Path)
    parser.add_argument("--thresholds-bed", required=True, type=Path)
    parser.add_argument("--per-base", required=True, type=Path)
    parser.add_argument("--mosdepth-summary", required=True, type=Path)
    parser.add_argument("--coverage-summary-out", required=True, type=Path)
    parser.add_argument("--chromosome-out", required=True, type=Path)
    parser.add_argument("--window-out", required=True, type=Path)
    parser.add_argument("--low-interval-out", required=True, type=Path)
    parser.add_argument("--thresholds", required=True)
    parser.add_argument("--window-size", required=True, type=int)
    parser.add_argument("--low-depth-threshold", required=True, type=int)
    parser.add_argument("--low-window-min-1x-breadth", required=True, type=float)
    parser.add_argument("--exclude-flags", required=True, type=int)
    parser.add_argument("--min-mapq", required=True, type=int)
    return parser.parse_args()


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("rt", encoding="utf-8", newline="")


def data_rows(path: Path):
    with open_text(path) as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            yield line_number, line.split("\t")


def read_fai(path: Path) -> OrderedDict[str, int]:
    contigs: OrderedDict[str, int] = OrderedDict()
    with path.open("rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 2:
                fail(f"{path}:{line_number}: malformed FAI row")
            name = fields[0]
            try:
                length = int(fields[1])
            except ValueError:
                fail(f"{path}:{line_number}: invalid contig length")
            if not name or name in contigs or length <= 0:
                fail(f"{path}:{line_number}: invalid or duplicate contig {name!r}")
            contigs[name] = length
    if not contigs:
        fail(f"{path}: FAI contains no contigs")
    return contigs


def parse_threshold_list(raw: str) -> list[int]:
    try:
        values = [int(value) for value in raw.split(",")]
    except ValueError:
        fail("coverage thresholds must be comma-separated integers")
    if not values or any(value <= 0 for value in values):
        fail("coverage thresholds must be positive")
    if values != sorted(set(values)):
        fail("coverage thresholds must be unique and ascending")
    if 1 not in values:
        fail("coverage thresholds must include 1x")
    return values


def read_mosdepth_summary(path: Path, contigs: OrderedDict[str, int]):
    rows: dict[str, tuple[int, int, float]] = {}
    total: tuple[int, int, float] | None = None
    with path.open("rt", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"chrom", "length", "bases", "mean", "min", "max"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            fail(f"{path}: unexpected Mosdepth summary header")
        for row in reader:
            name = row["chrom"]
            try:
                parsed = (int(row["length"]), int(row["bases"]), float(row["mean"]))
            except (TypeError, ValueError):
                fail(f"{path}: invalid numeric value in row {name!r}")
            if name == "total":
                total = parsed
            elif name in contigs:
                rows[name] = parsed
    if total is None:
        fail(f"{path}: missing total row")
    missing = [name for name in contigs if name not in rows]
    if missing:
        fail(f"{path}: missing contig summaries (first: {missing[0]})")
    return rows, total


def fmt_float(value: float) -> str:
    return f"{value:.6f}"


def pct(numerator: int, denominator: int) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def main() -> int:
    args = parse_args()
    thresholds = parse_threshold_list(args.thresholds)
    if args.window_size <= 0:
        fail("window size must be positive")
    if args.low_depth_threshold <= 1:
        fail("low-depth threshold must be greater than 1")
    if not 0.0 <= args.low_window_min_1x_breadth <= 100.0:
        fail("low-window 1x breadth must be between 0 and 100")

    contigs = read_fai(args.fai)
    contig_index = {name: index for index, name in enumerate(contigs)}
    chromosome_counts = {name: [0 for _ in thresholds] for name in contigs}
    chromosome_depth_sum = {name: 0.0 for name in contigs}
    observed_window_end = {name: 0 for name in contigs}
    window_count = 0
    zero_window_count = 0
    low_window_count = 0

    region_iter = data_rows(args.regions)
    threshold_iter = data_rows(args.thresholds_bed)
    previous_contig_index = -1

    with args.window_out.open("wt", encoding="utf-8", newline="") as window_handle:
        writer = csv.writer(window_handle, delimiter="\t", lineterminator="\n")
        header = ["#chrom", "start", "end", "window_bases", "mean_depth"]
        for threshold in thresholds:
            header.extend([f"bases_ge_{threshold}x", f"pct_ge_{threshold}x"])
        header.append("coverage_status")
        writer.writerow(header)

        for region_item, threshold_item in zip_longest(region_iter, threshold_iter):
            if region_item is None or threshold_item is None:
                fail("Mosdepth regions and thresholds files have different row counts")
            region_line, region = region_item
            threshold_line, threshold_row = threshold_item
            if len(region) != 4:
                fail(f"{args.regions}:{region_line}: expected 4 columns")
            if len(threshold_row) != 4 + len(thresholds):
                fail(
                    f"{args.thresholds_bed}:{threshold_line}: expected "
                    f"{4 + len(thresholds)} columns"
                )
            if region[:3] != threshold_row[:3]:
                fail("Mosdepth regions and thresholds coordinates do not match")
            chrom = region[0]
            if chrom not in contigs:
                fail(f"Mosdepth emitted contig absent from FAI: {chrom}")
            try:
                start, end = int(region[1]), int(region[2])
                mean_depth = float(region[3])
                counts = [int(value) for value in threshold_row[4:]]
            except ValueError:
                fail(f"{args.regions}:{region_line}: invalid numeric value")
            length = end - start
            if (
                start != observed_window_end[chrom]
                or length <= 0
                or length > args.window_size
                or end > contigs[chrom]
            ):
                fail(f"{args.regions}:{region_line}: invalid or discontinuous window")
            current_index = contig_index[chrom]
            if current_index < previous_contig_index:
                fail("Mosdepth windows are not in FAI contig order")
            previous_contig_index = current_index
            observed_window_end[chrom] = end
            if not math.isfinite(mean_depth) or mean_depth < 0:
                fail(f"{args.regions}:{region_line}: invalid mean depth")
            if any(value < 0 or value > length for value in counts):
                fail(f"{args.thresholds_bed}:{threshold_line}: invalid threshold count")
            if any(counts[index] < counts[index + 1] for index in range(len(counts) - 1)):
                fail(f"{args.thresholds_bed}:{threshold_line}: threshold counts increase")

            one_x_pct = pct(counts[thresholds.index(1)], length)
            if counts[thresholds.index(1)] == 0:
                status = "no_coverage"
                zero_window_count += 1
            elif one_x_pct < args.low_window_min_1x_breadth:
                status = "low_1x_breadth"
                low_window_count += 1
            else:
                status = "adequate_1x_breadth"

            output = [chrom, start, end, length, fmt_float(mean_depth)]
            for count in counts:
                output.extend([count, fmt_float(pct(count, length))])
            output.append(status)
            writer.writerow(output)

            window_count += 1
            chromosome_depth_sum[chrom] += mean_depth * length
            for index, count in enumerate(counts):
                chromosome_counts[chrom][index] += count

    incomplete = [name for name, length in contigs.items() if observed_window_end[name] != length]
    if incomplete:
        fail(f"Mosdepth windows do not span the FAI (first incomplete contig: {incomplete[0]})")

    low_interval_count = 0
    zero_interval_count = 0
    per_base_depth_sum = 0
    per_base_bases = 0
    per_base_covered_bases = 0
    per_base_chromosome_depth_sum = {name: 0 for name in contigs}
    per_base_chromosome_covered_bases = {name: 0 for name in contigs}
    observed_per_base_end = {name: 0 for name in contigs}
    active: dict[str, int | str] | None = None

    with args.low_interval_out.open("wt", encoding="utf-8", newline="") as low_handle:
        writer = csv.writer(low_handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ["#chrom", "start", "end", "coverage_class", "interval_bases", "mean_depth", "min_depth", "max_depth"]
        )

        def flush_active() -> None:
            nonlocal active, low_interval_count, zero_interval_count
            if active is None:
                return
            interval_bases = int(active["end"]) - int(active["start"])
            writer.writerow(
                [
                    active["chrom"],
                    active["start"],
                    active["end"],
                    active["coverage_class"],
                    interval_bases,
                    fmt_float(int(active["depth_sum"]) / interval_bases),
                    active["min_depth"],
                    active["max_depth"],
                ]
            )
            if active["coverage_class"] == "no_coverage":
                zero_interval_count += 1
            else:
                low_interval_count += 1
            active = None

        previous_contig_index = -1
        for line_number, fields in data_rows(args.per_base):
            if len(fields) != 4:
                fail(f"{args.per_base}:{line_number}: expected 4 columns")
            chrom = fields[0]
            if chrom not in contigs:
                fail(f"{args.per_base}:{line_number}: contig absent from FAI")
            try:
                start, end, depth = int(fields[1]), int(fields[2]), int(fields[3])
            except ValueError:
                fail(f"{args.per_base}:{line_number}: invalid numeric value")
            length = end - start
            if start != observed_per_base_end[chrom] or length <= 0 or end > contigs[chrom] or depth < 0:
                fail(f"{args.per_base}:{line_number}: invalid or discontinuous interval")
            current_index = contig_index[chrom]
            if current_index < previous_contig_index:
                fail("Mosdepth per-base intervals are not in FAI contig order")
            previous_contig_index = current_index
            observed_per_base_end[chrom] = end
            per_base_bases += length
            per_base_depth_sum += depth * length
            per_base_chromosome_depth_sum[chrom] += depth * length
            if depth >= 1:
                per_base_covered_bases += length
                per_base_chromosome_covered_bases[chrom] += length

            if depth == 0:
                coverage_class = "no_coverage"
            elif depth < args.low_depth_threshold:
                coverage_class = f"low_depth_1_to_{args.low_depth_threshold - 1}x"
            else:
                coverage_class = None

            if coverage_class is None:
                flush_active()
                continue
            if (
                active is not None
                and active["chrom"] == chrom
                and active["coverage_class"] == coverage_class
                and active["end"] == start
            ):
                active["end"] = end
                active["depth_sum"] = int(active["depth_sum"]) + depth * length
                active["min_depth"] = min(int(active["min_depth"]), depth)
                active["max_depth"] = max(int(active["max_depth"]), depth)
            else:
                flush_active()
                active = {
                    "chrom": chrom,
                    "start": start,
                    "end": end,
                    "coverage_class": coverage_class,
                    "depth_sum": depth * length,
                    "min_depth": depth,
                    "max_depth": depth,
                }
        flush_active()

    incomplete = [name for name, length in contigs.items() if observed_per_base_end[name] != length]
    if incomplete:
        fail(f"Mosdepth per-base track does not span the FAI (first incomplete contig: {incomplete[0]})")

    mosdepth_rows, mosdepth_total = read_mosdepth_summary(args.mosdepth_summary, contigs)
    reference_bases = sum(contigs.values())
    if per_base_bases != reference_bases:
        fail("per-base interval length does not equal reference length")
    total_counts = [sum(chromosome_counts[name][i] for name in contigs) for i in range(len(thresholds))]
    one_x_index = thresholds.index(1)
    if mosdepth_total[0] != reference_bases or mosdepth_total[1] != per_base_depth_sum:
        fail("Mosdepth summary totals disagree with per-base depth totals")
    if total_counts[one_x_index] != per_base_covered_bases:
        fail("Mosdepth threshold totals disagree with per-base covered bases")
    exact_mean_depth = per_base_depth_sum / reference_bases
    if abs(exact_mean_depth - mosdepth_total[2]) > 0.000002:
        fail("Mosdepth per-base mean disagrees with Mosdepth summary mean")

    with args.chromosome_out.open("wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        header = ["chrom", "chromosome_bases", "mean_depth"]
        for threshold in thresholds:
            header.extend([f"bases_ge_{threshold}x", f"pct_ge_{threshold}x"])
        writer.writerow(header)
        for chrom, length in contigs.items():
            summary_length, summary_depth_sum, summary_mean = mosdepth_rows[chrom]
            if summary_length != length or summary_depth_sum != per_base_chromosome_depth_sum[chrom]:
                fail(f"Mosdepth chromosome summary disagrees for {chrom}")
            if chromosome_counts[chrom][one_x_index] != per_base_chromosome_covered_bases[chrom]:
                fail(f"Mosdepth chromosome threshold breadth disagrees for {chrom}")
            output = [chrom, length, fmt_float(summary_mean)]
            for count in chromosome_counts[chrom]:
                output.extend([count, fmt_float(pct(count, length))])
            writer.writerow(output)

    zero_bases = reference_bases - total_counts[one_x_index]
    with args.coverage_summary_out.open("wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["metric", "value", "definition"])
        writer.writerow(["reference_bases", reference_bases, "FAI bases included in Mosdepth analysis"])
        writer.writerow(["mean_depth", fmt_float(exact_mean_depth), "sum(depth*bases)/reference_bases"])
        for threshold, count in zip(thresholds, total_counts):
            writer.writerow([f"bases_ge_{threshold}x", count, f"reference bases with depth >= {threshold}"])
            writer.writerow([f"pct_ge_{threshold}x", fmt_float(pct(count, reference_bases)), f"percent of reference bases with depth >= {threshold}"])
        writer.writerow(["zero_coverage_bases", zero_bases, "reference bases with depth 0"])
        writer.writerow(["pct_zero_coverage", fmt_float(pct(zero_bases, reference_bases)), "percent of reference bases with depth 0"])
        writer.writerow(["coverage_window_count", window_count, f"zero-based half-open windows, target size {args.window_size}"])
        writer.writerow(["zero_coverage_window_count", zero_window_count, "windows with no bases at >=1x"])
        writer.writerow(["low_1x_breadth_window_count", low_window_count, f"nonzero windows with <{args.low_window_min_1x_breadth:g}% of bases at >=1x"])
        writer.writerow(["zero_coverage_interval_count", zero_interval_count, "contiguous run-length intervals at depth 0"])
        writer.writerow(["low_depth_interval_count", low_interval_count, f"contiguous run-length intervals at depth 1 to {args.low_depth_threshold - 1}"])
        writer.writerow(["mosdepth_exclude_flag_mask", args.exclude_flags, "SAM flag mask excluded from coverage"])
        writer.writerow(["minimum_mapping_quality", args.min_mapq, "minimum MAPQ included in coverage"])

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
