from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from missus_tom.models.manifest import normalize_user_path


class MetadataCsvRequest(BaseModel):
    path: str
    sample_ids: list[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        return normalize_user_path(value)


class MetadataRow(BaseModel):
    sample_id: str
    condition: str
    batch: str | None = None
    biological_replicate: str | None = None
    intervention: str | None = None
    matched_sample_id: str | None = None


class MetadataCsvResult(BaseModel):
    path: str
    rows: list[MetadataRow]
    warnings: list[str]
    unmatched_samples: list[str]
    unused_rows: list[str]
