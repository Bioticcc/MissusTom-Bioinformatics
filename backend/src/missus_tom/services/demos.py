"""Local, deterministic synthetic demo bundle generation."""

from __future__ import annotations

import builtins
import fcntl
import gzip
import hashlib
import io
import json
import os
import selectors
import shutil
import stat
import subprocess
import threading
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import ValidationError

from missus_tom.config import settings
from missus_tom.models.command_log import CommandLogChunk
from missus_tom.models.demos import (
    DemoIntegrity,
    DemoPrepareJob,
    DemoPrepareStatus,
    DemoStatus,
)
from missus_tom.models.manifest import ProjectManifest
from missus_tom.services.dependencies import runtime_environment, runtime_tool

_CATALOG: Final = {
    "bulk-rnaseq": {
        "title": "Synthetic human bulk RNA-seq fixture",
        "note": (
            "Synthetic sequences and references generated locally for functional "
            "workflow validation; not for biological or clinical interpretation."
        ),
    },
    "ont-analysis": {
        "title": "Synthetic mouse ONT fixture",
        "note": (
            "Synthetic text placeholders only; the .bam is intentionally not a "
            "valid modBAM and cannot run the ONT workflow."
        ),
    },
}
_BUNDLE_MANIFEST = "BUNDLE_MANIFEST.json"
_FIXTURE_VERSION: Final = "2"
_LCG_MODULUS: Final = 2_147_483_647
_LCG_MULTIPLIER: Final = 1_664_525
_LCG_INCREMENT: Final = 1_013_904_223
_TRANSCRIPT_COUNT: Final = 24
_TRANSCRIPT_LENGTH: Final = 220
_READ_LENGTH: Final = 50
_ACTIVE: Final = {DemoPrepareStatus.RUNNING}

_BULK_SAMPLES: Final = (
    ("SYN_CONTROL_01", "control", "1", "H1"),
    ("SYN_CONTROL_02", "control", "2", "H2"),
    ("SYN_TREATMENT_01", "treatment", "1", "OD1"),
    ("SYN_TREATMENT_02", "treatment", "2", "OD2"),
)

_READ_COUNT_OFFSETS: Final = {
    ("H1", 0): -8,
    ("H1", 1): 12,
    ("H1", 2): -15,
    ("H1", 3): 20,
    ("H1", 4): -5,
    ("H1", 5): 7,
    ("H2", 0): 13,
    ("H2", 1): -17,
    ("H2", 2): 7,
    ("H2", 3): -12,
    ("H2", 4): 18,
    ("H2", 5): -6,
    ("OD1", 0): -12,
    ("OD1", 1): 20,
    ("OD1", 2): -5,
    ("OD1", 3): 8,
    ("OD1", 4): -18,
    ("OD1", 5): 15,
    ("OD2", 0): 18,
    ("OD2", 1): -8,
    ("OD2", 2): 12,
    ("OD2", 3): -20,
    ("OD2", 4): 5,
    ("OD2", 5): -14,
}


def lcg_sequence(seed: int, *, length: int = _TRANSCRIPT_LENGTH) -> str:
    """Deterministic pseudo-random DNA sequence matching the workflow smoke script."""
    value = seed
    bases = ("A", "C", "G", "T")
    output: list[str] = []
    for _ in range(length):
        value = (value * _LCG_MULTIPLIER + _LCG_INCREMENT) % _LCG_MODULUS
        output.append(bases[value % 4])
    return "".join(output)


def reverse_complement(sequence: str) -> str:
    table = str.maketrans("ACGTacgt", "TGCAtgca")
    return sequence.translate(table)[::-1]


def synthetic_read_count(smoke_tag: str, transcript_index: int) -> int:
    low = 35 + (transcript_index % 6) * 6
    high = 105 + (transcript_index % 5) * 13
    if smoke_tag.startswith("H"):
        count = low if transcript_index % 4 < 2 else high
    else:
        count = high if transcript_index % 4 < 2 else low
    return count + _READ_COUNT_OFFSETS[(smoke_tag, transcript_index % 6)]


class DemoService:
    """Owns only ``settings.state_directory / demos``; it never downloads data."""

    def __init__(self, *, state_directory: Path | None = None) -> None:
        self.state_directory = state_directory or settings.state_directory
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._run_lock_descriptors: dict[str, int] = {}
        self._jobs: dict[str, DemoPrepareJob] = {}
        self._recover_jobs()

    @property
    def root(self) -> Path:
        return self.state_directory / "demos"

    @property
    def jobs_root(self) -> Path:
        return self.root / "jobs"

    def list(self) -> builtins.list[DemoStatus]:
        return [self.status(identifier) for identifier in _CATALOG]

    def status(self, pipeline_identifier: str) -> DemoStatus:
        spec = self._spec(pipeline_identifier)
        bundle = self.root / pipeline_identifier
        metadata = self._read_verified_metadata(bundle, pipeline_identifier)
        execution_supported = self._execution_supported(bundle)
        job = self.latest_job(pipeline_identifier)
        if metadata is None:
            return DemoStatus(
                pipeline_identifier=pipeline_identifier,
                title=spec["title"],
                available=False,
                bundle_directory=str(bundle),
                message=(
                    "Synthetic demo bundle has not been prepared or failed "
                    "self-consistency verification."
                ),
                execution_note=spec["note"],
                job=job,
                execution_supported=execution_supported,
            )
        integrity = metadata["integrity"]
        return DemoStatus(
            pipeline_identifier=pipeline_identifier,
            title=spec["title"],
            available=True,
            bundle_directory=str(bundle),
            manifest_path=str(bundle / metadata["project_manifest"]),
            integrity=DemoIntegrity(
                manifest_path=metadata["project_manifest"],
                sha256=integrity["sha256"],
                file_count=integrity["file_count"],
            ),
            prepared_at=datetime.fromisoformat(metadata["prepared_at"]),
            message="Synthetic demo bundle is available locally and passed integrity verification.",
            execution_note=spec["note"],
            job=job,
            execution_supported=execution_supported,
        )

    def prepare(self, pipeline_identifier: str) -> DemoPrepareJob:
        self._spec(pipeline_identifier)
        with self._lock:
            active = self.latest_job(pipeline_identifier)
            if active and active.status in _ACTIVE:
                raise ValueError("demo preparation is already running for this pipeline")
            if any(job.status in _ACTIVE for job in self._jobs.values()):
                raise ValueError("another demo preparation is already running")
            job = DemoPrepareJob(
                job_identifier=str(uuid4()),
                pipeline_identifier=pipeline_identifier,
                status=DemoPrepareStatus.RUNNING,
                message="Preparing synthetic demo bundle",
                current_stage="preparing",
                started_at=datetime.now(UTC),
            )
            lock_descriptor = self._acquire_run_lock(job.job_identifier)
            self._jobs[job.job_identifier] = job
            try:
                self._run_lock_descriptors[job.job_identifier] = lock_descriptor
                self._persist(job)
                thread = threading.Thread(
                    target=self._prepare_worker,
                    args=(job.job_identifier,),
                    daemon=True,
                )
                self._threads[job.job_identifier] = thread
                thread.start()
            except Exception:
                self._jobs.pop(job.job_identifier, None)
                self._threads.pop(job.job_identifier, None)
                self._release_run_lock(job.job_identifier)
                raise
            return job.model_copy(deep=True)

    def prepare_job(self, job_identifier: str) -> DemoPrepareJob:
        with self._lock:
            try:
                return self._jobs[job_identifier].model_copy(deep=True)
            except KeyError as exc:
                raise ValueError(f"unknown demo prepare job: {job_identifier}") from exc

    def latest_job(self, pipeline_identifier: str) -> DemoPrepareJob | None:
        self._spec(pipeline_identifier)
        with self._lock:
            jobs = [
                item
                for item in self._jobs.values()
                if item.pipeline_identifier == pipeline_identifier
            ]
            if not jobs:
                return None
            return max(jobs, key=lambda item: item.created_at).model_copy(deep=True)

    def read_log(
        self, job_identifier: str, *, offset: int = 0, limit: int = 100_000
    ) -> CommandLogChunk:
        self.prepare_job(job_identifier)
        if offset < 0:
            raise ValueError("log offset must be non-negative")
        path = self._log_path(job_identifier)
        if not path.is_file():
            job = self.prepare_job(job_identifier)
            return CommandLogChunk(
                text="",
                next_offset=0,
                bytes_available=0,
                last_output_at=job.last_output_at,
            )
        size = path.stat().st_size
        start = min(offset, size)
        with path.open("rb") as handle:
            handle.seek(start)
            data = handle.read(limit)
        truncated = start + len(data) < size
        job = self.prepare_job(job_identifier)
        return CommandLogChunk(
            text=data.decode("utf-8", errors="replace"),
            next_offset=start + len(data),
            bytes_available=size,
            truncated=truncated,
            last_output_at=job.last_output_at,
        )

    def load_project(self, pipeline_identifier: str) -> ProjectManifest:
        if pipeline_identifier != "bulk-rnaseq":
            raise ValueError("only bulk-rnaseq supports loading a synthetic executable demo")
        status = self.status(pipeline_identifier)
        if not status.available:
            raise ValueError("synthetic bulk demo bundle is not available")
        if not status.execution_supported:
            raise ValueError("synthetic bulk demo is not configured for execution")
        manifest_path = status.manifest_path
        if manifest_path is None:
            raise ValueError("synthetic bulk demo manifest path is missing")
        try:
            payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            return ProjectManifest.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ValueError("synthetic bulk demo manifest is invalid") from exc

    def _prepare_worker(self, job_identifier: str) -> None:
        with self._lock:
            job = self._jobs[job_identifier]
        try:
            self._log(job, "Starting demo preparation.")
            if job.pipeline_identifier == "bulk-rnaseq":
                self._prepare_bulk(job)
            else:
                self._prepare_ont(job)
            job.status = DemoPrepareStatus.SUCCEEDED
            job.current_stage = "finalizing"
            job.message = "Synthetic demo bundle is ready"
            job.finished_at = datetime.now(UTC)
            self._log(job, "Demo preparation completed.")
        except Exception as exc:
            job.status = DemoPrepareStatus.FAILED
            job.message = str(exc)
            job.finished_at = datetime.now(UTC)
            self._log(job, f"Demo preparation failed: {exc}")
        finally:
            try:
                self._persist(job)
            finally:
                self._release_run_lock(job.job_identifier)

    def _prepare_bulk(self, job: DemoPrepareJob) -> None:
        bundle = self.root / job.pipeline_identifier
        self._safe_mkdir(self.root)
        self._set_stage(job, "preparing")
        self._clear_bundle(bundle)
        self._safe_mkdir(bundle)

        inputs = "inputs"
        references = "references"
        self._safe_mkdir(bundle / inputs)
        self._safe_mkdir(bundle / references)
        self._safe_mkdir(bundle / "project-output")

        self._set_stage(job, "writing_references")
        sequences = self._write_bulk_references(bundle / references, job)

        self._set_stage(job, "writing_reads")
        for sample_id, _condition, _replicate, smoke_tag in _BULK_SAMPLES:
            self._write_bulk_sample_fastqs(
                bundle / inputs,
                sample_id=sample_id,
                smoke_tag=smoke_tag,
                sequences=sequences,
                job=job,
            )

        manifest_payload = self._bulk_manifest(bundle, inputs, references)
        self._write_text(bundle / "project_manifest.json", self._json(manifest_payload))

        self._set_stage(job, "building_index")
        index_path = bundle / references / "transcripts.idx"
        fasta_path = bundle / references / "transcripts.fa"
        self._build_kallisto_index(job, index_path, fasta_path)

        self._set_stage(job, "finalizing")
        self._write_text(bundle / "README.txt", self._readme(job.pipeline_identifier))
        self._write_text(
            bundle / "fixture_metadata.json",
            self._json(
                {
                    "fixture_version": _FIXTURE_VERSION,
                    "synthetic_only": True,
                    "network_downloads": False,
                    "execution_supported": True,
                    "purpose": ("Synthetic functional validation fixture; not biological data."),
                }
            ),
        )
        self._finalize_bundle(job.pipeline_identifier, bundle)

    def _prepare_ont(self, job: DemoPrepareJob) -> None:
        bundle = self.root / job.pipeline_identifier
        self._safe_mkdir(self.root)
        self._set_stage(job, "preparing")
        self._clear_bundle(bundle)
        self._safe_mkdir(bundle)
        files = self._ont_files(bundle)
        for relative, content in files.items():
            self._write_bytes(bundle / relative, content)
        self._write_text(bundle / "README.txt", self._readme(job.pipeline_identifier))
        self._write_text(
            bundle / "fixture_metadata.json",
            self._json(
                {
                    "fixture_version": _FIXTURE_VERSION,
                    "synthetic_only": True,
                    "network_downloads": False,
                    "execution_supported": False,
                    "purpose": "UI and manifest integration fixture; not biological data.",
                }
            ),
        )
        self._set_stage(job, "finalizing")
        self._finalize_bundle(job.pipeline_identifier, bundle)

    def _finalize_bundle(self, pipeline_identifier: str, bundle: Path) -> None:
        relative_files = sorted(
            {
                str(path.relative_to(bundle))
                for path in bundle.rglob("*")
                if path.is_file() and not path.is_symlink()
            }
        )
        file_hashes = {relative: self._sha256(bundle / relative) for relative in relative_files}
        project_manifest = "project_manifest.json"
        execution_supported = pipeline_identifier == "bulk-rnaseq"
        metadata = {
            "format": "missus-tom-synthetic-demo-bundle",
            "fixture_version": _FIXTURE_VERSION,
            "pipeline_identifier": pipeline_identifier,
            "prepared_at": datetime.now(UTC).isoformat(),
            "project_manifest": project_manifest,
            "synthetic_only": True,
            "network_downloads": False,
            "execution_supported": execution_supported,
            "files": file_hashes,
            "integrity": {
                "sha256": file_hashes[project_manifest],
                "file_count": len(file_hashes),
            },
        }
        self._write_text(bundle / _BUNDLE_MANIFEST, self._json(metadata))

    def _write_bulk_references(self, references: Path, job: DemoPrepareJob) -> builtins.list[str]:
        transcripts = references / "transcripts.fa"
        biomart = references / "biomart.tsv"
        gtf = references / "annotation.gtf"
        sequences: builtins.list[str] = []
        with transcripts.open("w", encoding="utf-8") as fasta:
            biomart_lines = ["Gene stable ID version\tGene type\tGene name\n"]
            gtf_lines: builtins.list[str] = []
            for index in range(_TRANSCRIPT_COUNT):
                sequence = lcg_sequence(index + 17)
                sequences.append(sequence)
                transcript_id = f"ENST900000{index + 1:03d}"
                gene_id = f"ENSG900000{index + 1:03d}"
                if index < 12:
                    gene_name = f"SMOKEPC{index + 1}"
                    gene_type = "protein_coding"
                else:
                    gene_name = f"SMOKELNC{index - 11}"
                    gene_type = "lncRNA"
                header = (
                    f">{transcript_id}|{gene_id}|SMOKE|SMOKE|SMOKE|{gene_name}|SMOKE|{gene_type}"
                )
                fasta.write(f"{header}\n{sequence}\n")
                biomart_lines.append(f"{gene_id}\t{gene_type}\t{gene_name}\n")
                gtf_lines.append(
                    f"synthetic\tfixture\texon\t1\t{len(sequence)}\t.\t+\t.\t"
                    f'gene_id "{gene_id}"; transcript_id "{transcript_id}";\n'
                )
            self._write_text(biomart, "".join(biomart_lines))
            self._write_text(gtf, "".join(gtf_lines))
        self._log(job, f"Wrote {_TRANSCRIPT_COUNT} synthetic transcripts and reference tables.")
        return sequences

    def _write_bulk_sample_fastqs(
        self,
        inputs: Path,
        *,
        sample_id: str,
        smoke_tag: str,
        sequences: builtins.list[str],
        job: DemoPrepareJob,
    ) -> None:
        quality = "I" * _READ_LENGTH
        for mate in (1, 2):
            buffer = io.BytesIO()
            with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as handle:
                for index, sequence in enumerate(sequences):
                    count = synthetic_read_count(smoke_tag, index)
                    read1 = sequence[:_READ_LENGTH]
                    read2 = reverse_complement(sequence[-_READ_LENGTH:])
                    read = read1 if mate == 1 else read2
                    for pair in range(1, count + 1):
                        record = f"@{sample_id}_g{index}_p{pair}/{mate}\n{read}\n+\n{quality}\n"
                        handle.write(record.encode("ascii"))
            self._write_bytes(inputs / f"{sample_id}_R{mate}.fastq.gz", buffer.getvalue())
        self._log(job, f"Wrote paired FASTQs for {sample_id}.")

    def _build_kallisto_index(
        self, job: DemoPrepareJob, index_path: Path, fasta_path: Path
    ) -> None:
        executable = runtime_tool("kallisto", "bulk-rnaseq")
        if executable is None:
            raise RuntimeError(
                "kallisto is not installed in the managed bulk-rnaseq environment; "
                "install pipeline dependencies before preparing the executable demo"
            )
        command = [executable, "index", "-i", str(index_path), str(fasta_path)]
        self._run_subprocess(job, command, env=runtime_environment("bulk-rnaseq"))
        if not index_path.is_file():
            raise RuntimeError("kallisto index command did not create the expected index file")

    def _bulk_manifest(self, bundle: Path, inputs: str, references: str) -> dict[str, object]:
        samples = [
            self._sample(sample_id, condition, inputs, replicate=replicate)
            for sample_id, condition, replicate, _smoke in _BULK_SAMPLES
        ]
        return self._manifest(
            pipeline_identifier="bulk-rnaseq",
            bundle=bundle,
            input_directory=inputs,
            output_directory="project-output",
            organism="Homo sapiens",
            reference_genome="synthetic-reference",
            annotation_source="synthetic-fixture",
            reference_resources={
                "transcriptome_fasta": f"{references}/transcripts.fa",
                "annotation_gtf": f"{references}/annotation.gtf",
                "biomart": f"{references}/biomart.tsv",
                "kallisto_index": f"{references}/transcripts.idx",
            },
            library_type="synthetic total RNA",
            read_layout="paired-end",
            strandedness="unstranded",
            samples=samples,
            comparisons=[
                {
                    "comparison_id": "treatment_vs_control",
                    "numerator": "treatment",
                    "denominator": "control",
                    "label": "Synthetic treatment vs control",
                }
            ],
            parameters={
                "demo_fixture": True,
                "synthetic": True,
                "scientific_execution_supported": True,
                "minimum_group_size": 2,
            },
            execution_profile="local",
            resource_profile={"cpus": 2, "memory_gb": 4, "max_parallel_tasks": 1},
        )

    def _ont_files(self, bundle: Path) -> dict[str, bytes]:
        references = "references"
        manifest = self._manifest(
            pipeline_identifier="ont-analysis",
            bundle=bundle,
            input_directory="inputs",
            output_directory="project-output",
            organism="Mus musculus",
            reference_genome="GRCm38p6",
            annotation_source="synthetic-fixture",
            reference_resources={
                key: f"{references}/{filename}"
                for key, filename in {
                    "reference_fasta": "reference.fa",
                    "reference_fai": "reference.fa.fai",
                    "minimap2_index": "reference.mmi",
                    "gencode_gff3": "annotation.gff3",
                    "cpg_islands": "cpg_islands.bed",
                    "ccre_table": "ccre.tsv",
                    "intergenic_bed": "intergenic.bed",
                    "ont_instrument_report": "instrument_report.txt",
                }.items()
            },
            library_type="synthetic ONT DNA",
            read_layout="single-end",
            strandedness="unknown",
            samples=[
                {
                    "sample_id": "SYN_ON_T_01",
                    "r1_files": [],
                    "r2_files": [],
                    "ont_bam_files": [str((bundle / "inputs/synthetic_pass_modbam.bam").resolve())],
                    "condition": "single_sample",
                    "biological_replicate": "1",
                    "batch": None,
                    "covariates": {},
                    "included": True,
                }
            ],
            comparisons=[],
            parameters={
                "expected_pass_bam_count": 1,
                "demo_fixture": True,
                "scientific_execution_supported": False,
            },
            execution_profile="local",
        )
        return {
            "project_manifest.json": self._json(manifest).encode("utf-8"),
            "inputs/synthetic_pass_modbam.bam": b"NOT_A_BAM; synthetic UI fixture only\n",
            f"{references}/reference.fa": b">chrSynthetic\nACGTACGTACGT\n",
            f"{references}/reference.fa.fai": b"chrSynthetic\t12\t14\t12\t13\n",
            f"{references}/reference.mmi": b"NOT_A_MINIMAP2_INDEX; synthetic UI fixture only\n",
            f"{references}/annotation.gff3": b"##gff-version 3\n",
            f"{references}/cpg_islands.bed": b"chrSynthetic\t0\t4\n",
            f"{references}/ccre.tsv": b"id\tclass\nSYN1\tsynthetic\n",
            f"{references}/intergenic.bed": b"chrSynthetic\t4\t12\n",
            f"{references}/instrument_report.txt": b"Synthetic fixture; no instrument data.\n",
        }

    @staticmethod
    def _sample(
        sample_id: str, condition: str, inputs: str, *, replicate: str
    ) -> dict[str, object]:
        return {
            "sample_id": sample_id,
            "r1_files": [f"{inputs}/{sample_id}_R1.fastq.gz"],
            "r2_files": [f"{inputs}/{sample_id}_R2.fastq.gz"],
            "ont_bam_files": [],
            "condition": condition,
            "biological_replicate": replicate,
            "batch": None,
            "covariates": {},
            "included": True,
        }

    @staticmethod
    def _manifest(
        *,
        pipeline_identifier: str,
        bundle: Path,
        input_directory: str,
        output_directory: str,
        organism: str,
        reference_genome: str,
        annotation_source: str,
        reference_resources: dict[str, str],
        library_type: str,
        read_layout: str,
        strandedness: str,
        samples: Sequence[dict[str, object]],
        comparisons: Sequence[dict[str, object]],
        parameters: dict[str, object],
        execution_profile: str,
        resource_profile: dict[str, int] | None = None,
    ) -> dict[str, object]:
        def absolute(relative: str) -> str:
            return str((bundle / relative).resolve())

        normalized_samples = []
        for sample in samples:
            normalized = dict(sample)
            for key in ("r1_files", "r2_files"):
                raw_paths = normalized[key]
                if not isinstance(raw_paths, list):
                    raise ValueError(f"synthetic sample field {key} must be a list")
                normalized[key] = [absolute(str(item)) for item in raw_paths]
            normalized_samples.append(normalized)
        profile = resource_profile or {"cpus": 1, "memory_gb": 1, "max_parallel_tasks": 1}
        return {
            "schema_version": "1.0.0",
            "project_name": f"Synthetic {pipeline_identifier} demo",
            "project_identifier": str(
                uuid5(NAMESPACE_URL, f"missus-tom/demo/{pipeline_identifier}/{_FIXTURE_VERSION}")
            ),
            "created_at": "2000-01-01T00:00:00+00:00",
            "input_directory": absolute(input_directory),
            "output_directory": absolute(output_directory),
            "pipeline_identifier": pipeline_identifier,
            "pipeline_version": "0.4.0" if pipeline_identifier == "bulk-rnaseq" else "0.1.0",
            "organism": organism,
            "reference_genome": reference_genome,
            "annotation_source": annotation_source,
            "reference_resources": {
                key: absolute(value) for key, value in reference_resources.items()
            },
            "library_type": library_type,
            "read_layout": read_layout,
            "strandedness": strandedness,
            "samples": normalized_samples,
            "comparisons": comparisons,
            "parameters": parameters,
            "resource_profile": profile,
            "execution_profile": execution_profile,
            "application_version": "0.1.0",
            "pipeline_status": "draft",
        }

    def _readme(self, pipeline_identifier: str) -> str:
        if pipeline_identifier == "bulk-rnaseq":
            return (
                f"Missus Tom synthetic demo bundle ({pipeline_identifier})\n\n"
                "All content was generated locally, contains no biological patient data, "
                "and required no network access. The bulk RNA-seq fixture uses synthetic "
                "sequences and differential read counts so the workflow can be exercised "
                "for functional validation only. Do not use it for biological inference.\n"
            )
        return (
            f"Missus Tom synthetic demo bundle ({pipeline_identifier})\n\n"
            "All content was generated locally, contains no biological data, and "
            "required no network access. This machine-local bundle exists for "
            "UI/manifest integration only and can be regenerated on another "
            "machine. Do not use it for workflow or scientific validation.\n"
        )

    def _execution_supported(self, bundle: Path) -> bool:
        path = bundle / "fixture_metadata.json"
        if not path.is_file() or path.is_symlink():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(payload.get("execution_supported"))

    def _read_verified_metadata(
        self, bundle: Path, expected_pipeline_identifier: str
    ) -> dict[str, Any] | None:
        try:
            self._assert_safe_existing(bundle)
            metadata = json.loads((bundle / _BUNDLE_MANIFEST).read_text(encoding="utf-8"))
            if (
                not isinstance(metadata, dict)
                or metadata.get("format") != "missus-tom-synthetic-demo-bundle"
                or metadata.get("pipeline_identifier") != expected_pipeline_identifier
                or not isinstance(metadata.get("project_manifest"), str)
                or not isinstance(metadata.get("prepared_at"), str)
                or not isinstance(metadata.get("integrity"), dict)
            ):
                return None
            files = metadata.get("files")
            if not isinstance(files, dict) or not files:
                return None
            for relative, digest in files.items():
                if not isinstance(relative, str) or not isinstance(digest, str):
                    return None
                candidate = bundle / relative
                if (
                    Path(relative).is_absolute()
                    or ".." in Path(relative).parts
                    or not candidate.is_file()
                    or candidate.is_symlink()
                    or self._sha256(candidate) != digest
                ):
                    return None
            integrity = metadata["integrity"]
            if (
                not isinstance(integrity.get("sha256"), str)
                or not isinstance(integrity.get("file_count"), int)
                or integrity["sha256"] != files.get(metadata["project_manifest"])
                or integrity["file_count"] != len(files)
            ):
                return None
            datetime.fromisoformat(metadata["prepared_at"])
            return metadata
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def _spec(self, pipeline_identifier: str) -> dict[str, str]:
        try:
            return _CATALOG[pipeline_identifier]
        except KeyError as exc:
            raise ValueError(
                f"unsupported demo pipeline identifier: {pipeline_identifier}"
            ) from exc

    def _clear_bundle(self, bundle: Path) -> None:
        self._assert_safe_existing(bundle)
        if not bundle.exists():
            return
        for child in bundle.iterdir():
            if child.is_symlink():
                raise ValueError("demo bundle may not contain symbolic links")
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    def _safe_mkdir(self, path: Path) -> None:
        self._assert_safe_parent(path)
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.is_dir() or path.is_symlink():
            raise ValueError("demo storage path must be a real directory")

    def _assert_safe_parent(self, path: Path) -> None:
        resolved_root = self.state_directory.resolve(strict=False)
        if not path.resolve(strict=False).is_relative_to(resolved_root):
            raise ValueError("demo storage path escapes the configured state directory")
        current = path
        while current != resolved_root and not current.exists():
            current = current.parent
        self._assert_safe_existing(current)

    def _assert_safe_existing(self, path: Path) -> None:
        root = self.state_directory.resolve(strict=False)
        if not path.resolve(strict=False).is_relative_to(root):
            raise ValueError("demo storage path escapes the configured state directory")
        current = path
        while current != root:
            if current.exists() and current.is_symlink():
                raise ValueError("demo storage may not use symbolic links")
            current = current.parent
        if root.exists() and root.is_symlink():
            raise ValueError("demo storage may not use symbolic links")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, prefix=".demo-", delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(content)
                handle.flush()
                os.fchmod(handle.fileno(), stat.S_IRUSR | stat.S_IWUSR)
                os.fsync(handle.fileno())
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        os.replace(temporary, path)

    def _write_text(self, path: Path, content: str) -> None:
        self._write_bytes(path, content.encode("utf-8"))

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, indent=2, sort_keys=True) + "\n"

    def _job_path(self, job_identifier: str) -> Path:
        return self.jobs_root / f"{job_identifier}.json"

    def _log_path(self, job_identifier: str) -> Path:
        return self.jobs_root / f"{job_identifier}.prepare.log"

    def _acquire_run_lock(self, job_identifier: str) -> int:
        path = settings.state_directory / "runs" / ".active-run.lock"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(descriptor, 0)
            os.write(descriptor, job_identifier.encode("ascii"))
            return descriptor
        except OSError as exc:
            os.close(descriptor)
            if exc.errno in {11, 35}:
                raise ValueError("a workflow run is active or requires recovery") from exc
            raise

    def _release_run_lock(self, job_identifier: str) -> None:
        descriptor = self._run_lock_descriptors.pop(job_identifier, None)
        if descriptor is not None:
            with suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _persist(self, job: DemoPrepareJob) -> None:
        self._safe_mkdir(self.jobs_root)
        path = self._job_path(job.job_identifier)
        temporary = path.with_suffix(".tmp")
        descriptor = os.open(
            temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, job.model_dump_json().encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        temporary.replace(path)

    def _recover_jobs(self) -> None:
        jobs = self.jobs_root
        if not jobs.is_dir() or jobs.is_symlink():
            return
        for path in jobs.glob("*.json"):
            with suppress(OSError, ValueError):
                UUID(path.stem)
                if path.is_symlink():
                    continue
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    payload = os.read(descriptor, 1_000_000).decode("utf-8")
                finally:
                    os.close(descriptor)
                job = DemoPrepareJob.model_validate_json(payload)
                if job.status == DemoPrepareStatus.RUNNING:
                    job.status = DemoPrepareStatus.FAILED
                    job.message = "backend restarted before demo preparation completed."
                    job.finished_at = datetime.now(UTC)
                    self._persist(job)
                self._jobs[job.job_identifier] = job

    def _set_stage(self, job: DemoPrepareJob, stage: str) -> None:
        job.current_stage = stage
        self._log(job, f"Stage: {stage}")
        self._persist(job)

    def _log(self, job: DemoPrepareJob, line: str) -> None:
        stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        job.last_output_at = datetime.now(UTC)
        formatted = f"{stamp} {line}"
        job.log_tail = [*job.log_tail, formatted][-80:]
        self._append_command_log(job, formatted)
        self._persist(job)

    def _append_command_log(self, job: DemoPrepareJob, line: str) -> None:
        path = self._log_path(job.job_identifier)
        descriptor = os.open(
            path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, (line + "\n").encode("utf-8", errors="replace"))
        finally:
            os.close(descriptor)

    def _run_subprocess(
        self,
        job: DemoPrepareJob,
        command: builtins.list[str],
        *,
        env: dict[str, str] | None = None,
    ) -> None:
        self._log(job, "Running: " + " ".join(command))
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            shell=False,
            env=env,
            start_new_session=True,
        )
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        pending = b""
        try:
            while selector.get_map() or process.poll() is None:
                for key, _ in selector.select(timeout=1):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    pending += chunk
                    while b"\n" in pending or len(pending) >= 4096:
                        if b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                        else:
                            line, pending = pending[:4096], pending[4096:]
                        decoded = line.decode("utf-8", errors="replace").rstrip()
                        self._log(job, decoded[:2000])
            if pending:
                decoded = pending.decode("utf-8", errors="replace").rstrip()
                self._log(job, decoded[:2000])
            return_code = process.wait()
        except Exception:
            with suppress(ProcessLookupError):
                process.kill()
            process.wait()
            raise
        if return_code != 0:
            raise RuntimeError(f"command failed with exit code {return_code}: {' '.join(command)}")


demo_service = DemoService()
