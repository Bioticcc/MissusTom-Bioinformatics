import csv
"""Synthetic species/reference, runner configuration, and R chromosome regressions."""
import json
import os
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
runner = runpy.run_path(str(ROOT / "run_pipeline.py"))


class ReferenceProfileTests(unittest.TestCase):
    def test_runner_preserves_species_and_all_autosomes_and_invalidates_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            bam = inputs / "sample.bam"
            bam.write_text("synthetic")
            resources = {}
            for name in ("reference_fasta", "reference_fai", "minimap2_index"):
                path = root / name
                path.write_text("synthetic")
                resources[name] = str(path)
            previous = None
            for organism, reference, count in (
                ("Mus musculus", "GRCm38p6", 19), ("Homo sapiens", "GRCh38", 22),
                ("Mus musculus", "GRCm39", 19), ("Homo sapiens", "hg38", 22),
            ):
                Path(resources["reference_fai"]).write_text(
                    "".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, count + 1))
                )
                manifest = {
                    "schema_version": "1.0.0", "pipeline_identifier": "ont-analysis",
                    "pipeline_version": "0.1.0", "organism": organism,
                    "reference_genome": reference, "execution_profile": "local",
                    "input_directory": str(inputs), "reference_resources": resources,
                    "resource_profile": {"cpus": 1, "memory_gb": 2}, "comparisons": [],
                    "samples": [{"sample_id": "sample", "included": True,
                                 "ont_bam_files": [str(bam)]}],
                }
                manifest_path = root / "manifest.json"
                manifest_path.write_text(json.dumps(manifest))
                with patch.dict(runner["load_manifest"].__globals__, path_tool=lambda _: "/bin/true"):
                    values = runner["load_manifest"](manifest_path, root / "results", "test")
                chromosomes = values["MAIN_CHROMOSOMES"].split(",")
                self.assertEqual(values["ORGANISM"], organism)
                self.assertEqual(len(chromosomes), count)
                self.assertEqual(chromosomes[-1], f"chr{count}")
                runner["write_config"](values, root / "results")
                settings = Path(values["PIPELINE_SETTINGS_FILE"]).read_text()
                self.assertNotEqual(settings, previous)
                previous = settings
                manifest["organism"] = "Danio rerio"
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(runner["ManifestError"], "Unsupported ONT"):
                    runner["load_manifest"](manifest_path, root / "results", "test")


class CoreReportTests(unittest.TestCase):
    def test_feature_analysis_uses_selected_chromosomes_for_human_and_mouse(self):
        rscript = os.environ.get("ONT_TEST_RSCRIPT") or shutil.which("Rscript")
        if not rscript:
            self.skipTest("Rscript is unavailable")
        probe = subprocess.run([rscript, "--vanilla", "-e",
            'quit(status=if(requireNamespace("data.table", quietly=TRUE)) 0 else 1)'],
            capture_output=True, text=True)
        if probe.returncode:
            self.skipTest("data.table is unavailable")
        source = (ROOT / "lib/methylation_exploration.R").read_text()
        # Execute the feature script's actual chromosome-selection block with tiny FAIs.
        block = source[source.index("chromosome_order <-"):source.index("global_levels <-")]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for count, prefix in ((22, "chr"), (22, ""), (19, "chr")):
                names = [f"{prefix}{i}" for i in range(1, count + 1)]
                fai = root / "reference.fai"
                fai.write_text("".join(f"{name}\t100\t0\t100\t101\n" for name in names))
                script = root / "check.R"
                script.write_text(
                    'library(data.table)\nopt <- list("main-chromosomes" = '
                    + json.dumps(",".join(names)) + ', "fai" = ' + json.dumps(str(fai)) + ')\n'
                    + block + '\nstopifnot(nrow(fai) == ' + str(count)
                    + ', tail(fai$chrom, 1) == ' + json.dumps(names[-1])
                    + ', is_main_chromosome(' + json.dumps(names[-1]) + '))\n'
                )
                result = subprocess.run([rscript, "--vanilla", str(script)],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_human_and_mouse_reports_keep_species_and_last_autosome(self):
        rscript = os.environ.get("ONT_TEST_RSCRIPT") or shutil.which("Rscript")
        if not rscript:
            self.skipTest("Rscript is unavailable")
        probe = subprocess.run([rscript, "--vanilla", "-e",
            'quit(status=if(all(vapply(c("data.table","ggplot2"), requireNamespace, '
            'logical(1), quietly=TRUE))) 0 else 1)'], capture_output=True, text=True)
        if probe.returncode:
            self.skipTest("Core R plotting packages are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for organism, reference, count, prefix in (
                ("Homo sapiens", "GRCh38", 22, "chr"),
                ("Mus musculus", "GRCm38p6", 19, ""),
            ):
                names = [f"{prefix}{i}" for i in range(1, count + 1)]
                tables = {
                    "global-levels": "category\tpercent_of_valid_calls\tcall_count\tvalid_call_denominator\ncanonical_C\t70\t70\t100\n5mC\t20\t20\t100\n5hmC\t10\t10\t100\ntotal_modified\t30\t30\t100\n",
                    "chromosome-methylation": "chrom\tpercent_5mc\n" + "".join(f"{name}\t20\n" for name in names),
                    "chromosome-coverage": "chrom\tmean_depth\n" + "".join(f"{name}\t10\n" for name in names),
                    "coverage-summary": "metric\tvalue\nmean_depth\t10\n",
                }
                command = [rscript, "--vanilla", str(ROOT / "lib/core_methylation_qc.R"),
                    "--sample-id", "synthetic", "--reference-name", reference,
                    "--organism", organism, "--main-chromosomes", ",".join(names),
                    "--output-dir", str(root / reference)]
                for key, content in tables.items():
                    path = root / f"{key}.tsv"
                    path.write_text(content)
                    command.extend([f"--{key}", str(path)])
                result = subprocess.run(command, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = root / reference
                self.assertIn(organism, (report / "methylation_exploration_report.txt").read_text())
                self.assertIn(organism, (report / "ont_methylation_qc_report.html").read_text())
                data = (report / "tables/chromosome_methylation_plot_data.tsv").read_text()
                rows = list(csv.DictReader(data.splitlines(), delimiter="\t"))
                self.assertIn({"chrom": f"{prefix}{count}", "percent_5mc": "20"}, rows)
                self.assertEqual(len(list((report / "figures").glob("*.pdf"))), 4)
