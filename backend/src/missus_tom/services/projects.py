from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from missus_tom.config import settings
from missus_tom.models.manifest import ProjectManifest, ProjectSaveResult, ProjectValidationResult
from missus_tom.models.preflight import CheckStatus
from missus_tom.services.preflight import project_preflight

PROJECT_DIRECTORIES = (
    "input_manifest",
    "configuration",
    "work",
    "results/qc",
    "results/trimmed",
    "results/counts",
    "results/differential_expression",
    "results/enrichment",
    "results/figures",
    "results/tables",
    "reports",
    "logs",
)


def validate_project(manifest: ProjectManifest) -> ProjectValidationResult:
    checks = project_preflight(manifest)
    valid = not any(check.status == CheckStatus.BLOCKING for check in checks)
    return ProjectValidationResult(valid=valid, manifest=manifest, checks=checks)


def _write_json_atomic(path: Path, payload: dict[str, object]) -> int:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".manifest-", delete=False) as handle:
        temporary_path = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return len(encoded)


class ProjectHistoryStore:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or settings.state_directory / "missus_tom.sqlite3"

    def record(self, manifest: ProjectManifest, manifest_path: Path) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_identifier TEXT PRIMARY KEY,
                    project_name TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO projects(project_identifier, project_name, manifest_path, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(project_identifier) DO UPDATE SET
                    project_name = excluded.project_name,
                    manifest_path = excluded.manifest_path,
                    updated_at = excluded.updated_at
                """,
                (str(manifest.project_identifier), manifest.project_name, str(manifest_path)),
            )


def save_project(
    manifest: ProjectManifest,
    *,
    history_store: ProjectHistoryStore | None = None,
) -> ProjectSaveResult:
    validation = validate_project(manifest)
    if not validation.valid:
        blocking = [
            check.message for check in validation.checks if check.status == CheckStatus.BLOCKING
        ]
        raise ValueError("Project has blocking validation failures: " + "; ".join(blocking))

    project_directory = Path(manifest.output_directory)
    project_directory.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for relative in PROJECT_DIRECTORIES:
        destination = project_directory / relative
        destination.mkdir(parents=True, exist_ok=True)
        created.append(str(destination))

    manifest_path = project_directory / "input_manifest" / "project_manifest.json"
    written = _write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    (history_store or ProjectHistoryStore()).record(manifest, manifest_path)
    return ProjectSaveResult(
        project_directory=str(project_directory),
        manifest_path=str(manifest_path),
        created_directories=created,
        bytes_written=written,
    )
