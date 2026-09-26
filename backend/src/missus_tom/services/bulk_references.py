"""Prepare normalized Bulk RNA-seq annotation and reusable Kallisto indexes."""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TextIO

from pydantic import BaseModel, ConfigDict

from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest

NORMALIZATION_VERSION: Final = "1"
TRANSCRIPT_TO_GENE_COLUMNS: Final = (
    "transcript_id",
    "gene_id",
    "gene_name",
    "gene_biotype",
    "transcript_biotype",
)
MIN_ACCEPTABLE_OVERLAP: Final = 0.95
VERSION_STRIP_MIN_IMPROVEMENT: Final = 0.10
_COMPLETE_MARKER: Final = "complete.json"
_FAILED_MARKER: Final = "failed.json"
_INDEX_FILENAME: Final = "transcripts.idx"
_MAPPING_FILENAME: Final = "transcript_to_gene.tsv"
_BUILD_LOG: Final = "build.log"
PRODUCTION_PIPELINE_VERSION: Final = "0.5.0"
LEGACY_PIPELINE_VERSIONS: Final = frozenset({"0.4.0", "0.3.0-full-demo"})
SUPPORTED_PIPELINE_VERSIONS: Final = frozenset(
    {PRODUCTION_PIPELINE_VERSION, *LEGACY_PIPELINE_VERSIONS}
)

GENE_ID_KEYS: Final = ("gene_id",)
GENE_NAME_KEYS: Final = ("gene_name",)
GENE_BIOTYPE_KEYS: Final = ("gene_type", "gene_biotype")
TRANSCRIPT_BIOTYPE_KEYS: Final = ("transcript_type", "transcript_biotype")

FastaIdPolicy = Literal["exact", "version_stripped"]
ReferenceCommandRunner = Callable[
    [Sequence[str], Mapping[str, str] | None],
    subprocess.CompletedProcess[str],
]
CancellationCheck = Callable[[], bool]


class BulkReferenceError(Exception):
    """Predictable reference preparation or validation failure."""


class GtfTranscriptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    transcript_id: str
    gene_id: str
    gene_name: str = ""
    gene_biotype: str = ""
    transcript_biotype: str = ""


class OverlapAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: FastaIdPolicy
    fasta_transcript_count: int
    matched_transcript_count: int
    overlap_fraction: float
    exact_overlap_fraction: float
    version_stripped_overlap_fraction: float | None = None


class PreparedBulkReferences(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_mode: BulkReferenceMode
    analysis_only: bool
    kallisto_index: str | None = None
    transcript_to_gene: str
    index_identity: str | None = None
    annotation_identity: str | None = None
    fasta_id_policy: FastaIdPolicy | None = None
    overlap: OverlapAssessment | None = None
    transcriptome_fasta: str | None = None
    annotation_gtf: str | None = None
    cache_root: str


@dataclass(frozen=True, slots=True)
class KallistoRuntime:
    executable: Path
    version: str


def infer_bulk_reference_mode(
    reference_resources: Mapping[str, str],
    *,
    explicit_mode: BulkReferenceMode | None,
) -> BulkReferenceMode | None:
    if explicit_mode is not None:
        return explicit_mode
    if reference_resources.get("kallisto_index"):
        return BulkReferenceMode.EXISTING_INDEX
    if reference_resources.get("transcriptome_fasta") and reference_resources.get("annotation_gtf"):
        return BulkReferenceMode.BUILD
    return None


def legacy_biomart_migration_message(manifest: ProjectManifest) -> str | None:
    if manifest.pipeline_version not in LEGACY_PIPELINE_VERSIONS:
        return None
    resources = manifest.reference_resources
    has_biomart = bool(resources.get("biomart"))
    has_modern_annotation = bool(
        resources.get("annotation_gtf") or resources.get("transcript_to_gene")
    )
    if has_biomart and not has_modern_annotation:
        return (
            "This project uses the legacy BioMart-only reference contract for bulk RNA-seq "
            f"{manifest.pipeline_version}. Re-save it as pipeline version 0.5.0 with "
            "reference_mode and annotation_gtf or transcript_to_gene before running."
        )
    return None


def bulk_analysis_only(manifest: ProjectManifest) -> bool:
    if manifest.pipeline_identifier != "bulk-rnaseq":
        return False
    return manifest.parameters.get("start_stage") == "analysis"


def sha256_file(
    path: Path,
    *,
    chunk_size: int = 1024 * 1024,
    cancellation_check: CancellationCheck | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if cancellation_check and cancellation_check():
                raise BulkReferenceError("Reference preparation was cancelled.")
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def compute_index_identity(*, fasta_sha256: str, kallisto_version: str) -> str:
    payload = f"index-v1\n{fasta_sha256}\n{kallisto_version}\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_annotation_identity(
    *,
    fasta_sha256: str | None,
    gtf_sha256: str | None,
    supplied_mapping_sha256: str | None,
    normalization_version: str = NORMALIZATION_VERSION,
) -> str:
    payload = (
        f"annotation-v1\n{normalization_version}\n"
        f"{fasta_sha256 or ''}\n{gtf_sha256 or ''}\n{supplied_mapping_sha256 or ''}\n"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_gtf_attributes(raw: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for piece in raw.strip().split(";"):
        piece = piece.strip()
        if not piece:
            continue
        if " " not in piece:
            continue
        key, _, remainder = piece.partition(" ")
        value = remainder.strip().strip('"')
        if key:
            attributes[key] = value
    return attributes


def _first_attribute(attributes: Mapping[str, str], keys: Sequence[str]) -> str:
    for key in keys:
        value = attributes.get(key, "").strip()
        if value:
            return value
    return ""


def parse_gtf_transcript_records(
    gtf_path: Path,
    *,
    cancellation_check: CancellationCheck | None = None,
) -> dict[str, GtfTranscriptRecord]:
    by_transcript: dict[str, GtfTranscriptRecord] = {}
    feature_rows: dict[str, GtfTranscriptRecord] = {}
    gff3_attributes_seen = False
    with _open_reference_text(gtf_path) as handle:
        for line in handle:
            if cancellation_check and cancellation_check():
                raise BulkReferenceError("Reference preparation was cancelled.")
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 9:
                continue
            feature = fields[2]
            if "=" in fields[8] and '"' not in fields[8]:
                gff3_attributes_seen = True
            attributes = parse_gtf_attributes(fields[8])
            transcript_id = _first_attribute(attributes, ("transcript_id",))
            gene_id = _first_attribute(attributes, GENE_ID_KEYS)
            if not transcript_id or not gene_id:
                continue
            record = GtfTranscriptRecord(
                transcript_id=transcript_id,
                gene_id=gene_id,
                gene_name=_first_attribute(attributes, GENE_NAME_KEYS),
                gene_biotype=_first_attribute(attributes, GENE_BIOTYPE_KEYS),
                transcript_biotype=_first_attribute(attributes, TRANSCRIPT_BIOTYPE_KEYS),
            )
            existing = by_transcript.get(transcript_id)
            if existing is None or feature == "transcript":
                by_transcript[transcript_id] = record
            if feature == "transcript":
                feature_rows[transcript_id] = record
    for transcript_id, record in feature_rows.items():
        by_transcript[transcript_id] = record
    if not by_transcript and gff3_attributes_seen:
        raise BulkReferenceError(
            "The selected annotation uses GFF3-style attributes. "
            "Bulk RNA-seq reference preparation requires a matching GTF file."
        )
    return by_transcript


def parse_fasta_header_transcript_id(header: str) -> str:
    token = header.strip()
    if token.startswith(">"):
        token = token[1:]
    token = token.split()[0] if token else ""
    if "|" in token:
        return token.split("|", 1)[0]
    return token


def iter_fasta_transcript_ids(
    fasta_path: Path,
    *,
    cancellation_check: CancellationCheck | None = None,
) -> list[str]:
    ids: list[str] = []
    with _open_reference_text(fasta_path) as handle:
        for line in handle:
            if cancellation_check and cancellation_check():
                raise BulkReferenceError("Reference preparation was cancelled.")
            if line.startswith(">"):
                transcript_id = parse_fasta_header_transcript_id(line)
                if transcript_id:
                    ids.append(transcript_id)
    return ids


def _open_reference_text(path: Path) -> TextIO:
    if path.suffix.casefold() == ".gz":
        return gzip.open(path, mode="rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def strip_transcript_version(transcript_id: str) -> str:
    if "." in transcript_id:
        base, suffix = transcript_id.rsplit(".", 1)
        if suffix.isdigit():
            return base
    return transcript_id


def _overlap_fraction(fasta_ids: Sequence[str], annotation_ids: set[str]) -> float:
    if not fasta_ids:
        return 0.0
    matched = sum(1 for transcript_id in fasta_ids if transcript_id in annotation_ids)
    return matched / len(fasta_ids)


def assess_fasta_gtf_overlap(
    *,
    fasta_ids: Sequence[str],
    gtf_records: Mapping[str, GtfTranscriptRecord],
) -> OverlapAssessment:
    exact_annotation_ids = set(gtf_records.keys())
    exact_fraction = _overlap_fraction(fasta_ids, exact_annotation_ids)

    stripped_annotation: dict[str, GtfTranscriptRecord] = {}
    stripped_collisions: set[str] = set()
    for transcript_id, record in gtf_records.items():
        stripped_id = strip_transcript_version(transcript_id)
        existing = stripped_annotation.get(stripped_id)
        if existing is not None and existing.transcript_id != transcript_id:
            stripped_collisions.add(stripped_id)
        else:
            stripped_annotation[stripped_id] = record

    stripped_matches = 0
    for transcript_id in fasta_ids:
        if (
            transcript_id in exact_annotation_ids
            or strip_transcript_version(transcript_id) in stripped_annotation
        ):
            stripped_matches += 1
    stripped_fraction = stripped_matches / len(fasta_ids) if fasta_ids else 0.0

    if exact_fraction >= MIN_ACCEPTABLE_OVERLAP:
        policy: FastaIdPolicy = "exact"
        matched = sum(1 for transcript_id in fasta_ids if transcript_id in exact_annotation_ids)
    elif (
        stripped_fraction >= MIN_ACCEPTABLE_OVERLAP
        and stripped_fraction - exact_fraction >= VERSION_STRIP_MIN_IMPROVEMENT
        and not stripped_collisions
    ):
        policy = "version_stripped"
        matched = stripped_matches
    else:
        policy = "exact"
        matched = sum(1 for transcript_id in fasta_ids if transcript_id in exact_annotation_ids)

    overlap_fraction = matched / len(fasta_ids) if fasta_ids else 0.0
    return OverlapAssessment(
        policy=policy,
        fasta_transcript_count=len(fasta_ids),
        matched_transcript_count=matched,
        overlap_fraction=overlap_fraction,
        exact_overlap_fraction=exact_fraction,
        version_stripped_overlap_fraction=stripped_fraction,
    )


def map_fasta_to_gtf_records(
    *,
    fasta_ids: Sequence[str],
    gtf_records: Mapping[str, GtfTranscriptRecord],
    policy: FastaIdPolicy,
) -> list[GtfTranscriptRecord]:
    stripped_index: dict[str, GtfTranscriptRecord] = {}
    for transcript_id, record in gtf_records.items():
        stripped_index.setdefault(strip_transcript_version(transcript_id), record)

    mapped: list[GtfTranscriptRecord] = []
    for fasta_id in fasta_ids:
        source = gtf_records.get(fasta_id)
        if source is None and policy == "version_stripped":
            source = stripped_index.get(strip_transcript_version(fasta_id))
        if source is None:
            continue
        mapped.append(
            GtfTranscriptRecord(
                transcript_id=fasta_id,
                gene_id=source.gene_id,
                gene_name=source.gene_name,
                gene_biotype=source.gene_biotype,
                transcript_biotype=source.transcript_biotype,
            )
        )
    return mapped


def write_transcript_to_gene_table(path: Path, records: Sequence[GtfTranscriptRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(TRANSCRIPT_TO_GENE_COLUMNS) + "\n")
        for record in records:
            row = (
                record.transcript_id,
                record.gene_id,
                record.gene_name,
                record.gene_biotype,
                record.transcript_biotype,
            )
            handle.write("\t".join(row) + "\n")
    temp_path.replace(path)


def read_supplied_transcript_to_gene(path: Path) -> set[str]:
    with _open_reference_text(path) as handle:
        header = handle.readline().strip().split("\t")
        missing = [column for column in ("transcript_id", "gene_id") if column not in header]
        if missing:
            raise BulkReferenceError(
                "Supplied transcript_to_gene table is missing required columns: "
                + ", ".join(missing)
            )
        transcript_index = header.index("transcript_id")
        gene_index = header.index("gene_id")
        transcript_ids: set[str] = set()
        for line_number, line in enumerate(handle, start=2):
            fields = line.rstrip("\n").split("\t")
            if len(fields) <= max(transcript_index, gene_index):
                raise BulkReferenceError(
                    f"Supplied transcript_to_gene table has a malformed row at line {line_number}"
                )
            transcript_id = fields[transcript_index].strip()
            gene_id = fields[gene_index].strip()
            if not transcript_id or not gene_id:
                raise BulkReferenceError(
                    "Supplied transcript_to_gene table has an empty identifier "
                    f"at line {line_number}"
                )
            transcript_ids.add(transcript_id)
    if not transcript_ids:
        raise BulkReferenceError("Supplied transcript_to_gene table contains no mapping rows")
    return transcript_ids


def validate_mapping_fasta_overlap(
    mapping_path: Path,
    fasta_path: Path,
    *,
    cancellation_check: CancellationCheck | None = None,
) -> float:
    mapping_ids = read_supplied_transcript_to_gene(mapping_path)
    fasta_ids = iter_fasta_transcript_ids(
        fasta_path,
        cancellation_check=cancellation_check,
    )
    if not fasta_ids:
        raise BulkReferenceError("Transcriptome FASTA does not contain any transcript headers.")
    overlap = _overlap_fraction(fasta_ids, mapping_ids)
    if overlap < MIN_ACCEPTABLE_OVERLAP:
        raise BulkReferenceError(
            "Transcriptome FASTA and transcript_to_gene mapping appear incompatible: "
            f"only {overlap:.1%} of FASTA transcript identifiers matched exactly. "
            "Supply a mapping whose transcript_id values match the indexed FASTA."
        )
    return overlap


def validate_mapping_abundance_overlap(
    mapping_path: Path,
    abundance_paths: Sequence[tuple[str, Path]],
) -> None:
    mapping_ids = read_supplied_transcript_to_gene(mapping_path)
    for sample_id, abundance_path in abundance_paths:
        abundance_path = _require_file(abundance_path, f"abundance_tsv for sample {sample_id}")
        with abundance_path.open(encoding="utf-8") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            if "target_id" not in header:
                raise BulkReferenceError(
                    f"Sample {sample_id} abundance.tsv does not contain a target_id column."
                )
            target_index = header.index("target_id")
            target_ids = {
                fields[target_index].split("|", 1)[0]
                for line in handle
                if len(fields := line.rstrip("\n").split("\t")) > target_index
                and fields[target_index]
            }
        if not target_ids:
            raise BulkReferenceError(
                f"Sample {sample_id} abundance.tsv does not contain transcript rows."
            )
        overlap = _overlap_fraction(sorted(target_ids), mapping_ids)
        if overlap < MIN_ACCEPTABLE_OVERLAP:
            raise BulkReferenceError(
                f"Sample {sample_id} abundance.tsv and transcript-to-gene annotation "
                f"appear incompatible: only {overlap:.1%} of target identifiers matched. "
                "Supply annotation from the transcriptome used for quantification."
            )


def _write_complete_marker(
    directory: Path,
    *,
    identity: str,
    artifact: str,
    metadata: Mapping[str, object],
) -> None:
    payload = {
        "identity": identity,
        "artifact": artifact,
        "metadata": dict(metadata),
    }
    temp_path = directory / f".{_COMPLETE_MARKER}.tmp"
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(directory / _COMPLETE_MARKER)
    failed = directory / _FAILED_MARKER
    if failed.exists():
        failed.unlink()


def _read_complete_marker(directory: Path) -> dict[str, object] | None:
    marker = directory / _COMPLETE_MARKER
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _mark_failed(directory: Path, message: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"message": message}
    failed_path = directory / _FAILED_MARKER
    failed_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for name in (_INDEX_FILENAME, _MAPPING_FILENAME, _BUILD_LOG, _COMPLETE_MARKER):
        candidate = directory / name
        if candidate.exists():
            candidate.unlink()


def _cache_is_usable(directory: Path, *, artifact_name: str, identity: str) -> bool:
    if (directory / _FAILED_MARKER).is_file():
        return False
    marker = _read_complete_marker(directory)
    if marker is None or marker.get("identity") != identity:
        return False
    artifact = directory / artifact_name
    return artifact.is_file() and artifact.stat().st_size > 0


def _cached_overlap(directory: Path) -> OverlapAssessment | None:
    marker = _read_complete_marker(directory)
    metadata = marker.get("metadata") if marker else None
    payload = metadata.get("overlap") if isinstance(metadata, dict) else None
    if not isinstance(payload, dict):
        return None
    try:
        return OverlapAssessment.model_validate(payload)
    except ValueError:
        return None


@contextmanager
def _cache_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".prepare.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class BulkReferenceManager:
    """Prepare or reuse cached Kallisto indexes and normalized transcript-to-gene tables."""

    def __init__(
        self,
        *,
        cache_root: Path,
        kallisto: KallistoRuntime | None = None,
        log_writer: Callable[[str], None] | None = None,
        command_runner: ReferenceCommandRunner | None = None,
        environment: Mapping[str, str] | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> None:
        self._cache_root = cache_root.resolve()
        self._kallisto = kallisto
        self._log = log_writer or (lambda _message: None)
        self._command_runner = command_runner or self._run_command
        self._environment = environment
        self._cancellation_check = cancellation_check

    def _sha256_file(self, path: Path) -> str:
        return sha256_file(path, cancellation_check=self._cancellation_check)

    @staticmethod
    def _run_command(
        command: Sequence[str],
        environment: Mapping[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command),
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            env=dict(environment) if environment is not None else None,
        )

    def prepare(
        self,
        manifest: ProjectManifest,
        *,
        analysis_only: bool | None = None,
    ) -> PreparedBulkReferences:
        if manifest.pipeline_identifier != "bulk-rnaseq":
            raise BulkReferenceError("Bulk reference preparation requires a bulk-rnaseq manifest")

        if analysis_only is None:
            analysis_only = bulk_analysis_only(manifest)
        resources = manifest.reference_resources
        mode = infer_bulk_reference_mode(resources, explicit_mode=manifest.reference_mode)
        if mode is None:
            raise BulkReferenceError(
                "Could not determine bulk reference mode; set reference_mode explicitly"
            )

        supplied_mapping = resources.get("transcript_to_gene")
        supplied_gtf = resources.get("annotation_gtf")
        fasta_path = (
            Path(resources["transcriptome_fasta"]) if resources.get("transcriptome_fasta") else None
        )

        if analysis_only:
            prepared = self._prepare_analysis_only(
                mode=mode,
                supplied_mapping=Path(supplied_mapping) if supplied_mapping else None,
                supplied_gtf=Path(supplied_gtf) if supplied_gtf else None,
                fasta_path=fasta_path,
            )
            validate_mapping_abundance_overlap(
                Path(prepared.transcript_to_gene),
                [
                    (sample.sample_id, Path(sample.abundance_tsv))
                    for sample in manifest.samples
                    if sample.included and sample.abundance_tsv
                ],
            )
            return prepared

        if mode == BulkReferenceMode.BUILD:
            return self._prepare_build_mode(
                fasta_path=_require_file(fasta_path, "transcriptome_fasta"),
                gtf_path=_require_file(
                    Path(supplied_gtf) if supplied_gtf else None,
                    "annotation_gtf",
                ),
            )

        return self._prepare_existing_index_mode(
            index_path=_require_file(
                Path(resources["kallisto_index"]) if resources.get("kallisto_index") else None,
                "kallisto_index",
            ),
            supplied_mapping=Path(supplied_mapping) if supplied_mapping else None,
            supplied_gtf=Path(supplied_gtf) if supplied_gtf else None,
            fasta_path=fasta_path,
        )

    def _prepare_analysis_only(
        self,
        *,
        mode: BulkReferenceMode,
        supplied_mapping: Path | None,
        supplied_gtf: Path | None,
        fasta_path: Path | None,
    ) -> PreparedBulkReferences:
        if supplied_mapping is not None:
            supplied_mapping = _require_file(supplied_mapping, "transcript_to_gene")
            read_supplied_transcript_to_gene(supplied_mapping)
            if fasta_path and fasta_path.is_file():
                validate_mapping_fasta_overlap(
                    supplied_mapping,
                    fasta_path,
                    cancellation_check=self._cancellation_check,
                )
            mapping_sha = self._sha256_file(supplied_mapping)
            identity = compute_annotation_identity(
                fasta_sha256=self._sha256_file(fasta_path)
                if fasta_path and fasta_path.is_file()
                else None,
                gtf_sha256=None,
                supplied_mapping_sha256=mapping_sha,
            )
            return PreparedBulkReferences(
                reference_mode=mode,
                analysis_only=True,
                transcript_to_gene=str(supplied_mapping.resolve()),
                annotation_identity=identity,
                cache_root=str(self._cache_root),
            )

        gtf_path = _require_file(supplied_gtf, "annotation_gtf or transcript_to_gene")
        gtf_sha = self._sha256_file(gtf_path)
        fasta_sha = self._sha256_file(fasta_path) if fasta_path and fasta_path.is_file() else None
        identity = compute_annotation_identity(
            fasta_sha256=fasta_sha,
            gtf_sha256=gtf_sha,
            supplied_mapping_sha256=None,
        )
        cache_dir = self._cache_root / "transcript_to_gene" / identity
        artifact = cache_dir / _MAPPING_FILENAME
        with _cache_lock(cache_dir):
            if _cache_is_usable(
                cache_dir,
                artifact_name=_MAPPING_FILENAME,
                identity=identity,
            ):
                overlap = _cached_overlap(cache_dir)
                return PreparedBulkReferences(
                    reference_mode=mode,
                    analysis_only=True,
                    transcript_to_gene=str(artifact.resolve()),
                    annotation_identity=identity,
                    annotation_gtf=str(gtf_path.resolve()),
                    transcriptome_fasta=str(fasta_path.resolve()) if fasta_path else None,
                    fasta_id_policy=overlap.policy if overlap else None,
                    overlap=overlap,
                    cache_root=str(self._cache_root),
                )

            if fasta_path and fasta_path.is_file():
                overlap, records = self._normalize_with_fasta(fasta_path, gtf_path)
            else:
                records = list(
                    parse_gtf_transcript_records(
                        gtf_path,
                        cancellation_check=self._cancellation_check,
                    ).values()
                )
                if not records:
                    raise BulkReferenceError(
                        "The selected GTF does not contain transcript_id and gene_id attributes."
                    )
                overlap = None

            write_transcript_to_gene_table(artifact, records)
            _write_complete_marker(
                cache_dir,
                identity=identity,
                artifact=_MAPPING_FILENAME,
                metadata={
                    "normalization_version": NORMALIZATION_VERSION,
                    "gtf_sha256": gtf_sha,
                    "fasta_sha256": fasta_sha,
                    "fasta_id_policy": overlap.policy if overlap else None,
                    "overlap": overlap.model_dump(mode="json") if overlap else None,
                },
            )
        return PreparedBulkReferences(
            reference_mode=mode,
            analysis_only=True,
            transcript_to_gene=str(artifact.resolve()),
            annotation_identity=identity,
            annotation_gtf=str(gtf_path.resolve()),
            transcriptome_fasta=str(fasta_path.resolve()) if fasta_path else None,
            fasta_id_policy=overlap.policy if overlap else None,
            overlap=overlap,
            cache_root=str(self._cache_root),
        )

    def _prepare_build_mode(self, *, fasta_path: Path, gtf_path: Path) -> PreparedBulkReferences:
        fasta_sha = self._sha256_file(fasta_path)
        gtf_sha = self._sha256_file(gtf_path)
        overlap, records = self._normalize_with_fasta(fasta_path, gtf_path)

        annotation_identity = compute_annotation_identity(
            fasta_sha256=fasta_sha,
            gtf_sha256=gtf_sha,
            supplied_mapping_sha256=None,
        )
        mapping_dir = self._cache_root / "transcript_to_gene" / annotation_identity
        mapping_path = mapping_dir / _MAPPING_FILENAME
        with _cache_lock(mapping_dir):
            if not _cache_is_usable(
                mapping_dir,
                artifact_name=_MAPPING_FILENAME,
                identity=annotation_identity,
            ):
                write_transcript_to_gene_table(mapping_path, records)
                _write_complete_marker(
                    mapping_dir,
                    identity=annotation_identity,
                    artifact=_MAPPING_FILENAME,
                    metadata={
                        "normalization_version": NORMALIZATION_VERSION,
                        "gtf_sha256": gtf_sha,
                        "fasta_sha256": fasta_sha,
                        "fasta_id_policy": overlap.policy,
                        "overlap": overlap.model_dump(mode="json"),
                    },
                )

        index_path: Path | None = None
        index_identity: str | None = None
        if self._kallisto is not None:
            index_identity = compute_index_identity(
                fasta_sha256=fasta_sha,
                kallisto_version=self._kallisto.version,
            )
            index_dir = self._cache_root / "kallisto_index" / index_identity
            index_path = index_dir / _INDEX_FILENAME
            with _cache_lock(index_dir):
                if not _cache_is_usable(
                    index_dir,
                    artifact_name=_INDEX_FILENAME,
                    identity=index_identity,
                ):
                    self._build_kallisto_index(
                        index_dir,
                        fasta_path=fasta_path,
                        fasta_sha256=fasta_sha,
                        identity=index_identity,
                    )

        return PreparedBulkReferences(
            reference_mode=BulkReferenceMode.BUILD,
            analysis_only=False,
            kallisto_index=str(index_path.resolve()) if index_path else None,
            transcript_to_gene=str(mapping_path.resolve()),
            index_identity=index_identity,
            annotation_identity=annotation_identity,
            fasta_id_policy=overlap.policy,
            overlap=overlap,
            transcriptome_fasta=str(fasta_path.resolve()),
            annotation_gtf=str(gtf_path.resolve()),
            cache_root=str(self._cache_root),
        )

    def _prepare_existing_index_mode(
        self,
        *,
        index_path: Path,
        supplied_mapping: Path | None,
        supplied_gtf: Path | None,
        fasta_path: Path | None,
    ) -> PreparedBulkReferences:
        if supplied_mapping is not None:
            supplied_mapping = _require_file(supplied_mapping, "transcript_to_gene")
            read_supplied_transcript_to_gene(supplied_mapping)
            if fasta_path and fasta_path.is_file():
                validate_mapping_fasta_overlap(
                    supplied_mapping,
                    fasta_path,
                    cancellation_check=self._cancellation_check,
                )
            mapping_sha = self._sha256_file(supplied_mapping)
            identity = compute_annotation_identity(
                fasta_sha256=self._sha256_file(fasta_path)
                if fasta_path and fasta_path.is_file()
                else None,
                gtf_sha256=self._sha256_file(supplied_gtf)
                if supplied_gtf and supplied_gtf.is_file()
                else None,
                supplied_mapping_sha256=mapping_sha,
            )
            return PreparedBulkReferences(
                reference_mode=BulkReferenceMode.EXISTING_INDEX,
                analysis_only=False,
                kallisto_index=str(index_path.resolve()),
                transcript_to_gene=str(supplied_mapping.resolve()),
                annotation_identity=identity,
                transcriptome_fasta=str(fasta_path.resolve()) if fasta_path else None,
                annotation_gtf=str(supplied_gtf.resolve()) if supplied_gtf else None,
                cache_root=str(self._cache_root),
            )

        gtf_path = _require_file(supplied_gtf, "annotation_gtf or transcript_to_gene")
        gtf_sha = self._sha256_file(gtf_path)
        fasta_sha = self._sha256_file(fasta_path) if fasta_path and fasta_path.is_file() else None
        annotation_identity = compute_annotation_identity(
            fasta_sha256=fasta_sha,
            gtf_sha256=gtf_sha,
            supplied_mapping_sha256=None,
        )
        mapping_dir = self._cache_root / "transcript_to_gene" / annotation_identity
        mapping_path = mapping_dir / _MAPPING_FILENAME
        overlap: OverlapAssessment | None = None
        with _cache_lock(mapping_dir):
            if not _cache_is_usable(
                mapping_dir,
                artifact_name=_MAPPING_FILENAME,
                identity=annotation_identity,
            ):
                if fasta_path and fasta_path.is_file():
                    overlap, records = self._normalize_with_fasta(fasta_path, gtf_path)
                else:
                    records = list(
                        parse_gtf_transcript_records(
                            gtf_path,
                            cancellation_check=self._cancellation_check,
                        ).values()
                    )
                    if not records:
                        raise BulkReferenceError(
                            "The selected GTF does not contain transcript_id "
                            "and gene_id attributes."
                        )
                write_transcript_to_gene_table(mapping_path, records)
                _write_complete_marker(
                    mapping_dir,
                    identity=annotation_identity,
                    artifact=_MAPPING_FILENAME,
                    metadata={
                        "normalization_version": NORMALIZATION_VERSION,
                        "gtf_sha256": gtf_sha,
                        "fasta_sha256": fasta_sha,
                        "fasta_id_policy": overlap.policy if overlap else None,
                        "overlap": overlap.model_dump(mode="json") if overlap else None,
                    },
                )
            else:
                overlap = _cached_overlap(mapping_dir)

        return PreparedBulkReferences(
            reference_mode=BulkReferenceMode.EXISTING_INDEX,
            analysis_only=False,
            kallisto_index=str(index_path.resolve()),
            transcript_to_gene=str(mapping_path.resolve()),
            annotation_identity=annotation_identity,
            annotation_gtf=str(gtf_path.resolve()),
            transcriptome_fasta=str(fasta_path.resolve()) if fasta_path else None,
            fasta_id_policy=overlap.policy if overlap else None,
            overlap=overlap,
            cache_root=str(self._cache_root),
        )

    def _normalize_with_fasta(
        self,
        fasta_path: Path,
        gtf_path: Path,
    ) -> tuple[OverlapAssessment, list[GtfTranscriptRecord]]:
        gtf_records = parse_gtf_transcript_records(
            gtf_path,
            cancellation_check=self._cancellation_check,
        )
        if not gtf_records:
            raise BulkReferenceError(
                "The selected GTF does not contain transcript_id and gene_id attributes."
            )
        fasta_ids = iter_fasta_transcript_ids(
            fasta_path,
            cancellation_check=self._cancellation_check,
        )
        if not fasta_ids:
            raise BulkReferenceError("Transcriptome FASTA does not contain any transcript headers.")
        overlap = assess_fasta_gtf_overlap(fasta_ids=fasta_ids, gtf_records=gtf_records)
        if overlap.overlap_fraction < MIN_ACCEPTABLE_OVERLAP:
            raise BulkReferenceError(
                "Transcriptome FASTA and annotation GTF appear incompatible: "
                f"only {overlap.overlap_fraction:.1%} of FASTA transcript identifiers were found "
                f"in the annotation using {overlap.policy} matching "
                f"(exact {overlap.exact_overlap_fraction:.1%}"
                + (
                    f", version-stripped {overlap.version_stripped_overlap_fraction:.1%}"
                    if overlap.version_stripped_overlap_fraction is not None
                    else ""
                )
                + ")."
            )
        records = map_fasta_to_gtf_records(
            fasta_ids=fasta_ids,
            gtf_records=gtf_records,
            policy=overlap.policy,
        )
        if not records:
            raise BulkReferenceError(
                "Transcriptome FASTA and annotation GTF appear incompatible: "
                "no transcript identifiers could be mapped to gene_id values."
            )
        return overlap, records

    def _build_kallisto_index(
        self,
        index_dir: Path,
        *,
        fasta_path: Path,
        fasta_sha256: str,
        identity: str,
    ) -> None:
        if self._kallisto is None:
            raise BulkReferenceError("Kallisto runtime is not configured for index construction.")

        index_dir.mkdir(parents=True, exist_ok=True)
        if (index_dir / _FAILED_MARKER).is_file() or not _cache_is_usable(
            index_dir,
            artifact_name=_INDEX_FILENAME,
            identity=identity,
        ):
            for name in (_INDEX_FILENAME, _BUILD_LOG, _COMPLETE_MARKER, _FAILED_MARKER):
                candidate = index_dir / name
                if candidate.exists():
                    candidate.unlink()

        destination = index_dir / _INDEX_FILENAME
        temp_destination = index_dir / f".{_INDEX_FILENAME}.tmp"
        log_path = index_dir / _BUILD_LOG
        command = [
            str(self._kallisto.executable),
            "index",
            "-i",
            str(temp_destination),
            str(fasta_path.resolve()),
        ]
        self._log(f"Running Kallisto index build: {' '.join(command)}")
        try:
            completed = self._command_runner(command, self._environment)
        except OSError as exc:
            _mark_failed(index_dir, str(exc))
            raise BulkReferenceError(
                "Kallisto index construction failed. See the reference-preparation log."
            ) from exc

        log_text = (completed.stdout or "") + (completed.stderr or "")
        log_path.write_text(log_text, encoding="utf-8")
        if completed.returncode != 0 or not temp_destination.is_file():
            _mark_failed(index_dir, f"kallisto exited with status {completed.returncode}")
            stop_details = [
                line.strip()
                for line in log_text.splitlines()
                if line.startswith("Reference preparation stopped:")
            ]
            if stop_details:
                raise BulkReferenceError(
                    f"{stop_details[-1]} See the reference-preparation log for command output."
                )
            raise BulkReferenceError(
                "Kallisto index construction failed. See the reference-preparation log."
            )

        temp_destination.replace(destination)
        _write_complete_marker(
            index_dir,
            identity=identity,
            artifact=_INDEX_FILENAME,
            metadata={
                "kallisto_version": self._kallisto.version,
                "fasta_path": str(fasta_path.resolve()),
                "fasta_sha256": fasta_sha256,
                "fasta_size": fasta_path.stat().st_size,
                "fasta_mtime_ns": fasta_path.stat().st_mtime_ns,
            },
        )


def _require_file(path: Path | None, label: str) -> Path:
    if path is None or not path.is_file():
        raise BulkReferenceError(f"Missing or unreadable reference file: {label}")
    return path.resolve()
