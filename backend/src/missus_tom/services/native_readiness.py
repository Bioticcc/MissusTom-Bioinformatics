"""Operator-facing checks for the native systemd containment prerequisite."""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from missus_tom.services.run_containment import probe_native_containment

REQUIRED_CONTROLLERS = {"cpu", "memory", "pids"}


@dataclass(frozen=True)
class NativeReadiness:
    available: bool
    message: str
    guidance: str
    details: dict[str, Any]


def _wsl2() -> bool:
    try:
        release = platform.release().lower()
        version = Path("/proc/version").read_text(encoding="utf-8").lower()
        marker = f"{release} {version}"
        return "wsl2" in marker or (
            "microsoft" in marker and Path("/sys/fs/cgroup/cgroup.controllers").is_file()
        )
    except OSError:
        return "wsl2" in platform.release().lower()


def _guidance(wsl2: bool) -> str:
    if wsl2:
        return (
            "In Ubuntu, add [boot] and systemd=true on separate lines in /etc/wsl.conf. "
            "Close WSL, run wsl --shutdown from Windows PowerShell, then reopen Ubuntu. "
            "Check that the systemd user session is running. Bulk RNA-seq can use the Docker "
            "execution profile where available."
        )
    return (
        "Enable a systemd user session, set XDG_RUNTIME_DIR to its user-owned runtime directory, "
        "and delegate cpu, memory and pids cgroup controllers. Bulk RNA-seq can use the Docker "
        "execution profile where available."
    )


def inspect_native_readiness() -> NativeReadiness:
    """Check prerequisites, then exercise the exact owned workload launch path."""
    wsl2 = _wsl2() if sys.platform == "linux" else False
    guidance = _guidance(wsl2)
    details: dict[str, Any] = {"wsl2": wsl2}

    def failed(message: str) -> NativeReadiness:
        return NativeReadiness(False, message, guidance, details)

    if sys.platform != "linux":
        return failed("Native resource containment requires Linux.")

    try:
        pid1 = Path("/proc/1/comm").read_text(encoding="utf-8").strip()
    except OSError:
        pid1 = "unavailable"
    details["pid1"] = pid1
    if wsl2 and pid1 != "systemd":
        return failed(f"Systemd is not PID 1 (found {pid1}).")

    runtime_value = os.environ.get("XDG_RUNTIME_DIR", "")
    details["runtime_directory"] = runtime_value
    if not runtime_value:
        return failed("XDG_RUNTIME_DIR is unset; the systemd user session is unavailable.")
    runtime_dir = Path(runtime_value)
    try:
        runtime_state = runtime_dir.stat()
        valid_runtime = (
            stat.S_ISDIR(runtime_state.st_mode)
            and runtime_state.st_uid == os.getuid()
            and runtime_state.st_mode & 0o077 == 0
            and os.access(runtime_dir, os.R_OK | os.W_OK | os.X_OK)
        )
    except OSError:
        valid_runtime = False
    if not valid_runtime:
        return failed("XDG_RUNTIME_DIR is not an accessible, private directory owned by this user.")

    bus = runtime_dir / "bus"
    details["user_bus"] = str(bus)
    if not bus.is_socket():
        return failed("The systemd user bus socket is missing from XDG_RUNTIME_DIR.")

    if shutil.which("systemctl") is None:
        return failed("systemctl is unavailable, so the systemd user manager cannot be checked.")
    try:
        manager = subprocess.run(
            ["systemctl", "--user", "list-units", "--no-legend", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return failed(f"systemctl --user could not contact the user manager: {exc}")
    if manager.returncode != 0:
        return failed(
            "systemctl --user is not operational: "
            + (manager.stderr.strip() or f"exit status {manager.returncode}")
        )
    details["systemctl_user"] = "operational"

    try:
        controllers = set(
            Path("/sys/fs/cgroup/cgroup.controllers").read_text(encoding="utf-8").split()
        )
    except OSError:
        return failed("The cgroup v2 controller list is unavailable.")
    details["cgroup_controllers"] = sorted(controllers)
    missing = REQUIRED_CONTROLLERS - controllers
    if missing:
        return failed(
            "Required cgroup v2 controllers are unavailable: " + ", ".join(sorted(missing))
        )

    probe = probe_native_containment()
    details["workload_probe"] = probe.message
    if not probe.available:
        return failed(probe.message)
    return NativeReadiness(True, probe.message, guidance, details)
