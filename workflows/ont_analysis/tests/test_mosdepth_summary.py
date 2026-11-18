"""Reference-complete coverage and strict rejection of incomplete Mosdepth output."""

import csv
import gzip
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "lib/summarize_mosdepth.py"


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.files = {
            "fai": "chrBefore\t10\nchr1\t20\nchrAfter\t30\n",
            "alignment-idxstats": (
                "chrBefore\t10\t0\t0\nchr1\t20\t1\t0\nchrAfter\t30\t0\t0\n*\t0\t0\t0\n"
            ),
            "per-base": "chr1\t0\t10\t1\nchr1\t10\t20\t0\n",
            "mosdepth-summary": (
                "chrom\tlength\tbases\tmean\tmin\tmax\n"
                "chr1\t20\t10\t0.500000\t0\t1\n"
                "total\t20\t10\t0.500000\t0\t1\n"
            ),
        }
        regions = []
        thresholds = []
        for name, size in (("chrBefore", 10), ("chr1", 20), ("chrAfter", 30)):
            for start in range(0, size, 10):
                covered = name == "chr1" and start == 0
                regions.append(f"{name}\t{start}\t{start + 10}\t{1 if covered else 0}.000000\n")
                thresholds.append(
                    f"{name}\t{start}\t{start + 10}\tunknown\t{10 if covered else 0}\t0\t0\t0\n"
                )
        self.files["regions"] = "".join(regions)
        self.files["thresholds-bed"] = "".join(thresholds)

    def run_summary(self, omit_idxstats=False):
        command = [sys.executable, str(SCRIPT)]
        for key, content in self.files.items():
            if omit_idxstats and key == "alignment-idxstats":
                continue
            path = self.root / f"{key}.tsv"
            path.write_text(content)
            command.extend([f"--{key}", str(path)])
        for name in ("coverage-summary", "chromosome", "window", "low-interval"):
            command.extend([f"--{name}-out", str(self.root / f"{name}.tsv")])
        command.extend(
            [
                "--thresholds",
                "1,5,10,20",
                "--window-size",
                "10",
                "--low-depth-threshold",
                "5",
                "--low-window-min-1x-breadth",
                "80",
                "--exclude-flags",
                "1796",
                "--min-mapq",
                "0",
                "--per-base-out",
                "-",
            ]
        )
        return subprocess.run(command, capture_output=True, text=True, timeout=10)

    def metrics(self):
        with (self.root / "coverage-summary.tsv").open() as handle:
            return {r["metric"]: r["value"] for r in csv.DictReader(handle, delimiter="\t")}

    def test_whole_zero_read_contigs_are_included_in_tracks_and_denominators(self):
        result = self.run_summary()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "chrBefore\t0\t10\t0\nchr1\t0\t10\t1\nchr1\t10\t20\t0\nchrAfter\t0\t30\t0\n",
        )
        metrics = self.metrics()
        self.assertEqual(metrics["reference_bases"], "60")
        self.assertEqual(metrics["zero_coverage_bases"], "50")
        self.assertEqual(metrics["bases_ge_1x"], "10")
        self.assertEqual(metrics["pct_ge_1x"], "16.666667")
        self.assertEqual(metrics["mean_depth"], "0.166667")
        self.assertEqual(metrics["mosdepth_raw_summary_reference_bases"], "20")
        self.assertEqual(metrics["zero_alignment_contigs_padded"], "2")
        self.assertEqual(metrics["zero_alignment_bases_padded"], "40")
        self.assertEqual(metrics["zero_alignment_summaries_completed"], "2")
        with (self.root / "chromosome.tsv").open() as handle:
            rows = {r["chrom"]: r for r in csv.DictReader(handle, delimiter="\t")}
        self.assertEqual(rows["chrBefore"]["mean_depth"], "0.000000")
        self.assertEqual(rows["chrAfter"]["pct_ge_1x"], "0.000000")

    def test_full_existing_tracks_work_without_idxstats(self):
        self.files["per-base"] = (
            "chrBefore\t0\t10\t0\n" + self.files["per-base"] + "chrAfter\t0\t30\t0\n"
        )
        self.files["mosdepth-summary"] = (
            "chrom\tlength\tbases\tmean\tmin\tmax\nchrBefore\t10\t0\t0\t0\t0\n"
            "chr1\t20\t10\t0.5\t0\t1\nchrAfter\t30\t0\t0\t0\t0\n"
            "total\t60\t10\t0.166667\t0\t1\n"
        )
        result = self.run_summary(omit_idxstats=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.metrics()["zero_alignment_contigs_padded"], "0")

    def test_omitted_contigs_require_zero_alignment_and_window_evidence(self):
        scenarios = [
            ("no_idxstats", None),
            (
                "alignment-idxstats",
                self.files["alignment-idxstats"].replace("chrAfter\t30\t0", "chrAfter\t30\t1"),
            ),
            (
                "regions",
                self.files["regions"].replace(
                    "chrAfter\t0\t10\t0.000000", "chrAfter\t0\t10\t0.100000"
                ),
            ),
            (
                "thresholds-bed",
                self.files["thresholds-bed"].replace(
                    "chrAfter\t0\t10\tunknown\t0", "chrAfter\t0\t10\tunknown\t1"
                ),
            ),
        ]
        for key, value in scenarios:
            with self.subTest(key=key):
                original = self.files.get(key)
                if value is not None:
                    self.files[key] = value
                result = self.run_summary(omit_idxstats=key == "no_idxstats")
                self.assertNotEqual(result.returncode, 0)
                if value is not None:
                    self.files[key] = original

    def test_partial_contigs_gaps_and_mismatched_totals_still_fail(self):
        scenarios = [
            ("per-base", self.files["per-base"] + "chrAfter\t0\t10\t0\n"),
            ("per-base", self.files["per-base"].replace("chr1\t10\t20", "chr1\t11\t20")),
            ("per-base", self.files["per-base"].replace("chr1\t10\t20\t0\n", "")),
            ("per-base", "chrAfter\t0\t30\t0\n" + self.files["per-base"]),
            ("mosdepth-summary", self.files["mosdepth-summary"].replace("total\t20", "total\t21")),
            (
                "mosdepth-summary",
                self.files["mosdepth-summary"].replace("total\t20\t10", "total\t20\t11"),
            ),
            ("mosdepth-summary", self.files["mosdepth-summary"].replace("0.500000", "0.600000")),
            (
                "alignment-idxstats",
                self.files["alignment-idxstats"].replace("chrAfter\t30", "chrAfter\t31"),
            ),
        ]
        for key, value in scenarios:
            with self.subTest(key=key, value=value):
                original = self.files[key]
                self.files[key] = value
                self.assertNotEqual(self.run_summary().returncode, 0)
                self.files[key] = original


class NativeStageTests(unittest.TestCase):
    def test_real_mosdepth_zero_contigs_publish_complete_indexed_tracks(self):
        tools = {
            name: os.environ.get(f"ONT_TEST_{name.upper()}") or shutil.which(name)
            for name in ("samtools", "mosdepth", "bgzip", "tabix")
        }
        if not all(tools.values()):
            self.skipTest("Native coverage tools unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fasta = root / "reference.fa"
            fasta.write_text(
                ">chrBefore\n"
                + "C" * 10
                + "\n>chr1\n"
                + "CG" * 10
                + "\n>chrAfter\n"
                + "C" * 30
                + "\n"
            )
            subprocess.run(
                [tools["samtools"], "faidx", str(fasta)], check=True, capture_output=True
            )
            align = root / "results/02_alignment_qc/sample.aligned.sorted.bam"
            align.parent.mkdir(parents=True)
            sam = (
                "@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chrBefore\tLN:10\n"
                "@SQ\tSN:chr1\tLN:20\n@SQ\tSN:chrAfter\tLN:30\n"
                "r\t0\tchr1\t1\t60\t10M\t*\t0\t0\tCGCGCGCGCG\tIIIIIIIIII"
                "\tMM:Z:C+m,0;\tML:B:C,204\tMN:i:10\n"
            )
            subprocess.run(
                [tools["samtools"], "view", "-b", "-o", str(align), "-"],
                input=sam,
                text=True,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                [tools["samtools"], "index", str(align)], check=True, capture_output=True
            )
            settings = root / "settings.env"
            settings.write_text("synthetic\n")
            defaults = runpy.run_path(str(ROOT / "run_pipeline.py"))["DEFAULTS"]
            values = {
                key.upper(): 1 if key.endswith("threads") else value
                for key, value in defaults.items()
            }
            values.update({name.upper() + "_BIN": path for name, path in tools.items()})
            values.update(
                SAMPLE_OUTPUT=align.parents[1],
                SAMPLE_ID="sample",
                WORKFLOW_ROOT=ROOT,
                REFERENCE_FAI=Path(str(fasta) + ".fai"),
                PIPELINE_SETTINGS_FILE=settings,
                COVERAGE_WINDOW_SIZE=10,
            )
            config = root / "project.env"
            config.write_text("\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n")
            command = ["bash", str(ROOT / "stages/03_ont_qc_and_coverage.sh")]
            env = os.environ | {"PIPELINE_ENV": str(config)}
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            out = root / "results/03_ont_qc_coverage"
            with gzip.open(out / "per_base_coverage.bed.gz", "rt") as handle:
                track = handle.read()
            self.assertIn("chrBefore\t0\t10\t0\n", track)
            self.assertIn("chrAfter\t0\t30\t0\n", track)
            indexed = subprocess.run(
                [tools["tabix"], "-l", str(out / "per_base_coverage.bed.gz")],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()
            self.assertEqual(indexed, ["chrBefore", "chr1", "chrAfter"])
            with (out / "coverage_summary.tsv").open() as handle:
                metrics = {r["metric"]: r["value"] for r in csv.DictReader(handle, delimiter="\t")}
            self.assertEqual(metrics["reference_bases"], "60")
            self.assertEqual(metrics["mean_depth"], "0.166667")
            self.assertTrue((out / "mosdepth.raw.per-base.bed.gz.csi").is_file())
            again = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertIn("SKIP: current Stage 03 result", again.stdout)
