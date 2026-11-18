"""Runtime host-pressure sampling for controlled workflow cancellation."""

from __future__ import annotations

import logging
import math
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from missus_tom.services.resources import GIB, HostResources, inspect_host_resources

CHECK_INTERVAL_SECONDS = 5
CONSECUTIVE_UNHEALTHY_SAMPLES = 3
CONSECUTIVE_UNAVAILABLE_SAMPLES = 6
logger = logging.getLogger(__name__)
MIB = 1024**2
MIN_AVAILABLE_MEMORY_BYTES = 512 * MIB
MIN_OUTPUT_FREE_BYTES = GIB

HostInspector = Callable[[], HostResources]
DiskUsageInspector = Callable[[Path], Any]


class ResourceMonitor:
    """Debounce host pressure observations without changing host state."""

    def __init__(
        self,
        output_directory: str | Path,
        *,
        host_inspector: HostInspector = inspect_host_resources,
        disk_usage_inspector: DiskUsageInspector = shutil.disk_usage,
    ) -> None:
        self._output_directory = Path(output_directory)
        self._host_inspector = host_inspector
        self._disk_usage_inspector = disk_usage_inspector
        self._unhealthy_samples = {"memory": 0, "disk": 0}
        self._unavailable_samples = {"memory": 0, "disk": 0}

    def check(self) -> str | None:
        """Return a cancellation reason after sustained known host pressure."""
        reasons, unavailable = self._sample_unhealthy_reasons()
        sustained: list[str] = []
        lost: list[str] = []
        for metric in ("memory", "disk"):
            if metric in unavailable:
                self._unavailable_samples[metric] += 1
                if self._unavailable_samples[metric] == 1:
                    logger.warning("Resource measurement unavailable: %s", metric)
                if self._unavailable_samples[metric] >= CONSECUTIVE_UNAVAILABLE_SAMPLES:
                    lost.append(metric)
                # Only this metric's unavailable observation preserves its pressure history.
                continue
            self._unavailable_samples[metric] = 0
            self._unhealthy_samples[metric] = (
                self._unhealthy_samples[metric] + 1 if reasons[metric] else 0
            )
            if self._unhealthy_samples[metric] >= CONSECUTIVE_UNHEALTHY_SAMPLES:
                sustained.extend(reasons[metric])
        if sustained:
            return "Sustained host pressure: " + "; ".join(sustained)
        if lost:
            return "Resource monitoring unavailable for six consecutive checks: " + "; ".join(lost)
        return None

    def _sample_unhealthy_reasons(self) -> tuple[dict[str, list[str]], list[str]]:
        reasons: dict[str, list[str]] = {"memory": [], "disk": []}
        unavailable: list[str] = []
        try:
            host = self._host_inspector()
        except Exception:
            host = None
        if host is not None:
            reasons["memory"].extend(self._memory_reasons(host))
        if host is None or host.total_memory_bytes is None or host.available_memory_bytes is None:
            unavailable.append("memory")

        try:
            free_bytes = self._disk_usage_inspector(self._output_filesystem_path()).free
        except Exception:
            free_bytes = None
        if free_bytes is not None and free_bytes < MIN_OUTPUT_FREE_BYTES:
            reasons["disk"].append(
                f"output filesystem free space {free_bytes / GIB:.1f} GiB "
                f"is below {MIN_OUTPUT_FREE_BYTES / GIB:.1f} GiB"
            )
        if free_bytes is None:
            unavailable.append("disk")
        return reasons, unavailable

    def _memory_reasons(self, host: HostResources) -> list[str]:
        if host.total_memory_bytes is None or host.available_memory_bytes is None:
            return []
        threshold = max(
            MIN_AVAILABLE_MEMORY_BYTES,
            math.ceil(host.total_memory_bytes * 0.01),
        )
        if host.available_memory_bytes >= threshold:
            return []
        return [
            f"available RAM {host.available_memory_bytes / GIB:.1f} GiB "
            f"is below {threshold / GIB:.1f} GiB"
        ]

    def _output_filesystem_path(self) -> Path:
        path = self._output_directory
        while not path.exists() and path != path.parent:
            path = path.parent
        return path
