"""Small in-process diagnostics for the local desktop backend.

This intentionally records request metadata only: never request bodies, paths
to biological inputs, or environment values.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4


class BackendObservability:
    def __init__(self) -> None:
        self._lock = RLock()
        self._active_operations: dict[str, dict[str, str]] = {}
        self._recent_requests: deque[dict[str, Any]] = deque(maxlen=20)
        self._last_health_response: str | None = None

    def begin_operation(self, operation: str) -> str:
        token = str(uuid4())
        with self._lock:
            self._active_operations[token] = {
                "operation": operation,
                "started_at": datetime.now(UTC).isoformat(),
                "started_monotonic": str(monotonic()),
            }
        return token

    def finish_operation(self, token: str) -> None:
        with self._lock:
            operation = self._active_operations.pop(token, None)
            if operation is not None:
                self._recent_requests.append(
                    {
                        "path": f"operation:{operation['operation']}",
                        "status_code": 200,
                        "duration_ms": round(
                            (monotonic() - float(operation["started_monotonic"])) * 1000, 1
                        ),
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                )

    def record_request(self, path: str, status_code: int, elapsed_ms: float) -> None:
        item = {
            "path": path,
            "status_code": status_code,
            "duration_ms": round(elapsed_ms, 1),
            "completed_at": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            self._recent_requests.append(item)
            if path == "/health" and 200 <= status_code < 300:
                self._last_health_response = str(item["completed_at"])

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = [
                {
                    "operation": operation["operation"],
                    "started_at": operation["started_at"],
                    "elapsed_ms": round(
                        (monotonic() - float(operation["started_monotonic"])) * 1000, 1
                    ),
                }
                for operation in self._active_operations.values()
            ]
            return {
                "active_operations": active,
                "last_successful_health_response": self._last_health_response,
                "recent_requests": list(self._recent_requests),
                "slow_requests": [
                    item for item in self._recent_requests if item["duration_ms"] >= 1000
                ],
            }


backend_observability = BackendObservability()


def request_timer() -> float:
    return monotonic()
