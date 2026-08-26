from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DirectoryEntryKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


class DirectoryPreviewRequest(BaseModel):
    directory: str = Field(min_length=1)


class DirectoryEntry(BaseModel):
    name: str
    kind: DirectoryEntryKind
    file_type: str
    size_bytes: int | None = None


class DirectoryPreview(BaseModel):
    directory: str
    total_entries: int
    total_files: int
    total_directories: int
    total_bytes: int
    contains_data: bool
    truncated: bool
    entries: list[DirectoryEntry]
