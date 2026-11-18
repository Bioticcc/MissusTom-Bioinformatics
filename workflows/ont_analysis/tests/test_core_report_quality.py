"""Content/scope regression checks for descriptive ONT reports, using real R."""

import csv
import json
import os
import runpy
import shlex
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import test_feature_modes as fixtures

ROOT = Path(__file__).parents[1]


def report_rscript(test):
    """Return an R able to build the core report, or skip the calling test."""
    rscript = os.environ.get("ONT_TEST_RSCRIPT") or shutil.which("Rscript")
    if not rscript:
        test.skipTest("Rscript unavailable")
    probe = subprocess.run(
        [
            rscript,
            "--vanilla",
            "-e",
            'quit(status=!all(vapply(c("data.table", "ggplot2"), requireNamespace, '
            "logical(1), quietly=TRUE)))",
        ],
        capture_output=True,
        check=False,
    )
    if probe.returncode:
        test.skipTest("Core report R packages unavailable")
    return rscript


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        self.paths.extend(
            value
            for key, value in attrs
            if key in {"src", "href"} and value and not value.startswith("#")
        )


class CoreReportQualityTests(unittest.TestCase):
    def test_measured_modes_keep_primary_scope_metrics_and_all_report_links(self):
        rscript = report_rscript(self)
        for mode, species, primary in (
            ("5mc_only", "Homo sapiens", 22),
            ("5mc_5hmc", "Mus musculus", 19),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paths = fixtures.FeatureModeTests().make_inputs(root, mode)
                output = root / "report"
                workflow_log = root / "workflow.log"
                workflow_log.write_text(
                    "RUN SAMPLE: sample<&>\n> ~7 failed processing\nRUN SAMPLE: other\n> ~900 failed processing\n"
                )
                # Counts above signed 32-bit must remain ordinary readable integers.
                paths["coverage-summary"].write_text(
                    "metric\tvalue\nmean_depth\t0.14\npct_ge_1x\t12.6\nzero_coverage_bases\t2709240968\npct_zero_coverage\t87.4\n"
                )
                command = [
                    rscript,
                    "--vanilla",
                    str(ROOT / "lib/core_methylation_qc.R"),
                    "--sample-id",
                    "sample<&>",
                    "--organism",
                    species,
                    "--reference-name",
                    "test",
                    "--main-chromosomes",
                    ",".join(f"chr{i}" for i in range(1, primary + 1)),
                    "--modification-mode",
                    mode,
                    "--output-dir",
                    str(output),
                ]
                for key in (
                    "global-levels",
                    "chromosome-methylation",
                    "chromosome-coverage",
                    "coverage-summary",
                    "call-coverage",
                    "alignment-flagstat",
                ):
                    command.extend(["--" + key, str(paths[key])])
                command.extend(["--workflow-log", str(workflow_log)])
                result = subprocess.run(
                    command, capture_output=True, text=True, check=False, timeout=45
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                report = (output / "ont_methylation_qc_report.html").read_text()
                for expected in (
                    "QC summary",
                    "Reference-wide sequencing coverage",
                    "CpG modification-call accounting",
                    "2,709,240,968",
                    "sample&lt;&amp;&gt;",
                    "approximate, not unique reads",
                ):
                    self.assertIn(expected, report)
                self.assertEqual(report.count('<img src="previews/'), 4)
                self.assertIn("approximate, not unique reads)</th><td>7</td>", report)
                self.assertNotIn(">900</td>", report)
                if mode == "5mc_only":
                    self.assertIn("5hmC not measured", report)
                    self.assertIn("Not measured", report)
                with (
                    output / "tables/primary_chromosome_methylation.tsv"
                ).open() as handle:
                    main = list(csv.DictReader(handle, delimiter="\t"))
                with (
                    output / "tables/additional_contig_methylation.tsv"
                ).open() as handle:
                    extra = list(csv.DictReader(handle, delimiter="\t"))
                self.assertEqual(len(main), primary)
                self.assertEqual(len(main) + len(extra), 22)
                parser = Links()
                parser.feed(report)
                for link in parser.paths:
                    self.assertTrue((output / link).is_file(), link)
                self.assertTrue((output / "report_input_checksums.tsv").stat().st_size)

    def test_project_overview_uses_only_manifest_included_samples(self):
        build = runpy.run_path(str(ROOT / "lib/build_qc_overview.py"))["build"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "results"
            sample = results / "samples/A"
            for stage in (
                "03_ont_qc_coverage",
                "04_methylation",
                "05_methylation_exploration",
            ):
                (sample / stage).mkdir(parents=True)
            (sample / "03_ont_qc_coverage/coverage_summary.tsv").write_text(
                "metric\tvalue\nmean_depth\t0.14\npct_ge_1x\t12.6\npct_ge_10x\t0.1\npct_zero_coverage\t87.4\n"
            )
            (sample / "04_methylation/global_methylation_levels.tsv").write_text(
                "category\tmodification_mode\tvalid_call_denominator\tpercent_of_valid_calls\n5mC\t5mc_only\t100\t69\n5hmC\t5mc_only\tNA\tNA\n"
            )
            (
                sample / "05_methylation_exploration/ont_methylation_qc_report.html"
            ).write_text("report")
            (sample / "05_methylation_exploration/.stage05.complete").write_text(
                "complete"
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "organism": "Homo sapiens",
                        "reference_genome": "hg38",
                        "samples": [
                            {"sample_id": "A", "included": True},
                            {"sample_id": "excluded", "included": False},
                        ],
                    }
                )
            )
            build(manifest, results)
            report = (results / "project_qc/ont_project_qc_report.html").read_text()
            self.assertIn("1 included sample", report)
            self.assertIn("69.00%", report)
            self.assertIn("Not measured", report)
            parser = Links()
            parser.feed(report)
            for link in parser.paths:
                self.assertTrue((results / "project_qc" / link).is_file())

    def test_stage05_publishes_report_previews_and_reuses_complete_output(self):
        rscript = report_rscript(self)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = fixtures.FeatureModeTests().make_inputs(root, "5mc_only")
            output = root / "sample"
            s03 = output / "03_ont_qc_coverage"
            s04 = output / "04_methylation"
            s02 = output / "02_alignment_qc"
            for directory in (s03, s04, s02):
                directory.mkdir(parents=True)
            for key, target in (
                ("chromosome-coverage", s03 / "chromosome_coverage.tsv"),
                ("coverage-summary", s03 / "coverage_summary.tsv"),
                ("alignment-flagstat", s03 / "alignment_flagstat.txt"),
                ("alignment-stats", s03 / "alignment_stats.txt"),
                ("global-levels", s04 / "global_methylation_levels.tsv"),
                ("chromosome-methylation", s04 / "chromosome_methylation_levels.tsv"),
                ("call-coverage", s04 / "methylation_call_coverage.tsv"),
            ):
                shutil.copyfile(paths[key], target)
            for directory, stage in ((s03, "03"), (s04, "04")):
                (directory / f".stage{stage}.complete").write_text("complete\n")
            (s02 / "synthetic.alignment_summary.txt").write_text("alignment summary\n")
            (s04 / "modkit_all_context_summary.txt").write_text(
                "mod_bases\tC\ntotal_reads_used\t10\n"
            )
            settings = root / "settings.env"
            settings.write_text("settings\n")
            config = root / "project.env"
            values = {
                "SAMPLE_OUTPUT": str(output),
                "SAMPLE_ID": "synthetic",
                "WORKFLOW_ROOT": str(ROOT),
                "RSCRIPT_BIN": rscript,
                "MODIFICATION_MODE": "5mc_only",
                "ANNOTATION_EXPLORATION_ENABLED": "0",
                "PIPELINE_SETTINGS_FILE": str(settings),
                "ONT_INSTRUMENT_REPORT": "",
                "ORGANISM": "Homo sapiens",
                "MAIN_CHROMOSOMES": ",".join(f"chr{i}" for i in range(1, 23)),
                "REFERENCE_NAME": "hg38",
            }
            config.write_text(
                "\n".join(
                    f"{key}={shlex.quote(value)}" for key, value in values.items()
                )
            )
            command = ["bash", str(ROOT / "stages/05_methylation_exploration.sh")]
            first = subprocess.run(
                command,
                env=os.environ | {"PIPELINE_ENV": str(config)},
                capture_output=True,
                text=True,
                check=False,
                timeout=45,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            report = output / "05_methylation_exploration"
            self.assertEqual(len(list((report / "previews").glob("*.png"))), 4)
            self.assertTrue((report / "report_input_checksums.tsv").is_file())
            second = subprocess.run(
                command,
                env=os.environ | {"PIPELINE_ENV": str(config)},
                capture_output=True,
                text=True,
                check=False,
                timeout=45,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("SKIP: current Stage 05 result", second.stdout)
