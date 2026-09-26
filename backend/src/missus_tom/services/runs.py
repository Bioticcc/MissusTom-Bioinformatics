from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO, cast
from uuid import uuid4

from pydantic import ValidationError

from missus_tom.config import settings
from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.run import ResultArtifact, RunLog, RunRecord, RunStartStage, RunStatus
from missus_tom.pipeline_adapters.base import PipelineAdapter
from missus_tom.services.bulk_references import BulkReferenceManager, ReferenceCommandRunner
from missus_tom.services.dependencies import runtime_environment
from missus_tom.services.projects import read_project_manifest
from missus_tom.services.resource_monitor import CHECK_INTERVAL_SECONDS, ResourceMonitor

ACTIVE_STATUSES = {
    RunStatus.QUEUED,
    RunStatus.PREPARING,
    RunStatus.RUNNING,
    RunStatus.CANCELLING,
}
TERM_GRACE_SECONDS = 10
KILL_GRACE_SECONDS = 5
DOCKER_COMMAND_TIMEOUT_SECONDS = 8
HEARTBEAT_INTERVAL_SECONDS = 30 * 60


@dataclass(frozen=True)
class ProcessIdentity:
    process_id: int
    process_group_id: int
    start_ticks: int
    boot_id: str


@dataclass
class RunLocks:
    global_descriptor: int
    project_descriptor: int

    def descriptors(self) -> tuple[int, int]:
        return (self.global_descriptor, self.project_descriptor)

    def close(self) -> None:
        for descriptor in self.descriptors():
            with suppress(OSError):
                os.close(descriptor)


class RunManager:
    """Launch, monitor, recover, and stop only controlled adapter commands."""

    def __init__(
        self,
        adapter: object,
        *,
        registry_directory: Path | None = None,
        reference_manager: BulkReferenceManager | None = None,
    ) -> None:
        self.adapter = adapter
        self._using_default_registry = registry_directory is None
        self.registry_directory = registry_directory or settings.state_directory / "runs"
        self._reference_manager = reference_manager
        self._records: dict[str, RunRecord] = {}
        self._preparation_processes: dict[str, subprocess.Popen[str]] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._identities: dict[str, ProcessIdentity] = {}
        self._locks: dict[str, RunLocks] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._watchdogs: dict[str, threading.Thread] = {}
        self._finalizing: set[str] = set()
        self._lock = threading.RLock()
        self._recover_records()

    def _adapter_for(self, manifest: ProjectManifest) -> PipelineAdapter:
        resolver = getattr(self.adapter, "for_manifest", None)
        return cast(PipelineAdapter, resolver(manifest) if callable(resolver) else self.adapter)

    def _adapter_for_record(self, record: RunRecord) -> PipelineAdapter:
        getter = getattr(self.adapter, "get", None)
        return cast(
            PipelineAdapter,
            getter(record.pipeline_identifier) if callable(getter) else self.adapter,
        )

    def start(
        self,
        manifest: ProjectManifest,
        *,
        resume: bool = True,
        start_stage: RunStartStage = RunStartStage.QUANTIFICATION,
    ) -> RunRecord:
        adapter = self._adapter_for(manifest)
        if getattr(adapter, "requires_resume", False) and not resume:
            raise ValueError("this pipeline requires resume-enabled execution")
        adapter.validate_execution(manifest, start_stage=start_stage)
        job_identifier = str(uuid4())
        root = Path(manifest.output_directory)
        command = adapter.construct_command(manifest, start_stage=start_stage)
        self._make_engine_log_unique(command, root, job_identifier)
        if not resume:
            command = [argument for argument in command if argument != "-resume"]
        append_identifier = getattr(adapter, "append_run_identifier", None)
        command = (
            append_identifier(command, job_identifier)
            if callable(append_identifier)
            else [*command, "--run_id", job_identifier]
        )

        with self._lock:
            if self._has_active_admission():
                raise ValueError("another workflow job is active or requires recovery")
            uses_nextflow_sessions = manifest.pipeline_identifier == "bulk-rnaseq"
            is_nextflow_command = bool(command and command[0] == "nextflow")
            nextflow_run_name = (
                f"mt_{job_identifier.replace('-', '')}" if uses_nextflow_sessions else None
            )
            resume_from_run_name = (
                self._resume_source_for(manifest, start_stage)
                if resume and uses_nextflow_sessions
                else None
            )
            if uses_nextflow_sessions and nextflow_run_name:
                self._configure_nextflow_session(
                    command,
                    nextflow_run_name=nextflow_run_name,
                    resume_from_run_name=resume_from_run_name,
                )
            locks = self._acquire_locks(root, job_identifier)
            validator = getattr(adapter, "validate_saved_manifest", None)
            try:
                if callable(validator):
                    validator(manifest)
            except Exception:
                locks.close()
                raise
            record = RunRecord(
                job_identifier=job_identifier,
                project_identifier=str(manifest.project_identifier),
                project_name=manifest.project_name,
                pipeline_identifier=manifest.pipeline_identifier,
                status=RunStatus.QUEUED,
                current_stage="Waiting for local runner",
                command=command,
                log_path=str(root / "logs" / f"run-{job_identifier}.log"),
                results_directory=str(root / "results"),
                created_at=datetime.now(UTC),
                resume=resume,
                nextflow_run_name=nextflow_run_name,
                resume_from_run_name=resume_from_run_name,
                start_stage=start_stage,
                holds_admission=True,
                container_cleanup_required=(
                    is_nextflow_command and manifest.execution_profile.value == "docker"
                ),
            )
            self._records[job_identifier] = record
            self._locks[job_identifier] = locks
            persisted = False
            try:
                self._persist(record)
                persisted = True
                thread = threading.Thread(
                    target=self._run,
                    args=(job_identifier,),
                    name=f"missus-tom-run-{job_identifier}",
                    daemon=False,
                )
                self._threads[job_identifier] = thread
                thread.start()
            except Exception as exc:
                self._threads.pop(job_identifier, None)
                partial_state = (self.registry_directory / f"{job_identifier}.json").is_file()
                if persisted or partial_state:
                    record.status = RunStatus.FAILED
                    record.current_stage = "Failed to schedule local runner"
                    record.error_message = f"The local runner could not be started: {exc}"
                    record.finished_at = datetime.now(UTC)
                    record.holds_admission = False
                    self._persist_safely(record)
                    self._append_terminal_log_marker(record)
                else:
                    self._records.pop(job_identifier, None)
                self._release_locks(job_identifier)
                raise
            return record.model_copy(deep=True)

    def list_runs(self) -> list[RunRecord]:
        with self._lock:
            return [
                record.model_copy(deep=True)
                for record in sorted(
                    self._records.values(), key=lambda item: item.created_at, reverse=True
                )
            ]

    def get(self, job_identifier: str) -> RunRecord:
        with self._lock:
            try:
                return self._records[job_identifier].model_copy(deep=True)
            except KeyError as exc:
                raise KeyError("job was not found") from exc

    def cancel(self, job_identifier: str, *, reason: str | None = None) -> RunRecord:
        """Request cancellation without freeing admission before cleanup completes."""
        with self._lock:
            record = self._records.get(job_identifier)
            if record is None:
                raise KeyError("job was not found")
            if not record.holds_admission:
                raise ValueError(f"job is already {record.status.value}")
            if record.status == RunStatus.CANCELLING:
                return record.model_copy(deep=True)
            was_interrupted = record.status == RunStatus.INTERRUPTED
            record.status = RunStatus.CANCELLING
            record.current_stage = "Stopping controlled workflow process"
            record.error_message = reason
            self._persist_safely(record)
            process = self._processes.get(job_identifier)
            preparation_process = self._preparation_processes.get(job_identifier)
            identity = self._identities.get(job_identifier) or self._identity_from_record(record)

        if preparation_process is not None:
            self._signal_process_group(preparation_process, signal.SIGTERM)
        elif process is not None:
            self._signal_process_group(process, signal.SIGTERM)
        elif identity is not None:
            self._signal_verified_identity(identity, signal.SIGTERM)
        elif was_interrupted:
            self._mark_cleanup_unconfirmed(
                job_identifier,
                "No verified process identity was persisted; manual recovery is required.",
            )
            return self.get(job_identifier)

        if process is not None or identity is not None:
            self._start_cancellation_watchdog(job_identifier, process)
        with self._lock:
            return self._records[job_identifier].model_copy(deep=True)

    def cancel_all(self) -> None:
        with self._lock:
            active = [
                identifier for identifier, record in self._records.items() if record.holds_admission
            ]
        for identifier in active:
            with suppress(KeyError, ValueError):
                self.cancel(identifier)

    def shutdown(self, *, timeout: float = TERM_GRACE_SECONDS + KILL_GRACE_SECONDS + 2) -> None:
        """Stop owned work and wait a bounded period before the backend exits."""
        self.cancel_all()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                threads = [*self._threads.values(), *self._watchdogs.values()]
            pending = False
            for thread in threads:
                if thread is threading.current_thread() or not thread.is_alive():
                    continue
                pending = True
                thread.join(timeout=min(0.2, max(0, deadline - time.monotonic())))
            if not pending:
                return

    def read_log(
        self, job_identifier: str, *, offset: int | None = None, limit: int = 100_000
    ) -> RunLog:
        record = self.get(job_identifier)
        path = Path(record.log_path)
        if not path.is_file():
            return RunLog(job_identifier=job_identifier, text="")
        stat = path.stat()
        size = stat.st_size
        last_output_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        if offset is None:
            with path.open("rb") as handle:
                if size > limit:
                    handle.seek(-limit, os.SEEK_END)
                data = handle.read(limit)
            return RunLog(
                job_identifier=job_identifier,
                text=data.decode("utf-8", errors="replace"),
                truncated=size > limit,
                bytes_available=size,
                last_output_at=last_output_at,
            )
        clamped = min(max(offset, 0), size)
        truncated = offset > size
        with path.open("rb") as handle:
            handle.seek(clamped)
            data = handle.read(limit)
        truncated = truncated or clamped + len(data) < size
        return RunLog(
            job_identifier=job_identifier,
            text=data.decode("utf-8", errors="replace"),
            truncated=truncated,
            next_offset=clamped + len(data),
            bytes_available=size,
            last_output_at=last_output_at,
        )

    def artifacts(self, job_identifier: str) -> list[ResultArtifact]:
        record = self.get(job_identifier)
        project_root = Path(record.results_directory).parent.resolve(strict=True)
        artifact_roots = getattr(self._adapter_for_record(record), "artifact_roots", None)
        roots = (
            artifact_roots(project_root)
            if callable(artifact_roots)
            else {
                "qc": project_root / "results" / "qc",
                "trimmed_reads": project_root / "results" / "trimmed",
                "counts": project_root / "results" / "counts",
                "differential_expression": project_root / "results" / "differential_expression",
                "figures": project_root / "results" / "figures",
                "tables": project_root / "results" / "tables",
                "workflow_reports": project_root / "reports",
                "logs": project_root / "logs",
                "run_manifest": project_root / "input_manifest",
            }
        )
        artifacts: list[ResultArtifact] = []
        for category, root in roots.items():
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_symlink() or not path.is_file() or path.name == "llms-full.txt":
                    continue
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(project_root):
                    continue
                stat = resolved.stat()
                artifacts.append(
                    ResultArtifact(
                        category=category,
                        relative_path=str(resolved.relative_to(project_root)),
                        size_bytes=stat.st_size,
                        modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                    )
                )
                if len(artifacts) >= 5_000:
                    return artifacts
        return artifacts

    def _run(self, job_identifier: str) -> None:
        try:
            with self._lock:
                record = self._records[job_identifier]
                if record.status == RunStatus.CANCELLING:
                    self._finish_cancelled_before_launch(record)
                    return
                record.status = RunStatus.PREPARING
                adapter = self._adapter_for_record(record)
                record.current_stage = "Preparing workflow inputs"
                record.started_at = datetime.now(UTC)
                self._persist(record)
                command = list(record.command)
                log_path = Path(record.log_path)

            try:
                self._prepare_bulk_references_if_needed(job_identifier, adapter)
            except ValueError as exc:
                with self._lock:
                    failed_record = self._records.get(job_identifier)
                    if failed_record is not None and failed_record.status == RunStatus.CANCELLING:
                        self._finish_cancelled_before_launch(failed_record)
                        return
                self._fail_before_completion(job_identifier, str(exc))
                return

            with self._lock:
                record = self._records[job_identifier]
                if record.status == RunStatus.CANCELLING:
                    self._finish_cancelled_before_launch(record)
                    return
                command = list(record.command)
                record.current_stage = "Starting workflow runner"
                self._persist(record)

            log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(log_path.parent, 0o700)
            environment = runtime_environment(record.pipeline_identifier)
            if command and command[0] == "nextflow":
                environment["NXF_ANSI_LOG"] = "false"
                environment["NXF_OPTS"] = self._nxf_options(command)
            descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as log_handle:
                log_handle.write(f"Missus Tom {record.pipeline_identifier} workflow\n")
                log_handle.write("Command argument array: " + json.dumps(command) + "\n")
                log_handle.flush()
                with self._lock:
                    lock_descriptors = self._locks[job_identifier].descriptors()
                    for lock_descriptor in lock_descriptors:
                        os.set_inheritable(lock_descriptor, True)
                working_directory_for = getattr(adapter, "runner_working_directory", None)
                if callable(working_directory_for):
                    project_root = Path(record.results_directory).parent.resolve(strict=True)
                    working_directory = Path(working_directory_for(project_root)).resolve(
                        strict=True
                    )
                else:
                    workflow_directory = getattr(adapter, "workflow_directory", None)
                    if workflow_directory is None:
                        repository_root = getattr(adapter, "repository_root", None)
                        if repository_root is None:
                            raise ValueError("pipeline adapter has no workflow directory")
                        workflow_directory = repository_root / "workflows" / "bulk_rnaseq"
                    working_directory = Path(workflow_directory).resolve(strict=True)
                if not working_directory.is_dir():
                    raise ValueError("pipeline adapter working directory is not a directory")
                process = subprocess.Popen(
                    command,
                    cwd=working_directory,
                    env=environment,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                    pass_fds=lock_descriptors,
                )
                identity = self._read_process_identity(process.pid)
                with self._lock:
                    self._processes[job_identifier] = process
                    record = self._records[job_identifier]
                    record.process_id = process.pid
                    record.process_group_id = process.pid
                    if identity is not None:
                        self._identities[job_identifier] = identity
                        record.process_group_id = identity.process_group_id
                        record.process_start_ticks = identity.start_ticks
                        record.process_boot_id = identity.boot_id
                    record = self._records[job_identifier]
                    if record.status == RunStatus.CANCELLING:
                        self._persist(record)
                        self._signal_process_group(process, signal.SIGTERM)
                        self._start_cancellation_watchdog(job_identifier, process)
                    else:
                        record.status = RunStatus.RUNNING
                        record.current_stage = "Workflow runner"
                        self._persist(record)
                exit_code = self._wait_for_process_with_monitor(job_identifier, process, log_handle)
            self._finish_process(job_identifier, exit_code)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            with self._lock:
                launched_process = self._processes.get(job_identifier)
                launched_record = self._records.get(job_identifier)
                if launched_process is not None and launched_record is not None:
                    launched_record.status = RunStatus.CANCELLING
                    launched_record.current_stage = "Stopping after runner error"
                    launched_record.error_message = str(exc)
                    launched_record.holds_admission = True
                    with suppress(OSError):
                        self._persist(launched_record)
                else:
                    launched_process = None
            if launched_process is None:
                self._fail_before_completion(job_identifier, str(exc))
            else:
                self._signal_process_group(launched_process, signal.SIGTERM)
                self._start_cancellation_watchdog(job_identifier, launched_process)
        finally:
            with self._lock:
                self._processes.pop(job_identifier, None)
                self._threads.pop(job_identifier, None)

    def _finish_process(self, job_identifier: str, exit_code: int) -> None:
        # The wait thread and cancellation watchdog can reap the same process.
        # Only one may inspect/remove its containers and publish the final state.
        with self._lock:
            if job_identifier in self._finalizing:
                return
            self._finalizing.add(job_identifier)
        try:
            self._finalize_process(job_identifier, exit_code)
        finally:
            with self._lock:
                self._finalizing.discard(job_identifier)

    def _finalize_process(self, job_identifier: str, exit_code: int) -> None:
        with self._lock:
            record = self._records[job_identifier]
            if not record.holds_admission:
                return
            record.exit_code = exit_code
            cancelling = record.status == RunStatus.CANCELLING
            process_group_id = record.process_group_id
        if process_group_id is not None and self._process_group_exists(process_group_id):
            with suppress(ProcessLookupError):
                os.killpg(process_group_id, signal.SIGTERM)
            self._wait_for_process_group_exit(process_group_id, TERM_GRACE_SECONDS)
        if process_group_id is not None and self._process_group_exists(process_group_id):
            with suppress(ProcessLookupError):
                os.killpg(process_group_id, signal.SIGKILL)
            if not self._wait_for_process_group_exit(process_group_id, KILL_GRACE_SECONDS):
                self._mark_cleanup_unconfirmed(
                    job_identifier, "process group remained after the cancellation timeout"
                )
                return
        if not self._cleanup_owned_containers(job_identifier):
            self._mark_cleanup_unconfirmed(job_identifier)
            return
        with self._lock:
            record = self._records[job_identifier]
            if not record.holds_admission:
                return
            finished_at = datetime.now(UTC)
            record.finished_at = finished_at
            record.container_cleanup_verified_at = datetime.now(UTC)
            record.holds_admission = False
            if cancelling:
                record.status = RunStatus.CANCELLED
                record.current_stage = "Cancelled"
            elif exit_code == 0:
                record.status = RunStatus.COMPLETED
                record.current_stage = "Completed"
            else:
                record.status = RunStatus.FAILED
                record.current_stage = "Failed"
                record.error_message = f"Workflow runner exited with status {exit_code}"
            self._persist_safely(record)
            self._append_terminal_log_marker(record)
            self._release_locks(job_identifier)

    def _wait_for_process_with_monitor(
        self,
        job_identifier: str,
        process: subprocess.Popen[str],
        log_handle: TextIO,
    ) -> int:
        with self._lock:
            record = self._records[job_identifier]
            monitor = ResourceMonitor(Path(record.results_directory).parent)
            log_path = Path(record.log_path)
        cancellation_requested = False
        next_heartbeat = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS
        while True:
            try:
                return process.wait(timeout=CHECK_INTERVAL_SECONDS)
            except subprocess.TimeoutExpired:
                self._update_runner_stage_from_log(job_identifier, log_path)
                now = time.monotonic()
                if now >= next_heartbeat:
                    self._write_log_line_safely(
                        log_handle,
                        "Heartbeat at "
                        f"{self._format_log_timestamp(datetime.now(UTC))}: "
                        "workflow is still running.\n",
                    )
                    next_heartbeat = now + HEARTBEAT_INTERVAL_SECONDS
                reason = monitor.check()
                if reason is not None and not cancellation_requested:
                    self.cancel(job_identifier, reason=reason)
                    cancellation_requested = True

    def _update_runner_stage_from_log(self, job_identifier: str, path: Path) -> None:
        """Surface a runner-emitted stage path without assigning scientific meaning to it."""
        try:
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - 32_000))
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return
        matches = list(re.finditer(r"(?m)^RUN:\s+bash\s+.*?/stages/([^/\s]+)", text))
        if not matches:
            return
        stage = Path(matches[-1].group(1)).stem
        with self._lock:
            record = self._records.get(job_identifier)
            if record is None or record.status != RunStatus.RUNNING:
                return
            current_stage = f"Runner stage: {stage}"
            if record.current_stage != current_stage:
                record.current_stage = current_stage
                self._persist_safely(record)

    @staticmethod
    def _format_log_timestamp(value: datetime) -> str:
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _write_log_line_safely(handle: TextIO, line: str) -> None:
        with suppress(OSError, ValueError):
            handle.write(line)
            handle.flush()

    @staticmethod
    def _append_log_line_safely(path: Path, line: str) -> None:
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
        except (OSError, ValueError):
            return

    def _append_terminal_log_marker(self, record: RunRecord) -> None:
        """Record one operator-visible marker when this path makes a run terminal."""
        terminal_message = {
            RunStatus.CANCELLED: "Cancelled",
            RunStatus.COMPLETED: "Completed",
            RunStatus.FAILED: "Failed",
        }.get(record.status)
        if terminal_message is None or record.finished_at is None:
            return
        self._append_log_line_safely(
            Path(record.log_path),
            f"{terminal_message} at {self._format_log_timestamp(record.finished_at)}.\n",
        )

    def _finish_cancelled_before_launch(self, record: RunRecord) -> None:
        record.status = RunStatus.CANCELLED
        record.current_stage = "Cancelled before launch"
        record.finished_at = datetime.now(UTC)
        record.holds_admission = False
        self._persist_safely(record)
        self._append_terminal_log_marker(record)
        self._release_locks(record.job_identifier)

    def _prepare_bulk_references_if_needed(
        self, job_identifier: str, adapter: PipelineAdapter
    ) -> None:
        requires = getattr(adapter, "requires_run_reference_preparation", None)
        if not callable(requires):
            return
        project_root = Path(self._records[job_identifier].results_directory).parent
        manifest = read_project_manifest(project_root / "input_manifest" / "project_manifest.json")
        if not requires(manifest):
            return

        with self._lock:
            record = self._records[job_identifier]
            if record.status == RunStatus.CANCELLING:
                return
            record.current_stage = "Preparing references"
            self._persist(record)
            log_path = Path(record.log_path)

        prepare = getattr(adapter, "prepare_run_references", None)
        if not callable(prepare):
            raise ValueError(
                "reference preparation is required but not implemented for this adapter"
            )

        def log_writer(message: str) -> None:
            self._append_log_line_safely(
                log_path,
                f"{self._format_log_timestamp(datetime.now(UTC))} {message}\n",
            )

        execution_manifest, _prepared = prepare(
            manifest,
            job_identifier=job_identifier,
            manager=self._reference_manager,
            log_writer=log_writer,
            command_runner=self._reference_command_runner(
                job_identifier,
                memory_gb=manifest.resource_profile.memory_gb,
            ),
            start_stage=self._records[job_identifier].start_stage,
            cancellation_check=lambda: self._reference_cancel_requested(job_identifier),
        )

        with self._lock:
            record = self._records[job_identifier]
            if record.status == RunStatus.CANCELLING:
                return
            replace_manifest = getattr(adapter, "replace_command_manifest", None)
            if callable(replace_manifest):
                record.command = replace_manifest(record.command, execution_manifest)
            record.execution_manifest_path = str(execution_manifest)
            self._persist(record)

    def _reference_cancel_requested(self, job_identifier: str) -> bool:
        with self._lock:
            record = self._records.get(job_identifier)
            return record is None or record.status == RunStatus.CANCELLING

    def _reference_command_runner(
        self,
        job_identifier: str,
        *,
        memory_gb: float,
    ) -> ReferenceCommandRunner:
        def run(
            command: Sequence[str],
            environment: Mapping[str, str] | None,
        ) -> subprocess.CompletedProcess[str]:
            command_list = list(command)
            with self._lock:
                project_root = Path(self._records[job_identifier].results_directory).parent
            monitor = ResourceMonitor(project_root)
            memory_limit_bytes = int(memory_gb * 1024**3)
            process = subprocess.Popen(
                command_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=dict(environment) if environment is not None else None,
                start_new_session=True,
            )
            with self._lock:
                self._preparation_processes[job_identifier] = process
            term_sent_at: float | None = None
            stop_reason: str | None = None
            next_resource_check = time.monotonic() + CHECK_INTERVAL_SECONDS
            try:
                while True:
                    try:
                        stdout, stderr = process.communicate(timeout=0.2)
                        if stop_reason:
                            stderr = (
                                stderr or ""
                            ).rstrip() + f"\nReference preparation stopped: {stop_reason}\n"
                        return subprocess.CompletedProcess(
                            command_list,
                            process.returncode,
                            stdout,
                            stderr,
                        )
                    except subprocess.TimeoutExpired:
                        now = time.monotonic()
                        if stop_reason is None and self._reference_cancel_requested(job_identifier):
                            stop_reason = "cancellation requested"
                        if stop_reason is None and now >= next_resource_check:
                            pressure_reason = monitor.check()
                            rss_bytes = self._linux_process_rss_bytes(process.pid)
                            if rss_bytes is not None and rss_bytes > memory_limit_bytes:
                                pressure_reason = (
                                    f"Kallisto index memory use {rss_bytes / 1024**3:.1f} GiB "
                                    f"exceeded the configured {memory_gb:.1f} GiB budget"
                                )
                            if pressure_reason:
                                stop_reason = pressure_reason
                            next_resource_check = now + CHECK_INTERVAL_SECONDS
                        if stop_reason is None:
                            continue
                        if term_sent_at is None:
                            self._signal_process_group(process, signal.SIGTERM)
                            term_sent_at = now
                        elif now - term_sent_at >= TERM_GRACE_SECONDS:
                            self._signal_process_group(process, signal.SIGKILL)
            finally:
                with self._lock:
                    self._preparation_processes.pop(job_identifier, None)

        return run

    @staticmethod
    def _linux_process_rss_bytes(process_id: int) -> int | None:
        try:
            for line in Path(f"/proc/{process_id}/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
        return None

    def _fail_before_completion(self, job_identifier: str, message: str) -> None:
        with self._lock:
            record = self._records.get(job_identifier)
            if record is None:
                return
            if record.status == RunStatus.CANCELLING:
                record.status = RunStatus.CANCELLED
                record.current_stage = "Cancelled before launch"
            else:
                record.status = RunStatus.FAILED
                record.current_stage = "Failed to start"
                record.error_message = message
            record.finished_at = datetime.now(UTC)
            record.holds_admission = False
            self._persist_safely(record)
            self._append_terminal_log_marker(record)
            self._release_locks(job_identifier)

    def _enforce_cancellation(
        self, job_identifier: str, known_process: subprocess.Popen[str] | None = None
    ) -> None:
        with self._lock:
            record = self._records.get(job_identifier)
            if record is None or record.status != RunStatus.CANCELLING:
                return
            process = known_process or self._processes.get(job_identifier)
            identity = self._identities.get(job_identifier) or self._identity_from_record(record)
        if process is not None:
            try:
                process.wait(timeout=TERM_GRACE_SECONDS)
                self._finish_process(job_identifier, process.returncode or 0)
                return
            except subprocess.TimeoutExpired:
                self._signal_process_group(process, signal.SIGKILL)
                try:
                    process.wait(timeout=KILL_GRACE_SECONDS)
                    self._finish_process(job_identifier, process.returncode or 0)
                    return
                except subprocess.TimeoutExpired:
                    self._mark_cleanup_unconfirmed(
                        job_identifier, "process group did not exit after SIGKILL"
                    )
                    return
        if identity is None:
            self._mark_cleanup_unconfirmed(
                job_identifier, "no verified process identity is available"
            )
            return
        if self._identity_matches(identity):
            self._signal_verified_identity(identity, signal.SIGTERM)
            if self._wait_for_identity_exit(identity, TERM_GRACE_SECONDS):
                self._finish_recovered_cancellation(job_identifier)
                return
            if self._identity_matches(identity):
                self._signal_verified_identity(identity, signal.SIGKILL)
            if self._wait_for_identity_exit(identity, KILL_GRACE_SECONDS):
                self._finish_recovered_cancellation(job_identifier)
                return
            self._mark_cleanup_unconfirmed(
                job_identifier, "recovered process did not exit after SIGKILL"
            )
            return
        if self._process_group_exists(identity.process_group_id):
            self._mark_cleanup_unconfirmed(
                job_identifier,
                "The recovered leader identity changed while its process group remains active.",
            )
            return
        self._finish_recovered_cancellation(job_identifier)

    def _start_cancellation_watchdog(
        self, job_identifier: str, process: subprocess.Popen[str] | None = None
    ) -> None:
        with self._lock:
            existing = self._watchdogs.get(job_identifier)
            if existing is not None and existing.is_alive():
                return
            watchdog = threading.Thread(
                target=self._enforce_cancellation,
                args=(job_identifier, process),
                name=f"missus-tom-cancel-{job_identifier}",
                daemon=False,
            )
            self._watchdogs[job_identifier] = watchdog
            watchdog.start()

    def _finish_recovered_cancellation(self, job_identifier: str) -> None:
        with self._lock:
            record = self._records.get(job_identifier)
            process_group_id = record.process_group_id if record is not None else None
        if process_group_id is not None and self._process_group_exists(process_group_id):
            self._mark_cleanup_unconfirmed(
                job_identifier,
                "The recovered process group remains active after its leader exited.",
            )
            return
        if self._cleanup_owned_containers(job_identifier):
            with self._lock:
                record = self._records[job_identifier]
                if record.status != RunStatus.CANCELLING:
                    return
                record.status = RunStatus.CANCELLED
                record.current_stage = "Cancelled after recovery"
                record.finished_at = datetime.now(UTC)
                record.holds_admission = False
                record.container_cleanup_verified_at = datetime.now(UTC)
                self._persist_safely(record)
                self._append_terminal_log_marker(record)
                self._release_locks(job_identifier)
        else:
            self._mark_cleanup_unconfirmed(job_identifier)

    def _mark_cleanup_unconfirmed(self, job_identifier: str, message: str | None = None) -> None:
        with self._lock:
            record = self._records.get(job_identifier)
            if record is None:
                return
            record.status = RunStatus.INTERRUPTED
            record.current_stage = "Cleanup could not be confirmed"
            record.error_message = (
                message or "Owned Docker container cleanup could not be confirmed"
            )
            record.holds_admission = True
            self._persist_safely(record)

    def _cleanup_owned_containers(self, job_identifier: str) -> bool:
        with self._lock:
            record = self._records.get(job_identifier)
            if record is None or not record.container_cleanup_required:
                return True
        identifiers = self._owned_container_identifiers(job_identifier)
        if identifiers is None:
            return False
        if identifiers:
            try:
                removed = subprocess.run(
                    ["docker", "rm", "-f", *identifiers],
                    capture_output=True,
                    text=True,
                    timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
            if removed.returncode != 0:
                return False
        return self._owned_container_identifiers(job_identifier) == []

    @staticmethod
    def _owned_container_identifiers(job_identifier: str) -> list[str] | None:
        filter_value = f"label=missus_tom.run_id={job_identifier}"
        try:
            listed = subprocess.run(
                ["docker", "ps", "-aq", "--filter", filter_value],
                capture_output=True,
                text=True,
                timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if listed.returncode != 0:
            return None
        return [value for value in listed.stdout.split() if value]

    def _has_active_admission(self) -> bool:
        return any(record.holds_admission for record in self._records.values())

    def _acquire_locks(self, project_root: Path, job_identifier: str) -> RunLocks:
        global_path = self.registry_directory / ".active-run.lock"
        project_path = project_root / "logs" / ".active-run.lock"
        global_descriptor = self._acquire_lock(global_path, job_identifier)
        try:
            project_descriptor = self._acquire_lock(project_path, job_identifier)
        except Exception:
            with suppress(OSError):
                fcntl.flock(global_descriptor, fcntl.LOCK_UN)
                os.close(global_descriptor)
            raise
        return RunLocks(global_descriptor, project_descriptor)

    @staticmethod
    def _acquire_lock(path: Path, job_identifier: str) -> int:
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
                raise ValueError("another workflow job is active") from exc
            raise

    def _release_locks(self, job_identifier: str) -> None:
        locks = self._locks.pop(job_identifier, None)
        if locks is not None:
            locks.close()

    @staticmethod
    def _make_engine_log_unique(command: list[str], root: Path, job_identifier: str) -> None:
        with suppress(ValueError):
            index = command.index("-log")
            if index + 1 < len(command):
                command[index + 1] = str(root / "logs" / f"nextflow-engine-{job_identifier}.log")

    def _resume_source_for(
        self, manifest: ProjectManifest, start_stage: RunStartStage
    ) -> str | None:
        candidates = [
            record
            for record in self._records.values()
            if record.project_identifier == str(manifest.project_identifier)
            and record.pipeline_identifier == manifest.pipeline_identifier
            and record.status
            in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
        ]
        same_stage = [record for record in candidates if record.start_stage == start_stage]
        for record in sorted(
            same_stage or candidates, key=lambda item: item.created_at, reverse=True
        ):
            # A name is allocated before the worker thread starts.  Failed or
            # cancelled records can therefore contain a name that Nextflow never
            # created (for example if Java failed during bootstrap).  Completed
            # records reached a verified process exit; other terminal records
            # must have a bounded log indication of an actual session.
            if record.status == RunStatus.COMPLETED and record.nextflow_run_name:
                return record.nextflow_run_name
            legacy_name = self._legacy_nextflow_run_name(record)
            if legacy_name:
                return legacy_name
        return None

    @staticmethod
    def _configure_nextflow_session(
        command: list[str], *, nextflow_run_name: str, resume_from_run_name: str | None
    ) -> None:
        with suppress(ValueError):
            command.remove("-resume")
        try:
            insertion_index = command.index("run") + 2
        except ValueError:
            insertion_index = len(command)
        session_arguments = ["-name", nextflow_run_name]
        if resume_from_run_name:
            session_arguments.extend(["-resume", resume_from_run_name])
        command[insertion_index:insertion_index] = session_arguments

    @staticmethod
    def _legacy_nextflow_run_name(record: RunRecord) -> str | None:
        log_paths = [Path(record.log_path)]
        with suppress(ValueError, IndexError):
            log_paths.append(Path(record.command[record.command.index("-log") + 1]))
        log_paths.append(Path(record.log_path).parent / "nextflow-engine.log")
        seen: set[Path] = set()
        for path in log_paths:
            if path in seen:
                continue
            seen.add(path)
            try:
                size = path.stat().st_size
                with path.open("rb") as handle:
                    # Nextflow writes the session name near the start, while a
                    # late session UUID can be useful after a failed launch.
                    # Inspect both without loading an unbounded engine log.
                    head = handle.read(32_000)
                    if size > 200_000:
                        handle.seek(-200_000, os.SEEK_END)
                    tail = handle.read(200_000)
                    text = (head + tail).decode("utf-8", errors="replace")
            except OSError:
                continue
            matches = list(re.finditer(r"Launching .*?\[([A-Za-z0-9_-]+)\]", text))
            if matches:
                return matches[-1].group(1)
            sessions = list(re.finditer(r"Session UUID:\s*([0-9a-fA-F-]{36})", text))
            if sessions:
                return sessions[-1].group(1)
        return None

    @staticmethod
    def _nxf_options(command: list[str]) -> str:
        cpus = 1
        with suppress(ValueError, IndexError):
            cpus = max(1, int(command[command.index("--max_cpus") + 1]))
        return f"-Xms128m -Xmx1g -XX:ActiveProcessorCount={cpus}"

    @staticmethod
    def _read_process_identity(process_id: int) -> ProcessIdentity | None:
        try:
            stat = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
            _before, separator, fields_after_name = stat.rpartition(")")
            if not separator:
                return None
            fields = fields_after_name.split()
            process_group_id = int(fields[2])
            if process_group_id != process_id:
                return None
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
            return ProcessIdentity(process_id, process_group_id, int(fields[19]), boot_id)
        except (OSError, IndexError, ValueError):
            return None

    @classmethod
    def _identity_matches(cls, identity: ProcessIdentity) -> bool:
        current = cls._read_process_identity(identity.process_id)
        return (
            current is not None
            and current.process_group_id == identity.process_group_id
            and current.start_ticks == identity.start_ticks
            and current.boot_id == identity.boot_id
        )

    @staticmethod
    def _identity_from_record(record: RunRecord) -> ProcessIdentity | None:
        process_id = record.process_id
        process_group_id = record.process_group_id
        start_ticks = record.process_start_ticks
        boot_id = record.process_boot_id
        if process_id is None or process_group_id is None or start_ticks is None or boot_id is None:
            return None
        return ProcessIdentity(process_id, process_group_id, start_ticks, boot_id)

    @staticmethod
    def _signal_process_group(process: subprocess.Popen[str], signal_value: signal.Signals) -> None:
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal_value)

    def _signal_verified_identity(
        self, identity: ProcessIdentity, signal_value: signal.Signals
    ) -> bool:
        if not self._identity_matches(identity):
            return False
        with suppress(ProcessLookupError):
            os.killpg(identity.process_group_id, signal_value)
            return True
        return False

    def _wait_for_identity_exit(self, identity: ProcessIdentity, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._identity_matches(identity):
                return True
            time.sleep(0.1)
        return not self._identity_matches(identity)

    def _wait_for_process_group_exit(self, process_group_id: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._process_group_exists(process_group_id):
                return True
            time.sleep(0.1)
        return not self._process_group_exists(process_group_id)

    @staticmethod
    def _process_group_exists(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _current_boot_started_at() -> datetime | None:
        try:
            for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
                label, value = line.split(maxsplit=1)
                if label == "btime":
                    return datetime.fromtimestamp(int(value), UTC)
        except (OSError, ValueError):
            return None
        return None

    def _recovery_paths(self) -> list[Path]:
        registry_paths: set[Path] = set()
        with suppress(OSError):
            registry_paths.update(self.registry_directory.glob("*.json"))
        if not self._using_default_registry:
            return sorted(registry_paths)
        paths = set(registry_paths)
        registered_identifiers = {path.stem for path in registry_paths}
        database_path = settings.state_directory / "missus_tom.sqlite3"
        try:
            with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
                rows = connection.execute("SELECT manifest_path FROM projects").fetchall()
        except sqlite3.Error:
            rows = []
        for (manifest_path,) in rows:
            project_root = Path(manifest_path).parent.parent
            with suppress(OSError):
                paths.update(
                    path
                    for path in (project_root / "logs").glob("run-*.json")
                    if path.stem.removeprefix("run-") not in registered_identifiers
                )
        return sorted(paths)

    def _another_runner_holds_global_lock(self) -> bool:
        path = self.registry_directory / ".active-run.lock"
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except OSError:
            return True
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(descriptor)
            return True
        os.close(descriptor)
        return False

    def _recover_records(self) -> None:
        active_owner_exists = self._another_runner_holds_global_lock()
        for path in self._recovery_paths():
            try:
                record = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError):
                continue
            if record.job_identifier in self._records:
                continue
            if record.holds_admission or record.status in ACTIVE_STATUSES:
                if active_owner_exists:
                    continue
                identity = self._identity_from_record(record)
                containers = (
                    self._owned_container_identifiers(record.job_identifier)
                    if record.container_cleanup_required
                    else []
                )
                boot_started_at = self._current_boot_started_at()
                created_at = record.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                predates_current_boot = bool(
                    identity is None
                    and boot_started_at is not None
                    and created_at < boot_started_at
                    and containers == []
                )
                holds_admission = not predates_current_boot and (
                    identity is None
                    or containers is None
                    or bool(containers)
                    or self._identity_matches(identity)
                    or self._process_group_exists(identity.process_group_id)
                )
                record.status = RunStatus.INTERRUPTED
                record.current_stage = (
                    "Interrupted before current host boot"
                    if predates_current_boot
                    else "Recovered after backend restart"
                )
                record.error_message = (
                    (
                        "This run predates the current host boot, so its local process tree "
                        "cannot still exist. No run-labelled Docker containers were found."
                        if record.container_cleanup_required
                        else "This run predates the current host boot, so its local process "
                        "tree cannot still exist. It has no persisted process identity."
                    )
                    if predates_current_boot
                    else (
                        "A prior runner process may still be active; cancel this job to perform "
                        "verified cleanup."
                        if holds_admission
                        else "Backend restarted before this run reached a terminal state."
                    )
                )
                record.holds_admission = holds_admission
                if predates_current_boot:
                    record.finished_at = record.finished_at or boot_started_at
                if identity is not None and self._identity_matches(identity):
                    self._identities[record.job_identifier] = identity
                self._records[record.job_identifier] = record
                with suppress(OSError):
                    self._persist(record)
            else:
                self._records[record.job_identifier] = record

    def _persist(self, record: RunRecord) -> None:
        encoded = (json.dumps(record.model_dump(mode="json"), indent=2) + "\n").encode()
        project_destination = Path(record.log_path).parent / f"run-{record.job_identifier}.json"
        registry_destination = self.registry_directory / f"{record.job_identifier}.json"
        self._write_atomic(registry_destination, encoded)
        self._write_atomic(project_destination, encoded)

    def _persist_safely(self, record: RunRecord) -> None:
        """Disk failure must never prevent process cleanup or its proven completion."""
        try:
            self._persist(record)
        except OSError as exc:
            warning = f"Run state could not be fully saved: {exc}"
            if warning not in (record.error_message or ""):
                record.error_message = "; ".join(
                    message for message in (record.error_message, warning) if message
                )
            # The project disk may be full while the application registry is healthy.
            with suppress(OSError):
                encoded = (json.dumps(record.model_dump(mode="json"), indent=2) + "\n").encode()
                self._write_atomic(
                    self.registry_directory / f"{record.job_identifier}.json", encoded
                )

    @staticmethod
    def _write_atomic(destination: Path, encoded: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(destination.parent, 0o700)
        descriptor, name = tempfile.mkstemp(prefix=".run-state-", dir=destination.parent)
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
