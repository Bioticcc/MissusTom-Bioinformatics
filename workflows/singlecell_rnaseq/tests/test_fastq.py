"""FASTQ contracts and orchestration with explicitly substituted scientific tools."""

from __future__ import annotations

import copy
import gzip
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    fastq = importlib.import_module("run_fastq")
finally:
    sys.path.pop(0)
spec = importlib.util.spec_from_file_location("fastq_stage", ROOT / "bin/fastq_stage.py")
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


def reads(path, mate, *, identifier="fragment", length=None):
    sequence = "A" * (length if length is not None else (28 if mate == 1 else 50))
    with gzip.open(path, "wt") as handle:
        handle.write(f"@{identifier}/{mate}\n{sequence}\n+\n{'I' * len(sequence)}\n")


class FastqContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="singlecell-fastq-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "reference.fa").write_text(">chr1\n" + "A" * 1000 + "\n")
        (self.root / "genes.gtf").write_text(
            'chr1\tfixture\texon\t1\t100\t.\t+\t.\tgene_id "MT1"; transcript_id "tx1";\n'
        )
        (self.root / "whitelist.txt").write_text("AAAAAAAAAAAAAAAA\n")
        reads(self.root / "lane1 R1.fastq.gz", 1)
        reads(self.root / "lane1 R2.fastq.gz", 2)
        self.data = {
            "schema_version": "singlecell-fastq-v1",
            "reference": {
                "species": "test species",
                "genome_build": "test build+annotation",
                "mitochondrial_gene_ids": ["MT1"],
                "fasta": "reference.fa",
                "gtf": "genes.gtf",
                "sjdb_overhang": 49,
                "sa_index_n_bases": 3,
            },
            "samples": [
                {
                    "sample_id": "sample-1",
                    "donor_id": "donor-1",
                    "condition": "ctrl",
                    "batch": "batch-1",
                    "chemistry": "10x_3prime_v3",
                    "material": "cells",
                    "counting_mode": "Gene",
                    "barcode_whitelist": "whitelist.txt",
                    "expected_cells": 3000,
                    "lanes": [{"r1": "lane1 R1.fastq.gz", "r2": "lane1 R2.fastq.gz"}],
                    "qc": {
                        "min_counts": 1,
                        "min_features": 1,
                        "max_features": 100,
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

    def load(self, **overrides):
        self.path.write_text(json.dumps(self.data))
        return fastq.load_fastq_manifest(self.path, **overrides)

    def test_explicit_layout_staging_and_counting_modes(self):
        data = self.load()
        sample = data["samples"][0]
        self.assertEqual(sample["umi_length"], 12)
        self.assertEqual(sample["lanes"][0]["staged_r2"], "read0002.fastq.gz")
        self.assertEqual(self.load(chemistry="10x_3prime_v2")["samples"][0]["umi_length"], 10)
        self.data["samples"][0].update(material="nuclei", counting_mode="GeneFull")
        self.assertEqual(self.load()["samples"][0]["counting_mode"], "GeneFull")

    def test_unknown_chemistry_blocks_and_explicit_selection_works(self):
        self.data["samples"][0]["chemistry"] = "unknown"
        with self.assertRaisesRegex(ValueError, "confirmed chemistry"):
            self.load()
        self.assertEqual(self.load(chemistry="10x_3prime_v3")["samples"][0]["umi_length"], 12)
        catalog = json.loads((ROOT / "chemistries.json").read_text())
        supported = {entry["id"] for entry in catalog if entry["execution_supported"]}
        self.assertEqual(supported, set(fastq.CHEMISTRIES))

    def test_short_or_mispaired_reads_rejected(self):
        reads(self.root / "lane1 R1.fastq.gz", 1, length=26)
        with self.assertRaisesRegex(ValueError, "shorter"):
            self.load()
        reads(self.root / "lane1 R1.fastq.gz", 1)
        reads(self.root / "lane1 R2.fastq.gz", 2, identifier="different")
        with self.assertRaisesRegex(ValueError, "read IDs differ"):
            self.load()

    def test_duplicates_and_bad_whitelists_rejected(self):
        self.data["samples"][0]["lanes"].append(copy.deepcopy(self.data["samples"][0]["lanes"][0]))
        with self.assertRaisesRegex(ValueError, "cannot be reused"):
            self.load()
        self.data["samples"][0]["lanes"].pop()
        (self.root / "whitelist.txt").write_text("ACGT\n")
        with self.assertRaisesRegex(ValueError, "16-base"):
            self.load()

    def test_reference_contigs_mito_ids_and_small_genome_index_limits(self):
        self.data["reference"]["sa_index_n_bases"] = 14
        with self.assertRaisesRegex(ValueError, "too large"):
            self.load()
        self.data["reference"]["sa_index_n_bases"] = 3
        original = (self.root / "genes.gtf").read_text()
        (self.root / "genes.gtf").write_text(original.replace("chr1", "chr2"))
        with self.assertRaisesRegex(ValueError, "contig absent"):
            self.load()
        (self.root / "genes.gtf").write_text(original)
        self.data["reference"]["mitochondrial_gene_ids"] = ["unannotated"]
        with self.assertRaisesRegex(ValueError, "mitochondrial"):
            self.load()

    def test_check_only_never_starts_tools(self):
        self.load()
        with (
            patch("sys.argv", ["runner", "--manifest", str(self.path), "--check-only"]),
            patch.object(fastq.subprocess, "run") as run,
        ):
            self.assertEqual(fastq.main(), 0)
            run.assert_not_called()

    def test_full_pair_validation_catches_late_mismatch_and_truncation(self):
        sample = self.load()["samples"][0]
        lane = sample["lanes"][0]
        lane["staged_r1"], lane["staged_r2"] = lane["r1"], lane["r2"]
        with gzip.open(lane["r1"], "at") as handle:
            handle.write("@second/1\n" + "A" * 28 + "\n+\n" + "I" * 28 + "\n")
        with gzip.open(lane["r2"], "at") as handle:
            handle.write("@wrong/2\n" + "A" * 50 + "\n+\n" + "I" * 50 + "\n")
        with self.assertRaisesRegex(ValueError, "record 2"):
            stage.validate_pairs(sample)
        reads(Path(lane["r2"]), 2)
        with self.assertRaisesRegex(ValueError, "different record counts"):
            stage.validate_pairs(sample)

    def test_matrix_packaging_is_lossless_and_reproducible(self):
        source = self.root / "filtered"
        source.mkdir()
        (source / "features.tsv").write_text("MT1\tmitochondrial\nG2\tgene2\n")
        (source / "barcodes.tsv").write_text("AAAAAAAAAAAAAAAA\n")
        matrix = "%%MatrixMarket matrix coordinate integer general\n2 1 1\n1 1 7\n"
        (source / "matrix.mtx").write_text(matrix)
        stage.package_matrix(source, self.root / "matrix1")
        stage.package_matrix(source, self.root / "matrix2")
        for name in ("features.tsv.gz", "barcodes.tsv.gz", "matrix.mtx.gz"):
            self.assertEqual(
                (self.root / "matrix1" / name).read_bytes(),
                (self.root / "matrix2" / name).read_bytes(),
            )
        with gzip.open(self.root / "matrix1/matrix.mtx.gz", "rt") as handle:
            self.assertEqual(handle.read(), matrix)
        with gzip.open(self.root / "matrix1/features.tsv.gz", "rt") as handle:
            self.assertIn("MT1\tmitochondrial\tGene Expression", handle.read())

    def test_star_command_read_order_and_modern_cell_calling(self):
        sample = self.load()["samples"][0]
        with (
            patch.object(stage, "validate_pairs"),
            patch.object(stage, "star") as star,
            patch.object(Path, "is_file", return_value=True),
            patch.object(stage, "package_matrix"),
        ):
            stage.quantify(sample, 2)
        command = star.call_args.args[0]
        read_index = command.index("--readFilesIn")
        self.assertEqual(
            command[read_index + 1 : read_index + 3], ["read0002.fastq.gz", "read0001.fastq.gz"]
        )
        self.assertEqual(command[command.index("--soloUMIlen") + 1], "12")
        self.assertEqual(command[command.index("--soloCellFilter") + 1], "EmptyDrops_CR")
        self.assertEqual(command[command.index("--soloFeatures") + 1], "Gene")
        self.assertEqual(command[command.index("--outSAMtype") + 1], "None")

    @unittest.skipUnless(os.environ.get("SINGLECELL_TEST_NEXTFLOW") == "1", "opt-in Nextflow graph")
    def test_real_fastq_graph_and_matrix_handoff_with_substitute_tools(self):
        self.load()
        tools = self.root / "fake-bin"
        tools.mkdir()
        star = tools / "STAR"
        star.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
args = sys.argv[1:]
if args == ["--version"]:
    print("2.7.11b")
elif "genomeGenerate" in args:
    Path("star_index").mkdir(exist_ok=True)
    for name in ("Genome", "SA", "SAindex", "genomeParameters.txt", "geneInfo.tab"):
        Path("star_index", name).write_text("stub index")
else:
    assert Path("star_index/Genome").is_file()
    for name in args[args.index("--readFilesIn")+1:args.index("--readFilesIn")+3]:
        for lane in name.split(","):
            assert Path(lane).is_file()
    feature = args[args.index("--soloFeatures")+1]
    for subset in ("raw", "filtered"):
        root = Path("Solo.out", feature, subset)
        root.mkdir(parents=True)
        (root / "features.tsv").write_text("MT1\\tmt\\nG2\\tgene2\\n")
        (root / "barcodes.tsv").write_text(
            "AAAAAAAAAAAAAAAA\\nCCCCCCCCCCCCCCCC\\nGGGGGGGGGGGGGGGG\\n")
        (root / "matrix.mtx").write_text(
            "%%MatrixMarket matrix coordinate integer general\\n2 3 3\\n1 1 1\\n2 2 2\\n2 3 3\\n")
    Path("Solo.out", feature, "Summary.csv").write_text("test,stub\\n")
    Path("Log.final.out").write_text("stub mapping log")
    Path("Log.out").write_text("stub log")
""")
        star.chmod(0o755)
        r = tools / "Rscript"
        r.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
if any("check_dependencies.R" in arg for arg in sys.argv):
    sys.exit(0)
files = ["qc/cell_qc.tsv", "qc/sample_qc.tsv", "tables/features.tsv",
    "tables/cell_metadata.tsv", "tables/marker_status.tsv", "objects/singlecell.rds",
    "tables/provenance/prepared_manifest.json", "tables/provenance/sessionInfo.txt",
    "tables/provenance/installed_packages.txt", "tables/provenance/analysis_notes.txt",
    "tables/exploratory_cluster_markers.tsv", "figures/qc_retained_cells.pdf",
    "figures/pca_elbow.pdf"]
files += ["figures/umap_" + group + ".pdf" for group in
    ("seurat_clusters", "sample_id", "condition", "batch")]
for name in files:
    path = Path(name)
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text("substitute output; not scientific analysis")
""")
        r.chmod(0o755)
        # Two libraries, each with two explicit lanes and duplicate original basenames.
        for sample_index in (1, 2):
            if sample_index == 2:
                sample = copy.deepcopy(self.data["samples"][0])
                sample.update(sample_id="sample-2", donor_id="donor-2")
                self.data["samples"].append(sample)
            sample = self.data["samples"][sample_index - 1]
            sample["lanes"] = []
            for lane_index in (1, 2):
                directory = self.root / f"sample{sample_index}/lane{lane_index}"
                directory.mkdir(parents=True)
                for mate in (1, 2):
                    reads(directory / f"reads_R{mate}.fastq.gz", mate)
                sample["lanes"].append(
                    {
                        "r1": str(directory / "reads_R1.fastq.gz"),
                        "r2": str(directory / "reads_R2.fastq.gz"),
                    }
                )
        self.load()
        run_dir = self.root / "FASTQ run with spaces"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "run_fastq.py"),
                "--manifest",
                str(self.path),
                "--run-dir",
                str(run_dir),
                "--cpus",
                "1",
                "--memory-gb",
                "1",
            ],
            timeout=90,
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": str(tools) + ":" + os.environ["PATH"]},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for sample in self.data["samples"]:
            self.assertTrue(
                (
                    run_dir / "quantification" / sample["sample_id"] / "matrix/matrix.mtx.gz"
                ).is_file()
            )
        provenance = run_dir / "analysis/results/tables/provenance/fastq_manifest.json"
        self.assertTrue(provenance.is_file())
        prepared = json.loads(provenance.read_text())
        self.assertIn(str(self.root / "reference.fa"), prepared["provenance"]["sha256"])
        self.assertTrue((run_dir / "reports/trace.tsv").is_file())
        self.assertTrue(
            (run_dir / "analysis/reports/trace.tsv").is_file(),
            [str(path.relative_to(run_dir)) for path in run_dir.rglob("trace*")],
        )
        self.assertFalse((self.root / "reports").exists())


if __name__ == "__main__":
    unittest.main()
