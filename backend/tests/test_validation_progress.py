from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from missus_tom.main import app
from missus_tom.models.manifest import ProjectManifest, ProjectValidationResult
from missus_tom.services import preflight
from missus_tom.services.validation_progress import report_validation, validation_events

pytestmark = pytest.mark.anyio


async def test_stream_matches_normal_validation(
    manifest_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = ProjectManifest.model_validate(manifest_payload)
    resources = preflight.execution_resource_checks(manifest)
    disk = preflight.inspect_storage(Path(manifest.output_directory).parent)
    monkeypatch.setattr(preflight, "execution_resource_checks", lambda _: resources)
    monkeypatch.setattr(preflight, "inspect_storage", lambda _: disk)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        normal = await client.post("/api/v1/projects/validate", json=manifest_payload)
        streamed = await client.post("/api/v1/projects/validate/stream", json=manifest_payload)
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in streamed.text.splitlines()]
    assert events[-1] == {"type": "result", "result": normal.json()["data"]}
    assert any("Input directory:" in event.get("message", "") for event in events[:-1])


async def test_progress_arrives_before_validation_finishes(
    manifest_payload: dict[str, Any],
) -> None:
    release = Event()
    manifest = ProjectManifest.model_validate(manifest_payload)

    def validate() -> ProjectValidationResult:
        report_validation("Reading annotation")
        assert release.wait(3)
        return ProjectValidationResult(valid=True, manifest=manifest, checks=[])

    events = validation_events(validate)
    try:
        assert (await anext(events))["type"] == "progress"
        assert (await asyncio.wait_for(anext(events), 2))["message"] == "Reading annotation"
        release.set()
        assert (await anext(events))["type"] == "result"
    finally:
        release.set()
        await events.aclose()


async def test_validation_exception_is_terminal_event() -> None:
    def validate() -> ProjectValidationResult:
        raise ValueError("Annotation is unreadable")

    events = [event async for event in validation_events(validate)]
    assert events[-1] == {"type": "error", "message": "Annotation is unreadable"}


async def test_disconnect_stops_worker_at_next_checkpoint() -> None:
    release = Event()
    finished = Event()
    reached_past_checkpoint = Event()

    def validate() -> ProjectValidationResult:
        try:
            report_validation("Reading annotation")
            assert release.wait(3)
            report_validation("Next checkpoint")
            reached_past_checkpoint.set()
            raise AssertionError("Disconnected work continued")
        finally:
            finished.set()

    events = validation_events(validate)
    await anext(events)
    await anext(events)
    await events.aclose()
    release.set()
    assert await asyncio.to_thread(finished.wait, 3)
    assert not reached_past_checkpoint.is_set()


async def test_concurrent_progress_is_request_local(manifest_payload: dict[str, Any]) -> None:
    manifest = ProjectManifest.model_validate(manifest_payload)

    async def collect(label: str) -> list[dict[str, Any]]:
        def validate() -> ProjectValidationResult:
            report_validation(label)
            return ProjectValidationResult(valid=True, manifest=manifest, checks=[])

        return [event async for event in validation_events(validate)]

    first, second = await asyncio.gather(collect("first"), collect("second"))
    assert [event.get("message") for event in first][1] == "first"
    assert [event.get("message") for event in second][1] == "second"
