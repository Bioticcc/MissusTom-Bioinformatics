from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.run import ResultArtifact, RunLog, RunRecord, RunStatus
from missus_tom.pipeline_adapters.bulk_rnaseq import BulkRnaSeqAdapter

ACTIVE_STATUSES = {RunStatus.QUEUED, RunStatus.PREPARING, RunStatus.RUNNING}


class RunManager:
    """Runs only commands constructed by the controlled pipeline adapter."""

    def __init__(self, adapter: BulkRnaSeqAdapter) -> None:
        self.adapter = adapter
        self._records: dict[str, RunRecord] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    def start(self, manifest: ProjectManifest, *, resume: bool = True) -> RunRecord:
        self.adapter.validate_execution(manifest)
        with self._lock:
            if any(record.status in ACTIVE_STATUSES for record in self._records.values()):
                raise ValueError("another workflow job is active")

            job_identifier = str(uuid4())
            root = Path(manifest.output_directory)
            log_path = root / "logs" / f"run-{job_identifier}.log"
            command = self.adapter.construct_command(manifest)
            if not resume:
                command.remove("-resume")
            record = RunRecord(
                job_identifier=job_identifier,
                project_identifier=str(manifest.project_identifier),
                project_name=manifest.project_name,
                status=RunStatus.QUEUED,
                current_stage="Waiting for local runner",
                command=command,
                log_path=str(log_path),
                results_directory=str(root / "results"),
                created_at=datetime.now(UTC),
                resume=resume,
            )
            self._records[job_identifier] = record
            self._persist(record)
            thread = threading.Thread(
                target=self._run,
                args=(job_identifier,),
                name=f"missus-tom-run-{job_identifier}",
                daemon=True,
            )
            thread.start()
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

    def cancel(self, job_identifier: str) -> RunRecord:
        with self._lock:
            record = self._records.get(job_identifier)
            if record is None:
                raise KeyError("job was not found")
            if record.status not in ACTIVE_STATUSES:
                raise ValueError(f"job is already {record.status.value}")
            record.status = RunStatus.CANCELLED
            record.current_stage = "Cancelled"
            record.finished_at = datetime.now(UTC)
            process = self._processes.get(job_identifier)
            if process is not None and process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
            self._persist(record)
            return record.model_copy(deep=True)

    def cancel_all(self) -> None:
        with self._lock:
            active = [
                identifier
                for identifier, record in self._records.items()
                if record.status in ACTIVE_STATUSES
            ]
        for identifier in active:
            try:
                self.cancel(identifier)
            except (KeyError, ValueError):
                continue

    def read_log(self, job_identifier: str, *, limit: int = 100_000) -> RunLog:
        record = self.get(job_identifier)
        path = Path(record.log_path)
        if not path.is_file():
            return RunLog(job_identifier=job_identifier, text="")
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > limit:
                handle.seek(-limit, os.SEEK_END)
            data = handle.read()
        return RunLog(
            job_identifier=job_identifier,
            text=data.decode("utf-8", errors="replace"),
            truncated=size > limit,
        )

    def artifacts(self, job_identifier: str) -> list[ResultArtifact]:
        record = self.get(job_identifier)
        project_root = Path(record.results_directory).parent.resolve(strict=True)
        roots = {
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
        artifacts: list[ResultArtifact] = []
        for category, root in roots.items():
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_symlink() or not path.is_file():
                    continue
                if path.name == "llms-full.txt":
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
        with self._lock:
            record = self._records[job_identifier]
            if record.status == RunStatus.CANCELLED:
                return
            record.status = RunStatus.PREPARING
            record.current_stage = "Starting Nextflow"
            record.started_at = datetime.now(UTC)
            self._persist(record)
            command = list(record.command)
            log_path = Path(record.log_path)

        log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(log_path.parent, 0o700)
        environment = os.environ.copy()
        environment["NXF_ANSI_LOG"] = "false"
        try:
            descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as log_handle:
                log_handle.write("Missus Tom controlled human demo\n")
                log_handle.write("Command argument array: " + json.dumps(command) + "\n")
                log_handle.flush()
                process = subprocess.Popen(
                    command,
                    cwd=self.adapter.repository_root / "workflows" / "bulk_rnaseq",
                    env=environment,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                with self._lock:
                    self._processes[job_identifier] = process
                    record = self._records[job_identifier]
                    if record.status == RunStatus.CANCELLED:
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        record.status = RunStatus.RUNNING
                        record.current_stage = "Nextflow workflow"
                        self._persist(record)
                exit_code = process.wait()

            with self._lock:
                record = self._records[job_identifier]
                record.exit_code = exit_code
                record.finished_at = record.finished_at or datetime.now(UTC)
                if record.status != RunStatus.CANCELLED:
                    if exit_code == 0:
                        record.status = RunStatus.COMPLETED
                        record.current_stage = "Completed"
                    else:
                        record.status = RunStatus.FAILED
                        record.current_stage = "Failed"
                        record.error_message = f"Nextflow exited with status {exit_code}"
                self._persist(record)
        except (OSError, ValueError) as exc:
            with self._lock:
                record = self._records[job_identifier]
                if record.status != RunStatus.CANCELLED:
                    record.status = RunStatus.FAILED
                    record.current_stage = "Failed to start"
                    record.error_message = str(exc)
                    record.finished_at = datetime.now(UTC)
                    self._persist(record)
        finally:
            with self._lock:
                self._processes.pop(job_identifier, None)

    def _persist(self, record: RunRecord) -> None:
        destination = Path(record.log_path).parent / f"run-{record.job_identifier}.json"
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        encoded = (json.dumps(record.model_dump(mode="json"), indent=2) + "\n").encode()
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
