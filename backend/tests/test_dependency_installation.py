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


def job() -> DependencyInstallJob:
    return DependencyInstallJob(
        job_identifier=str(uuid4()),
        pipeline_identifier="ont-analysis",
        status="running",
        message="testing",
    )


def trust_dorado_archive(monkeypatch: pytest.MonkeyPatch, archive: Path) -> None:
    monkeypatch.setattr(
        dependencies,
        "_DORADO_ARCHIVE_SHA256",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
    )


def test_dorado_retains_distribution_and_contained_library_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    (source / "bin").mkdir(parents=True)
    (source / "lib").mkdir()
    (source / "bin" / "dorado").write_text("#!/bin/sh\necho 2.0.0\n")
    (source / "lib" / "example.so").write_text("library")
    (source / "lib" / "alias.so").symlink_to("example.so")
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname="dorado-2.0.0-linux-x64")
    trust_dorado_archive(monkeypatch, archive)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(installer, "_download", lambda _, target: shutil.copyfile(archive, target))
    destination = tmp_path / "generation"
    destination.mkdir()

    installer._install_dorado(job(), destination)

    executable = destination / "environment" / "bin" / "dorado"
    assert executable.is_symlink()
    distribution = executable.resolve().parents[1]
    assert (distribution / "lib" / "alias.so").read_text() == "library"
    assert not (destination / "dorado.tar.gz").exists()


def test_dorado_rejects_archive_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("../../escaped")
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))
    trust_dorado_archive(monkeypatch, archive)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(installer, "_download", lambda _, target: shutil.copyfile(archive, target))
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
    (source / "bin" / "dorado").write_text("#!/bin/sh\necho 2.0.0\n")
    for component in dependencies._DORADO_CUDNN_COMPONENTS:
        name = f"libcudnn{component}.so"
        (source / "lib" / f"{name}.9.8.0").write_text("private library")
        (source / "lib" / name).symlink_to(f"/etc/alternatives/{name.replace('.', '_')}")
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname="dorado-2.0.0-linux-x64")
    trust_dorado_archive(monkeypatch, archive)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(installer, "_download", lambda _, target: shutil.copyfile(archive, target))
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
        member = tarfile.TarInfo("dorado-2.0.0-linux-x64/lib/libcudnn.so")
        member.type = tarfile.SYMTYPE
        member.linkname = target
        bundle.addfile(member)
    trust_dorado_archive(monkeypatch, archive)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(installer, "_download", lambda _, path: shutil.copyfile(archive, path))
    destination = tmp_path / "generation"
    destination.mkdir()
    with pytest.raises(RuntimeError, match="missing required private library|unsafe link"):
        installer._install_dorado(job(), destination)


def test_dorado_rejects_archive_without_matching_pinned_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("dorado-2.0.0-linux-x64/bin/dorado")
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))
    monkeypatch.setattr(dependencies, "_DORADO_ARCHIVE_SHA256", "0" * 64)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    monkeypatch.setattr(installer, "_download", lambda _, path: shutil.copyfile(archive, path))
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
    monkeypatch.setattr(
        dependencies.shutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 1024**3)
    )
    monkeypatch.setattr(installer, "_ensure_micromamba", lambda *_: Path("/bin/true"))
    monkeypatch.setattr(installer, "_run", Mock())
    monkeypatch.setattr(installer, "_install_dorado", Mock())
    monkeypatch.setattr(
        installer, "_verify_environment", Mock(side_effect=RuntimeError("unusable"))
    )

    with pytest.raises(RuntimeError, match="unusable"):
        installer._install_environment(job())
    assert json.loads((root / "active.json").read_text()) == original


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
