"""Bounded, read-only forwarding of output from submitted Nextflow tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

TASK_LINE = re.compile(r"\[([0-9a-f]{2})/([0-9a-f]{6,})\]\s+Submitted process >\s+([^\r\n]+)")
MAX_LOG_SCAN_BYTES = 128 * 1024
MAX_TASK_STREAM_BYTES = 64 * 1024
MAX_TRACKED_TASKS = 64


@dataclass
class _Task:
    label: str
    prefix: str
    suffix: str
    directory: Path | None = None
    offsets: dict[str, int] = field(default_factory=lambda: {"out": 0, "err": 0})
    truncated: set[str] = field(default_factory=set)


class NextflowTaskOutput:
    """Read only tasks named by the current run's Nextflow submission lines."""

    def __init__(self, work_root: Path) -> None:
        self.work_root = work_root
        self.log_offset = 0
        self.pending_line = ""
        self.tasks: dict[tuple[str, str], _Task] = {}

    def pump(self, run_log: Path, destination: TextIO) -> str | None:
        latest_task = self._discover(run_log)
        for key, task in list(self.tasks.items()):
            directory = self._task_directory(task)
            if directory is None:
                continue
            for stream in ("out", "err"):
                self._forward_stream(task, stream, destination)
            if (directory / ".exitcode").is_file():
                self.tasks.pop(key, None)
        return latest_task

    def _discover(self, run_log: Path) -> str | None:
        try:
            with run_log.open("rb") as handle:
                handle.seek(self.log_offset)
                data = handle.read(MAX_LOG_SCAN_BYTES)
        except OSError:
            return None
        self.log_offset += len(data)
        if not data:
            return None
        lines = (self.pending_line + data.decode("utf-8", errors="replace")).splitlines(
            keepends=True
        )
        self.pending_line = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            self.pending_line = lines.pop()[-4096:]
        latest_task = None
        for line in lines:
            match = TASK_LINE.search(line)
            if match is None or len(self.tasks) >= MAX_TRACKED_TASKS:
                continue
            prefix, suffix, label = match.groups()
            if (prefix, suffix) not in self.tasks:
                latest_task = label[:120]
                self.tasks[(prefix, suffix)] = _Task(latest_task, prefix, suffix)
        return latest_task

    def _task_directory(self, task: _Task) -> Path | None:
        if task.directory is not None:
            return task.directory
        try:
            root = self.work_root.resolve(strict=True)
            parent = self.work_root / task.prefix
            matches = [path for path in parent.glob(f"{task.suffix}*") if path.is_dir()]
            if len(matches) != 1:
                return None
            resolved = matches[0].resolve(strict=True)
            if not resolved.is_relative_to(root):
                return None
        except OSError:
            return None
        task.directory = resolved
        return resolved

    def _forward_stream(self, task: _Task, stream: str, destination: TextIO) -> None:
        assert task.directory is not None
        path = task.directory / f".command.{stream}"
        try:
            if path.is_symlink() or not path.is_file():
                return
            offset = task.offsets[stream]
            remaining = MAX_TASK_STREAM_BYTES - offset
            if remaining <= 0:
                return
            with path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read(min(remaining, MAX_LOG_SCAN_BYTES))
                has_more = handle.read(1) != b""
        except OSError:
            return
        if data:
            task.offsets[stream] += len(data)
            text = data.decode("utf-8", errors="replace")
            destination.write(f"[Task {stream}: {task.label}]\n{text}")
            if not text.endswith("\n"):
                destination.write("\n")
            destination.flush()
        if (
            has_more
            and task.offsets[stream] >= MAX_TASK_STREAM_BYTES
            and stream not in task.truncated
        ):
            task.truncated.add(stream)
            destination.write(
                f"[Missus Tom lifecycle] Task {stream} preview limit reached: {task.label}\n"
            )
            destination.flush()
