from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from missus_tom.models.manifest import ProjectManifest
from missus_tom.models.run import RunStatus
from missus_tom.services.runs import RunManager


class StubAdapter:
    def __init__(self, root: Path) -> None:
        self.repository_root = root

    def validate_execution(self, _manifest: ProjectManifest) -> None:
        return None

    def construct_command(self, _manifest: ProjectManifest) -> list[str]:
        return [sys.executable, "-c", "print('controlled-run-ok')"]


def test_run_manager_captures_status_and_log(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest_payload["output_directory"] = str(tmp_path / "project")
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(StubAdapter(tmp_path))  # type: ignore[arg-type]

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
    assert "controlled-run-ok" in manager.read_log(started.job_identifier).text


def test_run_manager_indexes_analysis_categories(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    project_root = tmp_path / "project"
    manifest_payload["output_directory"] = str(project_root)
    manifest = ProjectManifest.model_validate(manifest_payload)
    (tmp_path / "workflows" / "bulk_rnaseq").mkdir(parents=True)
    manager = RunManager(StubAdapter(tmp_path))  # type: ignore[arg-type]
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
