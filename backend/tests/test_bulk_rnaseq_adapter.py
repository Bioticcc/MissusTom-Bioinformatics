from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import missus_tom.pipeline_adapters.bulk_rnaseq as bulk_module
from missus_tom.models.manifest import BulkReferenceMode, ProjectManifest
from missus_tom.models.run import RunStartStage
from missus_tom.pipeline_adapters.bulk_rnaseq import BulkRnaSeqAdapter, execution_manifest_path
from missus_tom.services import resources
from missus_tom.services.bulk_references import BulkReferenceManager, PreparedBulkReferences
from missus_tom.services.projects import ProjectHistoryStore, save_project


@pytest.fixture(autouse=True)
def host_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter contract tests must not depend on the developer machine's free RAM/disk."""
    monkeypatch.setattr(
        resources,
        "inspect_host_resources",
        lambda: resources.HostResources(16, 64 * resources.GIB, 48 * resources.GIB),
    )
    monkeypatch.setattr(
        resources.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=1000 * resources.GIB, total=2000 * resources.GIB),
    )


def _write_production_reference_files(payload: dict[str, Any]) -> None:
    resources = payload["reference_resources"]
    fasta = Path(resources["transcriptome_fasta"])
    gtf = Path(resources["annotation_gtf"])
    mapping = fasta.parent / "transcript_to_gene.tsv"
    fasta.write_text(">ENST000001\nACGT\n", encoding="utf-8")
    gtf.write_text(
        "chr1\tHAVANA\texon\t1\t10\t.\t+\t.\t"
        'gene_id "ENSG1"; transcript_id "ENST000001"; gene_type "protein_coding";\n',
        encoding="utf-8",
    )
    mapping.write_text(
        "transcript_id\tgene_id\tgene_name\tgene_biotype\ttranscript_biotype\n"
        "ENST000001\tENSG1\tGeneA\tprotein_coding\tprotein_coding\n",
        encoding="utf-8",
    )
    resources.pop("biomart", None)
    resources["transcript_to_gene"] = str(mapping)


def supported_manifest(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
) -> ProjectManifest:
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.1.0",
        reference_mode=BulkReferenceMode.EXISTING_INDEX.value,
        pipeline_version="0.5.0",
        organism="Homo sapiens",
        reference_genome="GRCh38",
        execution_profile="local",
        pipeline_status="planned",
    )
    _write_production_reference_files(payload)
    payload["parameters"] = {
        "adapter_r1": "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA",
        "adapter_r2": "AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT",
        "trim_quality": 20,
        "trim_minimum_length": 20,
        "minimum_group_size": 2,
        "adjusted_p_value": 0.05,
        "absolute_log2_fold_change": 0.3,
    }

    input_root = Path(payload["input_directory"])
    additions = []
    for sample_id, condition in (("synthetic_A2", "control"), ("synthetic_B2", "treatment")):
        r1 = input_root / f"{sample_id}_R1.fastq.gz"
        r2 = input_root / f"{sample_id}_R2.fastq.gz"
        r1.touch()
        r2.touch()
        additions.append(
            {
                "sample_id": sample_id,
                "r1_files": [str(r1)],
                "r2_files": [str(r2)],
                "condition": condition,
                "biological_replicate": "2",
                "batch": None,
                "covariates": {},
                "included": True,
            }
        )
    payload["samples"].extend(additions)
    return ProjectManifest.model_validate(payload)


def test_supported_user_project_is_executable(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    manifest = supported_manifest(tmp_path, manifest_payload)
    save_project(
        manifest,
        history_store=ProjectHistoryStore(tmp_path / "state.sqlite3"),
    )
    monkeypatch.setattr(
        bulk_module,
        "runtime_tool",
        lambda executable, _pipeline: f"/usr/bin/{executable}",
    )
    monkeypatch.setattr(
        bulk_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    adapter = BulkRnaSeqAdapter()
    adapter.validate_execution(manifest)
    plan = adapter.construct_run_plan(manifest)

    assert plan.execution_enabled is True
    assert plan.execution_profile == "local"
    assert plan.command_preview[plan.command_preview.index("-profile") + 1] == "local"
    assert "--max_cpus" in plan.command_preview
    manifest_index = plan.command_preview.index("--manifest") + 1
    assert plan.command_preview[manifest_index].endswith("project_manifest.json")
    assert plan.command_preview[-2:] == ["--start_stage", "quantification"]


def test_supported_user_project_allows_empty_replicate_ids(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    manifest = supported_manifest(tmp_path, manifest_payload)
    payload = manifest.model_dump(mode="json")
    for sample in payload["samples"]:
        sample["biological_replicate"] = ""
    without_replicates = ProjectManifest.model_validate(payload)
    save_project(
        without_replicates,
        history_store=ProjectHistoryStore(tmp_path / "optional-replicates-state.sqlite3"),
    )
    monkeypatch.setattr(bulk_module, "runtime_tool", lambda executable, _: f"/usr/bin/{executable}")
    monkeypatch.setattr(
        bulk_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    BulkRnaSeqAdapter().validate_execution(without_replicates)


def test_adapter_rejects_shell_unsafe_adapter_sequence(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    manifest = supported_manifest(tmp_path, manifest_payload)
    payload = manifest.model_dump(mode="json")
    payload["parameters"]["adapter_r1"] = "ACGT;touch_BAD"
    unsafe_manifest = ProjectManifest.model_validate(payload)

    with pytest.raises(ValueError, match="IUPAC"):
        BulkRnaSeqAdapter().validate_execution(unsafe_manifest)


def test_adapter_accepts_intervention_filtered_comparison(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    manifest = supported_manifest(tmp_path, manifest_payload)
    payload = manifest.model_dump(mode="json")
    for sample in payload["samples"]:
        sample["covariates"]["intervention"] = "D"
    payload["comparisons"][0]["intervention"] = "D"
    filtered = ProjectManifest.model_validate(payload)
    save_project(
        filtered,
        history_store=ProjectHistoryStore(tmp_path / "filtered-state.sqlite3"),
    )
    monkeypatch.setattr(bulk_module, "runtime_tool", lambda executable, _: f"/usr/bin/{executable}")
    monkeypatch.setattr(
        bulk_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    BulkRnaSeqAdapter().validate_execution(filtered)


def test_analysis_only_accepts_external_kallisto_tables(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    full_manifest = supported_manifest(tmp_path, manifest_payload)
    payload = full_manifest.model_dump(mode="json")
    payload["parameters"]["start_stage"] = "analysis"
    payload["reference_mode"] = BulkReferenceMode.BUILD.value
    payload["reference_resources"].pop("kallisto_index")
    payload["reference_resources"].pop("transcript_to_gene", None)
    for key in ("adapter_r1", "adapter_r2", "trim_quality", "trim_minimum_length"):
        payload["parameters"].pop(key)
    for sample in payload["samples"]:
        abundance = Path(payload["input_directory"]) / sample["sample_id"] / "abundance.tsv"
        abundance.parent.mkdir(exist_ok=True)
        abundance.write_text(
            "target_id\tlength\teff_length\test_counts\ttpm\n",
            encoding="utf-8",
        )
        sample["r1_files"] = []
        sample["r2_files"] = []
        sample["abundance_tsv"] = str(abundance)
    manifest = ProjectManifest.model_validate(payload)
    save_project(
        manifest,
        history_store=ProjectHistoryStore(tmp_path / "analysis-state.sqlite3"),
    )
    monkeypatch.setattr(bulk_module, "runtime_tool", lambda executable, _: f"/usr/bin/{executable}")
    monkeypatch.setattr(
        bulk_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    adapter = BulkRnaSeqAdapter()
    adapter.validate_execution(manifest, start_stage=RunStartStage.ANALYSIS)
    with pytest.raises(ValueError, match="adapter_r1"):
        adapter.validate_execution(manifest, start_stage=RunStartStage.QUANTIFICATION)

    assert adapter.construct_run_plan(manifest).command_preview[-1] == "analysis"


def test_local_profile_requires_nextflow_only(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    manifest = supported_manifest(tmp_path, manifest_payload)
    save_project(manifest, history_store=ProjectHistoryStore(tmp_path / "local-state.sqlite3"))
    seen: list[str] = []

    def runtime_tool(executable: str, _pipeline: str) -> str | None:
        seen.append(executable)
        return "/usr/bin/nextflow" if executable == "nextflow" else None

    def reject_docker_query(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        raise AssertionError("local profile must not query Docker")

    monkeypatch.setattr(bulk_module, "runtime_tool", runtime_tool)
    monkeypatch.setattr(bulk_module.subprocess, "run", reject_docker_query)

    BulkRnaSeqAdapter().validate_execution(manifest)

    assert seen == ["nextflow"]


def test_docker_profile_still_checks_docker(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    manifest = supported_manifest(tmp_path, manifest_payload)
    payload = manifest.model_dump(mode="json")
    payload["execution_profile"] = "docker"
    docker_manifest = ProjectManifest.model_validate(payload)
    save_project(
        docker_manifest,
        history_store=ProjectHistoryStore(tmp_path / "docker-state.sqlite3"),
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(bulk_module, "runtime_tool", lambda executable, _: f"/usr/bin/{executable}")

    def run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bulk_module.subprocess, "run", run)

    adapter = BulkRnaSeqAdapter()
    adapter.validate_execution(docker_manifest)
    plan = adapter.construct_run_plan(docker_manifest)

    assert calls == [["docker", "info", "--format", "{{.ServerVersion}}"]]
    assert plan.execution_enabled is True
    assert plan.execution_profile == "docker"


def test_adapter_rejects_profiles_other_than_local_and_docker(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    manifest = supported_manifest(tmp_path, manifest_payload)
    payload = manifest.model_dump(mode="json")
    payload["execution_profile"] = "apptainer"
    rejected = ProjectManifest.model_validate(payload)
    monkeypatch.setattr(bulk_module, "runtime_tool", lambda executable, _: f"/usr/bin/{executable}")

    with pytest.raises(ValueError, match="local tools or Docker"):
        BulkRnaSeqAdapter().validate_execution(rejected)

    plan = BulkRnaSeqAdapter().construct_run_plan(rejected)
    assert plan.execution_enabled is False
    assert any("Local tools or Docker" in warning for warning in plan.warnings)


def test_legacy_biomart_only_project_reports_migration_error(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    payload = deepcopy(manifest_payload)
    payload.update(
        schema_version="1.0.0",
        reference_mode=None,
        pipeline_version="0.4.0",
        organism="Homo sapiens",
        reference_genome="GRCh38",
    )
    payload["reference_resources"] = {
        "biomart": payload["reference_resources"]["biomart"],
        "kallisto_index": payload["reference_resources"]["kallisto_index"],
    }
    manifest = ProjectManifest.model_validate(payload)

    with pytest.raises(ValueError, match="legacy BioMart-only"):
        BulkRnaSeqAdapter().validate_execution(manifest)


def test_generic_organism_is_not_blocked_for_production_contract(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    manifest = supported_manifest(tmp_path, manifest_payload)
    payload = manifest.model_dump(mode="json")
    payload["organism"] = "Mus musculus"
    generic = ProjectManifest.model_validate(payload)
    save_project(
        generic,
        history_store=ProjectHistoryStore(tmp_path / "generic-organism.sqlite3"),
    )
    monkeypatch.setattr(bulk_module, "runtime_tool", lambda executable, _: f"/usr/bin/{executable}")
    monkeypatch.setattr(
        bulk_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    BulkRnaSeqAdapter().validate_execution(generic)


def test_prepare_run_references_writes_execution_manifest_snapshot(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
) -> None:
    manifest = supported_manifest(tmp_path, manifest_payload)
    job_identifier = "11111111-2222-4333-8444-555555555555"
    prepared = PreparedBulkReferences(
        reference_mode=BulkReferenceMode.EXISTING_INDEX,
        analysis_only=False,
        kallisto_index=manifest.reference_resources["kallisto_index"],
        transcript_to_gene=manifest.reference_resources["transcript_to_gene"],
        cache_root=str(tmp_path / "cache"),
    )
    manager = BulkReferenceManager(cache_root=tmp_path / "cache")
    manager.prepare = lambda _manifest, **_kwargs: prepared  # type: ignore[method-assign]

    adapter = BulkRnaSeqAdapter()
    destination, _ = adapter.prepare_run_references(
        manifest,
        job_identifier=job_identifier,
        manager=manager,
        start_stage=RunStartStage.ANALYSIS,
    )

    assert destination == execution_manifest_path(Path(manifest.output_directory), job_identifier)
    payload = destination.read_text(encoding="utf-8")
    decoded = json.loads(payload)
    assert "reference_provenance" in payload
    assert "transcript_to_gene" in payload
    assert "biomart" not in payload
    assert decoded["parameters"]["start_stage"] == "analysis"
    ProjectManifest.model_validate(decoded)


def test_missing_reference_mode_blocks_production_validation(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISSUS_TOM_EXECUTION_ENABLED", "1")
    manifest = supported_manifest(tmp_path, manifest_payload)
    payload = manifest.model_dump(mode="json")
    payload.pop("reference_mode")
    payload["schema_version"] = "1.0.0"
    without_mode = ProjectManifest.model_validate(payload)
    monkeypatch.setattr(bulk_module, "runtime_tool", lambda executable, _: f"/usr/bin/{executable}")

    with pytest.raises(ValueError, match="reference_mode"):
        BulkRnaSeqAdapter().validate_execution(without_mode)
