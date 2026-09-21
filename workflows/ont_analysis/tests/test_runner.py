import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).parents[1] / "run_pipeline.py"
spec = importlib.util.spec_from_file_location("ont_runner", MODULE)
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)

def manifest_contract(manifest):
    manifest.update(pipeline_identifier="ont-analysis", pipeline_version="0.1.0",
                    organism="Mus musculus", execution_profile="local")
    manifest["resource_profile"]["memory_gb"] = 2
    return manifest

class RunnerContractTests(unittest.TestCase):
    def test_run_id_contract(self):
        self.assertIsNotNone(runner.RUN_ID.fullmatch("safe-run_1.0"))
        self.assertIsNone(runner.RUN_ID.fullmatch("../unsafe"))

    def test_shell_quote_round_trip_safe_shape(self):
        self.assertEqual(runner.shell_quote("a'b"), "'a'\"'\"'b'")

    def test_project_manifest_mapping_writes_canonical_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root / "inputs"; inputs.mkdir(); bam = inputs / "chunk.bam"; bam.write_text("bam")
            resources = {}
            for key in ("reference_fasta", "reference_fai", "minimap2_index", "gencode_gff3", "cpg_islands", "ccre_table", "intergenic_bed", "ont_instrument_report"):
                resource = root / key; resource.write_text("x"); resources[key] = str(resource)
            manifest = {"schema_version": "1.0.0", "input_directory": str(inputs), "reference_genome": "GRCm38p6", "reference_resources": resources, "parameters": {}, "resource_profile": {"cpus": 1}, "comparisons": [], "samples": [{"sample_id": "mouse", "included": True, "ont_bam_files": [str(bam)]}]}
            manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest_contract(manifest)))
            with patch.object(runner, "path_tool", return_value="/bin/true"):
                values = runner.load_manifest(manifest_path, root / "results", "run-1")
            env = runner.write_config(values, root / "results")
            text = env.read_text()
            self.assertIn("REFERENCE_FAI=", text)
            self.assertIn("SAMPLE_OUTPUT='" + str((root / "results").resolve()), text)
            settings = root / "results" / "config" / "pipeline-settings.env"
            before = settings.read_text()
            before_mtime = settings.stat().st_mtime_ns
            time.sleep(0.01)
            rerun_values = dict(values); rerun_values["RUN_ID"] = "run-2"
            runner.write_config(rerun_values, root / "results")
            self.assertEqual(settings.read_text(), before)
            self.assertEqual(settings.stat().st_mtime_ns, before_mtime)

    def test_manifest_rejects_output_inside_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root / "inputs"; inputs.mkdir(); bam = inputs / "input.bam"; bam.write_text("bam")
            resources = {}
            for key in ("reference_fasta", "reference_fai", "minimap2_index", "gencode_gff3", "cpg_islands", "ccre_table", "intergenic_bed", "ont_instrument_report"):
                resource = root / key; resource.write_text("x"); resources[key] = str(resource)
            manifest = {"schema_version": "1.0.0", "input_directory": str(inputs), "reference_genome": "GRCm38p6", "reference_resources": resources, "parameters": {}, "resource_profile": {"cpus": 1}, "comparisons": [], "samples": [{"sample_id": "mouse", "included": True, "ont_bam_files": [str(bam)]}]}
            manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest_contract(manifest)))
            with patch.object(runner, "path_tool", return_value="/bin/true"):
                with self.assertRaisesRegex(runner.ManifestError, "outside input_directory"):
                    runner.load_manifest(manifest_path, inputs / "results", "run-1")

    def test_manifest_accepts_core_references_without_annotations_or_instrument_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root / "inputs"; inputs.mkdir(); bam = inputs / "chunk.bam"; bam.write_text("bam")
            resources = {}
            for key in ("reference_fasta", "reference_fai", "minimap2_index"):
                resource = root / key; resource.write_text("x"); resources[key] = str(resource)
            manifest = {"schema_version": "1.0.0", "input_directory": str(inputs), "reference_genome": "GRCm38p6", "reference_resources": resources, "parameters": {}, "resource_profile": {"cpus": 1}, "comparisons": [], "samples": [{"sample_id": "mouse", "included": True, "ont_bam_files": [str(bam)]}]}
            manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest_contract(manifest)))
            with patch.object(runner, "path_tool", return_value="/bin/true"):
                values = runner.load_manifest(manifest_path, root / "results", "run-1")
            self.assertEqual(values["ANNOTATION_EXPLORATION_ENABLED"], "0")
            self.assertEqual(values["ONT_INSTRUMENT_REPORT"], "")

    def test_manifest_rejects_partial_annotation_group_and_invalid_optional_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root / "inputs"; inputs.mkdir(); bam = inputs / "chunk.bam"; bam.write_text("bam")
            resources = {}
            for key in ("reference_fasta", "reference_fai", "minimap2_index"):
                resource = root / key; resource.write_text("x"); resources[key] = str(resource)
            partial = dict(resources); partial["gencode_gff3"] = str(root / "reference_fasta")
            manifest = {"schema_version": "1.0.0", "input_directory": str(inputs), "reference_genome": "GRCm38p6", "reference_resources": partial, "parameters": {}, "resource_profile": {"cpus": 1}, "comparisons": [], "samples": [{"sample_id": "mouse", "included": True, "ont_bam_files": [str(bam)]}]}
            manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest_contract(manifest)))
            with patch.object(runner, "path_tool", return_value="/bin/true"):
                with self.assertRaisesRegex(runner.ManifestError, "complete group"):
                    runner.load_manifest(manifest_path, root / "results", "run-1")
            manifest["reference_resources"] = {**resources, "ont_instrument_report": str(root / "missing.html")}
            manifest_path.write_text(json.dumps(manifest_contract(manifest)))
            with patch.object(runner, "path_tool", return_value="/bin/true"):
                with self.assertRaisesRegex(runner.ManifestError, "ont_instrument_report"):
                    runner.load_manifest(manifest_path, root / "results", "run-1")

    def test_stage01_stage02_fake_tools_are_restartable_and_keep_tags(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); tools = root / "tools"; tools.mkdir(); output = root / "results"; output.mkdir()
            bam = root / "input.bam"; bam.write_text("source\n")
            mmi = root / "reference.mmi"; mmi.write_text("index\n")
            fake_samtools = tools / "samtools"; fake_dorado = tools / "dorado"
            fake_dorado.write_text("#!/usr/bin/env bash\nprintf 'r\\t0\\tchr1\\t1\\t60\\t1M\\t*\\t0\\t0\\tA\\tI\\tMM:Z:C+m?,C+h?\\tML:B:C,1\\tMN:i:1\\n'\n")
            fake_samtools.write_text("""#!/usr/bin/env bash
set -eu
command=$1; shift
record=$'r\\t0\\tchr1\\t1\\t60\\t1M\\t*\\t0\\t0\\tA\\tI\\tMM:Z:C+m?,C+h?\\tML:B:C,1\\tMN:i:1'
case "$command" in
  quickcheck) exit 0 ;;
  view) for arg in "$@"; do [ "$arg" = "-c" ] && { echo 1; exit 0; }; done; echo "$record" ;;
  cat) while [ "$1" != "-b" ]; do shift; done; /bin/cat "$(/bin/cat "$2")" ;;
  sort) while [ "$1" != "-o" ]; do shift; done; output=$2; /bin/cat > "$output" ;;
  index) while [ "$1" != "-o" ]; do shift; done; echo index > "$2" ;;
  idxstats) echo 'chr1 1 1 0' ;;
  flagstat) echo '1 + 0 mapped (100.00% : N/A)' ;;
  *) echo "unsupported samtools command: $command" >&2; exit 2 ;;
esac
""")
            for executable in (fake_samtools, fake_dorado): executable.chmod(0o755)
            config = output / "config"; config.mkdir()
            bam_list = config / "ont_bam_files.list"; bam_list.write_text(str(bam) + "\n")
            settings = config / "pipeline-settings.env"; settings.write_text("stable=yes\n")
            env = config / "project.env"
            values = {
                "SAMPLE_OUTPUT": output, "SAMPLE_ID": "sample", "INPUT_BAM_LIST": bam_list,
                "EXPECTED_PASS_BAM_COUNT": "1", "REFERENCE_MMI": mmi, "PIPELINE_SETTINGS_FILE": settings,
                "DORADO_BIN": fake_dorado, "SAMTOOLS_BIN": fake_samtools, "ALIGNMENT_THREADS": "1",
                "VALIDATION_THREADS": "1", "SORT_THREADS": "1", "SORT_MEMORY_PER_THREAD": "1G",
            }
            env.write_text("\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n")
            run_environment = os.environ | {"PIPELINE_ENV": str(env)}
            for stage in ("01_align_modbam.sh", "01_align_modbam.sh", "02_finalize_alignment.sh", "02_finalize_alignment.sh"):
                subprocess.run(["bash", str(MODULE.parents[0] / "stages" / stage)], check=True, env=run_environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            chunk = output / "01_alignment" / "aligned_unsorted_chunks" / "input.aligned.unsorted.bam"
            final = output / "02_alignment_qc" / "sample.aligned.sorted.bam"
            self.assertTrue((chunk.with_suffix(chunk.suffix + ".complete")).is_file())
            self.assertTrue((output / "01_alignment" / ".stage01.complete").is_file())
            self.assertTrue((final.with_suffix(final.suffix + ".bai")).is_file())
            self.assertIn("MM:Z:", final.read_text())
            self.assertTrue((output / "02_alignment_qc" / ".stage02.complete").is_file())

    def test_expected_bam_count_must_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root / "inputs"; inputs.mkdir(); bam = inputs / "chunk.bam"; bam.write_text("bam")
            resources = {}
            for key in ("reference_fasta", "reference_fai", "minimap2_index", "gencode_gff3", "cpg_islands", "ccre_table", "intergenic_bed", "ont_instrument_report"):
                resource = root / key; resource.write_text("x"); resources[key] = str(resource)
            manifest = {"schema_version": "1.0.0", "input_directory": str(inputs), "reference_genome": "GRCm38p6", "reference_resources": resources, "parameters": {"expected_pass_bam_count": 2}, "resource_profile": {"cpus": 1}, "comparisons": [], "samples": [{"sample_id": "mouse", "included": True, "ont_bam_files": [str(bam)]}]}
            manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest_contract(manifest)))
            with patch.object(runner, "path_tool", return_value="/bin/true"):
                with self.assertRaisesRegex(runner.ManifestError, "expected_pass_bam_count"):
                    runner.load_manifest(manifest_path, root / "results", "run-1")

    def test_generated_output_rejects_nested_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / "results"; output.mkdir()
            (output / "tmp").symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(runner.ManifestError, "symbolic link"):
                runner.write_config({}, output)

    def test_sort_budget_counts_main_thread(self):
        settings = {key: 1 for key in runner.DEFAULTS if key.endswith("threads")}
        with self.assertRaisesRegex(runner.ManifestError, "sort memory"):
            runner.validate_settings(settings, 1, 1)

    def test_exploration_requires_matching_window_coordinates(self):
        settings = {key: 1 for key in runner.DEFAULTS if key.endswith("threads")}
        settings["coverage_window_size"] = 200000
        with self.assertRaisesRegex(runner.ManifestError, "must match"):
            runner.validate_settings(settings, 1, 4)
