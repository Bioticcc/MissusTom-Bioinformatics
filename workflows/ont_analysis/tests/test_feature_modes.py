"""Run the actual feature reports from small, pipeline-shaped methylation outputs."""

import csv
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class FeatureModeTests(unittest.TestCase):
    def test_joint_and_5mc_only_feature_reports(self):
        rscript = os.environ.get("ONT_TEST_RSCRIPT") or shutil.which("Rscript")
        if not rscript:
            self.skipTest("Rscript unavailable")
        packages = (
            'c("data.table","ggplot2","ggrepel","scales","patchwork",'
            '"GenomicRanges","rtracklayer","jsonlite")'
        )
        probe = subprocess.run(
            [
                rscript,
                "--vanilla",
                "-e",
                f"quit(status=if(all(vapply({packages},requireNamespace,logical(1),"
                "quietly=TRUE))) 0 else 1)",
            ],
            capture_output=True,
            text=True,
        )
        if probe.returncode:
            self.skipTest("Feature R packages unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            for mode in ("5mc_only", "5mc_5hmc"):
                with self.subTest(mode=mode):
                    root = Path(temporary) / mode
                    root.mkdir()
                    paths = self.make_inputs(root, mode)
                    output = root / "report"
                    command = [
                        rscript,
                        "--vanilla",
                        str(ROOT / "lib/methylation_exploration.R"),
                        "--sample-id",
                        "synthetic",
                        "--organism",
                        "Homo sapiens",
                        "--reference-name",
                        "GRCh38",
                        "--modification-mode",
                        mode,
                        "--main-chromosomes",
                        ",".join(f"chr{i}" for i in range(1, 23)),
                        "--output-dir",
                        str(output),
                        "--min-valid-coverage",
                        "1",
                        "--min-feature-cpgs",
                        "1",
                        "--top-window-count",
                        "20",
                        "--plot-dpi",
                        "72",
                    ]
                    for key, path in paths.items():
                        command.extend([f"--{key}", str(path)])
                    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
                    self.assertEqual(result.returncode, 0, result.stderr[-10000:])
                    figures = list((output / "figures").glob("*.pdf"))
                    self.assertGreaterEqual(len(figures), 19 if mode == "5mc_only" else 23)
                    with (output / "tables/feature_methylation_summary.tsv").open() as handle:
                        rows = list(csv.DictReader(handle, delimiter="\t"))
                    measured = [row for row in rows if row["valid_calls"] not in ("NA", "0")]
                    self.assertTrue(measured)
                    core = root / "core-report"
                    core_command = [
                        rscript,
                        "--vanilla",
                        str(ROOT / "lib/core_methylation_qc.R"),
                        "--sample-id",
                        "synthetic",
                        "--organism",
                        "Homo sapiens",
                        "--reference-name",
                        "GRCh38",
                        "--modification-mode",
                        mode,
                        "--main-chromosomes",
                        ",".join(f"chr{i}" for i in range(1, 23)),
                        "--output-dir",
                        str(core),
                    ]
                    for key in (
                        "global-levels",
                        "chromosome-methylation",
                        "chromosome-coverage",
                        "coverage-summary",
                    ):
                        core_command.extend([f"--{key}", str(paths[key])])
                    core_result = subprocess.run(
                        core_command, capture_output=True, text=True, timeout=30
                    )
                    self.assertEqual(core_result.returncode, 0, core_result.stderr)
                    self.assertEqual(len(list((core / "figures").glob("*.pdf"))), 4)
                    if mode == "5mc_only":
                        self.assertIn(
                            "5hmC not measured",
                            (core / "ont_methylation_qc_report.html").read_text(),
                        )
                        self.assertTrue(
                            all(row["weighted_5hmc_percent"] == "NA" for row in measured)
                        )
                        self.assertFalse(
                            any(
                                path.name.startswith(("10_", "11_", "15_", "16_"))
                                for path in figures
                            )
                        )
                        self.assertIn(
                            "5hmC not measured",
                            (output / "ont_methylation_qc_report.html").read_text(),
                        )

    def make_inputs(self, root, mode):
        names = [f"chr{i}" for i in range(1, 23)]
        fasta = root / "reference.fa"
        fai = root / "reference.fai"
        with fasta.open("w") as handle, fai.open("w") as index:
            for name in names:
                handle.write(f">{name}\n")
                offset = handle.tell()
                handle.write("CG" * 2000 + "\n")
                index.write(f"{name}\t4000\t{offset}\t4000\t4001\n")
        bed = root / "calls.bed.gz"
        stats = root / "stats.tsv"
        joint = mode == "5mc_5hmc"
        with gzip.open(bed, "wt") as handle, stats.open("w") as stat:
            stat.write(
                "#chrom\tstart\tend\tcount_m\tcount_valid_m"
                + ("\tcount_h\tcount_valid_h" if joint else "")
                + "\n"
            )
            for name in names:
                total_m = total_h = 0
                for pos in range(0, 4000, 2):
                    m = 1 + (pos // 100) % 5
                    h = 1 if joint else 0
                    total_m += m
                    total_h += h
                    for code, modified, other in (
                        (("m", m, h), ("h", h, m)) if joint else (("m", m, 0),)
                    ):
                        row = [
                            name,
                            pos,
                            pos + 1,
                            code,
                            10,
                            ".",
                            pos,
                            pos + 1,
                            "0,0,0",
                            10,
                            modified * 10,
                            modified,
                            10 - m - h,
                            other,
                            0,
                            0,
                            0,
                            0,
                        ]
                        handle.write("\t".join(map(str, row)) + "\n")
                stat.write(
                    f"{name}\t0\t4000\t{total_m}\t20000"
                    + (f"\t{total_h}\t20000" if joint else "")
                    + "\n"
                )
        command = [
            sys.executable,
            str(ROOT / "lib/summarize_cpg_bedmethyl.py"),
            "--fasta",
            str(fasta),
            "--fai",
            str(fai),
            "--bedmethyl",
            str(bed),
            "--modkit-stats",
            str(stats),
            "--window-size",
            "100",
            "--modification-mode",
            mode,
        ]
        paths = {"fai": fai, "bedmethyl": bed}
        for option, key in (
            ("global", "global-levels"),
            ("chromosome", "chromosome-methylation"),
            ("window", "window-methylation"),
            ("call-coverage", "call-coverage"),
        ):
            paths[key] = root / f"{key}.tsv"
            command.extend([f"--{option}-out", str(paths[key])])
        subprocess.run(command, check=True, capture_output=True, text=True)
        text = {
            "chromosome-coverage": "chrom\tmean_depth\tpct_ge_1x\n"
            + "".join(f"{name}\t10\t100\n" for name in names),
            "window-coverage": "chrom\tstart\tend\tmean_depth\tpct_ge_1x\n"
            + "".join(
                f"{name}\t{pos}\t{pos + 100}\t10\t100\n"
                for name in names
                for pos in range(0, 4000, 100)
            ),
            "coverage-summary": (
                "metric\tvalue\nmean_depth\t10\npct_ge_1x\t100\nzero_coverage_bases\t0\n"
            ),
            "alignment-stats": (
                "SN\traw total sequences:\t10\nSN\treads mapped:\t10\n"
                "SN\taverage length:\t100\nSN\tmaximum length:\t100\n"
                "SN\terror rate:\t0.01\n"
            ),
            "alignment-flagstat": "10 mapped\n",
            "stage02-summary": "synthetic\n",
            "instrument-report": "synthetic\n",
            "intergenic": "chr1\t0\t900\n",
            "ccre": "#chrom\tchromStart\tchromEnd\tccre\nchr1\t100\t900\tPLS\n",
            "cpg-islands": json.dumps(
                {"cpgIslandExt": {"chr1": [{"chrom": "chr1", "chromStart": 200, "chromEnd": 800}]}}
            ),
            "gff3": "##gff-version 3\n"
            + "".join(
                f"chr1\tsynthetic\t{kind}\t{start}\t{end}\t.\t+\t.\tID={kind}{start};gene_id=g1;gene_name=Gene1;gene_type=protein_coding;transcript_id=tx1;transcript_support_level=1\n"
                for kind, start, end in (
                    ("gene", 1001, 3500),
                    ("exon", 1101, 1600),
                    ("exon", 2501, 3000),
                    ("five_prime_UTR", 1101, 1150),
                    ("three_prime_UTR", 2901, 3000),
                )
            ),
        }
        for key, content in text.items():
            paths[key] = root / ("annotation.gff3" if key == "gff3" else f"{key}.txt")
            paths[key].write_text(content)
        return paths
