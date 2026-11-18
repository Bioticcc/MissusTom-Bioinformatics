from __future__ import annotations

import json
from pathlib import Path

import pytest

from missus_tom.models.dependencies import DependencyInstallJob
from missus_tom.services import dependencies, modkit_repair


def artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "artifact"
    directory.mkdir()
    binary = directory / "modkit"
    binary.write_bytes(b"reviewed binary fixture")
    manifest = {**modkit_repair.recipe(), "binary_sha256": modkit_repair.binary_sha256(binary)}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(modkit_repair, "artifact_directory", lambda: directory)
    return directory


def test_repair_install_preserves_conda_cache_hardlinks(tmp_path, monkeypatch):
    source = artifact(tmp_path, monkeypatch)
    prefix = tmp_path / "candidate"
    (prefix / "bin").mkdir(parents=True)
    cache = tmp_path / "package-cache-modkit"
    cache.write_bytes(b"stock tool")
    (prefix / "bin/modkit").hardlink_to(cache)
    installer = dependencies.DependencyInstaller(state_directory=tmp_path / "state")
    job = DependencyInstallJob(
        job_identifier="00000000-0000-0000-0000-000000000000",
        pipeline_identifier="ont-analysis",
        status="running",
        message="test",
    )
    installer._install_modkit_repair(job, prefix)
    assert cache.read_bytes() == b"stock tool"
    assert (prefix / "bin/modkit").read_bytes() == (source / "modkit").read_bytes()
    assert modkit_repair.problems(prefix) == []
    assert (
        dependencies.ont_lock_provenance(prefix)["modkit_repair"]["repair_id"]
        == (modkit_repair.recipe()["repair_id"])
    )
    (prefix / "bin/modkit").write_bytes(b"different binary")
    assert "checksum mismatch" in modkit_repair.problems(prefix)[0]


def test_wrong_source_and_missing_receipt_fail_closed(tmp_path, monkeypatch):
    source = artifact(tmp_path, monkeypatch)
    manifest = source / "manifest.json"
    content = json.loads(manifest.read_text())
    content["source_commit"] = "unreviewed"
    manifest.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="source identity"):
        modkit_repair.validate(source / "modkit", manifest)
    assert modkit_repair.problems(tmp_path / "old-environment")
