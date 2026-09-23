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


@dataclass(frozen=True)
class StorageInspection:
    path: str
    filesystem_type: str | None
    free_bytes: int
    total_bytes: int
    host_free_bytes: int | None
    measurement: str
    warning: str | None


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _decode_mount_point(raw: str) -> str:
    parts: list[str] = []
    index = 0
    while index < len(raw):
        if raw[index] == "\\" and index + 3 < len(raw) and raw[index + 1 : index + 4].isdigit():
            parts.append(chr(int(raw[index + 1 : index + 4], 8)))
            index += 4
        else:
            parts.append(raw[index])
            index += 1
    return "".join(parts)


def _existing_storage_path(path: Path) -> Path:
    candidate = path.expanduser()
    try:
        candidate = candidate.resolve(strict=False)
    except OSError:
        candidate = path.expanduser().absolute()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _filesystem_type(resolved_path: Path) -> str | None:
    try:
        target = str(resolved_path.resolve())
        best_mount = ""
        best_fstype: str | None = None
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            mount_point = _decode_mount_point(parts[1])
            if (target == mount_point or target.startswith(mount_point.rstrip("/") + "/")) and len(
                mount_point
            ) >= len(best_mount):
                best_mount = mount_point
                best_fstype = parts[2]
        return best_fstype
    except OSError:
        return None


def _wsl_host_mount() -> Path | None:
    preferred = Path("/mnt/c")
    if preferred.is_dir():
        return preferred
    mounts_root = Path("/mnt")
    if not mounts_root.is_dir():
        return None
    for entry in sorted(mounts_root.iterdir()):
        if entry.is_dir() and len(entry.name) == 1 and entry.name.isalpha():
            return entry
    return None


def _wsl_windows_mount_path(path: Path) -> bool:
    try:
        resolved = path.expanduser().resolve(strict=False)
    except OSError:
        resolved = path.expanduser().absolute()
    parts = resolved.parts
    if len(parts) < 3 or parts[0] != "/" or parts[1] != "mnt":
        return False
    drive = parts[2]
    return len(drive) == 1 and drive.isalpha()


def inspect_storage(path: Path) -> StorageInspection:
    inspected = _existing_storage_path(path)
    usage = shutil.disk_usage(inspected)
    fstype = _filesystem_type(inspected)
    measurement = "linux"
    warning: str | None = None
    host_free: int | None = None

    if is_wsl():
        if _wsl_windows_mount_path(path):
            measurement = "windows_mount"
        else:
            host_mount = _wsl_host_mount()
            if host_mount is not None:
                try:
                    host_free = shutil.disk_usage(host_mount).free
                except OSError:
                    host_free = None
            if host_free is not None and host_free < usage.free:
                measurement = "wsl_host_bounded"
                warning = (
                    "Reported Linux free space may exceed what the Windows host can provide; "
                    "capacity is limited by Windows host storage"
                )
            else:
                measurement = "wsl_virtual"
                warning = (
                    "WSL virtual disk free space may not reflect Windows host free space; "
                    "do not treat unbounded VHD capacity as confirmed physical storage"
                )

    return StorageInspection(
        path=str(inspected),
        filesystem_type=fstype,
        free_bytes=usage.free,
        total_bytes=usage.total,
        host_free_bytes=host_free,
        measurement=measurement,
        warning=warning,
    )


def effective_free_bytes(inspection: StorageInspection) -> int:
    if inspection.host_free_bytes is not None:
        if inspection.measurement == "wsl_host_bounded":
            return inspection.host_free_bytes
        if inspection.measurement == "wsl_virtual":
            return min(inspection.free_bytes, inspection.host_free_bytes)
    return inspection.free_bytes


def admission_free_bytes(inspection: StorageInspection, *, strict: bool) -> int | None:
    if inspection.measurement in ("linux", "windows_mount"):
        return inspection.free_bytes
    if inspection.measurement == "wsl_host_bounded":
        return inspection.host_free_bytes
    if inspection.measurement == "wsl_virtual":
        if inspection.host_free_bytes is not None:
            return min(inspection.free_bytes, inspection.host_free_bytes)
        return None if strict else inspection.free_bytes
    return inspection.free_bytes


def _workflow_disk_check_status(
    inspection: StorageInspection,
    *,
    admission_free: int | None,
    required_bytes: int,
    failure: CheckStatus,
    strict: bool,
) -> CheckStatus:
    unconfirmed_wsl = inspection.measurement == "wsl_virtual" and inspection.host_free_bytes is None
    if unconfirmed_wsl and strict:
        return failure
    if admission_free is None:
        return failure if strict else CheckStatus.WARNING
    if admission_free < required_bytes:
        return failure
    if inspection.measurement == "wsl_virtual" and not strict:
        return CheckStatus.WARNING
    if unconfirmed_wsl:
        return CheckStatus.WARNING
    return CheckStatus.PASSED


def _storage_check_message(
    inspection: StorageInspection,
    effective_free: int,
    *,
    extra: str = "",
) -> str:
    fstype = inspection.filesystem_type or "unknown"
    host_note = (
        f"; Windows host bound to {inspection.host_free_bytes / GIB:.1f} GiB free"
        if inspection.host_free_bytes is not None and inspection.measurement == "wsl_host_bounded"
        else ""
    )
    message = (
        f"{effective_free / GIB:.1f} GiB free on {inspection.path} "
        f"({fstype}, measurement={inspection.measurement}){host_note}"
    )
    if extra:
        message = f"{message}. {extra}"
    if inspection.warning:
        message = f"{message}. {inspection.warning}"
    return message


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
        disk = inspect_storage(parent)
        admission_free = admission_free_bytes(disk, strict=strict)
        effective_free = effective_free_bytes(disk)
        budget_extra = (
            f"allow at least {required_bytes / GIB:.1f} GiB for this run "
            "(estimate, including work and published copies)"
        )
        if admission_free is None:
            budget_extra = "Windows host free space could not be confirmed; " + budget_extra
        checks.append(
            PreflightCheck(
                check_id="workflow_disk_budget",
                label="Workflow disk budget",
                status=_workflow_disk_check_status(
                    disk,
                    admission_free=admission_free,
                    required_bytes=required_bytes,
                    failure=failure,
                    strict=strict,
                ),
                message=_storage_check_message(disk, effective_free, extra=budget_extra),
                details={
                    "free_bytes": disk.free_bytes,
                    "host_free_bytes": disk.host_free_bytes,
                    "measurement": disk.measurement,
                    "warning": disk.warning,
                    "admission_free_bytes": admission_free,
                    "estimated_required_bytes": required_bytes,
                    "input_bytes": input_bytes,
                    "path": disk.path,
                    "filesystem_type": disk.filesystem_type,
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
