#!/usr/bin/env python3
"""Build a descriptive project QC overview from published per-sample summaries."""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
from pathlib import Path
from urllib.parse import quote


def table(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def build(manifest: Path, results: Path) -> None:
    data = json.loads(manifest.read_text())
    samples = [sample for sample in data["samples"] if sample.get("included") is True]
    rows = []
    for sample in samples:
        name = sample["sample_id"]
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError("Unsafe sample identifier")
        root = results / "samples" / name
        report = root / "05_methylation_exploration/ont_methylation_qc_report.html"
        if (
            not report.is_file()
            or not (root / "05_methylation_exploration/.stage05.complete").is_file()
        ):
            raise ValueError(f"Sample report is not complete: {name}")
        coverage = {
            row["metric"]: row["value"]
            for row in table(root / "03_ont_qc_coverage/coverage_summary.tsv")
        }
        global_calls = {
            row["category"]: row
            for row in table(root / "04_methylation/global_methylation_levels.tsv")
        }
        rows.append(
            {
                "sample_id": name,
                "measurement_mode": global_calls["5mC"]["modification_mode"],
                "mean_depth": coverage["mean_depth"],
                "reference_bases_ge_1x_percent": coverage["pct_ge_1x"],
                "reference_bases_ge_10x_percent": coverage["pct_ge_10x"],
                "reference_zero_depth_percent": coverage["pct_zero_coverage"],
                "valid_cpg_calls": global_calls["5mC"]["valid_call_denominator"],
                "weighted_5mc_percent": global_calls["5mC"]["percent_of_valid_calls"],
                "weighted_5hmc_percent": global_calls["5hmC"]["percent_of_valid_calls"],
                "report_path": str(report.relative_to(results)),
            }
        )
    if not rows:
        raise ValueError("No included sample reports")
    destination = results / "project_qc"
    if destination.is_symlink():
        raise ValueError("Unsafe overview directory")
    destination.mkdir(exist_ok=True)
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    titles = (
        "Sample report",
        "Mode",
        "Mean depth",
        "Reference ≥1x",
        "Reference ≥10x",
        "Reference at 0x",
        "Valid CpG calls",
        "5mC",
        "5hmC",
    )
    body = []
    for row in rows:

        def number(key: str, suffix: str = "", current: dict[str, str] = row) -> str:
            value = current[key]
            return "Not measured" if value == "NA" else f"{float(value):,.2f}{suffix}"

        values = [
            html.escape(
                "5mC only" if row["measurement_mode"] == "5mc_only" else "5mC + 5hmC"
            ),
            number("mean_depth", "x"),
            number("reference_bases_ge_1x_percent", "%"),
            number("reference_bases_ge_10x_percent", "%"),
            number("reference_zero_depth_percent", "%"),
            f"{int(row['valid_cpg_calls']):,}",
            number("weighted_5mc_percent", "%"),
            number("weighted_5hmc_percent", "%"),
        ]
        link = "../" + quote(row["report_path"], safe="/")
        body.append(
            f'<tr><th><a href="{link}">{html.escape(row["sample_id"])}</a></th>'
            + "".join(f"<td>{value}</td>" for value in values)
            + "</tr>"
        )
    sample_label = "sample" if len(rows) == 1 else "samples"
    document = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>ONT project QC overview</title><style>body{font:16px system-ui;max-width:1500px;margin:32px auto;padding:0 20px;color:#243447;background:#f8fafc}table{border-collapse:collapse;background:white;width:100%}th,td{padding:12px;border-bottom:1px solid #dbe4ea;text-align:left}tbody th{min-width:240px;overflow-wrap:anywhere}td{white-space:nowrap}a{color:#086c85}.table{overflow:auto}.notice{background:#fff5dd;padding:16px}</style>"
        f"<h1>ONT project QC overview</h1><p>{len(rows)} included {sample_label} · {html.escape(data['organism'])} · {html.escape(data['reference_genome'])}</p>"
        '<p class="notice">Descriptive QC only. Coverage breadth and sequencing depth differ from modification-call depth. Methylation percentages summarize observed valid calls, not complete genomes. No biological grouping, differential methylation, or statistical significance is inferred. Click a sample for its full QC report.</p>'
        '<p><a href="sample_qc_summary.tsv">Download QC table</a></p><div class="table"><table><thead><tr>'
        + "".join(f"<th>{html.escape(title)}</th>" for title in titles)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></html>"
    )
    for name, text in (
        ("sample_qc_summary.tsv", stream.getvalue()),
        ("ont_project_qc_report.html", document),
    ):
        target = destination / name
        temporary = destination / (name + ".partial")
        if target.is_symlink() or temporary.is_symlink():
            raise ValueError("Unsafe report destination")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    args = parser.parse_args()
    build(args.manifest, args.results)
