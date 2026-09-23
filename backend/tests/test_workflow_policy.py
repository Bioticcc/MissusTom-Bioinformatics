from __future__ import annotations

import re
import subprocess
from pathlib import Path


def test_release_publish_job_targets_repository_without_checkout() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    release_workflow = (repository_root / ".github" / "workflows" / "release-linux.yml").read_text(
        encoding="utf-8"
    )
    publish_job = release_workflow.split("\n  publish:\n", maxsplit=1)[1]

    assert "actions/checkout" not in publish_job
    assert "GH_REPO: ${{ github.repository }}" in publish_job
    assert 'gh release view "${RELEASE_TAG}" --repo "${GH_REPO}"' in publish_job
    assert 'gh release upload "${RELEASE_TAG}" "${release_assets[@]}"' in publish_job
    assert "--clobber" in publish_job
    assert 'gh release create "${RELEASE_TAG}" "${release_assets[@]}"' in publish_job
    assert 'gh release delete-asset "${RELEASE_TAG}" "${asset_name}"' in publish_job
    assert "--yes" in publish_job
    assert "--json assets --jq '.assets[].name'" in publish_job
    assert publish_job.count('--repo "${GH_REPO}"') == 5


def test_linux_release_is_a_deb_only_zip() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    release_workflow = (repository_root / ".github" / "workflows" / "release-linux.yml").read_text(
        encoding="utf-8"
    )
    release_config_path = repository_root / "desktop" / "src-tauri" / "tauri.release.conf.json"
    release_config = release_config_path.read_text(encoding="utf-8")

    assert '"targets": ["deb"]' in release_config
    assert "appimage" not in release_workflow.lower()
    assert "bash scripts/create-linux-release-zip.sh" in release_workflow
    assert '--version "${release_version}"' in release_workflow
    assert '--deb "${deb_source}"' in release_workflow
    assert '--output-dir "${artifact_directory}"' in release_workflow
    release_zip = '"release-artifacts/ver${release_version}_Linux-x86_64_Ubuntu-Debian.zip"'
    assert release_zip in release_workflow
    assert "path: release-artifacts/*.zip" in release_workflow


def test_project_settings_exports_are_ignored_except_for_the_sanitized_example() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    for export_name in ("BRS-Human-01-debug-settings.json", "Test1-debug-settings.json"):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", export_name],
            cwd=repository_root,
            check=False,
        )
        assert result.returncode == 0, f"{export_name} must be ignored"

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "example_settings.json"],
        cwd=repository_root,
        check=False,
    )
    assert result.returncode == 1, "the sanitized example must remain trackable"


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
    native_retry_policy = "task.exitStatus in [134, 139] ? 'retry' : 'terminate'"
    kallisto_retry_policy = "task.exitStatus in [134, 139, 240] ? 'retry' : 'terminate'"
    fastqc_block = re.search(
        r"withLabel:\s*fastqc\s*\{(?P<body>.*?)^\s*\}", resources, re.MULTILINE | re.DOTALL
    )
    kallisto_block = re.search(
        r"withLabel:\s*kallisto\s*\{(?P<body>.*?)^\s*\}", resources, re.MULTILINE | re.DOTALL
    )

    assert fastqc_block is not None
    assert native_retry_policy in fastqc_block.group("body")
    assert "maxRetries = 1" in fastqc_block.group("body")
    assert kallisto_block is not None
    assert kallisto_retry_policy in kallisto_block.group("body")
    assert "maxRetries = 1" in kallisto_block.group("body")


def test_kallisto_watchdog_defines_bounded_two_hour_retry_signal() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (repository_root / "workflows" / "bulk_rnaseq" / "main.nf").read_text(
        encoding="utf-8"
    )
    process_block = re.search(
        r"process KALLISTO_QUANT \{(?P<body>.*?)^\}",
        workflow,
        re.MULTILINE | re.DOTALL,
    )

    assert process_block is not None
    body = process_block.group("body")
    assert "sleep 7200" in body
    assert re.search(r'kill -0 ["\']?\\?\$kallisto_pid', body)
    assert re.search(r'kill -TERM ["\']?\\?\$kallisto_pid', body)
    assert "sleep 60" in body
    assert re.search(r'kill -KILL ["\']?\\?\$kallisto_pid', body)
    assert re.search(r'wait ["\']?\\?\$kallisto_pid', body)
    assert re.search(r"kallisto_status\s*=\s*\\?\$\?", body)
    assert ".kallisto_time_limit_exceeded" in body
    assert "exit 240" in body
    assert re.search(r'exit ["\']?\\?\$kallisto_status', body)


def test_fastqc_retry_isolates_each_staged_fastq_in_a_one_thread_jvm() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (repository_root / "workflows" / "bulk_rnaseq" / "main.nf").read_text(
        encoding="utf-8"
    )

    for process_name in ("FASTQC_RAW", "FASTQC_CLEAN"):
        process_block = re.search(
            rf"process {process_name} \{{(?P<body>.*?)^\}}",
            workflow,
            re.MULTILINE | re.DOTALL,
        )

        assert process_block is not None
        body = process_block.group("body")
        assert re.search(r"task\.attempt\s*>\s*1", body)
        assert "run_fastqc_with_native_retry" in body
        assert "fastqc --threads ${task.cpus} --outdir ." in body


def test_fastqc_isolated_fallback_retries_each_file_once_for_native_crashes_only() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (repository_root / "workflows" / "bulk_rnaseq" / "main.nf").read_text(
        encoding="utf-8"
    )

    # A native JVM crash is recoverable once per staged file.  Any other FastQC
    # failure must retain its original status so Nextflow's error strategy can
    # terminate the task rather than masking a real input/tool failure.
    for process_name in ("FASTQC_RAW", "FASTQC_CLEAN"):
        process_block = re.search(
            rf"process {process_name} \{{(?P<body>.*?)^\}}",
            workflow,
            re.MULTILINE | re.DOTALL,
        )

        assert process_block is not None
        body = process_block.group("body")
        fallback = re.search(
            r"run_fastqc_with_native_retry\s*\(\)\s*\{(?P<body>.*?)^\s*\}",
            body,
            re.MULTILINE | re.DOTALL,
        )

        assert fallback is not None
        fallback_body = fallback.group("body")
        assert re.search(r"local\s+max_attempts\s*=\s*2\b", fallback_body)
        assert re.search(r"while\s+\(\(\s*attempt\s*<=\s*max_attempts\s*\)\)", fallback_body)
        assert re.search(
            r"fastqc\s+--threads\s+1\s+--outdir\s+\.\s+['\"]?\\?\$read['\"]?",
            fallback_body,
        )
        assert re.search(r"fastqc_status\s*=\s*\\?\$\?", fallback_body)
        assert re.search(
            r"fastqc_status\s*(?:-eq|-ne|==|!=)\s*134.*?"
            r"fastqc_status\s*(?:-eq|-ne|==|!=)\s*139",
            fallback_body,
            re.DOTALL,
        )
        assert re.search(r"attempt\s*(?:-ge|>=)\s*max_attempts", fallback_body)
        assert re.search(r"return\s+['\"]?\\?\$fastqc_status", fallback_body)


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


def test_local_profile_disables_docker_and_uses_the_host_executor() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    config = (repository_root / "workflows" / "bulk_rnaseq" / "nextflow.config").read_text(
        encoding="utf-8"
    )
    local_profile = re.search(r"local \{(?P<body>.*?)\n    \}", config, re.DOTALL)
    assert local_profile is not None
    assert "process.executor = 'local'" in local_profile.group("body")
    assert "docker.enabled = false" in local_profile.group("body")
    assert "docker.enabled = true" in config


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
