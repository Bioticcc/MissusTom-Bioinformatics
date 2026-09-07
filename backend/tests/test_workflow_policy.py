from __future__ import annotations

import re
from pathlib import Path


def test_local_workflow_has_no_fixed_task_wall_time() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow_root = repository_root / "workflows" / "bulk_rnaseq"
    workflow_sources = [
        workflow_root / "main.nf",
        workflow_root / "nextflow.config",
        *sorted((workflow_root / "conf").glob("*.config")),
    ]

    time_directive = re.compile(r"^\s*time(?:\s*=|\s+['\"])", re.MULTILINE)
    offenders = [
        str(path.relative_to(repository_root))
        for path in workflow_sources
        if time_directive.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], f"fixed task wall-time directives found in: {offenders}"


def test_workflow_retries_native_crashes_once() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow_root = repository_root / "workflows" / "bulk_rnaseq"
    config = (workflow_root / "nextflow.config").read_text(encoding="utf-8")
    resources = (workflow_root / "conf" / "resources.config").read_text(encoding="utf-8")

    assert "task.exitStatus == 139 ? 'retry' : 'terminate'" in config
    assert re.search(r"^\s*maxRetries\s*=\s*1\s*$", config, re.MULTILINE)
    assert "task.exitStatus in [134, 139] ? 'retry' : 'terminate'" in resources
    assert resources.count("maxRetries = 1") == 1


def test_workflow_resource_profile_is_a_total_local_executor_budget() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow_root = repository_root / "workflows" / "bulk_rnaseq"
    config = (workflow_root / "nextflow.config").read_text(encoding="utf-8")
    resources = (workflow_root / "conf" / "resources.config").read_text(encoding="utf-8")
    workflow = (workflow_root / "main.nf").read_text(encoding="utf-8")

    assert "cpus = params.max_cpus as Integer" in config
    assert 'memory = "${params.max_memory_gb as Double} GB"' in config
    assert "queueSize = params.max_parallel_tasks as Integer" in config
    assert "Integer positiveIntegerParameter(value, String parameterName)" in workflow
    assert "Double positiveFiniteParameter(value, String parameterName)" in workflow
    assert "positiveIntegerParameter(params.max_cpus, 'max_cpus')" in workflow
    assert "positiveFiniteParameter(params.max_memory_gb, 'max_memory_gb')" in workflow
    assert "positiveIntegerParameter(params.max_parallel_tasks, 'max_parallel_tasks')" in workflow
    assert "maxForks = params.max_parallel_tasks" not in resources


def test_docker_tasks_have_hard_resource_limits_and_scoped_run_label() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow_root = repository_root / "workflows" / "bulk_rnaseq"
    config = (workflow_root / "nextflow.config").read_text(encoding="utf-8")
    workflow = (workflow_root / "main.nf").read_text(encoding="utf-8")

    assert "docker.runOptions = '--network none'" in config
    assert '"--cpus ${task.cpus} --memory-swap ${task.memory.toBytes()}"' in config
    assert '" --label missus_tom.run_id=${params.run_id}"' in config
    assert "run_id = null" in config
    assert "run_id must be a canonical UUID when supplied." in workflow
    assert "OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1" in workflow
    assert "RCPP_PARALLEL_NUM_THREADS=1" in workflow


def test_workflow_uses_kallisto_052_container() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    resources = (
        repository_root / "workflows" / "bulk_rnaseq" / "conf" / "resources.config"
    ).read_text(encoding="utf-8")

    expected_digest = (
        "kallisto@sha256:7615f563aa2948fd087f7e4a666e252f275c60b2070729bc9a3804c8873527e5"
    )
    assert expected_digest in resources


def test_workflow_defaults_to_quantification_and_validates_start_stage() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow_root = repository_root / "workflows" / "bulk_rnaseq"
    config = (workflow_root / "nextflow.config").read_text(encoding="utf-8")
    workflow = (workflow_root / "main.nf").read_text(encoding="utf-8")

    assert "start_stage = 'quantification'" in config
    assert "start_stage in ['quantification', 'analysis']" in workflow
    assert "sample.abundance_tsv ?: (" in workflow
    assert '"${params.outdir}/counts/kallisto/${sample.sample_id}/abundance.tsv"' in workflow


def test_workflow_is_not_restricted_to_demo_sample_names() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (repository_root / "workflows" / "bulk_rnaseq" / "main.nf").read_text(
        encoding="utf-8"
    )

    assert "expected_demo_ids" not in workflow
    assert "OD1_vs_H" not in workflow
    assert "included_samples.size() != 8" not in workflow
    assert "manifest_data.comparisons.each" in workflow


def test_workflow_passes_explicit_intervention_filters_to_analysis() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow_root = repository_root / "workflows" / "bulk_rnaseq"
    workflow = (workflow_root / "main.nf").read_text(encoding="utf-8")
    analysis = (workflow_root / "bin" / "full_human_analysis.R").read_text(encoding="utf-8")

    assert "sample.covariates?.intervention" in workflow
    assert "comparison.intervention" in workflow
    assert "selected_samples$intervention == intervention_filter" in analysis


def test_raw_read_lists_do_not_concatenate_single_lane_paths() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (repository_root / "workflows" / "bulk_rnaseq" / "main.nf").read_text(
        encoding="utf-8"
    )

    assert "List asFileList(value)" in workflow
    assert "asFileList(read1_files) + asFileList(read2_files)" in workflow
    assert "def r1_lanes = asFileList(read1_files)" in workflow
    assert "def r2_lanes = asFileList(read2_files)" in workflow
    assert "r1_lanes.size() == 1 ? shellQuote(r1_lanes[0])" in workflow
    assert "r2_lanes.size() == 1 ? shellQuote(r2_lanes[0])" in workflow
    assert "if (r1_lanes.size() > 1)" in workflow
    assert "if (r2_lanes.size() > 1)" in workflow
    assert "${r1_input} ${r2_input}" in workflow
    assert "cat ${r1_args}" not in workflow
    assert "cat ${r2_args}" not in workflow
    assert "(read1_files + read2_files).collect" not in workflow
