from __future__ import annotations

import os
from pathlib import Path

from missus_tom.models.directories import (
    DirectoryEntry,
    DirectoryEntryKind,
    DirectoryPreview,
)

MAX_PREVIEW_ENTRIES = 500


def _file_type(name: str, kind: DirectoryEntryKind) -> str:
    if kind == DirectoryEntryKind.DIRECTORY:
        return "Folder"
    if kind == DirectoryEntryKind.SYMLINK:
        return "Symbolic link"
    lower = name.lower()
    for suffix, label in (
        (".fastq.gz", "FASTQ.GZ"),
        (".fq.gz", "FQ.GZ"),
        (".fastq", "FASTQ"),
        (".fq", "FQ"),
        (".html", "HTML"),
        (".json", "JSON"),
        (".tsv", "TSV"),
        (".csv", "CSV"),
        (".pdf", "PDF"),
        (".png", "PNG"),
        (".log", "Log"),
        (".txt", "Text"),
    ):
        if lower.endswith(suffix):
            return label
    suffix = Path(name).suffix.lstrip(".")
    return suffix.upper() if suffix else "File"


def preview_directory(directory: str) -> DirectoryPreview:
    """Return immediate metadata for a directory explicitly selected by the user."""
    requested = Path(directory).expanduser()
    resolved = requested.resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a directory: {resolved}")

    entries: list[DirectoryEntry] = []
    total_entries = 0
    total_files = 0
    total_directories = 0
    total_bytes = 0
    with os.scandir(resolved) as iterator:
        for item in iterator:
            total_entries += 1
            size: int | None = None
            if item.is_symlink():
                kind = DirectoryEntryKind.SYMLINK
            elif item.is_dir(follow_symlinks=False):
                kind = DirectoryEntryKind.DIRECTORY
                total_directories += 1
            elif item.is_file(follow_symlinks=False):
                kind = DirectoryEntryKind.FILE
                total_files += 1
                try:
                    size = item.stat(follow_symlinks=False).st_size
                    total_bytes += size
                except OSError:
                    size = None
            else:
                kind = DirectoryEntryKind.OTHER

            if len(entries) < MAX_PREVIEW_ENTRIES:
                entries.append(
                    DirectoryEntry(
                        name=item.name,
                        kind=kind,
                        file_type=_file_type(item.name, kind),
                        size_bytes=size,
                    )
                )

    entries.sort(
        key=lambda entry: (entry.kind != DirectoryEntryKind.DIRECTORY, entry.name.casefold())
    )
    return DirectoryPreview(
        directory=str(resolved),
        total_entries=total_entries,
        total_files=total_files,
        total_directories=total_directories,
        total_bytes=total_bytes,
        contains_data=total_entries > 0,
        truncated=total_entries > len(entries),
        entries=entries,
    )
