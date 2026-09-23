from __future__ import annotations

import math
import os
import platform
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from missus_tom.config import settings
from missus_tom.models.manifest import ExecutionProfile, ProjectManifest, ReadLayout
from missus_tom.models.preflight import CheckStatus, PreflightCheck, SystemPreflightResult
from missus_tom.services.dependencies import (
    _managed_root,
    dependency_installer,
    runtime_environment,
    runtime_tool,
)
from missus_tom.services.quantifications import has_kallisto_header
from missus_tom.services.resources import (
    GIB,
    StorageInspection,
    effective_free_bytes,
    execution_resource_checks,
    inspect_host_resources,
    inspect_storage,
)


def _version_check(
    check_id: str,
    label: str,
    executable: str,
    arguments: list[str],
    *,
    optional: bool,
    pipeline_identifier: str = "bulk-rnaseq",
) -> PreflightCheck:
    path = runtime_tool(executable, pipeline_identifier)
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
            env=runtime_environment(pipeline_identifier),
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


def _managed_tool_label(label: str, path: str | None, pipeline_identifier: str) -> str:
    if path and str(_managed_root(pipeline_identifier)) in path:
        return f"{label} (managed)"
    return label


def _disk_preflight_check(
    check_id: str,
    label: str,
    inspection: StorageInspection,
) -> PreflightCheck:
    effective_free = effective_free_bytes(inspection)
    fstype = inspection.filesystem_type or "unknown"
    host_note = (
        f"; Windows host bound to {inspection.host_free_bytes / GIB:.1f} GiB free"
        if inspection.host_free_bytes is not None
        else ""
    )
    message = (
        f"{effective_free / GIB:.1f} GiB free on {inspection.path} "
        f"({fstype}, measurement={inspection.measurement}){host_note}"
    )
    if inspection.warning:
        message = f"{message}. {inspection.warning}"
    if effective_free < 2 * GIB:
        status = CheckStatus.BLOCKING
    elif (
        effective_free < 10 * GIB
        or inspection.measurement == "wsl_virtual"
        or inspection.warning
    ):
        status = CheckStatus.WARNING
    else:
        status = CheckStatus.PASSED
    return PreflightCheck(
        check_id=check_id,
        label=label,
        status=status,
        message=message,
        details={
            "path": inspection.path,
            "filesystem_type": inspection.filesystem_type,
            "free_bytes": inspection.free_bytes,
            "host_free_bytes": inspection.host_free_bytes,
            "measurement": inspection.measurement,
            "warning": inspection.warning,
        },
    )


def _managed_pipeline_check(
    pipeline_identifier: str, *, check_id: str, label: str
) -> PreflightCheck:
    status_payload = dependency_installer.status(pipeline_identifier)
    if status_payload.manual_requirements:
        return PreflightCheck(
            check_id=check_id,
            label=label,
            status=CheckStatus.WARNING,
            message="; ".join(status_payload.manual_requirements),
            details={"missing": status_payload.missing},
        )
    if not status_payload.missing:
        return PreflightCheck(
            check_id=check_id,
            label=label,
            status=CheckStatus.PASSED,
            message="All required managed tools are installed",
        )
    missing = ", ".join(status_payload.missing)
    message = (
        f"Missing managed tools: {missing}. "
        "Open Setup and install pipeline dependencies before running workflows."
    )
    return PreflightCheck(
        check_id=check_id,
        label=label,
        status=CheckStatus.WARNING,
        message=message,
        details={"missing": status_payload.missing, "installable": status_payload.installable},
    )


def system_preflight() -> SystemPreflightResult:
    host = inspect_host_resources()
    disk_state = inspect_storage(settings.state_directory)
    disk_home = inspect_storage(Path.home())
    java_check = _version_check("java", "Java", "java", ["-version"], optional=False)
    if java_check.details and isinstance(java_check.details.get("path"), str):
        java_check = java_check.model_copy(
            update={
                "label": _managed_tool_label(
                    java_check.label, java_check.details["path"], "bulk-rnaseq"
                )
            }
        )
    nextflow_check = _version_check(
        "nextflow", "Nextflow", "nextflow", ["-version"], optional=True
    )
    if nextflow_check.details and isinstance(nextflow_check.details.get("path"), str):
        nextflow_check = nextflow_check.model_copy(
            update={
                "label": _managed_tool_label(
                    nextflow_check.label, nextflow_check.details["path"], "bulk-rnaseq"
                )
            }
        )
    memory_ok = host.available_memory_bytes is not None
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
            message=f"{host.logical_cpus} logical CPU(s) available for workflows",
            details={"logical_cpus": host.logical_cpus},
        ),
        PreflightCheck(
            check_id="memory",
            label="Available memory",
            status=CheckStatus.PASSED if memory_ok else CheckStatus.WARNING,
            message=(
                f"{host.available_memory_bytes / GIB:.1f} GiB available"
                if memory_ok
                else "Unavailable"
            ),
            details={
                "available_bytes": host.available_memory_bytes,
                "total_bytes": host.total_memory_bytes,
            },
        ),
        _disk_preflight_check("disk_state", "Application state filesystem", disk_state),
        _disk_preflight_check("disk_home", "User-data filesystem", disk_home),
        java_check,
        nextflow_check,
        _managed_pipeline_check(
            "bulk-rnaseq",
            check_id="managed_dependencies_bulk_rnaseq",
            label="Bulk RNA-seq managed dependencies",
        ),
        _managed_pipeline_check(
            "ont-analysis",
            check_id="managed_dependencies_ont_analysis",
            label="ONT analysis managed dependencies",
        ),
        PreflightCheck(
            check_id="bulk_adapter",
            label="Bulk RNA-seq adapter",
            status=CheckStatus.PASSED if settings.execution_enabled else CheckStatus.NOT_CONFIGURED,
            message=(
                "Human paired-end bulk RNA-seq execution is enabled"
                if settings.execution_enabled
                else "Execution is disabled in this backend process"
            ),
        ),
    ]
    return SystemPreflightResult(
        ready_for_framework=True,
        ready_for_real_execution=(
            settings.execution_enabled
            and java_check.status == CheckStatus.PASSED
            and nextflow_check.status == CheckStatus.PASSED
        ),
        checks=checks,
    )


def _output_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _summarize_identifiers(values: list[str], *, limit: int = 8) -> str:
    shown = values[:limit]
    summary = ", ".join(shown)
    remaining = len(values) - len(shown)
    return f"{summary} (+{remaining} more)" if remaining else summary


def project_preflight(manifest: ProjectManifest) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    input_path = Path(manifest.input_directory)
    output_path = Path(manifest.output_directory)
    configured_start_stage = manifest.parameters.get("start_stage", "quantification")
    analysis_only = configured_start_stage == "analysis"

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
    if not analysis_only:
        for sample in included:
            if manifest.read_layout == ReadLayout.PAIRED_END and (
                not sample.r1_files
                or not sample.r2_files
                or len(sample.r1_files) != len(sample.r2_files)
            ):
                pairing_errors.append(sample.sample_id)
            if manifest.read_layout == ReadLayout.SINGLE_END and (
                not sample.r1_files or sample.r2_files
            ):
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
            status=(
                CheckStatus.NOT_CONFIGURED
                if analysis_only
                else (CheckStatus.BLOCKING if assignment_failures else CheckStatus.PASSED)
            ),
            message=("Skipped for analysis-only input" if analysis_only else assignment_message),
            details={
                "missing_or_unreadable_count": len(missing_or_unreadable),
                "duplicate_assignment_count": len(duplicate_assignments),
            },
        )
    )

    missing_abundance: list[str] = []
    invalid_abundance: list[str] = []
    if analysis_only:
        for sample in included:
            if not sample.abundance_tsv:
                missing_abundance.append(sample.sample_id)
                continue
            abundance_path = Path(sample.abundance_tsv)
            try:
                resolved_abundance = abundance_path.resolve(strict=True)
            except OSError:
                missing_abundance.append(sample.sample_id)
                continue
            if (
                not resolved_abundance.is_file()
                or abundance_path.is_symlink()
                or not resolved_abundance.is_relative_to(input_path.resolve(strict=False))
                or not has_kallisto_header(resolved_abundance)
            ):
                invalid_abundance.append(sample.sample_id)
    abundance_failures = bool(missing_abundance or invalid_abundance)
    if missing_abundance:
        abundance_message = "Missing abundance.tsv input for: " + _summarize_identifiers(
            missing_abundance
        )
    elif invalid_abundance:
        abundance_message = (
            "Invalid Kallisto abundance tables under the input folder: "
            + _summarize_identifiers(invalid_abundance)
        )
    else:
        abundance_message = f"{len(included)} Kallisto abundance table(s) assigned"
    checks.append(
        PreflightCheck(
            check_id="quantification_inputs",
            label="Existing Kallisto results",
            status=(
                CheckStatus.BLOCKING
                if analysis_only and abundance_failures
                else (CheckStatus.PASSED if analysis_only else CheckStatus.NOT_CONFIGURED)
            ),
            message=(
                abundance_message
                if analysis_only
                else "Not required when starting with FASTQ quantification"
            ),
        )
    )

    unassigned_groups = [sample.sample_id for sample in included if not sample.condition.strip()]
    unassigned_replicates = [
        sample.sample_id for sample in included if not sample.biological_replicate.strip()
    ]
    groups = {sample.condition for sample in included if sample.condition.strip()}
    interventions = {
        value
        for sample in included
        if isinstance((value := sample.covariates.get("intervention")), str) and value
    }
    checks.append(
        PreflightCheck(
            check_id="experimental_groups",
            label="Experimental groups",
            status=CheckStatus.BLOCKING if unassigned_groups else CheckStatus.PASSED,
            message=f"Missing condition: {_summarize_identifiers(unassigned_groups)}"
            if unassigned_groups
            else f"Assigned groups: {', '.join(sorted(groups))}",
        )
    )
    checks.append(
        PreflightCheck(
            check_id="replicate_assignments",
            label="Replicate assignments",
            status=CheckStatus.WARNING if unassigned_replicates else CheckStatus.PASSED,
            message=(
                "Optional biological replicate IDs are missing; each sample will be counted "
                "separately for group-size validation: "
                + _summarize_identifiers(unassigned_replicates)
                if unassigned_replicates
                else "Every included sample has a biological replicate identifier"
            ),
        )
    )

    invalid_contrasts = [
        comparison.comparison_id
        for comparison in manifest.comparisons
        if comparison.numerator not in groups or comparison.denominator not in groups
    ]
    invalid_interventions = [
        comparison.comparison_id
        for comparison in manifest.comparisons
        if comparison.intervention and comparison.intervention not in interventions
    ]
    comparison_status = (
        CheckStatus.BLOCKING
        if invalid_contrasts or invalid_interventions or not manifest.comparisons
        else CheckStatus.PASSED
    )
    checks.append(
        PreflightCheck(
            check_id="comparisons",
            label="Requested comparisons",
            status=comparison_status,
            message=(
                f"Contrasts reference unknown groups: {', '.join(invalid_contrasts)}"
                if invalid_contrasts
                else (
                    "Contrasts reference unknown interventions: " + ", ".join(invalid_interventions)
                )
            )
            if invalid_contrasts or invalid_interventions
            else (
                f"{len(manifest.comparisons)} contrast(s) are valid"
                if manifest.comparisons
                else "At least one comparison is required"
            ),
        )
    )

    replicates: dict[str, set[str]] = defaultdict(set)
    for sample in included:
        replicates[sample.condition].add(sample.biological_replicate or sample.sample_id)
    configured_minimum = manifest.parameters.get("minimum_group_size", 2)
    minimum_is_explicit = "minimum_group_size" in manifest.parameters
    minimum_group_size = (
        configured_minimum
        if isinstance(configured_minimum, int) and not isinstance(configured_minimum, bool)
        else 2
    )
    comparison_replicates: dict[str, dict[str, set[str]]] = {}
    for comparison in manifest.comparisons:
        counts: dict[str, set[str]] = defaultdict(set)
        for sample in included:
            intervention = sample.covariates.get("intervention")
            if comparison.intervention and intervention != comparison.intervention:
                continue
            if sample.condition in (comparison.numerator, comparison.denominator):
                counts[sample.condition].add(sample.biological_replicate or sample.sample_id)
        comparison_replicates[comparison.comparison_id] = counts
    low_replicates = sorted(
        f"{comparison.comparison_id}:{group}"
        for comparison in manifest.comparisons
        for group in (comparison.numerator, comparison.denominator)
        if len(comparison_replicates[comparison.comparison_id].get(group, set()))
        < minimum_group_size
    )
    if not manifest.comparisons:
        low_replicates = sorted(
            group for group, values in replicates.items() if len(values) < minimum_group_size
        )
    design_incomplete = bool(unassigned_groups)
    checks.append(
        PreflightCheck(
            check_id="replicates",
            label="Biological replicates",
            status=(
                CheckStatus.NOT_CONFIGURED
                if design_incomplete
                else (
                    CheckStatus.BLOCKING
                    if low_replicates and minimum_is_explicit
                    else (CheckStatus.WARNING if low_replicates else CheckStatus.PASSED)
                )
            ),
            message=(
                "Complete condition assignments first"
                if design_incomplete
                else (
                    f"Fewer than {minimum_group_size} samples or replicate groups: "
                    f"{', '.join(low_replicates)}"
                )
            )
            if design_incomplete or low_replicates
            else (
                f"At least {minimum_group_size} sample(s) or replicate group(s) "
                "per comparison group"
            ),
            details={group: len(values) for group, values in sorted(replicates.items())},
        )
    )

    parameter_errors: list[str] = []
    if configured_start_stage not in {"quantification", "analysis"}:
        parameter_errors.append("start_stage must be quantification or analysis")
    if (
        not isinstance(configured_minimum, int)
        or isinstance(configured_minimum, bool)
        or configured_minimum < 2
    ):
        parameter_errors.append("minimum_group_size must be an integer of at least 2")
    for key, default, minimum, maximum, exclusive_minimum in (
        ("trim_quality", 20, 0, 50, False),
        ("trim_minimum_length", 20, 1, None, False),
        ("adjusted_p_value", 0.05, 0, 1, True),
        ("absolute_log2_fold_change", 0.30, 0, None, False),
    ):
        value = manifest.parameters.get(key, default)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            parameter_errors.append(f"{key} is outside its supported range")
            continue
        if (
            value < minimum
            or (exclusive_minimum and value == minimum)
            or (maximum is not None and value > maximum)
        ):
            parameter_errors.append(f"{key} is outside its supported range")
    for key in ("adapter_r1", "adapter_r2"):
        value = manifest.parameters.get(key)
        if value is not None and (
            not isinstance(value, str)
            or not re.fullmatch(r"[ACGTRYSWKMBDHVN]+", value.strip(), re.IGNORECASE)
        ):
            parameter_errors.append(f"{key} must be an IUPAC nucleotide sequence")
    if manifest.parameters.get("differential_expression", True) is not True:
        parameter_errors.append("differential_expression must be enabled")
    checks.append(
        PreflightCheck(
            check_id="pipeline_parameters",
            label="Pipeline parameters",
            status=CheckStatus.BLOCKING if parameter_errors else CheckStatus.PASSED,
            message="; ".join(parameter_errors)
            if parameter_errors
            else "Pipeline parameters are valid",
        )
    )

    checks.extend(execution_resource_checks(manifest))

    project_disk = inspect_storage(output_parent)
    checks.append(_disk_preflight_check("project_disk_space", "Project disk space", project_disk))

    required_references = {"biomart"} if analysis_only else {"kallisto_index", "biomart"}
    unconfigured_references = sorted(required_references - manifest.reference_resources.keys())
    missing_references = [
        key for key, value in manifest.reference_resources.items() if not Path(value).is_file()
    ]
    if unconfigured_references or missing_references:
        reference_status = CheckStatus.BLOCKING
        missing = sorted({*unconfigured_references, *missing_references})
        reference_message = f"Missing reference resources: {', '.join(missing)}"
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
    runtime_found = runtime_tool(required_runtime, manifest.pipeline_identifier) is not None
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
                "Human paired-end bulk RNA-seq execution is enabled"
                if settings.execution_enabled
                else "Execution is disabled for this backend process"
            ),
        )
    )
    return checks


def ont_analysis_preflight(manifest: ProjectManifest) -> list[PreflightCheck]:
    """Validate the intentionally narrow local ONT BAM-analysis contract."""
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
            message=(
                "Output directory is writable"
                if output_ok
                else f"Output directory can be created under {output_parent}"
                if creatable
                else "Output directory is not writable and cannot be created"
            ),
            details={"path": str(output_path), "existing_parent": str(output_parent)},
        )
    )
    unsafe_output = (
        input_path == output_path
        or output_path in input_path.parents
        or input_path in output_path.parents
        or output_path in {Path("/"), Path.home()}
    )
    checks.append(
        PreflightCheck(
            check_id="path_separation",
            label="Input/output separation",
            status=CheckStatus.BLOCKING if unsafe_output else CheckStatus.PASSED,
            message="Output must be separate from the input tree"
            if unsafe_output
            else "Input and output directories are separated",
        )
    )

    included = [sample for sample in manifest.samples if sample.included]
    sample_scope_ok = len(included) == 1
    checks.append(
        PreflightCheck(
            check_id="sample_identifiers",
            label="Sample identifiers",
            status=CheckStatus.PASSED if sample_scope_ok else CheckStatus.BLOCKING,
            message="One included ONT sample"
            if sample_scope_ok
            else "ONT analysis currently requires exactly one included sample",
        )
    )
    bam_errors: list[str] = []
    assigned: list[str] = []
    input_root = input_path.resolve(strict=False)
    for sample in included:
        if not sample.ont_bam_files:
            bam_errors.append(f"{sample.sample_id}: no BAM files")
            continue
        for value in sample.ont_bam_files:
            assigned.append(value)
            requested = Path(value)
            try:
                resolved = requested.resolve(strict=True)
            except OSError:
                bam_errors.append(f"{sample.sample_id}: missing BAM")
                continue
            if (
                requested.is_symlink()
                or not resolved.is_file()
                or resolved.suffix.lower() != ".bam"
                or not resolved.is_relative_to(input_root)
            ):
                bam_errors.append(f"{sample.sample_id}: invalid BAM")
    duplicates = sorted(value for value, count in Counter(assigned).items() if count > 1)
    if duplicates:
        bam_errors.append("duplicate BAM assignment")
    basename_collisions = sorted(
        basename
        for basename, count in Counter(Path(value).name for value in assigned).items()
        if count > 1
    )
    if basename_collisions:
        bam_errors.append("BAM basename collision: " + ", ".join(basename_collisions))
    expected_count = manifest.parameters.get("expected_pass_bam_count")
    expected_ok = expected_count is None or (
        isinstance(expected_count, int)
        and not isinstance(expected_count, bool)
        and expected_count > 0
        and expected_count == len(set(assigned))
    )
    checks.append(
        PreflightCheck(
            check_id="expected_pass_bam_count",
            label="Expected passing BAM count",
            status=CheckStatus.PASSED if expected_ok else CheckStatus.BLOCKING,
            message=(
                "Not explicitly configured; using assigned BAM count"
                if expected_count is None
                else f"Expected {expected_count} BAM(s), matching assigned files"
                if expected_ok
                else (
                    "expected_pass_bam_count must be a positive integer matching "
                    "unique assigned BAM files"
                )
            ),
        )
    )
    parameter_errors: list[str] = []
    for key in (
        "coverage_window_size",
        "methylation_window_size",
        "modkit_max_depth",
        "exploration_min_valid_coverage",
        "exploration_min_feature_cpgs",
    ):
        parameter_value = manifest.parameters.get(key)
        if parameter_value is None:
            continue
        maximum = 60_000 if key == "modkit_max_depth" else None
        if (
            not isinstance(parameter_value, int)
            or isinstance(parameter_value, bool)
            or parameter_value <= 0
            or (maximum is not None and parameter_value > maximum)
        ):
            limit = " between 1 and 60000" if maximum is not None else " a positive integer"
            parameter_errors.append(f"{key} must be{limit}")
    coverage_window_size = manifest.parameters.get("coverage_window_size", 100_000)
    methylation_window_size = manifest.parameters.get("methylation_window_size", 100_000)
    if coverage_window_size != methylation_window_size:
        parameter_errors.append(
            "coverage_window_size and methylation_window_size must be equal "
            "for coordinate-aligned Stage05 joins"
        )
    percentile = manifest.parameters.get("modkit_filter_percentile")
    if percentile is not None and (
        not isinstance(percentile, (int, float))
        or isinstance(percentile, bool)
        or not math.isfinite(percentile)
        or not 0 <= percentile < 1
    ):
        parameter_errors.append("modkit_filter_percentile must be a finite value from 0 to <1")
    checks.append(
        PreflightCheck(
            check_id="pipeline_parameters",
            label="ONT pipeline parameters",
            status=CheckStatus.BLOCKING if parameter_errors else CheckStatus.PASSED,
            message="; ".join(parameter_errors)
            if parameter_errors
            else "ONT pipeline parameters are valid",
        )
    )
    checks.append(
        PreflightCheck(
            check_id="ont_bam_files",
            label="ONT BAM files",
            status=CheckStatus.BLOCKING if bam_errors else CheckStatus.PASSED,
            message=(
                "; ".join(bam_errors)
                if bam_errors
                else f"{len(assigned)} regular BAM file(s) under the input directory"
            ),
            details={
                "duplicate_assignment_count": len(duplicates),
                "basename_collision_count": len(basename_collisions),
            },
        )
    )
    genome_ok = manifest.organism == "Mus musculus" and manifest.reference_genome == "GRCm38p6"
    checks.append(
        PreflightCheck(
            check_id="ont_reference_build",
            label="ONT reference build",
            status=CheckStatus.PASSED if genome_ok else CheckStatus.BLOCKING,
            message="Mus musculus GRCm38p6 is selected"
            if genome_ok
            else "ONT analysis requires Mus musculus with GRCm38p6",
        )
    )
    required = {
        "reference_fasta",
        "reference_fai",
        "minimap2_index",
    }
    annotation_resources = {
        "gencode_gff3",
        "cpg_islands",
        "ccre_table",
        "intergenic_bed",
    }
    supplied_annotations = annotation_resources & manifest.reference_resources.keys()
    missing = sorted(required - manifest.reference_resources.keys())
    if supplied_annotations and supplied_annotations != annotation_resources:
        missing.extend(sorted(annotation_resources - supplied_annotations))
    invalid: list[str] = []
    configured_resources = manifest.reference_resources.keys()
    for key in sorted(
        (required | supplied_annotations | {"ont_instrument_report"}) & configured_resources
    ):
        path = Path(manifest.reference_resources[key])
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            invalid.append(key)
            continue
        if path.is_symlink() or not resolved.is_file() or not os.access(resolved, os.R_OK):
            invalid.append(key)
    checks.append(
        PreflightCheck(
            check_id="references",
            label="ONT reference resources",
            status=CheckStatus.BLOCKING if missing or invalid else CheckStatus.PASSED,
            message=(
                "Missing reference resources: " + ", ".join([*missing, *invalid])
                if missing or invalid
                else (
                    "Core ONT references are regular readable files; "
                    "annotation exploration is enabled"
                    if supplied_annotations
                    else "Core ONT references are regular readable files; "
                    "annotation exploration is not configured"
                )
            ),
        )
    )
    checks.append(
        PreflightCheck(
            check_id="comparisons",
            label="Requested comparisons",
            status=CheckStatus.PASSED if not manifest.comparisons else CheckStatus.BLOCKING,
            message="No comparisons are configured"
            if not manifest.comparisons
            else "ONT analysis does not accept comparisons",
        )
    )
    checks.extend(execution_resource_checks(manifest))
    checks.append(
        PreflightCheck(
            check_id="execution_profile",
            label="Execution profile",
            status=(
                CheckStatus.PASSED
                if manifest.execution_profile.value == "local"
                else CheckStatus.BLOCKING
            ),
            message=(
                "Local Python runner is available"
                if manifest.execution_profile.value == "local"
                else "ONT analysis requires the local execution profile"
            ),
        )
    )
    missing_tools = [
        tool
        for tool in ("dorado", "samtools", "mosdepth", "modkit", "bgzip", "tabix", "Rscript")
        if runtime_tool(tool, "ont-analysis") is None
    ]
    checks.append(
        PreflightCheck(
            check_id="ont_runtime_tools",
            label="ONT runtime tools",
            status=CheckStatus.PASSED if not missing_tools else CheckStatus.NOT_CONFIGURED,
            message="Required ONT tools are available"
            if not missing_tools
            else "Missing from PATH: " + ", ".join(missing_tools),
            details={"missing": missing_tools},
        )
    )
    return checks
