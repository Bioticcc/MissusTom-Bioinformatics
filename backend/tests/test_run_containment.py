from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from missus_tom.services import run_containment
from missus_tom.services.run_containment import (
    RunContainmentSession,
    ScopeState,
    build_scope_command,
    build_scope_properties,
    cpu_quota_for_cpus,
    memory_limit_bytes,
    probe_native_containment,
    scope_status,
    stop_scope_unit,
)


def test_scope_command_and_property_construction() -> None:
    properties = build_scope_properties(
        "job-1234-5678",
        memory_gb=8.0,
        cpus=4,
        max_parallel_tasks=2,
    )
    assert properties.scope_unit == "missus-tom-run-job12345678.slice"
    assert properties.memory_max_bytes == memory_limit_bytes(8.0)
    assert properties.cpu_quota == "400%"
    assert properties.tasks_max == 640
    command = build_scope_command(properties)
    assert command[:3] == ["systemd-run", "--user", "--scope"]
    assert f"--slice={properties.scope_unit}" in command
    assert command[-2:] == ["sleep", "infinity"]


def test_cpu_quota_conversion() -> None:
    assert cpu_quota_for_cpus(1) == "100%"
    assert cpu_quota_for_cpus(4) == "400%"


def test_tasks_max_keeps_nextflow_runtime_headroom_at_single_task_concurrency() -> None:
    single = build_scope_properties("single", memory_gb=16, cpus=4, max_parallel_tasks=1)
    larger = build_scope_properties("larger", memory_gb=64, cpus=16, max_parallel_tasks=4)

    assert single.tasks_max == 512
    assert single.tasks_max > 32
    assert larger.tasks_max == 1280


def test_memory_limit_conversion() -> None:
    assert memory_limit_bytes(1.0) == 1024**3


class _FakeProcess:
    def __init__(self, pid: int, *, returncode: int | None = None, stderr: str = "") -> None:
        self.pid = pid
        self.returncode = returncode
        self.stderr = io.StringIO(stderr)
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        if self.returncode is None:
            self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_probe_requires_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_containment.sys, "platform", "darwin")
    result = probe_native_containment()
    assert result.available is False
    assert "Linux" in result.message


def test_probe_requires_user_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_containment.sys, "platform", "linux")
    monkeypatch.setattr(run_containment, "_user_bus_available", lambda: False)
    result = probe_native_containment()
    assert result.available is False
    assert "systemd user session bus" in result.message


def test_probe_uses_direct_systemd_launch_when_raw_migration_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model a WSL caller outside systemd with cgroup.procs writes denied."""
    slice_group = "/user.slice/user-1000.slice/user@1000.service/run.slice"
    scope_group = slice_group + "/payload.scope"
    child = _FakeProcess(202)
    child.stdout = io.StringIO(f"0::{scope_group}\n")
    stopped: list[str] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(run_containment.sys, "platform", "linux")
    monkeypatch.setattr(run_containment, "_user_bus_available", lambda: True)
    monkeypatch.setattr(
        run_containment, "_start_keeper", lambda _properties: (_FakeProcess(101), slice_group)
    )
    monkeypatch.setattr(
        run_containment, "_wait_for_probe_cgroup", lambda _unit, _process: scope_group
    )
    monkeypatch.setattr(run_containment.select, "select", lambda *_args: ([child.stdout], [], []))
    monkeypatch.setattr(
        run_containment, "stop_scope_unit", lambda unit: stopped.append(unit) or True
    )

    def launch(command: list[str], **_kwargs: object) -> _FakeProcess:
        commands.append(command)
        return child

    monkeypatch.setattr(run_containment.subprocess, "Popen", launch)
    result = probe_native_containment()
    assert result.available is True
    assert "limited run slice" in result.message
    assert len(commands) == 1
    assert commands[0][:3] == ["systemd-run", "--user", "--scope"]
    assert any(arg.startswith("--slice=missus-tom-probe-") for arg in commands[0])
    assert stopped and child.killed


def test_probe_payload_works_when_backend_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """A packaged backend executable cannot interpret Python's -c option."""
    slice_group = "/user.slice/run.slice"
    scope_group = slice_group + "/payload.scope"
    child = _FakeProcess(202)
    child.stdout = io.StringIO(f"0::{scope_group}\n")
    commands: list[list[str]] = []
    monkeypatch.setattr(run_containment.sys, "executable", "/usr/bin/missus-tom-backend")
    monkeypatch.setattr(
        run_containment, "_start_keeper", lambda _properties: (_FakeProcess(101), slice_group)
    )
    monkeypatch.setattr(
        run_containment, "_wait_for_probe_cgroup", lambda _unit, _process: scope_group
    )
    monkeypatch.setattr(run_containment.select, "select", lambda *_args: ([child.stdout], [], []))
    monkeypatch.setattr(run_containment, "stop_scope_unit", lambda _unit: True)

    def launch(command: list[str], **_kwargs: object) -> _FakeProcess:
        commands.append(command)
        return child

    monkeypatch.setattr(run_containment.subprocess, "Popen", launch)
    assert run_containment._probe_scope_assignment().available
    assert commands[0][-3:-1] == ["/bin/sh", "-c"]
    assert "/proc/$$/cgroup" in commands[0][-1]
    assert "/usr/bin/missus-tom-backend" not in commands[0]


def test_probe_rejects_workload_outside_slice(monkeypatch: pytest.MonkeyPatch) -> None:
    slice_group = "/user.slice/run.slice"
    child = _FakeProcess(202)
    stopped: list[str] = []
    monkeypatch.setattr(run_containment.sys, "platform", "linux")
    monkeypatch.setattr(run_containment, "_user_bus_available", lambda: True)
    monkeypatch.setattr(
        run_containment, "_start_keeper", lambda _properties: (_FakeProcess(101), slice_group)
    )
    monkeypatch.setattr(
        run_containment, "_wait_for_probe_cgroup", lambda _unit, _process: "/non-systemd"
    )
    monkeypatch.setattr(run_containment.subprocess, "Popen", lambda *_args, **_kwargs: child)
    monkeypatch.setattr(
        run_containment, "stop_scope_unit", lambda unit: stopped.append(unit) or True
    )
    result = probe_native_containment()
    assert result.available is False
    assert "outside the limited run slice" in result.message
    assert stopped and child.killed


def test_session_launches_payload_through_systemd_without_pid_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []
    child = _FakeProcess(202)

    def launch(command: list[str], **_kwargs: object) -> _FakeProcess:
        captured.append(command)
        return child

    monkeypatch.setattr(run_containment.subprocess, "Popen", launch)
    session = RunContainmentSession(
        "missus-tom-run-test.slice", keeper_process=Mock(poll=lambda: None)
    )
    assert session.launch_command(["nextflow", "run", "main.nf"]) is child
    assert "--slice=missus-tom-run-test.slice" in captured[0]
    assert captured[0][-3:] == ["nextflow", "run", "main.nf"]
    assert "_assign_pid_to_cgroup_procs" not in vars(run_containment)


def test_cancellation_stops_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:3] == ["systemctl", "--user", "stop"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["systemctl", "--user", "is-active"]:
            return subprocess.CompletedProcess(command, 3, stdout="inactive\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="/user.slice/scope\n", stderr="")

    monkeypatch.setattr(run_containment.subprocess, "run", fake_run)
    monkeypatch.setattr(run_containment, "_scope_processes", lambda _cgroup: ())
    keeper = Mock(poll=lambda: 0, stdout=None, stderr=None)
    session = RunContainmentSession(
        "missus-tom-run-test.scope",
        keeper_process=keeper,
    )
    assert session.stop(grace_seconds=0.1) is True
    assert any(call[:3] == ["systemctl", "--user", "stop"] for call in calls)
    keeper.wait.assert_called_once_with(timeout=5)


def test_failed_scope_start_reaps_keeper(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[str] = []

    class _Stream(io.StringIO):
        def close(self) -> None:
            closed.append("stderr")
            super().close()

    stderr = _Stream("scope failed\n")
    process = Mock(poll=lambda: 1, stderr=stderr, stdout=None, pid=5)
    process.wait.return_value = 1
    monkeypatch.setattr(run_containment, "require_native_containment", lambda: None)
    monkeypatch.setattr(run_containment.subprocess, "Popen", lambda *_args, **_kwargs: process)

    with pytest.raises(ValueError, match="scope failed"):
        RunContainmentSession.start(
            "failed-start",
            memory_gb=1,
            cpus=1,
            max_parallel_tasks=1,
        )

    process.wait.assert_called_once_with(timeout=5)
    assert closed == ["stderr"]
    process.kill.assert_not_called()


def test_scope_status_distinguishes_inactive_active_and_unqueryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_containment, "_control_group_for_unit", lambda _unit: "/test")
    monkeypatch.setattr(run_containment, "_scope_processes", lambda _cgroup: ())
    monkeypatch.setattr(
        run_containment.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout="active\n", stderr=""),
    )
    assert scope_status("test.scope").state == ScopeState.ACTIVE
    monkeypatch.setattr(
        run_containment.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 3, stdout="inactive\n", stderr=""
        ),
    )
    assert scope_status("test.scope").state == ScopeState.INACTIVE
    monkeypatch.setattr(run_containment.subprocess, "run", Mock(side_effect=OSError("no bus")))
    assert scope_status("test.scope").state == ScopeState.UNQUERYABLE


def test_scope_status_treats_nonempty_inactive_scope_as_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_containment.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 3, stdout="inactive\n", stderr=""
        ),
    )
    monkeypatch.setattr(run_containment, "_control_group_for_unit", lambda _unit: "/test")
    monkeypatch.setattr(run_containment, "_scope_processes", lambda _cgroup: (123, 456))

    status = scope_status("test.scope")

    assert status.state == ScopeState.ACTIVE
    assert "2 process" in status.message


def test_scope_status_accepts_removed_cgroup_after_systemd_confirms_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_containment.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 3, stdout="inactive\n", stderr=""
        ),
    )
    monkeypatch.setattr(run_containment, "_control_group_for_unit", lambda _unit: None)

    assert scope_status("test.scope").state == ScopeState.INACTIVE


def test_scope_status_keeps_active_scope_without_queryable_cgroup_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_containment.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout="active\n", stderr=""),
    )
    monkeypatch.setattr(run_containment, "_control_group_for_unit", lambda _unit: None)

    assert scope_status("test.scope").state == ScopeState.UNQUERYABLE


def _systemctl_result(
    command: list[str], *, stop_code: int, active: str
) -> subprocess.CompletedProcess[str]:
    action = command[2] if len(command) > 2 else ""
    if action == "stop":
        stderr = "Unit test.scope not loaded.\n" if stop_code == 5 else ""
        return subprocess.CompletedProcess(command, stop_code, stdout="", stderr=stderr)
    if action == "is-active":
        code = 0 if active == "active" else 3
        return subprocess.CompletedProcess(command, code, stdout=f"{active}\n", stderr="")
    if action == "show":
        if active == "unknown":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="/user.slice/test.scope\n", stderr="")
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_stop_scope_unit_failure_timeout_absent_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"stop": 0}

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        action = command[2] if len(command) > 2 else ""
        if action == "stop":
            calls["stop"] += 1
        return _systemctl_result(command, stop_code=1, active="active")

    monkeypatch.setattr(run_containment.subprocess, "run", fake_run)
    monkeypatch.setattr(run_containment, "_scope_processes", lambda _cgroup: (44,))
    assert stop_scope_unit("test.scope", grace_seconds=0.1) is False

    monkeypatch.setattr(
        run_containment.subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired(cmd=["systemctl"], timeout=5)),
    )
    assert stop_scope_unit("test.scope", grace_seconds=0.1) is False

    monkeypatch.setattr(
        run_containment.subprocess,
        "run",
        lambda command, **_kwargs: _systemctl_result(command, stop_code=5, active="unknown"),
    )
    assert stop_scope_unit("absent.scope", grace_seconds=0.1) is True

    state = {"stops": 0}

    def retry_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        action = command[2] if len(command) > 2 else ""
        if action == "stop":
            state["stops"] += 1
        active = "inactive" if state["stops"] > 1 else "active"
        stop_code = 0 if state["stops"] > 1 else 1
        return _systemctl_result(command, stop_code=stop_code, active=active)

    monkeypatch.setattr(run_containment.subprocess, "run", retry_run)
    monkeypatch.setattr(run_containment, "_scope_processes", lambda _cgroup: ())
    assert stop_scope_unit("test.scope", grace_seconds=0.1) is False
    assert stop_scope_unit("test.scope", grace_seconds=0.1) is True
    assert calls["stop"] == 1


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-only integration")
def test_linux_descendants_join_capped_scope() -> None:
    probe = probe_native_containment()
    if not probe.available:
        pytest.skip(f"systemd user containment unavailable: {probe.message}")
    session = RunContainmentSession.start(
        "integration-probe-job",
        memory_gb=0.25,
        cpus=1,
        max_parallel_tasks=1,
    )
    try:
        child = session.launch_command(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; "
                "print(Path('/proc/self/cgroup').read_text().strip(), flush=True); "
                "import time; time.sleep(2)",
            ],
            stdout=subprocess.PIPE,
        )
        assert child.stdout is not None
        reported = child.stdout.readline().strip().removeprefix("0::")
        scope_cgroup = session.descendant_cgroup_path()
        assert scope_cgroup is not None
        assert Path("/sys/fs/cgroup", reported.lstrip("/")).is_relative_to(scope_cgroup)
    finally:
        session.stop(grace_seconds=15)
        if "child" in locals() and child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        run_containment._terminate_owned_process(session._keeper_process)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-only integration")
def test_stopping_run_slice_ends_scoped_workload_and_descendants() -> None:
    probe = probe_native_containment()
    if not probe.available:
        pytest.skip(f"systemd user containment unavailable: {probe.message}")
    session = RunContainmentSession.start(
        "integration-stop-job", memory_gb=0.25, cpus=1, max_parallel_tasks=1
    )
    process = None
    try:
        script = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print('started',flush=True); time.sleep(30)"
        )
        process = session.launch_command(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
        )
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "started"
        assert scope_status(session.scope_id).state == ScopeState.ACTIVE
        assert session.stop(grace_seconds=10)
        assert scope_status(session.scope_id).state == ScopeState.INACTIVE
        process.wait(timeout=5)
    finally:
        session.stop(grace_seconds=5)
        if process is not None:
            run_containment._terminate_owned_process(process)


@pytest.mark.skipif(
    os.environ.get("MISSUS_TOM_CONTAINMENT_OOM_TEST") != "1",
    reason="Set MISSUS_TOM_CONTAINMENT_OOM_TEST=1 to run the memory budget violation probe",
)
def test_controlled_memory_budget_violation() -> None:
    probe = probe_native_containment()
    if not probe.available:
        pytest.skip(f"systemd user containment unavailable: {probe.message}")
    session = RunContainmentSession.start(
        "oom-probe-job",
        memory_gb=0.05,
        cpus=1,
        max_parallel_tasks=1,
    )
    try:
        allocator = session.launch_command(
            [
                sys.executable,
                "-c",
                "data = bytearray(128 * 1024 * 1024); data[:] = b'x'; import time; time.sleep(30)",
            ],
        )
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if allocator.poll() is not None:
                break
            time.sleep(0.2)
        assert allocator.poll() is not None
    finally:
        subprocess.run(
            ["systemctl", "--user", "stop", session.scope_id],
            check=False,
            timeout=15,
            shell=False,
        )
