"""Small real-tool check of legacy-tag input through the 5mC-only Stage 04."""

import csv
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class NativeFiveMcTests(unittest.TestCase):
    def test_legacy_bam_without_mn_produces_unmeasured_5hmc(self):
        for mode in ("5mc_only", "5mc_5hmc"):
            with self.subTest(mode=mode):
                self._check_mode(mode)

    def _check_mode(self, mode):
        tools = {
            name: os.environ.get(f"ONT_TEST_{name.upper()}") or shutil.which(name)
            for name in ("samtools", "modkit", "bgzip", "tabix")
        }
        if not all(tools.values()):
            self.skipTest("Native ONT tools unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fasta = root / "reference.fa"
            fasta.write_text(
                ">chr1\n" + "CG" * 10 + "\n>empty_cpg\nCGCG\n>no_cpg\nAAAA\n"
            )
            subprocess.run(
                [tools["samtools"], "faidx", str(fasta)],
                check=True,
                capture_output=True,
            )
            deltas = ",".join(["0"] * 10)
            mm = f"C+m,{deltas};" + (f"C+h,{deltas};" if mode == "5mc_5hmc" else "")
            probabilities = ",".join(
                ["204"] * 10 + (["26"] * 10 if mode == "5mc_5hmc" else [])
            )
            sam = "@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:20\n" + "".join(
                f"read{i}\t{flag}\tchr1\t1\t60\t20M\t*\t0\t0\t{'CG' * 10}\t{'I' * 20}"
                f"\tMm:Z:{mm}\tMl:B:C,{probabilities}\n"
                for i, flag in enumerate([0] * 10 + [2048, 256])
            )
            bam = subprocess.run(
                [tools["samtools"], "view", "-b", "-"],
                input=sam.encode(),
                capture_output=True,
                check=True,
            ).stdout
            output = root / "results"
            align = output / "02_alignment_qc/sample.aligned.sorted.bam"
            align.parent.mkdir(parents=True)
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "lib/normalize_modbam_tags.py"),
                    "--samtools",
                    tools["samtools"],
                    "--output",
                    str(align),
                ],
                input=bam,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [tools["samtools"], "index", str(align)],
                check=True,
                capture_output=True,
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
                SAMPLE_OUTPUT=output,
                SAMPLE_ID="sample",
                WORKFLOW_ROOT=ROOT,
                REFERENCE_FASTA=fasta,
                REFERENCE_FAI=Path(str(fasta) + ".fai"),
                MODIFICATION_MODE=mode,
                PIPELINE_SETTINGS_FILE=settings,
            )
            config = root / "project.env"
            config.write_text(
                "\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n"
            )
            result = subprocess.run(
                ["bash", str(ROOT / "stages/04_methylation_analysis.sh")],
                env=os.environ | {"PIPELINE_ENV": str(config)},
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            self.assertEqual(
                result.returncode, 0, result.stdout[-5000:] + result.stderr[-5000:]
            )
            with (
                output / "04_methylation/global_methylation_levels.tsv"
            ).open() as handle:
                rows = {
                    row["category"]: row
                    for row in csv.DictReader(handle, delimiter="\t")
                }
            self.assertEqual(rows["5mC"]["valid_call_denominator"], "100")
            with (
                output / "04_methylation/chromosome_methylation_levels.tsv"
            ).open() as handle:
                chromosomes = {
                    row["chrom"]: row for row in csv.DictReader(handle, delimiter="\t")
                }
            self.assertEqual(chromosomes["empty_cpg"]["reference_cpg_sites"], "2")
            self.assertEqual(chromosomes["empty_cpg"]["valid_calls"], "0")
            self.assertEqual(chromosomes["empty_cpg"]["pct_5mc_of_valid_calls"], "NA")
            self.assertEqual(chromosomes["no_cpg"]["reference_cpg_sites"], "0")
            if mode == "5mc_only":
                self.assertEqual(rows["5hmC"]["measurement_status"], "not_measured")
                self.assertEqual(rows["5hmC"]["call_count"], "NA")
                self.assertTrue((output / "04_methylation/cpg_5mc.bed.gz").is_file())
            else:
                self.assertEqual(rows["5hmC"]["measurement_status"], "measured")
                self.assertNotEqual(rows["5hmC"]["call_count"], "NA")
