from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from missus_tom.models.manifest import Scalar, normalize_user_path


class ReadAssignment(StrEnum):
    R1 = "R1"
    R2 = "R2"
    SINGLE = "single"
    AMBIGUOUS = "ambiguous"


class PairingStatus(StrEnum):
    PAIRED = "paired"
    SINGLE = "single"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"
    QUANTIFIED = "quantified"


class FastqDiscoveryRequest(BaseModel):
    directory: str
    recursive: bool = True

    @field_validator("directory")
    @classmethod
    def normalize_directory(cls, value: str) -> str:
        return normalize_user_path(value)


class DiscoveredFastq(BaseModel):
    path: str
    size_bytes: int = Field(ge=0)
    read: ReadAssignment
    lane: str | None = None


class ProposedSample(BaseModel):
    sample_id: str
    r1_files: list[str] = Field(default_factory=list)
    r2_files: list[str] = Field(default_factory=list)
    abundance_tsv: str | None = None
    lanes: list[str] = Field(default_factory=list)
    pairing_status: PairingStatus
    warnings: list[str] = Field(default_factory=list)
    condition: str = ""
    biological_replicate: str = ""
    batch: str | None = None
    covariates: dict[str, Scalar] = Field(default_factory=dict)
    included: bool = True


class FastqDiscoveryResult(BaseModel):
    directory: str
    samples: list[ProposedSample]
    files: list[DiscoveredFastq]
    unassigned_files: list[str]
    warnings: list[str]
    total_files: int
    total_bytes: int


class QuantificationDiscoveryRequest(BaseModel):
    directory: str
    recursive: bool = True

    @field_validator("directory")
    @classmethod
    def normalize_directory(cls, value: str) -> str:
        return normalize_user_path(value)


class DiscoveredQuantification(BaseModel):
    sample_id: str
    path: str
    size_bytes: int = Field(ge=0)


class QuantificationDiscoveryResult(BaseModel):
    directory: str
    samples: list[ProposedSample]
    files: list[DiscoveredQuantification]
    warnings: list[str]
    total_files: int
    total_bytes: int
