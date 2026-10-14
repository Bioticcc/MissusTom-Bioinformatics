from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.preflight import CheckStatus
from missus_tom.services import native_readiness, preflight
from missus_tom.services.run_containment import ContainmentProbeResult


def test_wsl_without_systemd_has_exact_repair_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native_readiness, "_wsl2", lambda: True)
    original = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == Path("/proc/1/comm"):
            return "init\n"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    result = native_readiness.inspect_native_readiness()

    assert result.available is False
    assert "not PID 1" in result.message
    assert "[boot]" in result.guidance
    assert "systemd=true" in result.guidance
    assert "wsl --shutdown" in result.guidance
    assert "Windows PowerShell" in result.guidance


def test_native_readiness_checks_manager_then_real_workload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(native_readiness, "_wsl2", lambda: False)
    monkeypatch.setattr(native_readiness.shutil, "which", lambda _command: "/usr/bin/systemctl")
    original = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == Path("/proc/1/comm"):
            return "systemd\n"
        if path == Path("/sys/fs/cgroup/cgroup.controllers"):
            return "cpu memory pids io\n"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "is_socket", lambda path: path == runtime / "bus")
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert kwargs["shell"] is False
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(native_readiness.subprocess, "run", run)
    probes: list[bool] = []

    def probe() -> ContainmentProbeResult:
        probes.append(True)
        return ContainmentProbeResult(True, "Owned workload launched inside a limited slice.")

    monkeypatch.setattr(native_readiness, "probe_native_containment", probe)
    result = native_readiness.inspect_native_readiness()
    check = preflight.native_containment_check()

    assert result.available is True
    assert result.details["cgroup_controllers"] == ["cpu", "io", "memory", "pids"]
    assert check.status.value == "passed"
    assert len(probes) == 2
    assert commands == [["systemctl", "--user", "list-units", "--no-legend", "--no-pager"]] * 2


def test_missing_user_bus_blocks_before_workload_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(native_readiness, "_wsl2", lambda: False)
    monkeypatch.setattr(Path, "read_text", lambda path, **_kwargs: "systemd\n")
    monkeypatch.setattr(
        native_readiness,
        "probe_native_containment",
        lambda: pytest.fail("workload probe must not run without a user bus"),
    )

    result = native_readiness.inspect_native_readiness()

    assert result.available is False
    assert "user bus socket" in result.message


def test_missing_cgroup_controller_blocks_before_workload_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(native_readiness, "_wsl2", lambda: False)
    monkeypatch.setattr(native_readiness.shutil, "which", lambda _command: "/usr/bin/systemctl")
    monkeypatch.setattr(Path, "is_socket", lambda path: path == runtime / "bus")
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, **_kwargs: (
            "cpu memory\n" if path == Path("/sys/fs/cgroup/cgroup.controllers") else "systemd\n"
        ),
    )
    monkeypatch.setattr(
        native_readiness.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )
    monkeypatch.setattr(
        native_readiness,
        "probe_native_containment",
        lambda: pytest.fail("workload probe must not run without pids controller"),
    )

    result = native_readiness.inspect_native_readiness()

    assert result.available is False
    assert "pids" in result.message


def test_local_project_reports_containment_blocker_without_blocking_docker(
    manifest_payload: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        preflight,
        "inspect_native_readiness",
        lambda: native_readiness.NativeReadiness(
            False,
            "The systemd user bus is unavailable.",
            "Enable the user session.",
            {"wsl2": False},
        ),
    )
    local = ProjectManifest.model_validate(manifest_payload)
    local_checks = preflight.project_preflight(local)
    containment = next(check for check in local_checks if check.check_id == "native_containment")

    assert containment.status == CheckStatus.WARNING
    assert "systemd user bus" in containment.message
    assert "Insufficient resources" not in containment.message

    manifest_payload["execution_profile"] = "docker"
    docker_checks = preflight.project_preflight(ProjectManifest.model_validate(manifest_payload))
    assert all(check.check_id != "native_containment" for check in docker_checks)
