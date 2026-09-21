from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from missus_tom.config import settings
from missus_tom.models.manifest import ProjectManifest, ProjectSaveResult, ProjectValidationResult
from missus_tom.models.preflight import CheckStatus
from missus_tom.models.projects import ProjectSummary
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
ONT_PROJECT_DIRECTORIES = (
    "input_manifest",
    "configuration",
    "work",
    "results/00_manifests",
    "results/config",
    "results/01_alignment",
    "results/02_alignment_qc",
    "results/03_ont_qc_coverage",
    "results/04_methylation",
    "results/05_methylation_exploration",
    "reports",
    "logs",
)
MAX_MANIFEST_BYTES = 8 * 1024 * 1024


def validate_project(
    manifest: ProjectManifest, *, adapter: object | None = None
) -> ProjectValidationResult:
    validate = getattr(adapter, "validate_project", None)
    checks = validate(manifest) if callable(validate) else project_preflight(manifest)
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

    def list_projects(self, *, limit: int = 50) -> list[ProjectSummary]:
        if not self.database_path.is_file():
            return []
        with sqlite3.connect(f"{self.database_path.as_uri()}?mode=ro", uri=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'"
            ).fetchone()
            if not exists:
                return []
            rows = connection.execute(
                "SELECT project_identifier, project_name, manifest_path, updated_at "
                "FROM projects ORDER BY updated_at DESC, project_identifier LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [
            ProjectSummary(
                project_identifier=identifier,
                project_name=name,
                manifest_path=path,
                updated_at=updated,
                available=Path(path).is_file(),
            )
            for identifier, name, path, updated in rows
        ]


def read_project_manifest(path: Path) -> ProjectManifest:
    if path.is_symlink() or not path.is_file():
        raise ValueError("The project manifest must be a regular file")
    with path.open("rb") as handle:
        encoded = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("Project manifests must be smaller than 8 MiB")
    return ProjectManifest.model_validate_json(encoded)


def open_project(
    manifest_path: Path,
    *,
    history_store: ProjectHistoryStore | None = None,
) -> ProjectManifest:
    """Load a saved manifest without rewriting it or requiring mounted inputs."""
    path = manifest_path.expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".json":
        raise ValueError("Choose a saved project_manifest.json file")
    manifest = read_project_manifest(path)
    expected = Path(manifest.output_directory) / "input_manifest" / "project_manifest.json"
    if path != expected.resolve(strict=False):
        raise ValueError(
            "This manifest is not in its saved project output directory. "
            "Open the original input_manifest/project_manifest.json file."
        )
    (history_store or ProjectHistoryStore()).record(manifest, path)
    return manifest


def project_directories(manifest: ProjectManifest) -> tuple[str, ...]:
    return (
        ONT_PROJECT_DIRECTORIES
        if manifest.pipeline_identifier == "ont-analysis"
        else PROJECT_DIRECTORIES
    )


def _validate_layout(project_root: Path, directories: tuple[str, ...]) -> None:
    for relative in directories:
        candidate = project_root
        for part in Path(relative).parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise ValueError(f"Project directories must not be symbolic links: {candidate}")
            if candidate.exists() and not candidate.is_dir():
                raise ValueError(f"A project directory is occupied by a file: {candidate}")


@contextmanager
def _project_save_lock(project_root: Path) -> Iterator[None]:
    logs = project_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(logs / ".active-run.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "This project has an active workflow. Wait for it to stop before saving changes."
            ) from exc
        yield
    finally:
        os.close(descriptor)


def save_project(
    manifest: ProjectManifest,
    *,
    history_store: ProjectHistoryStore | None = None,
    adapter: object | None = None,
) -> ProjectSaveResult:
    validation = validate_project(manifest, adapter=adapter)
    if not validation.valid:
        blocking = [
            check.message for check in validation.checks if check.status == CheckStatus.BLOCKING
        ]
        raise ValueError("Project has blocking validation failures: " + "; ".join(blocking))

    project_directory = Path(manifest.output_directory)
    directories = project_directories(manifest)
    _validate_layout(project_directory, directories)
    project_directory.mkdir(parents=True, exist_ok=True)
    with _project_save_lock(project_directory):
        manifest_path = project_directory / "input_manifest" / "project_manifest.json"
        if manifest_path.exists() or manifest_path.is_symlink():
            existing = read_project_manifest(manifest_path)
            if existing.project_identifier != manifest.project_identifier:
                raise ValueError(
                    "This output folder already belongs to another saved project. "
                    "Open that project or choose a different output folder."
                )
        created: list[str] = []
        for relative in directories:
            destination = project_directory / relative
            destination.mkdir(parents=True, exist_ok=True)
            created.append(str(destination))

        written = _write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
        (history_store or ProjectHistoryStore()).record(manifest, manifest_path)
    return ProjectSaveResult(
        project_directory=str(project_directory),
        manifest_path=str(manifest_path),
        created_directories=created,
        bytes_written=written,
    )
