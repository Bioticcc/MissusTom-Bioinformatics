from __future__ import annotations

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
    process_cgroup_path,
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
    assert properties.scope_unit == "missus-tom-run-job12345678.scope"
    assert properties.memory_max_bytes == memory_limit_bytes(8.0)
    assert properties.cpu_quota == "400%"
    assert properties.tasks_max == 64
    command = build_scope_command(properties)
    assert command[:4] == ["systemd-run", "--user", "--scope", f"--unit={properties.scope_unit}"]
    assert "-p" in command
    assert f"MemoryMax={properties.memory_max_bytes}" in command


def test_cpu_quota_conversion() -> None:
    assert cpu_quota_for_cpus(1) == "100%"
    assert cpu_quota_for_cpus(4) == "400%"


def test_memory_limit_conversion() -> None:
    assert memory_limit_bytes(1.0) == 1024**3


def test_unavailable_controller_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_containment, "_user_bus_available", lambda: False)
    result = probe_native_containment()
    assert result.available is False
    assert result.enablement


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
    session = RunContainmentSession(
        "missus-tom-run-test.scope",
        keeper_process=Mock(poll=lambda: None),
        cgroup_procs=Path("/tmp/unused"),
    )
    assert session.stop(grace_seconds=0.1) is True
    assert any(call[:3] == ["systemctl", "--user", "stop"] for call in calls)


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


def test_scope_status_requires_readable_cgroup_for_known_unit(
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
    monkeypatch.setattr(run_containment, "_scope_processes", lambda _cgroup: None)

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
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            start_new_session=True,
            shell=False,
        )
        session.assign_process(child.pid)
        time.sleep(0.2)
        scope_cgroup = session.descendant_cgroup_path()
        child_cgroup = process_cgroup_path(child.pid)
        assert scope_cgroup is not None
        assert child_cgroup is not None
        assert child_cgroup == scope_cgroup or str(child_cgroup).startswith(str(scope_cgroup))
    finally:
        subprocess.run(
            ["systemctl", "--user", "stop", session.scope_id],
            check=False,
            timeout=15,
            shell=False,
        )
        if "child" in locals() and child.poll() is None:
            child.kill()
            child.wait(timeout=5)


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
        allocator = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "data = bytearray(128 * 1024 * 1024); data[:] = b'x'; import time; time.sleep(30)",
            ],
            start_new_session=True,
            shell=False,
        )
        session.assign_process(allocator.pid)
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
