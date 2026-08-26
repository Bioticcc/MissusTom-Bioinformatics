from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from missus_tom.config import settings
from missus_tom.models.manifest import ExecutionProfile, ProjectManifest, ReadLayout
from missus_tom.models.preflight import CheckStatus, PreflightCheck, SystemPreflightResult


def _version_check(
    check_id: str,
    label: str,
    executable: str,
    arguments: list[str],
    *,
    optional: bool,
) -> PreflightCheck:
    path = shutil.which(executable)
    if path is None:
        return PreflightCheck(
            check_id=check_id,
            label=label,
            status=CheckStatus.NOT_CONFIGURED if optional else CheckStatus.WARNING,
            message=f"{label} was not found in PATH",
        )
    try:
        result = subprocess.run(
            [path, *arguments],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        output = (result.stdout or result.stderr).strip().splitlines()
        version = output[0][:300] if output else "version output unavailable"
        status = CheckStatus.PASSED if result.returncode == 0 else CheckStatus.WARNING
        return PreflightCheck(
            check_id=check_id,
            label=label,
            status=status,
            message=version,
            details={"path": path, "exit_code": result.returncode},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return PreflightCheck(
            check_id=check_id,
            label=label,
            status=CheckStatus.WARNING,
            message=f"Version check failed: {exc}",
            details={"path": path},
        )


def _memory_bytes() -> int | None:
    try:
        with Path("/proc/meminfo").open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def system_preflight() -> SystemPreflightResult:
    memory = _memory_bytes()
    disk = shutil.disk_usage(Path.home())
    java_check = _version_check("java", "Java", "java", ["-version"], optional=False)
    nextflow_check = _version_check("nextflow", "Nextflow", "nextflow", ["-version"], optional=True)
    docker_check = _version_check(
        "docker",
        "Docker",
        "docker",
        ["version", "--format", "{{.Server.Version}}"],
        optional=True,
    )
    checks = [
        PreflightCheck(
            check_id="operating_system",
            label="Operating system",
            status=CheckStatus.PASSED,
            message=f"{platform.system()} {platform.release()}",
            details={"platform": platform.platform()},
        ),
        PreflightCheck(
            check_id="cpu",
            label="CPU",
            status=CheckStatus.PASSED,
            message=f"{os.cpu_count() or 1} logical CPU(s) available",
            details={"logical_cpus": os.cpu_count() or 1},
        ),
        PreflightCheck(
            check_id="memory",
            label="Available memory",
            status=CheckStatus.PASSED if memory is not None else CheckStatus.WARNING,
            message=f"{memory / 1024**3:.1f} GiB available" if memory else "Unavailable",
            details={"available_bytes": memory},
        ),
        PreflightCheck(
            check_id="disk",
            label="Available disk space",
            status=CheckStatus.PASSED,
            message=f"{disk.free / 1024**3:.1f} GiB free on the user-data filesystem",
            details={"free_bytes": disk.free},
        ),
        java_check,
        nextflow_check,
        docker_check,
        _version_check("apptainer", "Apptainer", "apptainer", ["--version"], optional=True),
        PreflightCheck(
            check_id="bulk_adapter",
            label="Bulk RNA-seq adapter",
            status=CheckStatus.PASSED if settings.execution_enabled else CheckStatus.NOT_CONFIGURED,
            message=(
                "Controlled human demo execution is enabled"
                if settings.execution_enabled
                else "Controlled execution is disabled in this backend process"
            ),
        ),
    ]
    return SystemPreflightResult(
        ready_for_framework=True,
        ready_for_real_execution=(
            settings.execution_enabled
            and java_check.status == CheckStatus.PASSED
            and nextflow_check.status == CheckStatus.PASSED
            and docker_check.status == CheckStatus.PASSED
        ),
        checks=checks,
    )


def _output_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def project_preflight(manifest: ProjectManifest) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    input_path = Path(manifest.input_directory)
    output_path = Path(manifest.output_directory)

    input_ok = input_path.is_dir() and os.access(input_path, os.R_OK | os.X_OK)
    checks.append(
        PreflightCheck(
            check_id="input_directory",
            label="Input directory",
            status=CheckStatus.PASSED if input_ok else CheckStatus.BLOCKING,
            message="Input directory exists and is readable"
            if input_ok
            else "Input directory must exist and be readable",
            details={"path": str(input_path)},
        )
    )

    output_parent = _output_parent(output_path)
    output_ok = output_path.is_dir() and os.access(output_path, os.W_OK | os.X_OK)
    creatable = output_parent.is_dir() and os.access(output_parent, os.W_OK | os.X_OK)
    checks.append(
        PreflightCheck(
            check_id="output_directory",
            label="Output directory",
            status=CheckStatus.PASSED if output_ok or creatable else CheckStatus.BLOCKING,
            message="Output directory is writable"
            if output_ok
            else (
                f"Output directory can be created under {output_parent}"
                if creatable
                else "Output directory is not writable and cannot be created"
            ),
            details={"path": str(output_path), "existing_parent": str(output_parent)},
        )
    )

    same_path = input_path == output_path
    nested_output = input_path in output_path.parents
    output_contains_input = output_path in input_path.parents
    unsafe_output = output_path in {Path("/"), Path.home()} or output_contains_input
    checks.append(
        PreflightCheck(
            check_id="path_separation",
            label="Input/output separation",
            status=CheckStatus.BLOCKING
            if same_path or unsafe_output
            else (CheckStatus.WARNING if nested_output else CheckStatus.PASSED),
            message=(
                "Input and output directories are identical"
                if same_path
                else "Output is an unsafe broad directory or contains the input tree"
            )
            if same_path or unsafe_output
            else (
                "Output is nested inside the input tree; confirm this is intentional"
                if nested_output
                else "Input and output directories are separated"
            ),
        )
    )

    included = [sample for sample in manifest.samples if sample.included]
    ids = [sample.sample_id for sample in included]
    duplicate_ids = sorted(sample_id for sample_id, count in Counter(ids).items() if count > 1)
    checks.append(
        PreflightCheck(
            check_id="sample_identifiers",
            label="Sample identifiers",
            status=CheckStatus.BLOCKING if duplicate_ids or not included else CheckStatus.PASSED,
            message=(
                f"Duplicate sample identifiers: {', '.join(duplicate_ids)}"
                if duplicate_ids
                else (
                    "No samples are included"
                    if not included
                    else f"{len(included)} unique sample(s)"
                )
            ),
        )
    )

    pairing_errors: list[str] = []
    assigned_fastqs: list[str] = []
    missing_or_unreadable: list[str] = []
    for sample in included:
        if manifest.read_layout == ReadLayout.PAIRED_END and len(sample.r1_files) != len(
            sample.r2_files
        ):
            pairing_errors.append(sample.sample_id)
        if manifest.read_layout == ReadLayout.SINGLE_END and sample.r2_files:
            pairing_errors.append(sample.sample_id)
        for filename in [*sample.r1_files, *sample.r2_files]:
            assigned_fastqs.append(filename)
            fastq_path = Path(filename)
            if not fastq_path.is_file() or not os.access(fastq_path, os.R_OK):
                missing_or_unreadable.append(filename)

    duplicate_assignments = sorted(
        filename for filename, count in Counter(assigned_fastqs).items() if count > 1
    )
    assignment_failures = bool(pairing_errors or missing_or_unreadable or duplicate_assignments)
    if pairing_errors:
        assignment_message = f"Inconsistent mate counts: {', '.join(pairing_errors)}"
    elif missing_or_unreadable:
        assignment_message = (
            f"{len(missing_or_unreadable)} assigned FASTQ file(s) are missing or unreadable"
        )
    elif duplicate_assignments:
        assignment_message = (
            f"{len(duplicate_assignments)} FASTQ file(s) are assigned more than once"
        )
    else:
        assignment_message = "FASTQ assignments are internally consistent and readable"
    checks.append(
        PreflightCheck(
            check_id="fastq_pairing",
            label="FASTQ assignments",
            status=CheckStatus.BLOCKING if assignment_failures else CheckStatus.PASSED,
            message=assignment_message,
            details={
                "missing_or_unreadable_count": len(missing_or_unreadable),
                "duplicate_assignment_count": len(duplicate_assignments),
            },
        )
    )

    unassigned_groups = [sample.sample_id for sample in included if not sample.condition.strip()]
    groups = {sample.condition for sample in included if sample.condition.strip()}
    checks.append(
        PreflightCheck(
            check_id="experimental_groups",
            label="Experimental groups",
            status=CheckStatus.BLOCKING if unassigned_groups else CheckStatus.PASSED,
            message=f"Missing condition: {', '.join(unassigned_groups)}"
            if unassigned_groups
            else f"Assigned groups: {', '.join(sorted(groups))}",
        )
    )

    invalid_contrasts = [
        comparison.comparison_id
        for comparison in manifest.comparisons
        if comparison.numerator not in groups or comparison.denominator not in groups
    ]
    comparison_status = (
        CheckStatus.BLOCKING
        if invalid_contrasts
        else (CheckStatus.WARNING if not manifest.comparisons else CheckStatus.PASSED)
    )
    checks.append(
        PreflightCheck(
            check_id="comparisons",
            label="Requested comparisons",
            status=comparison_status,
            message=f"Contrasts reference unknown groups: {', '.join(invalid_contrasts)}"
            if invalid_contrasts
            else (
                f"{len(manifest.comparisons)} contrast(s) are valid"
                if manifest.comparisons
                else "No comparisons have been requested"
            ),
        )
    )

    replicates: dict[str, set[str]] = defaultdict(set)
    for sample in included:
        replicates[sample.condition].add(sample.biological_replicate)
    low_replicates = sorted(group for group, values in replicates.items() if len(values) < 2)
    checks.append(
        PreflightCheck(
            check_id="replicates",
            label="Biological replicates",
            status=CheckStatus.WARNING if low_replicates else CheckStatus.PASSED,
            message=f"Fewer than two biological replicates: {', '.join(low_replicates)}"
            if low_replicates
            else "Replicate counts are visible and at least two per group",
            details={group: len(values) for group, values in sorted(replicates.items())},
        )
    )

    disk = shutil.disk_usage(output_parent)
    checks.append(
        PreflightCheck(
            check_id="project_disk_space",
            label="Project disk space",
            status=CheckStatus.WARNING if disk.free < 10 * 1024**3 else CheckStatus.PASSED,
            message=f"{disk.free / 1024**3:.1f} GiB free",
            details={"free_bytes": disk.free, "path": str(output_parent)},
        )
    )

    missing_references = [
        key for key, value in manifest.reference_resources.items() if not Path(value).is_file()
    ]
    if not manifest.reference_resources:
        reference_status = CheckStatus.NOT_CONFIGURED
        reference_message = "Reference resource file paths have not been configured"
    elif missing_references:
        reference_status = CheckStatus.BLOCKING
        reference_message = f"Missing reference resources: {', '.join(sorted(missing_references))}"
    else:
        reference_status = CheckStatus.PASSED
        reference_message = f"{len(manifest.reference_resources)} reference resource(s) found"
    checks.append(
        PreflightCheck(
            check_id="references",
            label="Reference resources",
            status=reference_status,
            message=reference_message,
        )
    )

    required_runtime = {
        ExecutionProfile.LOCAL: "nextflow",
        ExecutionProfile.DOCKER: "docker",
        ExecutionProfile.APPTAINER: "apptainer",
    }[manifest.execution_profile]
    runtime_found = shutil.which(required_runtime) is not None
    checks.append(
        PreflightCheck(
            check_id="execution_profile",
            label="Execution profile",
            status=CheckStatus.PASSED if runtime_found else CheckStatus.NOT_CONFIGURED,
            message=(
                f"{manifest.execution_profile.value} tooling detected"
                if runtime_found
                else f"{required_runtime} is not installed; this does not block project setup"
            ),
        )
    )
    checks.append(
        PreflightCheck(
            check_id="real_execution",
            label="Scientific execution",
            status=CheckStatus.PASSED if settings.execution_enabled else CheckStatus.NOT_CONFIGURED,
            message=(
                "Controlled human demo execution is enabled"
                if settings.execution_enabled
                else "Controlled execution is disabled for this backend process"
            ),
        )
    )
    return checks
