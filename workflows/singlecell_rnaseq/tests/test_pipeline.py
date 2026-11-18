"""Synthetic contracts only: no user objects, package installs or network access."""

from __future__ import annotations

import copy
import gzip
import hashlib
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

# Two samples stored as split v5 layers, with two populations and an earlier analysis.
SEURAT_FIXTURE = r"""
suppressPackageStartupMessages(library(Seurat))
args <- commandArgs(TRUE)
genes <- c("MT-ND1", sprintf("GENE%03d", 1:99))
make_counts <- function(sample) {
    values <- outer(seq_len(100), seq_len(60), function(gene, cell) {
        1L + ((gene * 13L + cell * 7L + sample) %% 11L) +
            ifelse((gene <= 50L) == (cell <= 30L), 20L, 0L)
    })
    dimnames(values) <- list(genes, sprintf("S%d_CELL%03d", sample, seq_len(60)))
    Matrix::Matrix(values, sparse = TRUE)
}
counts <- cbind(make_counts(1L), make_counts(2L))
object <- CreateSeuratObject(counts, min.cells = 0, min.features = 0)
object$library <- rep(c("lib-1", "lib-2"), each = 60)
object$subject <- rep(c("donor-1", "donor-2"), each = 60)
object$group <- rep(c("ctrl", "stim"), each = 60)
object$run <- "run-1"
object$seurat_clusters <- "earlier-label"
object[["RNA"]] <- split(object[["RNA"]], f = object$library)
object <- NormalizeData(object, verbose = FALSE)
saveRDS(object, args[1])
cat(sum(counts), "\n", file = args[2])
"""


def fake_rds(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(b"X\nsynthetic signature only"))


class InputContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="singlecell-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        fake_rds(self.root / "objects" / "input.rds")
        self.data = {
            "schema_version": "singlecell-seurat-v1",
            "input": {
                "seurat_rds": "objects/input.rds",
                "assay": "RNA",
                "metadata_columns": {
                    "sample_id": "library",
                    "donor_id": "subject",
                    "condition": "group",
                    "batch": "run",
                },
            },
            "reference": {
                "species": "test species",
                "genome_build": "test build+annotation",
                "mitochondrial_gene_ids": ["MT-ND1"],
            },
            "qc": {
                "min_counts": 1,
                "min_features": 1,
                "max_features": 100,
                "max_mito_percent": 100,
            },
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

    def test_relative_object_path_resolves_beside_the_manifest(self):
        data = self.load()
        self.assertEqual(data["input"]["seurat_rds"], str(self.root / "objects/input.rds"))

    def test_unknown_fields_and_invalid_nested_types(self):
        for field, value in (
            ("unexpected", 1),
            ("input", []),
            ("reference", []),
            ("qc", None),
            ("analysis", None),
        ):
            original = copy.deepcopy(self.data)
            self.data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load()
            self.data = original

    def test_earlier_fastq_and_matrix_contracts_are_rejected(self):
        for version in ("singlecell-fastq-v1", "singlecell-counts-v1"):
            self.data["schema_version"] = version
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "seurat-v1"):
                self.load()

    def test_object_must_be_an_existing_rds_file(self):
        (self.root / "objects/notes.txt").write_text("not an object")
        (self.root / "objects/plain.rds").write_text("not an object")
        for name, message in (
            ("objects/notes.txt", r"\.rds file"),
            ("objects/missing.rds", "missing Seurat object"),
            ("objects/plain.rds", "saveRDS"),
        ):
            self.data["input"]["seurat_rds"] = name
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                self.load()

    def test_every_metadata_role_is_explicit(self):
        del self.data["input"]["metadata_columns"]["donor_id"]
        with self.assertRaisesRegex(ValueError, "metadata_columns"):
            self.load()
        self.data["input"]["metadata_columns"]["donor_id"] = " "
        with self.assertRaisesRegex(ValueError, "donor_id"):
            self.load()

    def test_missing_mito_ids_rejected(self):
        for ids in ([], [""], ["MT-ND1", "MT-ND1"]):
            self.data["reference"]["mitochondrial_gene_ids"] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.load()

    def test_bad_numeric_and_bool_values(self):
        for value in (True, -1, 101, float("nan"), "20"):
            self.data["qc"]["max_mito_percent"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()

    def test_reversed_feature_cutoffs(self):
        self.data["qc"]["min_features"] = 101
        with self.assertRaisesRegex(ValueError, "max_features"):
            self.load()

    def test_no_unsupported_methods(self):
        self.data["analysis"]["integration"] = "harmony"
        with self.assertRaisesRegex(ValueError, "integration=none"):
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
        self.assertEqual(len(prepared["provenance"]["sha256"]), 8)
        self.assertIn(str(self.root / "objects/input.rds"), prepared["provenance"]["sha256"])
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

    @unittest.skipUnless(shutil.which("Rscript"), "Rscript not installed")
    def test_cell_qc_boundaries(self):
        probe = subprocess.run(
            ["Rscript", "--vanilla", "-e", 'quit(status=!requireNamespace("Matrix", quietly=TRUE))'],
            capture_output=True,
        )
        if probe.returncode:
            self.skipTest("Matrix is unavailable")
        script = self.root / "test_qc.R"
        script.write_text("""
args <- commandArgs(TRUE)
source(args[1])
counts <- Matrix::sparseMatrix(i = c(1, 2, 2), j = c(1, 2, 3), x = c(1, 2, 3), dims = c(2, 3),
                               dimnames = list(c("MT-ND1", "GENE2"), c("AA", "BB", "CC")))
qc <- cell_qc(counts, "MT-ND1", list(min_counts=1, min_features=1,
    max_features=2, max_mito_percent=0))
stopifnot(identical(qc$retained, c(FALSE, TRUE, TRUE)),
          identical(qc$cell_id, c("AA", "BB", "CC")),
          identical(qc$mito_percent, c(100, 0, 0)), identical(qc$n_counts, c(1, 2, 3)))
boundary <- cell_qc(counts, "MT-ND1", list(min_counts=2, min_features=1,
    max_features=1, max_mito_percent=0))
stopifnot(identical(boundary$retained, c(FALSE, TRUE, TRUE)))
counts[, 1] <- 0
zero <- cell_qc(counts, "MT-ND1", list(min_counts=1, min_features=1,
    max_features=2, max_mito_percent=100))
stopifnot(!zero$retained[1], is.nan(zero$mito_percent[1]))
stopifnot(inherits(try(cell_qc(counts, "absent", list()), silent=TRUE), "try-error"))
""")
        result = subprocess.run(
            ["Rscript", "--vanilla", str(script), str(ROOT / "bin/import_qc.R")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(
        os.environ.get("SINGLECELL_TEST_SEURAT") == "1", "opt-in isolated Seurat runtime"
    )
    def test_import_rejects_objects_that_cannot_be_analyzed(self):
        fixture = self.root / "fixture.R"
        fixture.write_text(SEURAT_FIXTURE)
        rds = self.root / "objects/input.rds"
        total = self.root / "total.txt"
        subprocess.run(["Rscript", "--vanilla", str(fixture), str(rds), str(total)], check=True)
        script = self.root / "reject.R"
        script.write_text(r"""
suppressPackageStartupMessages(library(Seurat))
args <- commandArgs(TRUE)
source(args[1])
columns <- list(sample_id = "library", donor_id = "subject", condition = "group", batch = "run")
rejected <- function(expr, pattern) {
    message <- tryCatch({ expr; "" }, error = conditionMessage)
    if (!grepl(pattern, message)) stop("Expected '", pattern, "' but saw: '", message, "'")
}
imported <- read_seurat_input(args[2], "RNA", columns)
stopifnot(ncol(imported$counts) == 120L, identical(imported$metadata$sample_id[[1]], "lib-1"),
          "input_seurat_clusters" %in% names(imported$metadata))
rejected(read_seurat_input(args[2], "ADT", columns), "Assay 'ADT'")
missing <- modifyList(columns, list(condition = "absent"))
rejected(read_seurat_input(args[2], "RNA", missing), "Metadata column 'absent'")

object <- readRDS(args[2])
blank <- object
blank$group[1] <- NA
path <- tempfile(fileext = ".rds"); saveRDS(blank, path)
rejected(read_seurat_input(path, "RNA", columns), "cells without a value")
counts <- as.matrix(LayerData(JoinLayers(object), layer = "counts")) / 3
normalized <- CreateSeuratObject(Matrix::Matrix(counts, sparse = TRUE), min.cells = 0,
                                 min.features = 0, meta.data = object[[]])
path <- tempfile(fileext = ".rds"); saveRDS(normalized, path)
rejected(read_seurat_input(path, "RNA", columns), "raw nonnegative integer counts")
path <- tempfile(fileext = ".rds"); saveRDS(list(not = "seurat"), path)
rejected(read_seurat_input(path, "RNA", columns), "one Seurat object")
""")
        result = subprocess.run(
            ["Rscript", "--vanilla", str(script), str(ROOT / "bin/import_qc.R"), str(rds)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(
        os.environ.get("SINGLECELL_TEST_SEURAT") == "1", "opt-in isolated Seurat runtime"
    )
    def test_full_seurat_analysis_preserves_input_counts_and_metadata(self):
        # Run only after activating the isolated candidate environment.
        fixture = self.root / "fixture.R"
        fixture.write_text(SEURAT_FIXTURE)
        rds = self.root / "objects/input.rds"
        total = self.root / "total.txt"
        subprocess.run(["Rscript", "--vanilla", str(fixture), str(rds), str(total)], check=True)
        before = hashlib.sha256(rds.read_bytes()).hexdigest()
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
            timeout=420,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(hashlib.sha256(rds.read_bytes()).hexdigest(), before)
        assertion = self.root / "assert_object.R"
        assertion.write_text("""
args <- commandArgs(TRUE)
suppressPackageStartupMessages(library(Seurat))
object <- readRDS(args[1])
counts <- LayerData(object, assay="RNA", layer="counts")
stopifnot(inherits(counts, "sparseMatrix"), sum(counts) == as.numeric(readLines(args[2])[1]),
          ncol(counts) == 120L, nrow(counts) == 100L,
          identical(rownames(counts)[1], "MT-ND1"),
          all(table(object$sample_id) == 60L),
          setequal(object$donor_id, c("donor-1", "donor-2")),
          setequal(object$condition, c("ctrl", "stim")),
          all(object$input_seurat_clusters == "earlier-label"),
          !identical(as.character(object$seurat_clusters), as.character(object$input_seurat_clusters)),
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
                str(total),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(
        os.environ.get("SINGLECELL_TEST_NEXTFLOW") == "1", "opt-in Nextflow staging"
    )
    def test_real_nextflow_stages_the_object(self):
        # Substitute only R execution; exercise the actual graph, staging and publication.
        # This is an orchestration test, NOT a successful Seurat scientific analysis.
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake_r = fake_bin / "Rscript"
        fake_r.write_text("""#!/usr/bin/env python3
from pathlib import Path
assert Path("input_object.rds").is_file()
assert Path("import_qc.R").is_file()
for name in ("qc", "tables", "figures", "objects"):
    Path(name).mkdir()
    Path(name, "staging-only.txt").write_text("not scientific results")
""")
        fake_r.chmod(0o755)
        data = self.load()
        prepared = self.root / "prepared.json"
        prepared.write_text(json.dumps(data))
        run_dir = self.root / "staging"
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
