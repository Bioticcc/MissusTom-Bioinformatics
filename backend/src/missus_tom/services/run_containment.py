"""Linux-native hard resource containment for local workflow runs.

One limited systemd slice belongs to each run. A keeper keeps it active; every
owned workload is the direct payload of a transient scope inside that slice.
No process is migrated across cgroup hierarchies by Missus Tom.
"""

from __future__ import annotations

import os
import re
import select
import subprocess
import sys
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TextIO
from uuid import uuid4

_GIB = 1024**3

# TasksMax counts Linux tasks (threads as well as processes), unlike the
# scientific workflow concurrency setting.  A Nextflow JVM needs a sizeable
# control-plane budget before it launches one scientific task: JVM/Groovy/GPars
# actors, executor and file-transfer pools, launcher shells, and tool threads.
# Keep that runtime budget independent of workflow parallelism, then add bounded
# capacity for CPU workers and each concurrently scheduled workflow task.
TASKS_MAX_RUNTIME_BASELINE = 256
TASKS_MAX_PER_CPU = 32
TASKS_MAX_PER_PARALLEL_TASK = 128
TASKS_MAX_CEILING = 4096
SCOPE_UNIT_PREFIX = "missus-tom-run-"
_PROBE_SCOPE_PREFIX = "missus-tom-probe-"
_PROBE_READY_TIMEOUT_SECONDS = 15.0
_BUILD_LOG_PATTERN = re.compile(r"See (\S+build\.log)")


@dataclass(frozen=True)
class ContainmentProbeResult:
    available: bool
    message: str
    enablement: str | None = None


@dataclass(frozen=True)
class ScopeProperties:
    scope_unit: str
    memory_max_bytes: int
    cpu_quota: str
    tasks_max: int


class ScopeState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNQUERYABLE = "unqueryable"


@dataclass(frozen=True)
class ScopeStatus:
    state: ScopeState
    message: str


def memory_limit_bytes(memory_gb: float) -> int:
    return int(memory_gb * _GIB)


def cpu_quota_for_cpus(cpus: int) -> str:
    return f"{max(1, cpus) * 100}%"


def build_scope_properties(
    job_identifier: str,
    *,
    memory_gb: float,
    cpus: int,
    max_parallel_tasks: int,
) -> ScopeProperties:
    sanitized = job_identifier.replace("-", "")
    return ScopeProperties(
        scope_unit=f"{SCOPE_UNIT_PREFIX}{sanitized}.slice",
        memory_max_bytes=memory_limit_bytes(memory_gb),
        cpu_quota=cpu_quota_for_cpus(cpus),
        tasks_max=min(
            TASKS_MAX_CEILING,
            TASKS_MAX_RUNTIME_BASELINE
            + max(1, cpus) * TASKS_MAX_PER_CPU
            + max(1, max_parallel_tasks) * TASKS_MAX_PER_PARALLEL_TASK,
        ),
    )


def build_scope_command(properties: ScopeProperties) -> list[str]:
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        f"--slice={properties.scope_unit}",
        f"--unit={properties.scope_unit.removesuffix('.slice')}-keeper.scope",
        "--",
        "sleep",
        "infinity",
    ]


def build_workload_command(slice_unit: str, command: list[str]) -> list[str]:
    """Launch a payload through the same systemd path used by the probe."""
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        f"--slice={slice_unit}",
        f"--unit={slice_unit.removesuffix('.slice')}-{uuid4().hex}.scope",
        "--",
        *command,
    ]


def native_containment_enablement_instructions() -> str:
    return (
        "Enable a systemd user session with delegated cpu, memory and pids controllers. "
        "Ensure XDG_RUNTIME_DIR is set; on WSL2 use systemd=true in /etc/wsl.conf "
        "and restart WSL. Alternatively use the Docker execution profile."
    )


def _user_bus_available() -> bool:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        return False
    return Path(runtime_dir).joinpath("bus").is_socket()


def _containment_unavailable(message: str) -> ContainmentProbeResult:
    return ContainmentProbeResult(
        available=False,
        message=message,
        enablement=native_containment_enablement_instructions(),
    )


def _slice_limits_match(control_group: str, properties: ScopeProperties) -> bool:
    root = Path("/sys/fs/cgroup").resolve()
    group = (root / control_group.lstrip("/")).resolve()
    if not group.is_relative_to(root):
        return False
    try:
        memory = int((group / "memory.max").read_text().strip())
        tasks = int((group / "pids.max").read_text().strip())
        cpu_budget, cpu_period = (group / "cpu.max").read_text().split()
        return (
            memory == properties.memory_max_bytes
            and tasks == properties.tasks_max
            and cpu_budget != "max"
            and int(cpu_budget) * 100 == int(cpu_period) * int(properties.cpu_quota[:-1])
        )
    except (OSError, ValueError):
        return False


def _set_slice_limits(properties: ScopeProperties, control_group: str) -> None:
    completed = subprocess.run(
        [
            "systemctl",
            "--user",
            "set-property",
            "--runtime",
            properties.scope_unit,
            f"MemoryMax={properties.memory_max_bytes}",
            f"CPUQuota={properties.cpu_quota}",
            f"TasksMax={properties.tasks_max}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        shell=False,
    )
    if completed.returncode != 0 or not _slice_limits_match(control_group, properties):
        raise ValueError(
            "Systemd could not enforce the run slice CPU, memory and task limits: "
            + (completed.stderr or "cgroup limit verification failed").strip()
        )


def _start_keeper(properties: ScopeProperties) -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(
        build_scope_command(properties),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        shell=False,
    )
    ready = _wait_for_probe_cgroup(properties.scope_unit, process)
    if isinstance(ready, ContainmentProbeResult):
        _terminate_owned_process(process)
        raise ValueError(ready.message)
    try:
        _set_slice_limits(properties, ready)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        stop_scope_unit(properties.scope_unit)
        _terminate_owned_process(process)
        raise
    return process, ready


def _wait_for_probe_cgroup(
    scope_unit: str,
    scope_process: subprocess.Popen[str],
) -> str | ContainmentProbeResult:
    deadline = time.monotonic() + _PROBE_READY_TIMEOUT_SECONDS
    while True:
        if scope_process.poll() is not None:
            detail = ""
            if scope_process.stderr is not None:
                detail = scope_process.stderr.read().strip()
            message = "systemd-run --user could not create a delegated scope"
            if detail:
                message = f"{message}: {detail}"
            return _containment_unavailable(message)
        control_group = _control_group_for_unit(scope_unit)
        if control_group is not None:
            return control_group
        if time.monotonic() >= deadline:
            return _containment_unavailable(
                "systemd-run --user started but did not publish a scope cgroup before timing out."
            )
        time.sleep(0.05)


def _terminate_owned_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    with suppress(OSError):
        if process.poll() is None:
            process.kill()
    with suppress(OSError, subprocess.TimeoutExpired):
        process.wait(timeout=5)
    for stream in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
        if stream is not None:
            with suppress(OSError):
                stream.close()


def _cleanup_containment_probe(
    scope_unit: str,
    *,
    scope_process: subprocess.Popen[str] | None,
    child: subprocess.Popen[str] | None,
    stop_scope: bool,
) -> None:
    """Stop only the probe scope and reap only the processes this probe started."""
    if stop_scope:
        stop_scope_unit(scope_unit)
    _terminate_owned_process(child)
    _terminate_owned_process(scope_process)


def _probe_scope_assignment() -> ContainmentProbeResult:
    """Exercise the production slice and direct scoped payload launch."""
    scope_unit = f"{_PROBE_SCOPE_PREFIX}{uuid4().hex}.slice"
    properties = ScopeProperties(scope_unit, 256 * 1024**2, "100%", 128)
    scope_process: subprocess.Popen[str] | None = None
    child: subprocess.Popen[str] | None = None
    try:
        scope_process, ready = _start_keeper(properties)
        command = build_workload_command(
            scope_unit,
            [
                "/bin/sh",
                "-c",
                "/bin/cat /proc/$$/cgroup && exec /bin/sleep 30",
            ],
        )
        child_unit = next(
            value.removeprefix("--unit=") for value in command if value.startswith("--unit=")
        )
        child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            shell=False,
        )
        child_group = _wait_for_probe_cgroup(child_unit, child)
        if isinstance(child_group, ContainmentProbeResult):
            return child_group
        if not Path(child_group).is_relative_to(Path(ready)):
            return _containment_unavailable("The workload scope is outside the limited run slice.")
        if child.stdout is None or not select.select([child.stdout], [], [], 5)[0]:
            return _containment_unavailable("The scoped workload did not report its cgroup.")
        reported = child.stdout.readline().strip().removeprefix("0::")
        if reported != child_group:
            return _containment_unavailable(
                "The scoped workload's cgroup membership could not be confirmed."
            )
        return ContainmentProbeResult(
            available=True,
            message="Systemd can launch owned workloads inside a limited run slice.",
        )
    except Exception as exc:
        return _containment_unavailable(f"Native resource containment could not be verified: {exc}")
    finally:
        _cleanup_containment_probe(
            scope_unit,
            scope_process=scope_process,
            child=child,
            stop_scope=scope_process is not None,
        )


def probe_native_containment() -> ContainmentProbeResult:
    if sys.platform != "linux":
        return _containment_unavailable("Native resource containment requires Linux.")
    if not _user_bus_available():
        return _containment_unavailable(
            "Native resource containment requires an active systemd user session bus."
        )
    return _probe_scope_assignment()


def require_native_containment() -> None:
    probe = probe_native_containment()
    if not probe.available:
        raise ValueError(
            "Native resource containment is required for local execution but is unavailable: "
            f"{probe.message} {probe.enablement or ''}".strip()
        )


def scope_status(scope_unit: str) -> ScopeStatus:
    """Read unit and cgroup state; inability to verify emptiness is never clean."""
    try:
        completed = subprocess.run(
            ["systemctl", "--user", "is-active", scope_unit],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ScopeStatus(ScopeState.UNQUERYABLE, f"could not query scope: {exc}")
    output = (completed.stdout or "").strip().lower()
    recognized_inactive = output in {"inactive", "failed", "unknown"}
    recognized_active = output in {"active", "activating", "deactivating"}
    if not recognized_inactive and not recognized_active and completed.returncode != 0:
        return ScopeStatus(
            ScopeState.UNQUERYABLE,
            (completed.stderr or output or f"systemctl returned {completed.returncode}").strip(),
        )
    control_group = _control_group_for_unit(scope_unit)
    if control_group is None:
        # Transient scopes are commonly removed immediately after they stop.
        # A systemd-confirmed inactive/failed/absent unit has no cgroup left to
        # inspect, which is a clean terminal state rather than an uncertainty.
        if recognized_inactive:
            return ScopeStatus(ScopeState.INACTIVE, f"scope is {output or 'absent'}")
        return ScopeStatus(
            ScopeState.UNQUERYABLE,
            f"scope is {output or 'reported'} but its cgroup could not be queried",
        )
    processes = _scope_processes(control_group)
    if processes is None:
        return ScopeStatus(ScopeState.UNQUERYABLE, "scope cgroup membership could not be read")
    if scope_unit.endswith(".slice"):
        try:
            events = (
                Path("/sys/fs/cgroup") / control_group.lstrip("/") / "cgroup.events"
            ).read_text()
            populated = next(
                line.split()[1] for line in events.splitlines() if line.startswith("populated ")
            )
        except (OSError, StopIteration, IndexError):
            return ScopeStatus(
                ScopeState.UNQUERYABLE, "slice descendant membership could not be read"
            )
        if populated not in {"0", "1"}:
            return ScopeStatus(ScopeState.UNQUERYABLE, "invalid slice descendant membership")
        if populated == "1":
            return ScopeStatus(ScopeState.ACTIVE, "slice contains owned processes")
    elif processes:
        return ScopeStatus(
            ScopeState.ACTIVE,
            f"scope cgroup contains {len(processes)} process(es)",
        )
    if recognized_inactive:
        return ScopeStatus(ScopeState.INACTIVE, f"{output}; scope cgroup is empty")
    if recognized_active or completed.returncode == 0:
        return ScopeStatus(ScopeState.ACTIVE, f"{output or 'active'}; scope cgroup is empty")
    return ScopeStatus(
        ScopeState.UNQUERYABLE,
        (completed.stderr or output or f"systemctl returned {completed.returncode}").strip(),
    )


def _scope_processes(control_group: str) -> tuple[int, ...] | None:
    cgroup_root = Path("/sys/fs/cgroup").resolve()
    procs_path = (cgroup_root / control_group.lstrip("/") / "cgroup.procs").resolve()
    if not procs_path.is_relative_to(cgroup_root):
        return None
    try:
        raw = procs_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return tuple(int(value) for value in raw.split())
    except ValueError:
        return None


def stop_scope_unit(scope_unit: str, *, grace_seconds: float = 10.0) -> bool:
    """Stop a scope and treat it as clean only after status confirms it is inactive.

    A non-zero ``systemctl stop`` result is success only when the unit is absent
    or otherwise confirmed inactive. Timeouts and unreadable status stay failed.
    """
    try:
        completed = subprocess.run(
            ["systemctl", "--user", "stop", scope_unit],
            capture_output=True,
            text=True,
            timeout=max(5.0, grace_seconds + 5.0),
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode == 0:
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            if scope_status(scope_unit).state == ScopeState.INACTIVE:
                _revert_slice_properties(scope_unit)
                return True
            time.sleep(0.1)
    inactive = scope_status(scope_unit).state == ScopeState.INACTIVE
    if inactive:
        _revert_slice_properties(scope_unit)
    return inactive


def _revert_slice_properties(unit: str) -> None:
    if not unit.endswith(".slice"):
        return
    with suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            ["systemctl", "--user", "revert", unit],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )


class RunContainmentSession:
    """One limited systemd user slice containing scoped prep and workflow."""

    def __init__(
        self,
        scope_unit: str,
        *,
        keeper_process: subprocess.Popen[str],
    ) -> None:
        self.scope_unit = scope_unit
        self._keeper_process = keeper_process

    @property
    def scope_id(self) -> str:
        return self.scope_unit

    @classmethod
    def start(
        cls,
        job_identifier: str,
        *,
        memory_gb: float,
        cpus: int,
        max_parallel_tasks: int,
    ) -> RunContainmentSession:
        require_native_containment()
        properties = build_scope_properties(
            job_identifier,
            memory_gb=memory_gb,
            cpus=cpus,
            max_parallel_tasks=max_parallel_tasks,
        )
        process, _ = _start_keeper(properties)
        return cls(properties.scope_unit, keeper_process=process)

    def launch_command(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout: int | TextIO | None = None,
        stderr: int | TextIO | None = None,
        pass_fds: tuple[int, ...] = (),
    ) -> subprocess.Popen[str]:
        """Start a child through systemd inside this run's limited slice."""
        return subprocess.Popen(
            build_workload_command(self.scope_unit, command),
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=True,
            start_new_session=True,
            pass_fds=pass_fds,
            shell=False,
        )

    def stop(self, *, grace_seconds: float = 10.0) -> bool:
        stopped = stop_scope_unit(self.scope_unit, grace_seconds=grace_seconds)
        if stopped:
            # The scope stop also ends the keeper process launched by start().
            # Reap it so its stderr pipe cannot survive the session.
            _terminate_owned_process(self._keeper_process)
        return stopped

    def is_inactive(self) -> bool:
        return scope_status(self.scope_unit).state == ScopeState.INACTIVE

    def descendant_cgroup_path(self) -> Path | None:
        cgroup = _control_group_for_unit(self.scope_unit)
        if cgroup is None:
            return None
        return Path("/sys/fs/cgroup") / cgroup.lstrip("/")


def _control_group_for_unit(unit: str) -> str | None:
    try:
        completed = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "ControlGroup", "--value"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    value = (completed.stdout or "").strip()
    return value or None


def parse_build_log_path(message: str) -> Path | None:
    match = _BUILD_LOG_PATTERN.search(message)
    if match is None:
        return None
    return Path(match.group(1))
