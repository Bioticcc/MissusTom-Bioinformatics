"""Linux-native hard resource containment for local workflow runs.

Production starts one keeper scope per run and moves owned child processes into
it by appending their PIDs to that scope's ``cgroup.procs`` file. The capability
probe performs that same migration. A successful ``systemd-run --user --scope --
true`` only proves that a transient scope can be created.

Launching each owned command as the direct payload of ``systemd-run --user
--scope`` would place that process in the scope without a later cgroup
migration, including on hosts that allow scope creation but reject
``cgroup.procs`` writes. That launch shape is not used: preparation and the
workflow are started as separate children of an existing scope, and only those
owned PIDs may be moved into it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

_GIB = 1024**3

TASKS_MAX_PER_PARALLEL_TASK = 32
SCOPE_UNIT_PREFIX = "missus-tom-run-"
_PROBE_SCOPE_PREFIX = "missus-tom-probe-"
_PROBE_READY_TIMEOUT_SECONDS = 15.0
_PROBE_MEMBERSHIP_TIMEOUT_SECONDS = 2.0
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
        scope_unit=f"{SCOPE_UNIT_PREFIX}{sanitized}.scope",
        memory_max_bytes=memory_limit_bytes(memory_gb),
        cpu_quota=cpu_quota_for_cpus(cpus),
        tasks_max=max(1, max_parallel_tasks) * TASKS_MAX_PER_PARALLEL_TASK,
    )


def build_scope_command(properties: ScopeProperties) -> list[str]:
    return [
        "systemd-run",
        "--user",
        "--scope",
        f"--unit={properties.scope_unit}",
        "-p",
        f"MemoryMax={properties.memory_max_bytes}",
        "-p",
        f"CPUQuota={properties.cpu_quota}",
        "-p",
        f"TasksMax={properties.tasks_max}",
        "--",
        "sleep",
        "infinity",
    ]


def native_containment_enablement_instructions() -> str:
    return (
        "Enable delegated cgroup controllers for your user session so an owned child process "
        "can be moved into a systemd user scope. Ensure XDG_RUNTIME_DIR is set, log in through "
        "a systemd user session (not a bare SSH shell without lingering), and on WSL2 use "
        "systemd=true in /etc/wsl.conf then restart WSL. A successful "
        "'systemd-run --user --scope true' is not sufficient: the session must allow writing "
        "that child's PID to the scope cgroup.procs file. Alternatively use the Docker "
        "execution profile."
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


def _assign_pid_to_cgroup_procs(cgroup_procs: Path, process_id: int) -> None:
    """Append one owned PID to a cgroup.procs file.

    Callers must pass a process they started. This never signals or adopts any
    other process.
    """
    with cgroup_procs.open("a", encoding="utf-8") as handle:
        handle.write(f"{process_id}\n")
        handle.flush()


def _cgroup_procs_file(control_group: str) -> Path | None:
    cgroup_root = Path("/sys/fs/cgroup").resolve()
    procs_path = (cgroup_root / control_group.lstrip("/") / "cgroup.procs").resolve()
    try:
        inside_root = procs_path.is_relative_to(cgroup_root)
    except ValueError:
        return None
    if not inside_root or not procs_path.is_file():
        return None
    return procs_path


def _spawn_probe_scope(scope_unit: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            "systemd-run",
            "--user",
            "--scope",
            "--collect",
            f"--unit={scope_unit}",
            "--",
            "sleep",
            "30",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )


def _spawn_probe_child() -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["sleep", "30"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
        shell=False,
    )


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


def _process_belongs_to_cgroup(process_id: int, control_group: str) -> bool:
    scope_path = Path("/sys/fs/cgroup") / control_group.lstrip("/")
    deadline = time.monotonic() + _PROBE_MEMBERSHIP_TIMEOUT_SECONDS
    while True:
        try:
            child_path = process_cgroup_path(process_id)
            if child_path is not None and _path_is_within(child_path, scope_path):
                return True
        except OSError:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _terminate_owned_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    with suppress(OSError):
        if process.poll() is None:
            process.kill()
    with suppress(OSError, subprocess.TimeoutExpired):
        process.wait(timeout=5)


def _cleanup_containment_probe(
    scope_unit: str,
    *,
    scope_process: subprocess.Popen[str] | None,
    child: subprocess.Popen[str] | None,
    stop_scope: bool,
) -> None:
    """Stop only the probe scope and reap only the processes this probe started."""
    if stop_scope:
        with suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["systemctl", "--user", "stop", scope_unit],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                shell=False,
            )
    _terminate_owned_process(child)
    _terminate_owned_process(scope_process)


def _probe_scope_assignment() -> ContainmentProbeResult:
    """Create a disposable scope and migrate one harmless child into it.

    This must not call ``RunContainmentSession.start`` or
    ``require_native_containment``: those entry points invoke this probe.
    """
    scope_unit = f"{_PROBE_SCOPE_PREFIX}{uuid4().hex}.scope"
    scope_process: subprocess.Popen[str] | None = None
    child: subprocess.Popen[str] | None = None
    try:
        try:
            scope_process = _spawn_probe_scope(scope_unit)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _containment_unavailable(f"systemd-run --user is unavailable: {exc}")
        ready = _wait_for_probe_cgroup(scope_unit, scope_process)
        if isinstance(ready, ContainmentProbeResult):
            return ready
        procs = _cgroup_procs_file(ready)
        if procs is None:
            return _containment_unavailable(
                "systemd-run --user created a scope, but its cgroup.procs file is not accessible."
            )
        try:
            child = _spawn_probe_child()
        except OSError as exc:
            return _containment_unavailable(
                f"Could not start a probe process for cgroup assignment: {exc}"
            )
        try:
            _assign_pid_to_cgroup_procs(procs, child.pid)
        except OSError as exc:
            return _containment_unavailable(
                "A systemd user scope was created, but this session cannot assign a "
                f"process to that scope ({exc.__class__.__name__}: {exc}). Delegated "
                "cgroup controllers are required before workflow processes can be moved "
                "into the scope."
            )
        if not _process_belongs_to_cgroup(child.pid, ready):
            return _containment_unavailable(
                "A probe process was written to the scope cgroup.procs file, but its "
                "cgroup membership could not be confirmed."
            )
        return ContainmentProbeResult(
            available=True,
            message=(
                "systemd user scopes are available and can accept assigned workflow processes."
            ),
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
        if output == "unknown":
            return ScopeStatus(ScopeState.INACTIVE, "scope is absent")
        return ScopeStatus(
            ScopeState.UNQUERYABLE,
            f"scope is {output or 'reported'} but its cgroup could not be queried",
        )
    processes = _scope_processes(control_group)
    if processes is None:
        return ScopeStatus(ScopeState.UNQUERYABLE, "scope cgroup membership could not be read")
    if processes:
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
                return True
            time.sleep(0.1)
    return scope_status(scope_unit).state == ScopeState.INACTIVE


class RunContainmentSession:
    """One systemd user scope holding prep and workflow descendants."""

    def __init__(
        self,
        scope_unit: str,
        *,
        keeper_process: subprocess.Popen[str],
        cgroup_procs: Path,
    ) -> None:
        self.scope_unit = scope_unit
        self._keeper_process = keeper_process
        self._cgroup_procs = cgroup_procs

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
        process = subprocess.Popen(
            build_scope_command(properties),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            shell=False,
        )
        deadline = time.monotonic() + 30.0
        cgroup: str | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                detail = (process.stderr.read() if process.stderr else "").strip()
                raise ValueError(
                    "Could not start the resource containment scope"
                    + (f": {detail}" if detail else "")
                )
            cgroup = _control_group_for_unit(properties.scope_unit)
            if cgroup is not None:
                break
            time.sleep(0.05)
        if cgroup is None:
            process.kill()
            process.wait(timeout=5)
            raise ValueError("Started containment scope but could not resolve its cgroup path")
        procs = Path("/sys/fs/cgroup") / cgroup.lstrip("/") / "cgroup.procs"
        if not procs.is_file():
            process.kill()
            process.wait(timeout=5)
            raise ValueError(f"Containment cgroup.procs is not accessible: {procs}")
        return cls(properties.scope_unit, keeper_process=process, cgroup_procs=procs)

    def assign_process(self, process_id: int) -> None:
        try:
            _assign_pid_to_cgroup_procs(self._cgroup_procs, process_id)
        except OSError as exc:
            raise ValueError(f"Could not assign process {process_id} to containment scope") from exc

    def stop(self, *, grace_seconds: float = 10.0) -> bool:
        return stop_scope_unit(self.scope_unit, grace_seconds=grace_seconds)

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


def process_cgroup_path(process_id: int) -> Path | None:
    try:
        raw = Path(f"/proc/{process_id}/cgroup").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in raw.splitlines():
        if line.startswith("0::"):
            relative = line.removeprefix("0::").strip()
            if relative:
                return Path("/sys/fs/cgroup") / relative.lstrip("/")
    return None


def parse_build_log_path(message: str) -> Path | None:
    match = _BUILD_LOG_PATTERN.search(message)
    if match is None:
        return None
    return Path(match.group(1))
