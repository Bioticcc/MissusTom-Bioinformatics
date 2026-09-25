from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest

from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.run import RunRecord, RunStartStage, RunStatus
from missus_tom.pipeline_adapters.bulk_rnaseq import BulkRnaSeqAdapter
from missus_tom.services import runs as runs_module
from missus_tom.services.projects import ProjectHistoryStore, save_project
from missus_tom.services.runs import ProcessIdentity, RunManager


class StubAdapter:
    def __init__(self, root: Path) -> None:
        self.repository_root = root

    def validate_execution(
        self,
        _manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> None:
        return None

    def construct_command(
        self,
        _manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> list[str]:
        return [
            sys.executable,
            "-c",
            "print('controlled-run-ok')",
            "-resume",
            "--start_stage",
            start_stage.value,
        ]


class SleepingAdapter(StubAdapter):
    def construct_command(
        self,
        _manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> list[str]:
        return [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
        ]


class HeartbeatAdapter(StubAdapter):
    def construct_command(
        self,
        _manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> list[str]:
        return [sys.executable, "-c", "import time; time.sleep(0.12)"]


class DescendantAdapter(SleepingAdapter):
    def construct_command(
        self,
        _manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> list[str]:
        child = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
        parent = (
            "import signal, subprocess, sys, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
        )
        return [sys.executable, "-c", parent]


class NextflowCommandAdapter(StubAdapter):
    def construct_command(
        self,
        _manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> list[str]:
        del start_stage
        return ["nextflow", "run", "main.nf", "-resume"]


class ResumeRequiredAdapter(StubAdapter):
    @property
    def requires_resume(self) -> bool:
        return True


class StageReportingAdapter(StubAdapter):
    def construct_command(
        self,
        _manifest: ProjectManifest,
        *,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> list[str]:
        del start_stage
        return [
            sys.executable,
            "-c",
            "import time; print('RUN: bash /runner/stages/01_align_modbam.sh', flush=True); "
            "time.sleep(0.2)",
        ]


def wait_for_terminal(manager: RunManager, job_identifier: str) -> RunRecord:
    for _ in range(300):
        record = manager.get(job_identifier)
        if not record.holds_admission:
            return record
        time.sleep(0.01)
    pytest.fail("run did not reach a terminal state")


def wait_for_status(manager: RunManager, job_identifier: str, status: RunStatus) -> RunRecord:
    for _ in range(300):
        record = manager.get(job_identifier)
        if record.status == status:
            return record
        time.sleep(0.01)
    pytest.fail(f"run did not reach {status}")


def test_run_log_offset_read(tmp_path: Path, manifest_payload: dict[str, Any]) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    started = manager.start(manifest)
    record = wait_for_terminal(manager, started.job_identifier)
    assert record.status == RunStatus.COMPLETED

    tail = manager.read_log(started.job_identifier, limit=1000)
    assert tail.truncated in {True, False}
    assert tail.bytes_available is not None

    head = manager.read_log(started.job_identifier, offset=0, limit=5)
    rest = manager.read_log(started.job_identifier, offset=head.next_offset, limit=10_000)
    assert head.text == tail.text[: len(head.text)]
    assert head.truncated is True
    assert rest.truncated is False
    assert head.text + rest.text == tail.text[: head.next_offset + len(rest.text)]


def test_run_manager_captures_status_and_log(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]

    started = manager.start(manifest)
    record = started
    for _ in range(100):
        record = manager.get(started.job_identifier)
        if record.status not in {
            RunStatus.QUEUED,
            RunStatus.PREPARING,
            RunStatus.RUNNING,
        }:
            break
        time.sleep(0.01)

    assert record.status == RunStatus.COMPLETED
    assert record.exit_code == 0
    assert record.finished_at is not None
    log_text = manager.read_log(started.job_identifier).text
    assert "controlled-run-ok" in log_text
    completed_at = record.finished_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    assert f"Completed at {completed_at}." in log_text


def test_run_manager_writes_timestamped_heartbeats(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    monkeypatch.setattr(runs_module, "CHECK_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(runs_module, "HEARTBEAT_INTERVAL_SECONDS", 0.03)
    manager = RunManager(HeartbeatAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]

    started = manager.start(manifest)
    record = wait_for_terminal(manager, started.job_identifier)
    log_text = manager.read_log(started.job_identifier).text

    assert record.status == RunStatus.COMPLETED
    assert "Heartbeat at " in log_text
    assert ": workflow is still running." in log_text
    assert "Completed at " in log_text


def test_run_manager_can_start_without_resume(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]

    started = manager.start(manifest, resume=False)

    assert started.resume is False
    assert "-resume" not in started.command
    for _ in range(100):
        if manager.get(started.job_identifier).status not in {
            RunStatus.QUEUED,
            RunStatus.PREPARING,
            RunStatus.RUNNING,
        }:
            break
        time.sleep(0.01)


def test_run_manager_rejects_non_resumable_ont_style_execution(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    manager = RunManager(ResumeRequiredAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="requires resume-enabled"):
        manager.start(manifest, resume=False)

    assert manager.list_runs() == []


def test_run_manager_reports_runner_stage_from_controlled_log(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    monkeypatch.setattr(runs_module, "CHECK_INTERVAL_SECONDS", 0.01)
    manager = RunManager(StageReportingAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]

    started = manager.start(manifest)
    record = wait_for_status(manager, started.job_identifier, RunStatus.RUNNING)
    for _ in range(30):
        record = manager.get(started.job_identifier)
        if record.current_stage == "Runner stage: 01_align_modbam":
            break
        time.sleep(0.01)

    assert record.current_stage == "Runner stage: 01_align_modbam"


def test_run_manager_records_analysis_only_start_stage(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]

    started = manager.start(manifest, start_stage=RunStartStage.ANALYSIS)

    assert started.start_stage == RunStartStage.ANALYSIS
    stage_index = started.command.index("--start_stage")
    assert started.command[stage_index : stage_index + 2] == ["--start_stage", "analysis"]
    assert "--run_id" in started.command
    assert "-name" in started.command
    for _ in range(100):
        if manager.get(started.job_identifier).status not in {
            RunStatus.QUEUED,
            RunStatus.PREPARING,
            RunStatus.RUNNING,
        }:
            break
        time.sleep(0.01)


def test_run_manager_indexes_analysis_categories(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    project_root = tmp_path / "project"
    manifest_payload["output_directory"] = str(project_root)
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    started = manager.start(manifest)
    for _ in range(100):
        if manager.get(started.job_identifier).status == RunStatus.COMPLETED:
            break
        time.sleep(0.01)

    expected = {
        "differential_expression": "full_results.tsv",
        "figures": "Volcano_plot.png",
        "tables": "comparison_status.tsv",
    }
    for category, filename in expected.items():
        destination = project_root / "results" / category / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("result", encoding="utf-8")

    artifacts = manager.artifacts(started.job_identifier)

    assert {artifact.category for artifact in artifacts} >= set(expected)


def test_cancellation_retains_admission_until_process_reaped(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    monkeypatch.setattr(runs_module, "TERM_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(runs_module, "KILL_GRACE_SECONDS", 0.1)
    manager = RunManager(SleepingAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    started = manager.start(manifest)

    for _ in range(100):
        if manager.get(started.job_identifier).status == RunStatus.RUNNING:
            break
        time.sleep(0.01)
    cancelling = manager.cancel(started.job_identifier)

    assert cancelling.status == RunStatus.CANCELLING
    assert cancelling.holds_admission is True
    with pytest.raises(ValueError, match="active"):
        manager.start(manifest)

    cancelled = wait_for_terminal(manager, started.job_identifier)
    assert cancelled.status == RunStatus.CANCELLED
    assert cancelled.container_cleanup_verified_at is not None


def test_registry_recovers_completed_run(tmp_path: Path, manifest_payload: dict[str, Any]) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    registry = tmp_path / "state"
    manager = RunManager(StubAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]
    started = manager.start(manifest)
    completed = wait_for_terminal(manager, started.job_identifier)

    recovered = RunManager(StubAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]

    assert completed.status == RunStatus.COMPLETED
    assert recovered.get(started.job_identifier).status == RunStatus.COMPLETED


def test_resume_selects_same_project_session_and_never_global_last_run(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project-a")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    project_b_identifier = str(uuid4())
    now = datetime.now(UTC)
    manager._records = {
        "project-a-quantification": RunRecord(
            job_identifier="project-a-quantification",
            project_identifier=str(manifest.project_identifier),
            project_name="Project A",
            status=RunStatus.COMPLETED,
            command=["nextflow", "run"],
            log_path=str(tmp_path / "project-a" / "logs" / "run-a.log"),
            results_directory=str(tmp_path / "project-a" / "results"),
            created_at=now,
            nextflow_run_name="mt_project_a_quantification",
        ),
        "project-b-last": RunRecord(
            job_identifier="project-b-last",
            project_identifier=project_b_identifier,
            project_name="Project B",
            status=RunStatus.COMPLETED,
            command=["nextflow", "run"],
            log_path=str(tmp_path / "project-b" / "logs" / "run-b.log"),
            results_directory=str(tmp_path / "project-b" / "results"),
            created_at=now + timedelta(seconds=1),
            nextflow_run_name="mt_project_b_last",
        ),
    }

    started = manager.start(manifest)

    assert started.resume_from_run_name == "mt_project_a_quantification"
    resume_index = started.command.index("-resume")
    assert started.command[resume_index + 1] == "mt_project_a_quantification"
    assert "mt_project_b_last" not in started.command
    assert started.nextflow_run_name is not None
    assert started.nextflow_run_name.startswith("mt_")
    assert wait_for_terminal(manager, started.job_identifier).status == RunStatus.COMPLETED


def test_resume_omits_bare_flag_without_same_project_history(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project-a")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    manager._records["other-project"] = RunRecord(
        job_identifier="other-project",
        project_identifier=str(uuid4()),
        project_name="Other project",
        status=RunStatus.COMPLETED,
        command=["nextflow", "run"],
        log_path=str(tmp_path / "project-b" / "logs" / "run-b.log"),
        results_directory=str(tmp_path / "project-b" / "results"),
        created_at=datetime.now(UTC),
        nextflow_run_name="mt_other_project",
    )

    started = manager.start(manifest)

    assert started.resume_from_run_name is None
    assert "-resume" not in started.command
    assert wait_for_terminal(manager, started.job_identifier).status == RunStatus.COMPLETED


def test_resume_falls_back_to_project_local_legacy_log_name(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    log_path = tmp_path / "project" / "logs" / "run-legacy.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        "Launching `main.nf` [legacy_project_run]\n" + "x" * 210_000,
        encoding="utf-8",
    )
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    manager._records["legacy-project"] = RunRecord(
        job_identifier="legacy-project",
        project_identifier=str(manifest.project_identifier),
        project_name="Legacy project",
        status=RunStatus.FAILED,
        command=["nextflow", "run"],
        log_path=str(log_path),
        results_directory=str(tmp_path / "project" / "results"),
        created_at=datetime.now(UTC),
    )

    started = manager.start(manifest)

    assert started.resume_from_run_name == "legacy_project_run"
    assert started.command[started.command.index("-resume") + 1] == "legacy_project_run"
    assert wait_for_terminal(manager, started.job_identifier).status == RunStatus.COMPLETED


def test_resume_skips_unlaunched_terminal_name_for_prior_completed_session(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    now = datetime.now(UTC)
    manager._records = {
        "completed": RunRecord(
            job_identifier="completed",
            project_identifier=str(manifest.project_identifier),
            project_name="Project",
            status=RunStatus.COMPLETED,
            command=["nextflow", "run"],
            log_path=str(tmp_path / "project" / "logs" / "run-completed.log"),
            results_directory=str(tmp_path / "project" / "results"),
            created_at=now,
            nextflow_run_name="mt_real_completed_session",
        ),
        "failed-before-launch": RunRecord(
            job_identifier="failed-before-launch",
            project_identifier=str(manifest.project_identifier),
            project_name="Project",
            status=RunStatus.FAILED,
            command=["nextflow", "run"],
            log_path=str(tmp_path / "project" / "logs" / "run-unlaunched.log"),
            results_directory=str(tmp_path / "project" / "results"),
            created_at=now + timedelta(seconds=1),
            nextflow_run_name="mt_never_created",
        ),
    }

    started = manager.start(manifest)

    assert started.resume_from_run_name == "mt_real_completed_session"
    assert "mt_never_created" not in started.command
    assert wait_for_terminal(manager, started.job_identifier).status == RunStatus.COMPLETED


def test_recovery_fails_closed_for_legacy_active_record_without_identity(tmp_path: Path) -> None:
    registry = tmp_path / "state"
    registry.mkdir()
    record = RunRecord(
        job_identifier="cde91c1d-7c72-4d93-bb47-9719db9b6886",
        project_identifier="b6fd9dfd-4393-4bbd-b611-14a30296a2f7",
        project_name="Legacy run",
        status=RunStatus.RUNNING,
        command=["nextflow", "run"],
        log_path=str(tmp_path / "project" / "logs" / "run-legacy.log"),
        results_directory=str(tmp_path / "project" / "results"),
        created_at=datetime.now(UTC),
    )
    (registry / f"{record.job_identifier}.json").write_text(
        record.model_dump_json(), encoding="utf-8"
    )

    recovered = RunManager(StubAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]

    recovered_record = recovered.get(record.job_identifier)
    assert recovered_record.status == RunStatus.INTERRUPTED
    assert recovered_record.holds_admission is True
    assert "may still be active" in (recovered_record.error_message or "")


def test_recovery_releases_legacy_run_that_predates_current_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "state"
    registry.mkdir()
    boot_started_at = datetime(2026, 9, 4, tzinfo=UTC)
    record = RunRecord(
        job_identifier="17393b03-a9f5-4360-996e-2297f9c55599",
        project_identifier="b6fd9dfd-4393-4bbd-b611-14a30296a2f7",
        project_name="Pre-boot legacy run",
        status=RunStatus.RUNNING,
        command=["nextflow", "run"],
        log_path=str(tmp_path / "project" / "logs" / "run-legacy.log"),
        results_directory=str(tmp_path / "project" / "results"),
        created_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    (registry / f"{record.job_identifier}.json").write_text(
        record.model_dump_json(), encoding="utf-8"
    )
    monkeypatch.setattr(
        RunManager,
        "_current_boot_started_at",
        staticmethod(lambda: boot_started_at),
    )

    recovered = RunManager(StubAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]

    recovered_record = recovered.get(record.job_identifier)
    assert recovered_record.status == RunStatus.INTERRUPTED
    assert recovered_record.holds_admission is False
    assert recovered_record.finished_at == boot_started_at


def test_global_lock_blocks_second_manager_until_cancellation_finishes(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    monkeypatch.setattr(runs_module, "TERM_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(runs_module, "KILL_GRACE_SECONDS", 0.1)
    registry = tmp_path / "state"
    first = RunManager(SleepingAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]
    second = RunManager(SleepingAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]
    started = first.start(manifest)

    with pytest.raises(ValueError, match="active"):
        second.start(manifest)

    first.cancel(started.job_identifier)
    assert wait_for_terminal(first, started.job_identifier).status == RunStatus.CANCELLED


def test_initial_persist_failure_leaves_no_queued_record(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    monkeypatch.setattr(manager, "_persist", Mock(side_effect=OSError("state disk unavailable")))

    with pytest.raises(OSError, match="state disk unavailable"):
        manager.start(manifest)

    assert manager.list_runs() == []
    assert manager._locks == {}


def test_partial_initial_persistence_is_terminal_without_launch(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = ProjectManifest.model_validate(manifest_payload)
    registry = tmp_path / "state"
    manager = RunManager(StubAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]
    write_atomic = manager._write_atomic

    def fail_project_state(destination: Path, encoded: bytes) -> None:
        if destination.parent != registry:
            raise OSError("project filesystem full")
        write_atomic(destination, encoded)

    monkeypatch.setattr(manager, "_write_atomic", fail_project_state)
    with pytest.raises(OSError, match="filesystem full"):
        manager.start(manifest)
    record = manager.list_runs()[0]
    assert record.status == RunStatus.FAILED
    assert not record.holds_admission
    assert manager._processes == {}
    assert manager._locks == {}
    restored = RunManager(StubAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]
    assert restored.get(record.job_identifier).status == RunStatus.FAILED


def test_persistent_state_failure_cannot_prevent_cancellation_or_lock_release(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_module, "TERM_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(runs_module, "KILL_GRACE_SECONDS", 0.1)
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(SleepingAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    started = manager.start(manifest)
    wait_for_status(manager, started.job_identifier, RunStatus.RUNNING)
    process = manager._processes[started.job_identifier]
    monkeypatch.setattr(manager, "_persist", Mock(side_effect=OSError("disk full")))
    manager.cancel(started.job_identifier)
    record = wait_for_terminal(manager, started.job_identifier)
    assert record.status == RunStatus.CANCELLED
    assert process.poll() is not None
    assert manager._locks == {}
    assert "could not be fully saved" in (record.error_message or "")


def test_concurrent_finalizers_do_not_duplicate_container_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    entered, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def finalize(identifier: str, _code: int) -> None:
        calls.append(identifier)
        entered.set()
        assert release.wait(timeout=2)

    monkeypatch.setattr(manager, "_finalize_process", finalize)
    first = threading.Thread(target=manager._finish_process, args=("same-job", 0))
    first.start()
    try:
        assert entered.wait(timeout=1)
        manager._finish_process("same-job", 0)
        assert calls == ["same-job"]
    finally:
        release.set()
        first.join(timeout=2)
    assert manager._finalizing == set()


def test_thread_start_failure_persists_terminal_failure_not_queued_state(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    registry = tmp_path / "state"
    manager = RunManager(StubAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]
    monkeypatch.setattr(
        threading.Thread, "start", Mock(side_effect=RuntimeError("thread unavailable"))
    )

    with pytest.raises(RuntimeError, match="thread unavailable"):
        manager.start(manifest)

    record = manager.list_runs()[0]
    assert record.status == RunStatus.FAILED
    assert record.holds_admission is False
    assert manager.read_log(record.job_identifier).text.count("Failed at ") == 1
    recovered = RunManager(StubAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]
    assert recovered.get(record.job_identifier).status == RunStatus.FAILED


def test_popen_failure_appends_a_single_failed_terminal_marker(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    monkeypatch.setattr(runs_module.subprocess, "Popen", Mock(side_effect=OSError("no runner")))

    started = manager.start(manifest)
    failed = wait_for_terminal(manager, started.job_identifier)

    assert failed.status == RunStatus.FAILED
    assert manager.read_log(started.job_identifier).text.count("Failed at ") == 1


def test_prelaunch_cancellation_appends_a_cancelled_terminal_marker(tmp_path: Path) -> None:
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    record = RunRecord(
        job_identifier="a0876ed1-10c5-4bfc-b5c4-c367e3781122",
        project_identifier="d47bbd35-bd13-4698-8eb6-5baf75127835",
        project_name="Cancelled before launch",
        pipeline_identifier="bulk-rnaseq",
        status=RunStatus.CANCELLING,
        command=["nextflow", "run"],
        log_path=str(tmp_path / "project" / "logs" / "run-prelaunch.log"),
        results_directory=str(tmp_path / "project" / "results"),
        created_at=datetime.now(UTC),
        holds_admission=True,
    )
    manager._records[record.job_identifier] = record
    manager._persist(record)

    manager._finish_cancelled_before_launch(record)

    assert manager.read_log(record.job_identifier).text.count("Cancelled at ") == 1


def test_post_popen_persist_failure_stops_process_before_releasing_admission(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    monkeypatch.setattr(runs_module, "TERM_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(runs_module, "KILL_GRACE_SECONDS", 0.1)
    manager = RunManager(SleepingAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    persist = manager._persist
    calls = 0

    def fail_running_persist(record: RunRecord) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected post-Popen persist failure")
        persist(record)

    monkeypatch.setattr(manager, "_persist", fail_running_persist)
    started = manager.start(manifest)

    record = wait_for_terminal(manager, started.job_identifier)
    assert record.status == RunStatus.CANCELLED
    assert record.holds_admission is False
    assert manager._processes == {}


def test_sigkill_escalation_stops_stubborn_descendant_group(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    monkeypatch.setattr(runs_module, "TERM_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(runs_module, "KILL_GRACE_SECONDS", 0.1)
    manager = RunManager(DescendantAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    started = manager.start(manifest)
    wait_for_status(manager, started.job_identifier, RunStatus.RUNNING)

    manager.cancel(started.job_identifier)

    assert wait_for_terminal(manager, started.job_identifier).status == RunStatus.CANCELLED
    assert manager.read_log(started.job_identifier).text.count("Cancelled at ") == 1


def test_container_cleanup_follows_nextflow_execution_profile(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    original_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        return original_popen([sys.executable, "-c", "print('profile-check')"], **kwargs)

    monkeypatch.setattr(runs_module.subprocess, "Popen", fake_popen)
    manager = RunManager(NextflowCommandAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    monkeypatch.setattr(manager, "_cleanup_owned_containers", lambda _job_identifier: True)

    local_manifest = ProjectManifest.model_validate(manifest_payload)
    local_run = manager.start(local_manifest)
    assert local_run.container_cleanup_required is False
    assert local_run.command[0] == "nextflow"
    assert wait_for_terminal(manager, local_run.job_identifier).status == RunStatus.COMPLETED

    docker_payload = dict(manifest_payload)
    docker_payload["execution_profile"] = "docker"
    docker_payload["output_directory"] = str(tmp_path / "docker-project")
    docker_run = manager.start(ProjectManifest.model_validate(docker_payload))
    assert docker_run.container_cleanup_required is True
    assert wait_for_terminal(manager, docker_run.job_identifier).status == RunStatus.COMPLETED


@pytest.mark.parametrize(
    ("pipeline_version", "project_name"),
    [
        ("0.4.0", "ordinary-project"),
        ("0.3.0-full-demo", "synthetic-demo-project"),
    ],
)
def test_bulk_nextflow_runs_from_project_root_when_workflow_is_packaged_read_only(
    tmp_path: Path,
    manifest_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    pipeline_version: str,
    project_name: str,
) -> None:
    packaged_root = tmp_path / "packaged-resources"
    workflow = packaged_root / "workflows" / "bulk_rnaseq"
    workflow.mkdir(parents=True)
    main_nf = workflow / "main.nf"
    main_nf.touch()
    workflow.chmod(0o555)
    packaged_root.chmod(0o555)
    request.addfinalizer(lambda: workflow.chmod(0o755))
    request.addfinalizer(lambda: packaged_root.chmod(0o755))
    monkeypatch.setenv("MISSUS_TOM_RESOURCE_ROOT", str(packaged_root))

    project_root = tmp_path / project_name
    manifest_payload["pipeline_version"] = pipeline_version
    manifest_payload["output_directory"] = str(project_root)
    manifest = ProjectManifest.model_validate(manifest_payload)
    save_project(manifest, history_store=ProjectHistoryStore(tmp_path / "history.sqlite3"))
    adapter = BulkRnaSeqAdapter()
    monkeypatch.setattr(adapter, "validate_execution", lambda *_args, **_kwargs: None)
    original_popen = subprocess.Popen
    captured: dict[str, Any] = {}

    def fake_popen(command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        captured["work_exists"] = Path(command[command.index("-work-dir") + 1]).is_dir()
        create_nextflow_state = (
            "from pathlib import Path; "
            "state = Path('.nextflow'); "
            "state.mkdir(); "
            "(state / 'history.lock').touch()"
        )
        return original_popen([sys.executable, "-c", create_nextflow_state], **kwargs)

    monkeypatch.setattr(runs_module.subprocess, "Popen", fake_popen)
    manager = RunManager(adapter, registry_directory=tmp_path / "state")
    started = manager.start(manifest)

    assert wait_for_terminal(manager, started.job_identifier).status == RunStatus.COMPLETED
    command = captured["command"]
    assert captured["cwd"] == project_root.resolve()
    assert captured["work_exists"] is True
    assert command[command.index("run") + 1] == str(main_nf.resolve())
    assert command[command.index("-work-dir") + 1] == str(project_root / "work")
    assert (project_root / ".nextflow" / "history.lock").is_file()
    assert not (workflow / ".nextflow").exists()


def test_docker_cleanup_failure_holds_admission_and_retry_can_finish(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    monkeypatch.setattr(runs_module, "TERM_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(runs_module, "KILL_GRACE_SECONDS", 0.1)
    manager = RunManager(SleepingAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    started = manager.start(manifest)
    wait_for_status(manager, started.job_identifier, RunStatus.RUNNING)
    with manager._lock:
        manager._records[started.job_identifier].container_cleanup_required = True
    monkeypatch.setattr(
        runs_module.subprocess, "run", Mock(side_effect=OSError("docker unavailable"))
    )

    manager.cancel(started.job_identifier)
    interrupted = wait_for_status(manager, started.job_identifier, RunStatus.INTERRUPTED)
    assert interrupted.holds_admission is True
    for _ in range(100):
        with manager._lock:
            if started.job_identifier not in manager._processes:
                break
        time.sleep(0.01)

    monkeypatch.setattr(
        runs_module.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")),
    )
    manager.cancel(started.job_identifier)
    assert wait_for_terminal(manager, started.job_identifier).status == RunStatus.CANCELLED


def test_stale_process_identity_never_signals_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = RunManager(StubAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    identity = ProcessIdentity(process_id=17, process_group_id=17, start_ticks=1, boot_id="old")
    kill_process_group = Mock()
    monkeypatch.setattr(manager, "_identity_matches", Mock(return_value=False))
    monkeypatch.setattr(runs_module.os, "killpg", kill_process_group)

    assert manager._signal_verified_identity(identity, signal.SIGTERM) is False
    kill_process_group.assert_not_called()


def test_recovered_dead_leader_allows_only_labelled_container_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "state"
    registry.mkdir()
    record = RunRecord(
        job_identifier="965ae2ca-7279-40b8-9b93-ddf5cf31a7d1",
        project_identifier="b6fd9dfd-4393-4bbd-b611-14a30296a2f7",
        project_name="Container-only recovery",
        status=RunStatus.RUNNING,
        command=["nextflow", "run"],
        log_path=str(tmp_path / "project" / "logs" / "run-recovered.log"),
        results_directory=str(tmp_path / "project" / "results"),
        created_at=datetime.now(UTC),
        process_id=777_777,
        process_group_id=777_777,
        process_start_ticks=1,
        process_boot_id="old-boot",
        holds_admission=True,
        container_cleanup_required=True,
    )
    (registry / f"{record.job_identifier}.json").write_text(
        record.model_dump_json(), encoding="utf-8"
    )
    monkeypatch.setattr(
        RunManager,
        "_owned_container_identifiers",
        staticmethod(lambda _job_identifier: ["owned-container"]),
    )
    manager = RunManager(StubAdapter(tmp_path), registry_directory=registry)  # type: ignore[arg-type]
    monkeypatch.setattr(manager, "_identity_matches", Mock(return_value=False))
    monkeypatch.setattr(manager, "_process_group_exists", Mock(return_value=False))
    monkeypatch.setattr(
        manager,
        "_owned_container_identifiers",
        Mock(return_value=[]),
    )
    kill_process_group = Mock()
    monkeypatch.setattr(runs_module.os, "killpg", kill_process_group)

    manager.cancel(record.job_identifier)

    cancelled = wait_for_terminal(manager, record.job_identifier)
    assert cancelled.status == RunStatus.CANCELLED
    assert manager.read_log(record.job_identifier).text.count("Cancelled at ") == 1
    kill_process_group.assert_not_called()


def test_monitor_reason_is_retained_on_controlled_cancellation(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    class PressuredMonitor:
        def __init__(self, _output_directory: Path) -> None:
            return None

        def check(self) -> str:
            return "Sustained host pressure: available RAM below threshold"

    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    monkeypatch.setattr(runs_module, "CHECK_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(runs_module, "TERM_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(runs_module, "KILL_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(runs_module, "ResourceMonitor", PressuredMonitor)
    manager = RunManager(SleepingAdapter(tmp_path), registry_directory=tmp_path / "state")  # type: ignore[arg-type]
    started = manager.start(manifest)

    cancelled = wait_for_terminal(manager, started.job_identifier)
    assert cancelled.status == RunStatus.CANCELLED
    assert "Sustained host pressure" in (cancelled.error_message or "")
