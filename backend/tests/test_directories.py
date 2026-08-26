from __future__ import annotations

from pathlib import Path

from missus_tom.models.directories import DirectoryEntryKind
from missus_tom.services.directories import MAX_PREVIEW_ENTRIES, preview_directory


def test_preview_lists_immediate_entries_without_following_symlinks(tmp_path: Path) -> None:
    (tmp_path / "reads").mkdir()
    (tmp_path / "sample_R1.fastq.gz").write_bytes(b"1234")
    (tmp_path / "report.html").write_text("report", encoding="utf-8")
    (tmp_path / "reads" / "nested.fastq.gz").touch()
    (tmp_path / "linked").symlink_to(tmp_path / "reads", target_is_directory=True)

    result = preview_directory(str(tmp_path))

    assert result.total_entries == 4
    assert result.total_files == 2
    assert result.total_directories == 1
    assert result.total_bytes == 10
    assert result.contains_data is True
    by_name = {entry.name: entry for entry in result.entries}
    assert by_name["sample_R1.fastq.gz"].file_type == "FASTQ.GZ"
    assert by_name["linked"].kind == DirectoryEntryKind.SYMLINK
    assert "nested.fastq.gz" not in by_name


def test_preview_empty_directory(tmp_path: Path) -> None:
    result = preview_directory(str(tmp_path))

    assert result.total_entries == 0
    assert result.contains_data is False
    assert result.entries == []


def test_preview_reports_truncation_but_counts_all_entries(tmp_path: Path) -> None:
    for index in range(MAX_PREVIEW_ENTRIES + 2):
        (tmp_path / f"file-{index:04d}.txt").touch()

    result = preview_directory(str(tmp_path))

    assert result.total_entries == MAX_PREVIEW_ENTRIES + 2
    assert len(result.entries) == MAX_PREVIEW_ENTRIES
    assert result.truncated is True
