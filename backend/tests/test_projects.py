from __future__ import annotations

import asyncio
import fcntl
import os
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from missus_tom.api import routes
from missus_tom.main import app
from missus_tom.models.manifest import ProjectManifest
from missus_tom.services.projects import ProjectHistoryStore, open_project, save_project


def test_history_lists_saved_projects_and_missing_files(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    store = ProjectHistoryStore(tmp_path / "history.sqlite3")
    assert store.list_projects() == []
    assert not store.database_path.exists()
    manifest = ProjectManifest.model_validate(manifest_payload)
    saved = save_project(manifest, history_store=store)
    assert store.list_projects()[0].available is True
    Path(saved.manifest_path).unlink()
    assert store.list_projects()[0].available is False


def test_open_preserves_manifest_and_handles_missing_inputs(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    store = ProjectHistoryStore(tmp_path / "history.sqlite3")
    manifest = ProjectManifest.model_validate(manifest_payload)
    saved = save_project(manifest, history_store=store)
    path = Path(saved.manifest_path)
    before = path.read_bytes(), path.stat().st_mtime_ns
    Path(manifest.samples[0].r1_files[0]).unlink()
    assert open_project(path, history_store=store) == manifest
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_open_rejects_moved_or_oversized_manifest(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    path = tmp_path / "copy.json"
    manifest = ProjectManifest.model_validate(manifest_payload)
    path.write_text(manifest.model_dump_json())
    with pytest.raises(ValueError, match="saved project output directory"):
        open_project(path)
    with path.open("wb") as handle:
        handle.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="8 MiB"):
        open_project(path)


def test_save_cannot_replace_another_project_identity(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    store = ProjectHistoryStore(tmp_path / "history.sqlite3")
    manifest = ProjectManifest.model_validate(manifest_payload)
    saved = save_project(manifest, history_store=store)
    path = Path(saved.manifest_path)
    before = path.read_bytes()
    manifest.project_identifier = uuid4()
    with pytest.raises(ValueError, match="another saved project"):
        save_project(manifest, history_store=store)
    assert path.read_bytes() == before


def test_save_does_not_change_active_project_manifest(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    store = ProjectHistoryStore(tmp_path / "history.sqlite3")
    manifest = ProjectManifest.model_validate(manifest_payload)
    saved = save_project(manifest, history_store=store)
    path = Path(saved.manifest_path)
    before = path.read_bytes()
    lock_path = Path(manifest.output_directory) / "logs/.active-run.lock"
    descriptor = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest.project_name = "Changed during execution"
        with pytest.raises(ValueError, match="active workflow"):
            save_project(manifest, history_store=store)
        assert path.read_bytes() == before
    finally:
        os.close(descriptor)
    save_project(manifest, history_store=store)
    assert path.read_bytes() != before


def test_save_rejects_symlinked_project_directories(
    tmp_path: Path, manifest_payload: dict[str, Any]
) -> None:
    manifest = ProjectManifest.model_validate(manifest_payload)
    root = Path(manifest.output_directory)
    root.mkdir()
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (root / "input_manifest").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic links"):
        save_project(manifest, history_store=ProjectHistoryStore(tmp_path / "history.sqlite3"))
    assert list(outside.iterdir()) == []


@pytest.mark.anyio
async def test_project_history_and_open_api(
    tmp_path: Path, manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path / "state"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/projects")).json()["data"] == []
        saved = await client.post("/api/v1/projects/save", json=manifest_payload)
        path = saved.json()["data"]["manifest_path"]
        recent = (await client.get("/api/v1/projects")).json()["data"]
        assert recent[0]["manifest_path"] == path
        Path(manifest_payload["samples"][0]["r1_files"][0]).unlink()
        opened = await client.post("/api/v1/projects/open", json={"manifest_path": path})
        assert opened.status_code == 200
        result = opened.json()["data"]
        assert result["manifest"]["project_identifier"] == manifest_payload["project_identifier"]
        assert result["validation"]["valid"] is False
        assert result["plan"]["execution_enabled"] is False
        assert result["plan"]["warnings"]
        missing = await client.post(
            "/api/v1/projects/open", json={"manifest_path": str(tmp_path / "missing.json")}
        )
        assert missing.status_code == 404
        relative = await client.post("/api/v1/projects/open", json={"manifest_path": "x.json"})
        assert relative.status_code == 422


@pytest.mark.anyio
async def test_slow_filesystem_request_does_not_block_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    original = routes.discover_fastqs

    def slow_discovery(directory: str, recursive: bool) -> Any:
        entered.set()
        release.wait(timeout=3)
        return original(directory, recursive)

    monkeypatch.setattr(routes, "discover_fastqs", slow_discovery)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        discovery = asyncio.create_task(
            client.post("/api/v1/fastq/discover", json={"directory": str(tmp_path)})
        )
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            response = await asyncio.wait_for(client.get("/health"), timeout=1)
            assert response.status_code == 200
            assert not discovery.done()
        finally:
            release.set()
            await discovery
