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
                resource = root / key; resource.write_text("".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, 20)) if key == "reference_fai" else "x"); resources[key] = str(resource)
            manifest = {"schema_version": "1.0.0", "input_directory": str(inputs), "reference_genome": "GRCm38p6", "reference_resources": resources, "parameters": {}, "resource_profile": {"cpus": 1}, "comparisons": [], "samples": [{"sample_id": "mouse", "included": True, "ont_bam_files": [str(bam)]}]}
            manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest_contract(manifest)))
            with patch.object(runner, "path_tool", return_value="/bin/true"):
                values = runner.load_manifest(manifest_path, root / "results", "run-1")
            env = runner.write_config(values, root / "results")
            text = env.read_text()
            self.assertIn("MODIFICATION_MODE='5mc_5hmc'", text)
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
                resource = root / key; resource.write_text("".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, 20)) if key == "reference_fai" else "x"); resources[key] = str(resource)
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
                resource = root / key; resource.write_text("".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, 20)) if key == "reference_fai" else "x"); resources[key] = str(resource)
            manifest = {"schema_version": "1.0.0", "input_directory": str(inputs), "reference_genome": "GRCm38p6", "reference_resources": resources, "parameters": {}, "resource_profile": {"cpus": 1}, "comparisons": [], "samples": [{"sample_id": "mouse", "included": True, "ont_bam_files": [str(bam)]}]}
            manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest_contract(manifest)))
            with patch.object(runner, "path_tool", return_value="/bin/true"):
                values = runner.load_manifest(manifest_path, root / "results", "run-1")
            self.assertEqual(values["ANNOTATION_EXPLORATION_ENABLED"], "0")
            self.assertEqual(values["ONT_INSTRUMENT_REPORT"], "")

    def test_multi_sample_check_only_creates_isolated_configs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root / "inputs"; inputs.mkdir()
            bam_one = inputs / "one.bam"; bam_one.write_text("bam")
            bam_two = inputs / "two.bam"; bam_two.write_text("bam")
            resources = {}
            for key in ("reference_fasta", "reference_fai", "minimap2_index"):
                resource = root / key; resource.write_text("".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, 20)) if key == "reference_fai" else "x"); resources[key] = str(resource)
            manifest = {
                "schema_version": "1.0.0", "input_directory": str(inputs),
                "reference_genome": "GRCm38p6", "reference_resources": resources,
                "parameters": {"expected_pass_bam_count": 2}, "resource_profile": {"cpus": 1},
                "comparisons": [], "samples": [
                    {"sample_id": "mouse_one", "included": True, "ont_bam_files": [str(bam_one)]},
                    {"sample_id": "mouse_two", "included": True, "ont_bam_files": [str(bam_two)]},
                ],
            }
            manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest_contract(manifest)))
            with patch.object(runner, "path_tool", return_value="/bin/true"), patch.object(
                runner.sys, "argv", ["run_pipeline.py", "--manifest", str(manifest_path), "--outdir", str(root / "results"), "--run-id", "run-1", "--check-only"]
            ):
                self.assertEqual(runner.main(), 0)
            for sample_id in ("mouse_one", "mouse_two"):
                env_path = root / "results" / "samples" / sample_id / "config" / "project.env"
                self.assertTrue(env_path.is_file())
                self.assertIn(f"SAMPLE_ID='{sample_id}'", env_path.read_text())

    def test_multi_sample_manifest_rejects_total_bam_count_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root / "inputs"; inputs.mkdir()
            bam = inputs / "one.bam"; bam.write_text("bam")
            manifest = {"parameters": {"expected_pass_bam_count": 2}, "samples": [{"sample_id": "mouse", "included": True, "ont_bam_files": [str(bam)]}], "comparisons": []}
            manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(runner.ManifestError, "expected_pass_bam_count"):
                runner.included_sample_ids(manifest_path)

    def test_manifest_rejects_partial_annotation_group_and_invalid_optional_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root / "inputs"; inputs.mkdir(); bam = inputs / "chunk.bam"; bam.write_text("bam")
            resources = {}
            for key in ("reference_fasta", "reference_fai", "minimap2_index"):
                resource = root / key; resource.write_text("".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, 20)) if key == "reference_fai" else "x"); resources[key] = str(resource)
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
        self._check_stage01_stage02_restartable(generate_index=False)

    def test_stage01_prepares_and_reuses_optional_index_and_keeps_tags(self):
        self._check_stage01_stage02_restartable(generate_index=True)

    def _check_stage01_stage02_restartable(self, generate_index):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); tools = root / "tools"; tools.mkdir(); output = root / "results"; output.mkdir()
            bam = root / "input.bam"; bam.write_text("source\n")
            mmi = root / "reference.mmi"
            if not generate_index:
                mmi.write_text("index\n")
            fasta = root / "reference.fa"; fasta.write_text(">chr1\nACGT\n")
            fake_minimap2 = tools / "minimap2"
            count = root / "index_builds"
            fake_minimap2.write_text("#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n"
                "if '--version' in sys.argv:\n print('2.31-test'); sys.exit(0)\n"
                f"count=Path({str(count)!r})\n"
                "count.write_text(str(int(count.read_text())+1) if count.exists() else '1')\n"
                "Path(sys.argv[sys.argv.index('-d')+1]).write_text('index')\n")
            fake_minimap2.chmod(0o755)
            fake_samtools = tools / "samtools"; fake_dorado = tools / "dorado"
            fake_dorado.write_text("#!/usr/bin/env bash\nprintf 'r\\t0\\tchr1\\t1\\t60\\t1M\\t*\\t0\\t0\\tA\\tI\\tMM:Z:C+m?,C+h?\\tML:B:C,1\\tMN:i:1\\n'\n")
            fake_samtools.write_text("""#!/usr/bin/env bash
set -eu
command=$1; shift
record=$'r\\t0\\tchr1\\t1\\t60\\t1M\\t*\\t0\\t0\\tA\\tI\\tMM:Z:C+m?,C+h?\\tML:B:C,1\\tMN:i:1'
case "$command" in
  quickcheck) exit 0 ;;
  view) if [ "${1:-}" = "-b" ]; then while [ "$1" != "-o" ]; do shift; done; /bin/cat > "$2"; exit 0; fi
        if [ "${1:-}" = "-h" ]; then /bin/cat; exit 0; fi
        for arg in "$@"; do [ "$arg" = "-c" ] && { echo 1; exit 0; }; done; echo "$record" ;;
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
                "REFERENCE_MMI_GENERATED": "1" if generate_index else "0",
                "MINIMAP2_BIN": fake_minimap2, "REFERENCE_FASTA": fasta,
                "WORKFLOW_ROOT": MODULE.parent,
            }
            env.write_text("\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n")
            run_environment = os.environ | {"PIPELINE_ENV": str(env)}
            subprocess.run(["bash", str(MODULE.parent / "stages/01_align_modbam.sh"), "--check-only"],
                           check=True, env=run_environment, capture_output=True, text=True)
            self.assertEqual(mmi.exists(), not generate_index)
            for stage in ("01_align_modbam.sh", "01_align_modbam.sh", "02_finalize_alignment.sh", "02_finalize_alignment.sh"):
                subprocess.run(["bash", str(MODULE.parents[0] / "stages" / stage)], check=True, env=run_environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            chunk = output / "01_alignment" / "aligned_unsorted_chunks" / "input.aligned.unsorted.bam"
            final = output / "02_alignment_qc" / "sample.aligned.sorted.bam"
            self.assertTrue((chunk.with_suffix(chunk.suffix + ".complete")).is_file())
            self.assertTrue((output / "01_alignment" / ".stage01.complete").is_file())
            self.assertTrue((final.with_suffix(final.suffix + ".bai")).is_file())
            self.assertIn("MM:Z:", final.read_text())
            self.assertTrue((output / "02_alignment_qc" / ".stage02.complete").is_file())
            if generate_index:
                self.assertEqual(count.read_text(), "1")
                self.assertTrue(mmi.with_suffix(".mmi.json").is_file())

    def test_expected_bam_count_must_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); inputs = root / "inputs"; inputs.mkdir(); bam = inputs / "chunk.bam"; bam.write_text("bam")
            resources = {}
            for key in ("reference_fasta", "reference_fai", "minimap2_index", "gencode_gff3", "cpg_islands", "ccre_table", "intergenic_bed", "ont_instrument_report"):
                resource = root / key; resource.write_text("".join(f"chr{i}\t100\t0\t100\t101\n" for i in range(1, 20)) if key == "reference_fai" else "x"); resources[key] = str(resource)
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


class ReportsOnlyTests(unittest.TestCase):
    def test_reports_only_never_rebuilds_config_or_runs_earlier_stages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "logs").mkdir()
            (root / "logs/.active-run.lock").touch()
            results = root / "results"
            config = results / "samples/sample/config"
            config.mkdir(parents=True)
            (config / "project.env").write_text("existing configuration\n")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"samples": [{"sample_id": "sample", "included": True, "ont_bam_files": ["unused.bam"]}], "comparisons": []}))
            with patch.object(runner.sys, "argv", ["run_pipeline.py", "--manifest", str(manifest), "--outdir", str(results), "--run-id", "refresh", "--reports-only"]), patch.object(runner, "write_config", side_effect=AssertionError("must not rewrite config")), patch.object(runner, "load_manifest", side_effect=AssertionError("must not require raw inputs")), patch.object(runner.subprocess, "run") as run:
                self.assertEqual(runner.main(), 0)
                self.assertEqual(len(run.call_args_list), 2)
                self.assertEqual(run.call_args_list[0].args[0], ["bash", str(runner.STAGES[-1])])
                self.assertIn("build_qc_overview.py", run.call_args_list[1].args[0][1])
            self.assertEqual((config / "project.env").read_text(), "existing configuration\n")

    def test_reports_only_refuses_an_active_project_before_starting_a_stage(self):
        import fcntl

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "logs").mkdir()
            manifest = root / "manifest.json"
            manifest.write_text("{}")
            with (root / "logs/.active-run.lock").open("w") as held:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(runner.sys, "argv", ["run_pipeline.py", "--manifest", str(manifest), "--outdir", str(root / "results"), "--run-id", "refresh", "--reports-only"]), patch.object(runner.subprocess, "run") as run:
                    self.assertEqual(runner.main(), 1)
                    run.assert_not_called()
