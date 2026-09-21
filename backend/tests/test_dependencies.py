from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from missus_tom.models.dependencies import (
    DependencyInstallJob,
    DependencyInstallStatus,
    DependencyRequirement,
)
from missus_tom.services import dependencies
from missus_tom.services.dependencies import (
    ONT_R_PACKAGES,
    DependencyInstaller,
    runtime_environment,
)


def test_status_reports_missing_requirements_without_marker_trust(tmp_path, monkeypatch) -> None:
    installer = DependencyInstaller(state_directory=tmp_path / "dependencies")
    monkeypatch.setattr(
        installer,
        "_requirements",
        lambda _pipeline: [
            DependencyRequirement(name="samtools", installed=True, managed=False, detail="system"),
            DependencyRequirement(
                name="modkit", installed=False, managed=False, detail="not found"
            ),
        ],
    )

    status = installer.status("ont-analysis")

    assert status.missing == ["modkit"]
    assert status.job is None
    assert status.installable is False
    assert "SHA-256" in status.manual_requirements[0]
    assert "data.table" in ONT_R_PACKAGES


def test_ont_installation_fails_closed_without_reviewed_dorado_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = DependencyInstaller(state_directory=tmp_path / "dependencies")
    monkeypatch.setattr(installer, "_supported_platform", lambda: True)

    with pytest.raises(ValueError, match="authoritative pinned SHA-256"):
        installer.install("ont-analysis")


def test_recovery_marks_abandoned_install_failed(tmp_path) -> None:
    jobs = tmp_path / "dependencies" / "jobs"
    jobs.mkdir(parents=True)
    job = {
        "job_identifier": "00000000-0000-0000-0000-000000000001",
        "pipeline_identifier": "ont-analysis",
        "status": "running",
        "message": "working",
        "log_tail": [],
    }
    (jobs / f"{job['job_identifier']}.json").write_text(json.dumps(job))

    installer = DependencyInstaller(state_directory=tmp_path / "dependencies")

    recovered = installer._job_for_pipeline("ont-analysis")
    assert recovered is not None
    assert recovered.status == DependencyInstallStatus.FAILED


def test_private_runtime_does_not_use_system_r_library(monkeypatch) -> None:
    monkeypatch.setenv("R_LIBS_USER", "/system/r")
    environment = runtime_environment("ont-analysis")
    assert environment.get("R_LIBS_USER") != "/system/r"


def test_bulk_runtime_includes_only_validated_docker_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    managed_bin = tmp_path / "managed" / "bin"
    docker = tmp_path / "host-docker" / "docker"
    monkeypatch.setattr(dependencies, "_managed_bin", lambda _: managed_bin)
    monkeypatch.setattr(
        dependencies,
        "runtime_tool",
        lambda name, pipeline: (
            str(docker) if (name, pipeline) == ("docker", "bulk-rnaseq") else None
        ),
    )

    environment = runtime_environment("bulk-rnaseq")

    assert environment["PATH"].split(":") == [
        str(managed_bin),
        str(docker.parent),
        "/usr/bin",
        "/bin",
    ]


def test_state_directory_refuses_symlinked_ancestor(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symlinks"):
        DependencyInstaller._safe_directory(link / "jobs")


def test_command_output_is_streamed_to_private_log(tmp_path: Path) -> None:
    installer = DependencyInstaller(state_directory=tmp_path / "dependencies")
    job = DependencyInstallJob(
        job_identifier="00000000-0000-0000-0000-000000000002",
        pipeline_identifier="ont-analysis",
        status=DependencyInstallStatus.RUNNING,
        message="test",
    )
    installer._run(job, [sys.executable, "-c", "print('bounded output')"])

    log = tmp_path / "dependencies" / "jobs" / f"{job.job_identifier}.install.log"
    assert log.read_text(encoding="utf-8") == "bounded output\n"
    assert job.log_tail[-1].endswith("bounded output")


def test_shared_run_admission_lock_excludes_second_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path / "state"))
    first = DependencyInstaller(state_directory=tmp_path / "first")
    second = DependencyInstaller(state_directory=tmp_path / "second")
    identifier = "00000000-0000-0000-0000-000000000003"
    descriptor = first._acquire_run_lock(identifier)
    first._run_lock_descriptors[identifier] = descriptor
    try:
        with pytest.raises(ValueError, match="workflow run is active"):
            second._acquire_run_lock("00000000-0000-0000-0000-000000000004")
    finally:
        first._release_run_lock(identifier)
