"""Synthetic-only checks of the migrated modified-base denominators."""

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MethylationSummaryTests(unittest.TestCase):
    def test_5mc_only_uses_weighted_counts_and_marks_5hmc_unmeasured(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "reference.fa").write_text(">chr1\nCGCG\n")
            (root / "reference.fai").write_text("chr1\t4\t6\t4\t5\n")
            rows = [
                [
                    "chr1",
                    pos,
                    pos + 1,
                    "m",
                    valid,
                    ".",
                    pos,
                    pos + 1,
                    "0,0,0",
                    valid,
                    100 * modified / valid,
                    modified,
                    valid - modified,
                    0,
                    0,
                    0,
                    0,
                    0,
                ]
                for pos, valid, modified in ((0, 10, 6), (2, 30, 3))
            ]
            bed = root / "calls.bed"
            bed.write_text("".join("\t".join(map(str, row)) + "\n" for row in rows))
            (root / "stats.tsv").write_text(
                "#chrom\tstart\tend\tcount_m\tcount_valid_m\nchr1\t0\t4\t9\t40\n"
            )
            command = [
                sys.executable,
                str(Path(__file__).parents[1] / "lib/summarize_cpg_bedmethyl.py"),
                "--modification-mode",
                "5mc_only",
                "--fasta",
                str(root / "reference.fa"),
                "--fai",
                str(root / "reference.fai"),
                "--bedmethyl",
                str(bed),
                "--modkit-stats",
                str(root / "stats.tsv"),
                "--window-size",
                "2",
            ]
            for name in ("global", "chromosome", "window", "call-coverage"):
                command.extend([f"--{name}-out", str(root / f"{name}.tsv")])
            subprocess.run(command, check=True, capture_output=True, text=True)
            with (root / "global.tsv").open() as handle:
                values = {row["category"]: row for row in csv.DictReader(handle, delimiter="\t")}
            self.assertEqual(float(values["5mC"]["percent_of_valid_calls"]), 22.5)
            self.assertEqual(values["5hmC"]["call_count"], "NA")
            self.assertEqual(values["5hmC"]["percent_of_valid_calls"], "NA")
            self.assertEqual(values["5hmC"]["measurement_status"], "not_measured")
            with (root / "chromosome.tsv").open() as handle:
                chrom = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(chrom["modified_5hmc_calls"], "NA")
            self.assertEqual(chrom["pct_5hmc_of_valid_calls"], "NA")
            rows[0][13] = 1
            rows[0][12] -= 1
            bed.write_text("".join("\t".join(map(str, row)) + "\n" for row in rows))
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no other modification", result.stderr)

    def test_separate_modifications_use_weighted_valid_call_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fasta = root / "reference.fa"
            fasta.write_text(">chr1\nCGCG\n")
            fai = root / "reference.fai"
            fai.write_text("chr1\t4\t6\t4\t5\n")
            bed = root / "calls.bed"
            rows = []
            # Unequal depths distinguish a weighted result from mean percentages.
            for position, valid, m, h in ((0, 10, 6, 2), (2, 30, 3, 6)):
                canonical = valid - m - h
                for code, modified, other in (("m", m, h), ("h", h, m)):
                    rows.append(
                        [
                            "chr1",
                            position,
                            position + 1,
                            code,
                            valid,
                            ".",
                            position,
                            position + 1,
                            "0,0,0",
                            valid,
                            100 * modified / valid,
                            modified,
                            canonical,
                            other,
                            0,
                            0,
                            0,
                            0,
                        ]
                    )
            bed.write_text("".join("\t".join(map(str, row)) + "\n" for row in rows))
            stats = root / "stats.tsv"
            stats.write_text(
                "#chrom\tstart\tend\tcount_h\tcount_valid_h\tcount_m\tcount_valid_m\nchr1\t0\t4\t8\t40\t9\t40\n"
            )
            command = [
                sys.executable,
                str(Path(__file__).parents[1] / "lib" / "summarize_cpg_bedmethyl.py"),
                "--fasta",
                str(fasta),
                "--fai",
                str(fai),
                "--bedmethyl",
                str(bed),
                "--modkit-stats",
                str(stats),
                "--window-size",
                "2",
            ]
            for option in ("global", "chromosome", "window", "call-coverage"):
                command.extend([f"--{option}-out", str(root / f"{option}.tsv")])
            subprocess.run(command, check=True, capture_output=True, text=True)
            with (root / "global.tsv").open() as handle:
                values = {row["category"]: row for row in csv.DictReader(handle, delimiter="\t")}
            self.assertEqual(values["5mC"]["valid_call_denominator"], "40")
            self.assertEqual(values["5hmC"]["valid_call_denominator"], "40")
            self.assertEqual(float(values["5mC"]["percent_of_valid_calls"]), 22.5)
            self.assertEqual(float(values["5hmC"]["percent_of_valid_calls"]), 20)
            # Missing paired calls must fail rather than silently merging channels.
            bed.write_text("\t".join(map(str, rows[0])) + "\n")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("only one modification row", result.stderr)
