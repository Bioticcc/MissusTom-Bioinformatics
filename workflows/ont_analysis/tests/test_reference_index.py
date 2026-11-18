"""Synthetic checks for optional, reusable ONT reference-index preparation."""

import json
import os
import random
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
helper = runpy.run_path(str(ROOT / "lib/prepare_minimap2_index.py"))
prepare_index = helper["prepare_index"]
runner = runpy.run_path(str(ROOT / "run_pipeline.py"))


class IndexPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fasta = self.root / "reference with spaces.fa"
        self.fasta.write_text(">chr1\nACGT\n")
        self.index = self.root / "results/reference/reference.lr-hq.mmi"
        self.tool = self.root / "minimap2"
        self.calls = self.root / "calls"
        self.tool.write_text(
            "#!/usr/bin/env python3\n"
            + """
import os, sys
from pathlib import Path
if "--version" in sys.argv:
    print("2.31-test"); sys.exit(0)
assert sys.argv[1:3] == ["-x", "lr:hq"]
assert sys.argv[3:5] == ["-t", "2"]
"""
            + f"calls = Path({str(self.calls)!r})\n"
            + """
calls.write_text(str(int(calls.read_text()) + 1) if calls.exists() else "1")
target = Path(sys.argv[sys.argv.index("-d") + 1])
target.write_bytes(b"synthetic index:" + Path(sys.argv[-1]).read_bytes())
if os.environ.get("ONT_FAKE_INDEX_FAIL"):
    sys.exit(7)
if os.environ.get("ONT_FAKE_FASTA_CHANGE"):
    Path(sys.argv[-1]).write_text(">chr1\\nTGCA\\n")
"""
        )
        self.tool.chmod(0o755)

    def prepare(self):
        return prepare_index(self.fasta, self.index, self.tool, 2)

    def test_reuses_shared_index_and_records_exact_build_provenance(self):
        self.prepare()
        before = self.index.stat().st_mtime_ns
        self.prepare()
        self.assertEqual(self.calls.read_text(), "1")
        self.assertEqual(self.index.stat().st_mtime_ns, before)
        metadata = json.loads(self.index.with_suffix(".mmi.json").read_text())
        self.assertEqual(metadata["signature"]["preset"], "lr:hq")
        self.assertEqual(metadata["signature"]["minimap2_version"], "2.31-test")
        self.assertEqual(metadata["fasta_sha256"], helper["sha256"](self.fasta))
        self.assertEqual(metadata["index_sha256"], helper["sha256"](self.index))

    def test_rebuilds_when_fasta_index_metadata_or_tool_changes(self):
        self.prepare()
        self.fasta.write_text(">chr1\nTGCA\n")
        self.prepare()
        self.index.write_text("corrupted")
        self.prepare()
        self.index.with_suffix(".mmi.json").write_text("{")
        self.prepare()
        self.tool.write_text(self.tool.read_text() + "\n# new executable revision\n")
        self.prepare()
        self.assertEqual(self.calls.read_text(), "5")

    def test_failed_or_changing_reference_build_is_not_published(self):
        for variable, error in (
            ("ONT_FAKE_INDEX_FAIL", subprocess.CalledProcessError),
            ("ONT_FAKE_FASTA_CHANGE", ValueError),
        ):
            with (
                self.subTest(variable=variable),
                patch.dict(os.environ, {variable: "1"}),
                self.assertRaises(error),
            ):
                self.prepare()
            self.assertFalse(self.index.exists())
            self.assertFalse(self.index.with_suffix(".mmi.json").exists())
            self.assertEqual(list(self.index.parent.glob(".*partial-*")), [])

    def test_symlinked_output_is_rejected_without_modifying_target(self):
        self.index.parent.mkdir(parents=True)
        target = self.root / "keep"
        target.write_text("unchanged")
        self.index.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.prepare()
        self.assertEqual(target.read_text(), "unchanged")

    def test_missing_index_maps_all_samples_to_one_project_index_without_building(self):
        inputs = self.root / "inputs"
        inputs.mkdir()
        bam = inputs / "sample.bam"
        bam.write_text("bam")
        fai = self.root / "reference.fai"
        fai.write_text("".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, 20)))
        manifest = {
            "schema_version": "1.0.0",
            "pipeline_identifier": "ont-analysis",
            "pipeline_version": "0.1.0",
            "organism": "Mus musculus",
            "reference_genome": "GRCm38p6",
            "execution_profile": "local",
            "input_directory": str(inputs),
            "resource_profile": {"cpus": 2, "memory_gb": 4},
            "parameters": {"modification_mode": "5mc_only"},
            "reference_resources": {"reference_fasta": str(self.fasta), "reference_fai": str(fai)},
            "samples": [
                {"sample_id": name, "included": True, "ont_bam_files": [str(bam)]}
                for name in ("one", "two")
            ],
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest))
        for sample in ("one", "two"):
            with patch.dict(
                runner["load_manifest"].__globals__, path_tool=lambda _: str(self.tool)
            ):
                values = runner["load_manifest"](
                    path,
                    self.root / "results/samples" / sample,
                    "test",
                    sample_id=sample,
                    reference_output=self.index.parent,
                )
            self.assertEqual(values["REFERENCE_MMI"], str(self.index))
            self.assertEqual(values["REFERENCE_MMI_GENERATED"], "1")
            self.assertEqual(values["MODIFICATION_MODE"], "5mc_only")
        self.assertFalse(self.index.exists())
        self.assertFalse(self.calls.exists())


class RealMinimap2Tests(unittest.TestCase):
    def test_generated_index_can_align_synthetic_reads(self):
        tool = os.environ.get("ONT_TEST_MINIMAP2") or shutil.which("minimap2")
        if not tool:
            self.skipTest("Minimap2 is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sequence = "".join(random.Random(42).choices("ACGT", k=4000))
            fasta = root / "reference.fa"
            fasta.write_text(">chr1\n" + sequence + "\n")
            query = root / "query.fa"
            query.write_text(">read\n" + sequence[500:2500] + "\n")
            index = prepare_index(fasta, root / "reference.mmi", Path(tool), 1)
            result = subprocess.run(
                [tool, "-a", "-x", "lr:hq", str(index), str(query)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("read\t0\tchr1\t", result.stdout)
