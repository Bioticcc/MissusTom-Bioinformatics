from __future__ import annotations

import os
from pathlib import Path

from missus_tom.models.discovery import PairingStatus
from missus_tom.services.fastq import discover_fastqs


def make_files(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).touch()


def test_correct_paired_end_matching(tmp_path: Path) -> None:
    make_files(tmp_path, "alpha_R1_001.fastq.gz", "alpha_R2_001.fastq.gz")
    result = discover_fastqs(str(tmp_path))

    assert result.total_files == 2
    assert len(result.samples) == 1
    assert result.samples[0].sample_id == "alpha"
    assert result.samples[0].pairing_status == PairingStatus.PAIRED
    assert len(result.samples[0].r1_files) == len(result.samples[0].r2_files) == 1


def test_single_end_files(tmp_path: Path) -> None:
    make_files(tmp_path, "single.fastq")
    result = discover_fastqs(str(tmp_path))

    assert result.samples[0].pairing_status == PairingStatus.SINGLE
    assert result.samples[0].r2_files == []


def test_missing_mate_is_reported(tmp_path: Path) -> None:
    make_files(tmp_path, "orphan_R1.fastq.gz")
    result = discover_fastqs(str(tmp_path))

    assert result.samples[0].pairing_status == PairingStatus.UNMATCHED
    assert any("Missing R2" in warning for warning in result.samples[0].warnings)


def test_duplicate_matches_are_ambiguous(tmp_path: Path) -> None:
    make_files(tmp_path, "dup_R1.fastq", "dup_R1.fq", "dup_R2.fastq")
    result = discover_fastqs(str(tmp_path))

    assert result.samples[0].pairing_status == PairingStatus.AMBIGUOUS
    assert any("Duplicate assignments" in warning for warning in result.samples[0].warnings)


def test_multiple_lanes_are_preserved(tmp_path: Path) -> None:
    make_files(
        tmp_path,
        "lane_sample_L001_R1_001.fastq.gz",
        "lane_sample_L001_R2_001.fastq.gz",
        "lane_sample_L002_R1_001.fastq.gz",
        "lane_sample_L002_R2_001.fastq.gz",
    )
    result = discover_fastqs(str(tmp_path))

    assert len(result.samples) == 1
    assert result.samples[0].sample_id == "lane_sample"
    assert result.samples[0].lanes == ["L001", "L002"]
    assert len(result.samples[0].r1_files) == len(result.samples[0].r2_files) == 2


def test_ambiguous_filename_is_unassigned(tmp_path: Path) -> None:
    make_files(tmp_path, "confusing_R1_R2.fastq.gz")
    result = discover_fastqs(str(tmp_path))

    assert len(result.unassigned_files) == 1
    assert result.samples == []
    assert any("more than one read marker" in warning for warning in result.warnings)


def test_compressed_and_uncompressed_extensions(tmp_path: Path) -> None:
    make_files(
        tmp_path,
        "a_R1.fq.gz",
        "a_R2.fq.gz",
        "b_1.fastq",
        "b_2.fastq",
    )
    result = discover_fastqs(str(tmp_path))

    assert result.total_files == 4
    assert {sample.sample_id for sample in result.samples} == {"a", "b"}
    assert all(sample.pairing_status == PairingStatus.PAIRED for sample in result.samples)


def test_filenames_containing_spaces_are_safe(tmp_path: Path) -> None:
    make_files(tmp_path, "sample alpha_R1.fastq.gz", "sample alpha_R2.fastq.gz")
    result = discover_fastqs(str(tmp_path))

    assert result.samples[0].sample_id == "sample_alpha"
    assert "sample alpha_R1.fastq.gz" in result.samples[0].r1_files[0]


def test_empty_directory(tmp_path: Path) -> None:
    result = discover_fastqs(str(tmp_path))

    assert result.total_files == 0
    assert result.samples == []
    assert any("No supported FASTQ" in warning for warning in result.warnings)


def test_unsupported_files_are_ignored(tmp_path: Path) -> None:
    make_files(tmp_path, "notes.txt", "alignment.bam", "archive.zip")
    result = discover_fastqs(str(tmp_path))

    assert result.total_files == 0
    assert result.files == []


def test_symlink_is_not_followed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    make_files(target, "hidden_R1.fastq.gz", "hidden_R2.fastq.gz")
    link = tmp_path / "linked-data"
    os.symlink(target, link)

    result = discover_fastqs(str(tmp_path), recursive=True)

    assert result.total_files == 2
    assert all("linked-data" not in item.path for item in result.files)
    assert any("Skipped symbolic link" in warning for warning in result.warnings)
