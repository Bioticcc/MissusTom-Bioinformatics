from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from missus_tom.models.dependencies import (
    DependencyInstallJob,
    DependencyInstallStatus,
    DependencyRequirement,
)
from missus_tom.services import dependencies
from missus_tom.services.dependencies import (
    BULK_R_PACKAGES,
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
    assert status.installable is True
    assert status.manual_requirements == []
    assert "data.table" in ONT_R_PACKAGES


def test_ont_installation_status_is_available_with_pinned_dorado_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = DependencyInstaller(state_directory=tmp_path / "dependencies")
    monkeypatch.setattr(installer, "_supported_platform", lambda: True)

    status = installer.status("ont-analysis")

    assert status.installable is True
    assert status.manual_requirements == []


def test_bulk_requirements_are_native_and_do_not_require_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = DependencyInstaller(state_directory=tmp_path / "dependencies")
    monkeypatch.setattr(dependencies, "runtime_tool", lambda *_: None)

    status = installer.status("bulk-rnaseq")
    requirement_names = [requirement.name for requirement in status.requirements]

    assert dependencies._PACKAGE_CATALOG["bulk-rnaseq"] == (
        "nextflow=24.04.4",
        "openjdk=17",
        "fastqc=0.12.1",
        "multiqc=1.33",
        "cutadapt=5.2",
        "kallisto=0.52.0",
        "r-base",
    )
    assert BULK_R_PACKAGES == ("DESeq2", "tximport", "ggplot2")
    assert requirement_names == [
        "nextflow",
        "java",
        "fastqc",
        "multiqc",
        "cutadapt",
        "kallisto",
        "Rscript",
        "Bulk R packages",
    ]
    assert "Docker daemon" not in requirement_names
    assert "Bulk analysis image" not in requirement_names
    assert status.manual_requirements == []


def test_kallisto_readiness_uses_version_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    installer = DependencyInstaller()
    monkeypatch.setattr(dependencies, "runtime_tool", lambda *_: "/managed/bin/kallisto")
    monkeypatch.setattr(dependencies, "runtime_environment", lambda _: {"PATH": "/managed/bin"})
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(dependencies.subprocess, "run", run)

    requirement = installer._tool_requirement("kallisto", "bulk-rnaseq", managed=False)

    assert requirement.installed is True
    assert run.call_args.args[0] == ["/managed/bin/kallisto", "version"]


def test_ont_installation_still_fails_closed_without_a_dorado_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = DependencyInstaller(state_directory=tmp_path / "dependencies")
    monkeypatch.setattr(installer, "_supported_platform", lambda: True)
    monkeypatch.setattr(dependencies, "_DORADO_ARCHIVE_SHA256", None)

    status = installer.status("ont-analysis")

    assert status.installable is False
    assert "SHA-256" in status.manual_requirements[0]
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


def test_dependency_install_log_supports_offset_reads(tmp_path: Path) -> None:
    installer = DependencyInstaller(state_directory=tmp_path / "dependencies")
    installer._safe_directory(tmp_path / "dependencies" / "jobs")
    job = DependencyInstallJob(
        job_identifier="00000000-0000-0000-0000-000000000004",
        pipeline_identifier="bulk-rnaseq",
        status=DependencyInstallStatus.RUNNING,
        message="test",
    )
    installer._append_command_log(job, "alpha")
    installer._append_command_log(job, "beta")

    first = installer.read_log(job.job_identifier, offset=0, limit=6)
    second = installer.read_log(job.job_identifier, offset=first.next_offset, limit=10)

    assert first.text == "alpha\n"
    assert first.truncated is True
    assert second.text == "beta\n"
    assert second.truncated is False
    assert second.next_offset == first.bytes_available


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


def test_install_rejects_unconfirmed_wsl_virtual_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from missus_tom.services.resources import StorageInspection

    installer = DependencyInstaller(state_directory=tmp_path / "dependencies")
    job = DependencyInstallJob(
        job_identifier="00000000-0000-0000-0000-000000000005",
        pipeline_identifier="bulk-rnaseq",
        status=DependencyInstallStatus.RUNNING,
        message="test",
    )

    def fake_storage(_path: Path) -> StorageInspection:
        return StorageInspection(
            path="/home/user/.missus-tom",
            filesystem_type="ext4",
            free_bytes=500 * 1024**3,
            total_bytes=1000 * 1024**3,
            host_free_bytes=None,
            measurement="wsl_virtual",
            warning="WSL virtual disk free space may not reflect Windows host free space",
        )

    monkeypatch.setattr(dependencies, "inspect_storage", fake_storage)

    with pytest.raises(RuntimeError, match="cannot confirm Windows host free space"):
        installer._install_environment(job)
