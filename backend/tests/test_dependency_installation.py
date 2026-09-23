from __future__ import annotations

import hashlib
import io
import itertools
import json
import shutil
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from missus_tom.models.dependencies import DependencyInstallJob
from missus_tom.services import dependencies
from missus_tom.services.resources import StorageInspection


def _linux_storage(path: Path, *, free_bytes: int = 100 * 1024**3) -> StorageInspection:
    return StorageInspection(
        path=str(path),
        filesystem_type="ext4",
        free_bytes=free_bytes,
        total_bytes=free_bytes * 2,
        host_free_bytes=None,
        measurement="linux",
        warning=None,
    )


def job() -> DependencyInstallJob:
    return DependencyInstallJob(
        job_identifier=str(uuid4()),
        pipeline_identifier="ont-analysis",
        status="running",
        message="testing",
    )


def bulk_job() -> DependencyInstallJob:
    return DependencyInstallJob(
        job_identifier=str(uuid4()),
        pipeline_identifier="bulk-rnaseq",
        status="running",
        message="testing",
    )


def trust_dorado_archive(monkeypatch: pytest.MonkeyPatch, archive: Path) -> None:
    monkeypatch.setattr(
        dependencies,
        "_DORADO_ARCHIVE_SHA256",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
    )


class DownloadResponse:
    def __init__(self, payload: bytes, content_length: str | None) -> None:
        self._payload = io.BytesIO(payload)
        self.headers = {} if content_length is None else {"Content-Length": content_length}
        self.read_sizes: list[int] = []

    def __enter__(self) -> DownloadResponse:
        return self

    def __exit__(self, *_: object) -> None:
        self._payload.close()

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._payload.read(size)


def test_dorado_release_is_pinned_to_the_reviewed_official_archive() -> None:
    assert dependencies._DORADO_VERSION == "2.1.2"
    assert dependencies._DORADO_URL == (
        "https://cdn.oxfordnanoportal.com/software/analysis/dorado-2.1.2-linux-x64.tar.gz"
    )
    assert dependencies._DORADO_ARCHIVE_SHA256 == (
        "f4ed83acfb75cf07ffe8a0fc78e26828fc911fcfc8177920be6104e1d0e02485"
    )
    assert dependencies._DORADO_ARCHIVE_ROOT == "dorado-2.1.2-linux-x64"
    assert dependencies._DORADO_ARCHIVE_SIZE_BYTES == 3_466_666_099
    assert dependencies._DORADO_CUDNN_VERSION == "9.8.0"
    expected_reviewed_links = (
        ("", "/etc/alternatives/libcudnn_so", "libcudnn.so.9.8.0"),
        ("_graph", "/etc/alternatives/libcudnn_graph_so", "libcudnn_graph.so.9.8.0"),
        (
            "_engines_runtime_compiled",
            "/etc/alternatives/libcudnn_engines_runtime_compiled_so",
            "libcudnn_engines_runtime_compiled.so.9.8.0",
        ),
        ("_adv", "/etc/alternatives/libcudnn_adv_so", "libcudnn_adv.so.9.8.0"),
        (
            "_engines_precompiled",
            "/etc/alternatives/libcudnn_engines_precompiled_so",
            "libcudnn_engines_precompiled.so.9.8.0",
        ),
        ("_ops", "/etc/alternatives/libcudnn_ops_so", "libcudnn_ops.so.9.8.0"),
        (
            "_heuristic",
            "/etc/alternatives/libcudnn_heuristic_so",
            "libcudnn_heuristic.so.9.8.0",
        ),
        ("_cnn", "/etc/alternatives/libcudnn_cnn_so", "libcudnn_cnn.so.9.8.0"),
    )
    assert (
        tuple(
            (
                component,
                f"/etc/alternatives/libcudnn{component}_so",
                f"libcudnn{component}.so.{dependencies._DORADO_CUDNN_VERSION}",
            )
            for component in dependencies._DORADO_CUDNN_COMPONENTS
        )
        == expected_reviewed_links
    )


def test_dorado_download_transfers_exact_expected_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "dorado.tar.gz"
    payload = b"official-archive"
    monkeypatch.setattr(
        dependencies.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: DownloadResponse(payload, str(len(payload))),
    )

    dependencies.DependencyInstaller._download(
        dependencies._DORADO_URL, destination, expected_size_bytes=len(payload)
    )

    assert destination.read_bytes() == payload


def test_dorado_download_rejects_content_length_mismatch_and_removes_partial_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "dorado.tar.gz"
    monkeypatch.setattr(
        dependencies.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: DownloadResponse(b"payload", "8"),
    )

    with pytest.raises(RuntimeError, match="Content-Length"):
        dependencies.DependencyInstaller._download(
            dependencies._DORADO_URL, destination, expected_size_bytes=7
        )

    assert not destination.exists()


@pytest.mark.parametrize(
    ("payload", "message"),
    [(b"12345678", "exceeded expected size"), (b"123456", "does not match expected size")],
)
def test_dorado_download_rejects_oversize_or_short_response_and_removes_partial_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes, message: str
) -> None:
    destination = tmp_path / "dorado.tar.gz"
    response = DownloadResponse(payload, "7")
    monkeypatch.setattr(
        dependencies.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(RuntimeError, match=message):
        dependencies.DependencyInstaller._download(
            dependencies._DORADO_URL, destination, expected_size_bytes=7
        )

    assert not destination.exists()
    if len(payload) > 7:
        assert response.read_sizes == [8]


def test_dorado_retains_distribution_and_contained_library_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    (source / "bin").mkdir(parents=True)
    (source / "lib").mkdir()
    (source / "bin" / "dorado").write_text("#!/bin/sh\necho 2.1.2\n")
    (source / "lib" / "example.so").write_text("library")
    (source / "lib" / "alias.so").symlink_to("example.so")
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname=dependencies._DORADO_ARCHIVE_ROOT)
    trust_dorado_archive(monkeypatch, archive)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(
        installer, "_download", lambda _, target, **__: shutil.copyfile(archive, target)
    )
    destination = tmp_path / "generation"
    destination.mkdir()

    install_job = job()
    installer._install_dorado(install_job, destination)

    executable = destination / "environment" / "bin" / "dorado"
    assert executable.is_symlink()
    distribution = executable.resolve().parents[1]
    assert (distribution / "lib" / "alias.so").read_text() == "library"
    assert not (destination / "dorado.tar.gz").exists()
    assert any(
        "Downloading Dorado 2.1.2 (3,466,666,099 bytes" in line for line in install_job.log_tail
    )
    assert any("Installed Dorado 2.1.2" in line for line in install_job.log_tail)


def test_dorado_streams_archive_checksum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    (source / "bin").mkdir(parents=True)
    (source / "bin" / "dorado").write_text("#!/bin/sh\n", encoding="utf-8")
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname=dependencies._DORADO_ARCHIVE_ROOT)
    trust_dorado_archive(monkeypatch, archive)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _: (_ for _ in ()).throw(AssertionError("archive must be checksummed as a stream")),
    )
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(
        installer, "_download", lambda _, target, **__: shutil.copyfile(archive, target)
    )
    destination = tmp_path / "generation"
    destination.mkdir()

    installer._install_dorado(job(), destination)


def test_dorado_rejects_archive_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("../../escaped")
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))
    trust_dorado_archive(monkeypatch, archive)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(
        installer, "_download", lambda _, target, **__: shutil.copyfile(archive, target)
    )
    destination = tmp_path / "generation"
    destination.mkdir()

    with pytest.raises(RuntimeError, match="unsafe path"):
        installer._install_dorado(job(), destination)
    assert not (tmp_path / "escaped").exists()


def test_dorado_localizes_all_reviewed_cudnn_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    (source / "bin").mkdir(parents=True)
    (source / "lib").mkdir()
    (source / "bin" / "dorado").write_text("#!/bin/sh\necho 2.1.2\n")
    for component in dependencies._DORADO_CUDNN_COMPONENTS:
        name = f"libcudnn{component}.so"
        (source / "lib" / f"{name}.9.8.0").write_text("private library")
        (source / "lib" / name).symlink_to(f"/etc/alternatives/{name.replace('.', '_')}")
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname=dependencies._DORADO_ARCHIVE_ROOT)
    trust_dorado_archive(monkeypatch, archive)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(
        installer, "_download", lambda _, target, **__: shutil.copyfile(archive, target)
    )
    destination = tmp_path / "generation"
    destination.mkdir()

    installer._install_dorado(job(), destination)

    distribution = (destination / "environment" / "bin" / "dorado").resolve().parents[1]
    for component in dependencies._DORADO_CUDNN_COMPONENTS:
        link = distribution / "lib" / f"libcudnn{component}.so"
        assert not link.readlink().is_absolute()
        assert link.resolve().is_relative_to(destination)
        assert link.read_text() == "private library"


@pytest.mark.parametrize("target", ["/etc/alternatives/libcudnn_so", "/unreviewed/library.so"])
def test_dorado_never_falls_back_to_external_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo(f"{dependencies._DORADO_ARCHIVE_ROOT}/lib/libcudnn.so")
        member.type = tarfile.SYMTYPE
        member.linkname = target
        bundle.addfile(member)
    trust_dorado_archive(monkeypatch, archive)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(
        installer, "_download", lambda _, path, **__: shutil.copyfile(archive, path)
    )
    destination = tmp_path / "generation"
    destination.mkdir()
    with pytest.raises(RuntimeError, match="missing required private library|unsafe link"):
        installer._install_dorado(job(), destination)


def test_dorado_rejects_archive_without_matching_pinned_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo(f"{dependencies._DORADO_ARCHIVE_ROOT}/bin/dorado")
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))
    monkeypatch.setattr(dependencies, "_DORADO_ARCHIVE_SHA256", "0" * 64)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(
        installer, "_download", lambda _, path, **__: shutil.copyfile(archive, path)
    )
    destination = tmp_path / "generation"
    destination.mkdir()

    with pytest.raises(RuntimeError, match="checksum verification failed"):
        installer._install_dorado(job(), destination)


def test_failed_candidate_does_not_replace_active_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    root = tmp_path / "dependencies" / "ont-analysis"
    root.mkdir(parents=True)
    original = {"environment": "environments/previous/environment"}
    (root / "active.json").write_text(json.dumps(original))
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "dependencies")
    monkeypatch.setattr(dependencies, "inspect_storage", lambda path: _linux_storage(path))
    monkeypatch.setattr(installer, "_ensure_micromamba", lambda *_: Path("/bin/true"))
    monkeypatch.setattr(installer, "_run", Mock())
    monkeypatch.setattr(installer, "_install_dorado", Mock())
    monkeypatch.setattr(
        installer, "_verify_environment", Mock(side_effect=RuntimeError("unusable"))
    )

    with pytest.raises(RuntimeError, match="unusable"):
        installer._install_environment(job())
    assert json.loads((root / "active.json").read_text()) == original


def test_bulk_install_uses_native_r_packages_without_docker_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "dependencies")
    monkeypatch.setattr(dependencies, "inspect_storage", lambda path: _linux_storage(path))
    monkeypatch.setattr(installer, "_ensure_micromamba", lambda *_: Path("/bin/true"))
    run = Mock()
    monkeypatch.setattr(installer, "_run", run)
    install_r = Mock()
    monkeypatch.setattr(installer, "_install_bulk_r_packages", install_r)
    install_images = Mock()
    monkeypatch.setattr(installer, "_install_bulk_images", install_images)
    monkeypatch.setattr(installer, "_verify_environment", Mock())
    monkeypatch.setattr(installer, "_activate", Mock())

    install_job = bulk_job()
    installer._install_environment(install_job)

    create_command = run.call_args.args[1]
    assert "fastqc=0.12.1" in create_command
    assert "multiqc=1.33" in create_command
    assert "cutadapt=5.2" in create_command
    assert "kallisto=0.52.0" in create_command
    install_r.assert_called_once()
    assert install_r.call_args.args[0] is install_job
    install_images.assert_not_called()


def test_bulk_verification_checks_kallisto_and_r_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    prefix = tmp_path / "dependencies/bulk-rnaseq/environments/generation/environment"
    (prefix / "bin").mkdir(parents=True)
    for tool in dependencies._TOOL_CATALOG["bulk-rnaseq"]:
        (prefix / "bin" / tool).write_text("#!/bin/sh\n", encoding="utf-8")
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "dependencies")
    run = Mock()
    monkeypatch.setattr(installer, "_run", run)

    installer._verify_environment(bulk_job(), prefix)

    commands = [call.args[1] for call in run.call_args_list]
    assert [str(prefix / "bin" / "kallisto"), "version"] in commands
    r_command = commands[-1]
    assert r_command[:3] == [str(prefix / "bin" / "Rscript"), "--vanilla", "-e"]
    assert all(package in r_command[-1] for package in dependencies.BULK_R_PACKAGES)


def test_active_prefix_is_not_renamed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    root = tmp_path / "dependencies" / "ont-analysis"
    prefix = root / "environments" / "generation" / "environment"
    (prefix / "bin").mkdir(parents=True)
    dependencies.DependencyInstaller._activate(root, prefix)
    assert dependencies._managed_bin("ont-analysis") == prefix / "bin"
    assert prefix.is_dir()


def test_bootstrap_verifies_archive_and_binary_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"#!/bin/sh\necho bootstrap\n"
    archive = tmp_path / "bootstrap.tar.bz2"
    with tarfile.open(archive, "w:bz2") as bundle:
        member = tarfile.TarInfo("bin/micromamba")
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))
    binary_hash = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(dependencies, "_MICROMAMBA_SHA256", binary_hash)
    monkeypatch.setattr(
        dependencies, "_MICROMAMBA_ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(installer, "_download_text", lambda _: binary_hash)
    monkeypatch.setattr(installer, "_download", lambda _, target: shutil.copyfile(archive, target))
    staging = tmp_path / "staging"
    staging.mkdir()
    executable = installer._ensure_micromamba(staging, job())
    assert executable.read_bytes() == payload


def test_silent_installer_command_is_terminated_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    clock = itertools.count(0, 1801)
    monkeypatch.setattr(dependencies.time, "monotonic", lambda: next(clock))
    with pytest.raises(RuntimeError, match="timed out"):
        installer._run(job(), ["/bin/sleep", "30"])
