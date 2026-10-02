"""Request-local progress for read-only project validation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import suppress
from contextvars import ContextVar
from threading import Event
from typing import Any

from missus_tom.models.manifest import ProjectValidationResult
from missus_tom.models.preflight import PreflightCheck

_reporter: ContextVar[Callable[[str], None] | None] = ContextVar(
    "validation_reporter", default=None
)


def report_validation(message: str) -> None:
    reporter = _reporter.get()
    if reporter is not None:
        reporter(message)


class ProgressChecks(list[PreflightCheck]):
    """Report completed checks as the preflight assembles its normal result."""

    def append(self, check: PreflightCheck) -> None:
        super().append(check)
        report_validation(f"{check.label}: {check.status.value} — {check.message}")

    def extend(self, checks: Iterable[PreflightCheck]) -> None:
        if isinstance(checks, ProgressChecks):
            super().extend(checks)
        else:
            for check in checks:
                self.append(check)


class ValidationDisconnected(Exception):
    pass


async def validation_events(
    validate: Callable[[], ProjectValidationResult],
) -> AsyncIterator[dict[str, Any]]:
    loop = asyncio.get_running_loop()
    events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    stopped = Event()

    def emit(event: dict[str, Any]) -> None:
        if stopped.is_set():
            raise ValidationDisconnected()
        loop.call_soon_threadsafe(events.put_nowait, event)

    def run() -> None:
        token = _reporter.set(lambda message: emit({"type": "progress", "message": message}))
        try:
            report_validation("Starting project validation in the local backend.")
            result = validate()
            emit({"type": "result", "result": result.model_dump(mode="json")})
        except ValidationDisconnected:
            pass
        except Exception as exc:
            if not stopped.is_set():
                emit({"type": "error", "message": str(exc) or "Project validation failed."})
        finally:
            _reporter.reset(token)

    task = asyncio.create_task(asyncio.to_thread(run))
    try:
        while True:
            event = await events.get()
            yield event
            if event["type"] in {"result", "error"}:
                break
    finally:
        stopped.set()
        # Blocking reads stop at the next progress checkpoint; never kill shared workers.
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
