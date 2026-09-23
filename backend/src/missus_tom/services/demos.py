"""Local, deterministic, deliberately non-scientific demo bundle generation."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import stat
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final
from uuid import NAMESPACE_URL, uuid5

from missus_tom.config import settings
from missus_tom.models.demos import DemoIntegrity, DemoStatus

_CATALOG: Final = {
    "bulk-rnaseq": {
        "title": "Synthetic human bulk RNA-seq fixture",
        "note": (
            "Synthetic sequences and placeholder references only; this bundle is "
            "not a scientific execution fixture."
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
_FIXTURE_VERSION: Final = "1"


class DemoService:
    """Owns only ``settings.state_directory / demos``; it never downloads data."""

    def __init__(self, *, state_directory: Path | None = None) -> None:
        self.state_directory = state_directory or settings.state_directory

    @property
    def root(self) -> Path:
        return self.state_directory / "demos"

    def list(self) -> list[DemoStatus]:
        return [self.status(identifier) for identifier in _CATALOG]

    def status(self, pipeline_identifier: str) -> DemoStatus:
        spec = self._spec(pipeline_identifier)
        bundle = self.root / pipeline_identifier
        metadata = self._read_verified_metadata(bundle, pipeline_identifier)
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
        )

    def prepare(self, pipeline_identifier: str) -> DemoStatus:
        self._spec(pipeline_identifier)
        self._safe_mkdir(self.root)
        bundle = self.root / pipeline_identifier
        self._safe_mkdir(bundle)
        files = self._write_bundle(pipeline_identifier, bundle)
        file_hashes = {relative: self._sha256(bundle / relative) for relative in sorted(files)}
        project_manifest = "project_manifest.json"
        metadata = {
            "format": "missus-tom-synthetic-demo-bundle",
            "fixture_version": _FIXTURE_VERSION,
            "pipeline_identifier": pipeline_identifier,
            "prepared_at": datetime.now(UTC).isoformat(),
            "project_manifest": project_manifest,
            "synthetic_only": True,
            "network_downloads": False,
            "files": file_hashes,
            "integrity": {
                "sha256": file_hashes[project_manifest],
                "file_count": len(file_hashes),
            },
        }
        self._write_text(bundle / _BUNDLE_MANIFEST, self._json(metadata))
        return self.status(pipeline_identifier)

    def _write_bundle(self, pipeline_identifier: str, bundle: Path) -> set[str]:
        files: dict[str, bytes] = {
            "README.txt": self._readme(pipeline_identifier).encode("utf-8"),
            "fixture_metadata.json": self._json(
                {
                    "fixture_version": _FIXTURE_VERSION,
                    "synthetic_only": True,
                    "network_downloads": False,
                    "execution_supported": False,
                    "purpose": "UI and manifest integration fixture; not biological data.",
                }
            ).encode("utf-8"),
        }
        if pipeline_identifier == "bulk-rnaseq":
            files.update(self._bulk_files(bundle))
        else:
            files.update(self._ont_files(bundle))
        for relative, content in files.items():
            self._write_bytes(bundle / relative, content)
        return set(files)

    def _bulk_files(self, bundle: Path) -> dict[str, bytes]:
        inputs = "inputs"
        references = "references"
        manifest = self._manifest(
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
            strandedness="reverse",
            samples=[
                self._sample("SYN_CONTROL_01", "control", inputs),
                self._sample("SYN_TREATMENT_01", "treatment", inputs),
            ],
            comparisons=[
                {
                    "comparison_id": "treatment_vs_control",
                    "numerator": "treatment",
                    "denominator": "control",
                    "label": "Synthetic treatment vs control",
                }
            ],
            parameters={"demo_fixture": True, "scientific_execution_supported": False},
            execution_profile="local",
        )
        result: dict[str, bytes] = {"project_manifest.json": self._json(manifest).encode("utf-8")}
        for sample in ("SYN_CONTROL_01", "SYN_TREATMENT_01"):
            for mate in (1, 2):
                result[f"{inputs}/{sample}_R{mate}.fastq.gz"] = self._gzip_fastq(sample, mate)
        result.update(
            {
                f"{references}/transcripts.fa": b">SYNTHETIC_TX1\nACGTACGTACGT\n",
                f"{references}/annotation.gtf": (
                    b'synthetic\tfixture\tgene\t1\t12\t.\t+\t.\tgene_id "SYNTHETIC_GENE1";\n'
                ),
                f"{references}/biomart.tsv": (
                    b"ensembl_gene_id\thgnc_symbol\nSYNTHETIC_GENE1\tSYN1\n"
                ),
                f"{references}/transcripts.idx": (
                    b"NOT_A_KALLISTO_INDEX; synthetic UI fixture only\n"
                ),
            }
        )
        return result

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
    def _sample(sample_id: str, condition: str, inputs: str) -> dict[str, object]:
        return {
            "sample_id": sample_id,
            "r1_files": [f"{inputs}/{sample_id}_R1.fastq.gz"],
            "r2_files": [f"{inputs}/{sample_id}_R2.fastq.gz"],
            "ont_bam_files": [],
            "condition": condition,
            "biological_replicate": "1",
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
            "resource_profile": {"cpus": 1, "memory_gb": 1, "max_parallel_tasks": 1},
            "execution_profile": execution_profile,
            "application_version": "0.1.0",
            "pipeline_status": "draft",
        }

    @staticmethod
    def _gzip_fastq(sample: str, mate: int) -> bytes:
        import io

        buffer = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as handle:
            handle.write(f"@{sample}:000000001/{mate}\nACGTACGT\n+\nIIIIIIII\n".encode("ascii"))
        return buffer.getvalue()

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, indent=2, sort_keys=True) + "\n"

    def _readme(self, pipeline_identifier: str) -> str:
        return (
            f"Missus Tom synthetic demo bundle ({pipeline_identifier})\n\n"
            "All content was generated locally, contains no biological data, and "
            "required no network access. This machine-local bundle exists for "
            "UI/manifest integration only and can be regenerated on another "
            "machine. Do not use it for workflow or scientific validation.\n"
        )

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


demo_service = DemoService()
