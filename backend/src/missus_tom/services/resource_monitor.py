"""Runtime host-pressure sampling for controlled workflow cancellation."""

from __future__ import annotations

import math
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from missus_tom.services.resources import GIB, HostResources, inspect_host_resources

CHECK_INTERVAL_SECONDS = 5
CONSECUTIVE_UNHEALTHY_SAMPLES = 3
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
        self._unhealthy_samples = 0

    def check(self) -> str | None:
        """Return a cancellation reason after sustained known host pressure."""
        reasons = self._sample_unhealthy_reasons()
        if not reasons:
            self._unhealthy_samples = 0
            return None

        self._unhealthy_samples += 1
        if self._unhealthy_samples < CONSECUTIVE_UNHEALTHY_SAMPLES:
            return None
        return "Sustained host pressure: " + "; ".join(reasons)

    def _sample_unhealthy_reasons(self) -> list[str]:
        reasons: list[str] = []
        try:
            host = self._host_inspector()
        except Exception:
            host = None
        if host is not None:
            reasons.extend(self._memory_reasons(host))

        try:
            free_bytes = self._disk_usage_inspector(self._output_filesystem_path()).free
        except Exception:
            free_bytes = None
        if free_bytes is not None and free_bytes < MIN_OUTPUT_FREE_BYTES:
            reasons.append(
                f"output filesystem free space {free_bytes / GIB:.1f} GiB "
                f"is below {MIN_OUTPUT_FREE_BYTES / GIB:.1f} GiB"
            )
        return reasons

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
