"""Synthetic contracts only: no user matrices, package installs or network access."""

from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("singlecell_runner", ROOT / "run_pipeline.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def matrix(directory: Path, values=(1, 2, 3)) -> None:
    directory.mkdir(parents=True)
    contents = {
        "features.tsv.gz": "ENSMT1\tmt-gene\tGene Expression\nENSG2\tGene2\tGene Expression\n",
        "barcodes.tsv.gz": "AA-1\nBB-1\nCC-1\n",
        "matrix.mtx.gz": "%%MatrixMarket matrix coordinate integer general\n% fixture\n2 3 3\n"
        + f"1 1 {values[0]}\n2 2 {values[1]}\n2 3 {values[2]}\n",
    }
    for name, content in contents.items():
        with gzip.open(directory / name, "wt") as handle:
            handle.write(content)


class InputContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="singlecell-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        matrix(self.root / "library1" / "filtered_feature_bc_matrix")
        self.data = {
            "schema_version": "singlecell-counts-v1",
            "reference": {
                "species": "test species",
                "genome_build": "test build+annotation",
                "mitochondrial_gene_ids": ["ENSMT1"],
            },
            "samples": [
                {
                    "sample_id": "sample-1",
                    "donor_id": "donor-1",
                    "condition": "ctrl",
                    "batch": "batch-1",
                    "matrix_dir": "library1/filtered_feature_bc_matrix",
                    "matrix_kind": "filtered",
                    "qc": {
                        "min_counts": 1,
                        "min_features": 1,
                        "max_features": 2,
                        "max_mito_percent": 100,
                    },
                }
            ],
            "analysis": {
                "normalization": "log_normalize",
                "integration": "none",
                "variable_features": 20,
                "pcs": 2,
                "resolution": 0.5,
                "seed": 42,
                "cluster_markers": True,
            },
        }
        self.path = self.root / "manifest.json"

    def load(self):
        self.path.write_text(json.dumps(self.data))
        return runner.load_manifest(self.path)

    def test_valid_relative_paths_and_explicit_biology(self):
        data = self.load()
        self.assertEqual(data["samples"][0]["staged_dir"], "matrix0001")
        self.assertTrue(Path(data["samples"][0]["matrix_dir"]).is_absolute())
        self.assertEqual(data["samples"][0]["condition"], "ctrl")

    def test_unknown_fields_and_invalid_nested_types(self):
        for field, value in (
            ("unexpected", 1),
            ("reference", []),
            ("analysis", None),
            ("samples", {}),
        ):
            original = copy.deepcopy(self.data)
            self.data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load()
            self.data = original

    def test_raw_droplets_rejected(self):
        self.data["samples"][0]["matrix_kind"] = "raw"
        with self.assertRaisesRegex(ValueError, "cell-calling"):
            self.load()

    def test_missing_mito_ids_rejected(self):
        for ids in ([], ["not-in-matrix"], ["ENSMT1", "ENSMT1"]):
            self.data["reference"]["mitochondrial_gene_ids"] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.load()

    def test_duplicate_sample_or_input_rejected(self):
        self.data["samples"].append(copy.deepcopy(self.data["samples"][0]))
        with self.assertRaisesRegex(ValueError, "sample_id"):
            self.load()
        self.data["samples"][1]["sample_id"] = "sample-2"
        with self.assertRaisesRegex(ValueError, "same matrix"):
            self.load()

    def test_bad_numeric_and_bool_values(self):
        for value in (True, -1, 101, float("nan"), "20"):
            self.data["samples"][0]["qc"]["max_mito_percent"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()

    def test_reversed_feature_cutoffs(self):
        self.data["samples"][0]["qc"]["min_features"] = 3
        with self.assertRaisesRegex(ValueError, "max_features"):
            self.load()

    def test_no_unsupported_methods_or_implicit_metadata(self):
        self.data["analysis"]["integration"] = "harmony"
        with self.assertRaisesRegex(ValueError, "integration=none"):
            self.load()
        self.data["analysis"]["integration"] = "none"
        del self.data["samples"][0]["donor_id"]
        with self.assertRaisesRegex(ValueError, "donor_id"):
            self.load()

    def test_dimension_and_multimodal_rejection(self):
        directory = self.root / "library1/filtered_feature_bc_matrix"
        with gzip.open(directory / "barcodes.tsv.gz", "wt") as handle:
            handle.write("AA-1\nBB-1\n")
        with self.assertRaisesRegex(ValueError, "dimensions"):
            self.load()
        with gzip.open(directory / "features.tsv.gz", "wt") as handle:
            handle.write("ENSMT1\tmt\tAntibody Capture\n")
        with self.assertRaisesRegex(ValueError, "Gene Expression"):
            self.load()

    def test_feature_order_must_match(self):
        second = copy.deepcopy(self.data["samples"][0])
        second.update(sample_id="sample-2", matrix_dir="library2/filtered_feature_bc_matrix")
        directory = self.root / second["matrix_dir"]
        matrix(directory)
        with gzip.open(directory / "features.tsv.gz", "wt") as handle:
            handle.write("ENSG2\tGene2\tGene Expression\nENSMT1\tmt-gene\tGene Expression\n")
        self.data["samples"].append(second)
        with self.assertRaisesRegex(ValueError, "identical ordered"):
            self.load()

    def test_check_only_has_no_execution_or_created_state(self):
        self.load()
        with (
            patch("sys.argv", ["runner", "--manifest", str(self.path), "--check-only"]),
            patch.object(runner.subprocess, "run") as run,
        ):
            self.assertEqual(runner.main(), 0)
            run.assert_not_called()

    def test_runner_preserves_existing_run_directory(self):
        self.load()
        run_dir = self.root / "existing-run"
        run_dir.mkdir()
        sentinel = run_dir / "keep.txt"
        sentinel.write_text("user work")
        with (
            patch("sys.argv", ["runner", "--manifest", str(self.path), "--run-dir", str(run_dir)]),
            patch.object(runner.shutil, "which", return_value="tool"),
            patch.object(runner.subprocess, "run"),
            self.assertRaises(SystemExit),
        ):
            runner.main()
        self.assertEqual(sentinel.read_text(), "user work")

    def test_runner_hashes_and_launches_fixed_argument_array(self):
        self.load()
        run_dir = self.root / "run with spaces"
        with (
            patch("sys.argv", ["runner", "--manifest", str(self.path), "--run-dir", str(run_dir)]),
            patch.object(runner.shutil, "which", return_value="tool"),
            patch.object(runner.subprocess, "run") as run,
            patch.object(runner, "verify_outputs") as verify,
        ):
            self.assertEqual(runner.main(), 0)
        prepared = json.loads((run_dir / "input_manifest/prepared_manifest.json").read_text())
        self.assertEqual(len(prepared["provenance"]["sha256"]), 10)
        command = run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertIn(str(run_dir / "work"), command)
        self.assertIn("-offline", command)
        self.assertEqual(run.call_args.kwargs["cwd"], run_dir)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["env"]["NXF_OFFLINE"], "true")
        verify.assert_called_once_with(run_dir, markers=True)

    def test_incomplete_outputs_cannot_report_success(self):
        run_dir = self.root / "incomplete"
        (run_dir / "results/objects").mkdir(parents=True)
        (run_dir / "results/objects/singlecell.rds").touch()
        with self.assertRaisesRegex(ValueError, "objects/singlecell.rds"):
            runner.verify_outputs(run_dir, markers=True)

    @unittest.skipUnless(
        os.environ.get("SINGLECELL_TEST_SEURAT") == "1", "opt-in isolated Seurat runtime"
    )
    def test_full_seurat_analysis_preserves_counts_and_metadata(self):
        # Synthetic two-population libraries, with known integer counts and cell IDs.
        # Run only after activating the isolated candidate environment.
        expected_total = 0
        for index in (1, 2):
            directory = self.root / f"library{index}/filtered_feature_bc_matrix"
            if directory.exists():
                shutil.rmtree(directory)
            directory.mkdir(parents=True)
            genes = ["ENSMT1"] + [f"ENSG{gene:04d}" for gene in range(1, 100)]
            entries = []
            for cell in range(60):
                for gene in range(100):
                    count = 1 + (gene * 13 + cell * 7 + index) % 11
                    count += 20 if (gene < 50) == (cell < 30) else 0
                    expected_total += count
                    entries.append(f"{gene + 1} {cell + 1} {count}\n")
            contents = {
                "features.tsv.gz": "".join(f"{gene}\tSymbol\tGene Expression\n" for gene in genes),
                "barcodes.tsv.gz": "".join(f"CELL{cell:03d}-1\n" for cell in range(60)),
                "matrix.mtx.gz": "%%MatrixMarket matrix coordinate integer general\n"
                + f"100 60 {len(entries)}\n"
                + "".join(entries),
            }
            for name, content in contents.items():
                with gzip.open(directory / name, "wt") as handle:
                    handle.write(content)
        second = copy.deepcopy(self.data["samples"][0])
        second.update(
            sample_id="sample-2",
            donor_id="donor-2",
            condition="stim",
            matrix_dir="library2/filtered_feature_bc_matrix",
        )
        self.data["samples"].append(second)
        for sample in self.data["samples"]:
            sample["qc"]["max_features"] = 100
        self.load()
        run_dir = self.root / "full-scientific-run"
        result = subprocess.run(
            [
                "python3",
                str(ROOT / "run_pipeline.py"),
                "--manifest",
                str(self.path),
                "--run-dir",
                str(run_dir),
                "--cpus",
                "1",
                "--memory-gb",
                "2",
            ],
            timeout=180,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        assertion = self.root / "assert_object.R"
        assertion.write_text("""
args <- commandArgs(TRUE)
suppressPackageStartupMessages(library(Seurat))
object <- readRDS(args[1])
counts <- LayerData(object, assay="RNA", layer="counts")
stopifnot(inherits(counts, "sparseMatrix"), sum(counts) == as.numeric(args[2]),
          ncol(counts) == 120L, nrow(counts) == 100L,
          identical(rownames(counts)[1], "ENSMT1"),
          all(table(object$sample_id) == 60L),
          setequal(object$donor_id, c("donor-1", "donor-2")),
          ncol(Embeddings(object, "pca")) == 2L,
          ncol(Embeddings(object, "umap")) == 2L,
          length(unique(colnames(object))) == 120L)
""")
        result = subprocess.run(
            [
                "Rscript",
                "--vanilla",
                str(assertion),
                str(run_dir / "results/objects/singlecell.rds"),
                str(expected_total),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("Rscript"), "Rscript not installed")
    def test_real_sparse_import_qc_and_count_rejection(self):
        self.load()
        script = self.root / "test_import.R"
        script.write_text("""
args <- commandArgs(TRUE)
source(args[1])
data <- read_count_matrix(args[2])
stopifnot(inherits(data$counts, "sparseMatrix"))
qc <- cell_qc(data$counts, "ENSMT1", list(min_counts=1, min_features=1,
    max_features=2, max_mito_percent=0))
stopifnot(identical(qc$retained, c(FALSE, TRUE, TRUE)),
          identical(qc$mito_percent, c(100, 0, 0)), identical(qc$n_counts, c(1, 2, 3)))
boundary <- cell_qc(data$counts, "ENSMT1", list(min_counts=2, min_features=1,
    max_features=1, max_mito_percent=0))
stopifnot(identical(boundary$retained, c(FALSE, TRUE, TRUE)))
data$counts[, 1] <- 0
zero <- cell_qc(data$counts, "ENSMT1", list(min_counts=1, min_features=1,
    max_features=2, max_mito_percent=100))
stopifnot(!zero$retained[1], is.nan(zero$mito_percent[1]))
""")
        directory = self.root / "library1/filtered_feature_bc_matrix"
        result = subprocess.run(
            ["Rscript", "--vanilla", str(script), str(ROOT / "bin/import_qc.R"), str(directory)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rejection = self.root / "reject.R"
        rejection.write_text("""
args <- commandArgs(TRUE)
source(args[1])
stopifnot(inherits(try(read_count_matrix(args[2]), silent=TRUE), "try-error"))
""")
        for value in (-1, 0.5, "NaN"):
            shutil.rmtree(directory)
            matrix(directory, values=(value, 2, 3))
            result = subprocess.run(
                [
                    "Rscript",
                    "--vanilla",
                    str(rejection),
                    str(ROOT / "bin/import_qc.R"),
                    str(directory),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(
        os.environ.get("SINGLECELL_TEST_NEXTFLOW") == "1", "opt-in Nextflow staging"
    )
    def test_real_nextflow_stages_one_and_multiple_directories(self):
        # Substitute only R execution; exercise the actual graph, staging and publication.
        # This is an orchestration test, NOT a successful Seurat scientific analysis.
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake_r = fake_bin / "Rscript"
        fake_r.write_text("""#!/usr/bin/env python3
import json
from pathlib import Path
data = json.loads(Path("prepared_manifest.json").read_text())
for sample in data["samples"]:
    directory = Path(sample["staged_dir"])
    assert directory.is_dir(), str(directory)
    assert (directory / "matrix.mtx.gz").is_file()
assert Path("import_qc.R").is_file()
for name in ("qc", "tables", "figures", "objects"):
    Path(name).mkdir()
    Path(name, "staging-only.txt").write_text("not scientific results")
""")
        fake_r.chmod(0o755)
        for size in (1, 2):
            if size == 2:
                matrix(self.root / "library2/filtered_feature_bc_matrix")
                second = copy.deepcopy(self.data["samples"][0])
                second.update(
                    sample_id="sample-2", matrix_dir="library2/filtered_feature_bc_matrix"
                )
                self.data["samples"].append(second)
            data = self.load()
            prepared = self.root / f"prepared{size}.json"
            prepared.write_text(json.dumps(data))
            run_dir = self.root / f"staging{size}"
            run_dir.mkdir()
            command = [
                "nextflow",
                "run",
                str(ROOT / "main.nf"),
                "-offline",
                "-profile",
                "local",
                "--prepared_manifest",
                str(prepared),
                "--outdir",
                str(run_dir / "results"),
                "--max_cpus",
                "1",
                "--max_memory_gb",
                "1",
            ]
            result = subprocess.run(
                command,
                cwd=run_dir,
                timeout=90,
                capture_output=True,
                text=True,
                env={**os.environ, "PATH": str(fake_bin) + ":" + os.environ["PATH"]},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((run_dir / "results/qc/staging-only.txt").is_file())


if __name__ == "__main__":
    unittest.main()
