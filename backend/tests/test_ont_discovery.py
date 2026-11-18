from pathlib import Path

import pytest
from fastapi import HTTPException

from missus_tom.api.routes import post_ont_discover
from missus_tom.models.discovery import OntDiscoveryRequest
from missus_tom.services.ont_discovery import discover_ont_bams


def test_scan_ignores_indexes_and_symlinks_and_preserves_distinct_files(tmp_path: Path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for folder in (inputs, inputs / "nested"):
        folder.mkdir(exist_ok=True)
        (folder / "same.bam").write_bytes(b"bam")
        (folder / "same.bam.bai").touch()
    (inputs / "notes.txt").touch()
    (inputs / "link.bam").symlink_to(inputs / "same.bam")
    (inputs / "linked_dir").symlink_to(inputs / "nested", target_is_directory=True)
    result = discover_ont_bams(str(inputs))
    assert result.total_files == 2
    assert result.total_bytes == 6
    assert len({sample.sample_id for sample in result.samples}) == 2
    assert all(len(sample.ont_bam_files) == 1 for sample in result.samples)
    assert all(not sample.condition for sample in result.samples)
    assert len([warning for warning in result.warnings if "symbolic link" in warning]) == 2
    assert discover_ont_bams(str(inputs), recursive=False).total_files == 1


def test_names_remain_unique_after_sanitizing(tmp_path: Path):
    for name in ("a b.bam", "a_b.bam", "a_b_2.bam", "...bam"):
        (tmp_path / name).touch()
    samples = discover_ont_bams(str(tmp_path)).samples
    assert len({sample.sample_id for sample in samples}) == 4
    assert all(sample.sample_id for sample in samples)


def test_endpoint_returns_typed_bams_and_rejects_invalid_paths(tmp_path: Path):
    (tmp_path / "A.bam").write_bytes(b"abc")
    result = post_ont_discover(OntDiscoveryRequest(directory=str(tmp_path)))
    assert result.data.model_dump()["samples"][0]["ont_bam_files"] == [str(tmp_path / "A.bam")]
    for path in (tmp_path / "missing", tmp_path / "A.bam"):
        with pytest.raises(HTTPException) as error:
            post_ont_discover(OntDiscoveryRequest(directory=str(path)))
        assert error.value.status_code == 400
    link = tmp_path / "alias"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic links"):
        discover_ont_bams(str(link))
    with pytest.raises(HTTPException) as error:
        post_ont_discover(OntDiscoveryRequest(directory=str(link)))
    assert error.value.status_code == 400


def test_empty_directory(tmp_path: Path):
    result = discover_ont_bams(str(tmp_path))
    assert result.samples == []
    assert result.total_bytes == result.total_files == 0
