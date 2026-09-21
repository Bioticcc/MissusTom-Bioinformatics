"""Conservative local execution admission; no input contents are inspected."""

from __future__ import annotations

import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.preflight import CheckStatus, PreflightCheck

GIB = 1024**3


@dataclass(frozen=True)
class HostResources:
    logical_cpus: int
    total_memory_bytes: int | None
    available_memory_bytes: int | None

    @property
    def workflow_cpus(self) -> int:
        return max(1, self.logical_cpus - max(1, math.ceil(self.logical_cpus * 0.1)))

    @property
    def reserved_memory_bytes(self) -> int:
        # Includes the bounded Nextflow JVM, backend, and desktop headroom.
        return max(2 * GIB, math.ceil((self.total_memory_bytes or 0) * 0.1))

    @property
    def workflow_memory_bytes(self) -> int | None:
        if self.total_memory_bytes is None or self.available_memory_bytes is None:
            return None
        return max(
            0,
            min(self.total_memory_bytes, self.available_memory_bytes) - self.reserved_memory_bytes,
        )


def inspect_host_resources() -> HostResources:
    try:
        cpus = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = os.cpu_count() or 1
    memory: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if fields and fields[0] in {"MemTotal:", "MemAvailable:"}:
                memory[fields[0]] = int(fields[1]) * 1024
    except (OSError, ValueError, IndexError):
        memory = {}
    total, available = memory.get("MemTotal:"), memory.get("MemAvailable:")
    # Respect unified cgroup limits when the API itself is resource constrained.
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            cpus = min(cpus, max(1, int(quota) // int(period)))
    except (OSError, ValueError, ZeroDivisionError):
        pass
    try:
        limit = int(Path("/sys/fs/cgroup/memory.max").read_text())
        used = int(Path("/sys/fs/cgroup/memory.current").read_text())
        if total is not None and available is not None:
            total, available = min(total, limit), min(available, max(0, limit - used))
    except (OSError, ValueError):
        pass
    return HostResources(cpus, total, available)


def estimated_input_bytes(manifest: ProjectManifest, *, analysis_only: bool = False) -> int:
    paths: set[Path] = set()
    for sample in manifest.samples:
        if not sample.included:
            continue
        if manifest.pipeline_identifier == "ont-analysis":
            paths.update(Path(name) for name in sample.ont_bam_files)
        elif analysis_only:
            paths.add(
                Path(sample.abundance_tsv)
                if sample.abundance_tsv
                else Path(manifest.output_directory)
                / "results/counts/kallisto"
                / sample.sample_id
                / "abundance.tsv"
            )
        else:
            paths.update(Path(name) for name in [*sample.r1_files, *sample.r2_files])
    total = 0
    for path in paths:
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            # Input readability is checked separately by project/execution validation.
            continue
    return total


def execution_resource_checks(
    manifest: ProjectManifest,
    *,
    analysis_only: bool | None = None,
    strict: bool = False,
) -> list[PreflightCheck]:
    host = inspect_host_resources()
    failure = CheckStatus.BLOCKING if strict else CheckStatus.WARNING
    profile = manifest.resource_profile
    memory_budget = host.workflow_memory_bytes
    cpu_ok = profile.cpus <= host.workflow_cpus
    memory_ok = memory_budget is not None and profile.memory_gb * GIB <= memory_budget
    checks = [
        PreflightCheck(
            check_id="workflow_cpu_budget",
            label="Workflow CPU budget",
            status=CheckStatus.PASSED if cpu_ok else failure,
            message=(
                f"{profile.cpus} CPU(s) requested; up to {host.workflow_cpus} available "
                "for the workflow after reserving desktop capacity"
            ),
            details={"requested_cpus": profile.cpus, "safe_cpus": host.workflow_cpus},
        ),
        PreflightCheck(
            check_id="workflow_memory_budget",
            label="Workflow memory budget",
            status=CheckStatus.PASSED if memory_ok else failure,
            message=(
                f"{profile.memory_gb:g} GiB requested; "
                f"{memory_budget / GIB:.1f} GiB currently available for the workflow "
                f"after reserving {host.reserved_memory_bytes / GIB:.1f} GiB"
                if memory_budget is not None
                else "Cannot determine available RAM; execution requires a readable memory limit"
            ),
            details={
                "requested_bytes": profile.memory_gb * GIB,
                "safe_bytes": memory_budget,
                "reserved_bytes": host.reserved_memory_bytes,
            },
        ),
    ]
    if analysis_only is None:
        analysis_only = manifest.parameters.get("start_stage") == "analysis"
    input_bytes = estimated_input_bytes(manifest, analysis_only=analysis_only)
    # FASTQ work copies, trimming, published copies, reports, and a fixed margin.
    required_bytes = input_bytes * (2 if analysis_only else 4) + 10 * GIB
    output = Path(manifest.output_directory)
    parent = output
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    try:
        free = shutil.disk_usage(parent).free
        checks.append(
            PreflightCheck(
                check_id="workflow_disk_budget",
                label="Workflow disk budget",
                status=CheckStatus.PASSED if free >= required_bytes else failure,
                message=(
                    f"{free / GIB:.1f} GiB free on the output filesystem; "
                    f"allow at least {required_bytes / GIB:.1f} GiB for this run "
                    "(estimate, including work and published copies)"
                ),
                details={
                    "free_bytes": free,
                    "estimated_required_bytes": required_bytes,
                    "input_bytes": input_bytes,
                    "path": str(parent),
                },
            )
        )
    except OSError:
        checks.append(
            PreflightCheck(
                check_id="workflow_disk_budget",
                label="Workflow disk budget",
                status=failure,
                message="Cannot inspect free space on the project output filesystem",
            )
        )
    return checks


def validate_execution_resources(manifest: ProjectManifest, *, analysis_only: bool) -> None:
    failures = [
        check.message
        for check in execution_resource_checks(manifest, analysis_only=analysis_only, strict=True)
        if check.status == CheckStatus.BLOCKING
    ]
    if failures:
        raise ValueError("Insufficient resources for a safe run: " + "; ".join(failures))
