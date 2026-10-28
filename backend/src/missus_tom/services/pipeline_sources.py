"""Allowlisted, immutable custom workflow-source revisions."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from datetime import UTC, datetime
from difflib import unified_diff
from pathlib import Path
from typing import cast

from missus_tom.config import settings
from missus_tom.models.pipeline_sources import (
    PipelineDifference,
    PipelineRevision,
    PipelineSourceContent,
    PipelineSourceFile,
    PipelineSourceStatus,
)

_PIPELINES = {
    "bulk-rnaseq": ("Bulk RNA-seq", "bulk_rnaseq"),
    "ont-analysis": ("ONT Analysis", "ont_analysis"),
}
_EXTENSIONS = {
    ".nf": "nextflow",
    ".py": "python",
    ".R": "r",
    ".sh": "shell",
    ".config": "config",
    ".md": "markdown",
}
_NAMED_SOURCES = {"run_with_timeout": "shell"}
_MAX_SOURCE_BYTES = 2_000_000


class PipelineSourceService:
    def official_root(self, pipeline_identifier: str) -> Path:
        try:
            _, directory = _PIPELINES[pipeline_identifier]
        except KeyError as exc:
            raise ValueError("unsupported pipeline identifier") from exc
        root = (settings.resource_root / "workflows" / directory).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("official workflow source is unavailable")
        return root

    def _pipeline_root(self, pipeline_identifier: str) -> Path:
        if pipeline_identifier not in _PIPELINES:
            raise ValueError("unsupported pipeline identifier")
        return settings.state_directory / "custom-pipelines" / pipeline_identifier

    def _active_path(self, pipeline_identifier: str) -> Path:
        return self._pipeline_root(pipeline_identifier) / "active.json"

    def _read_active(self, pipeline_identifier: str) -> str | None:
        path = self._active_path(pipeline_identifier)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            value = payload.get("revision_id")
            if not isinstance(value, str) or not value:
                raise ValueError
            # Reject an unsafe value here too, before any caller can treat this
            # activation as if no custom workflow had been selected.
            if "/" in value or "\\" in value or ".." in value:
                raise ValueError
            return value
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(
                "custom pipeline activation is invalid; restore or select a valid custom revision"
            ) from exc

    def _revision_root(self, pipeline_identifier: str, revision_id: str) -> Path:
        if not revision_id or "/" in revision_id or "\\" in revision_id or ".." in revision_id:
            raise ValueError("invalid pipeline revision")
        root = self._pipeline_root(pipeline_identifier) / "revisions" / revision_id
        if not root.is_dir():
            raise ValueError("custom pipeline revision is unavailable")
        return root.resolve(strict=True)

    @staticmethod
    def _sha(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _relative(self, root: Path, value: str) -> Path:
        if not value or value.startswith("/") or "\\" in value:
            raise ValueError("invalid pipeline source path")
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid pipeline source path")
        try:
            resolved = (root / relative).resolve(strict=True)
        except OSError as exc:
            raise ValueError("pipeline source path is not allowed") from exc
        if (
            not resolved.is_relative_to(root.resolve(strict=True))
            or not resolved.is_file()
            or resolved.is_symlink()
        ):
            raise ValueError("pipeline source path is not allowed")
        if relative.as_posix() not in {item.path for item in self._files(root)}:
            raise ValueError("pipeline source path is not an editable workflow file")
        return relative

    def _files(self, root: Path) -> list[PipelineSourceFile]:
        files: list[PipelineSourceFile] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink() or path.name.startswith("."):
                continue
            suffix = path.suffix
            language = _EXTENSIONS.get(suffix) or _NAMED_SOURCES.get(path.name)
            if language is None or path.stat().st_size > _MAX_SOURCE_BYTES:
                continue
            relative = path.relative_to(root).as_posix()
            payload = path.read_bytes()
            try:
                payload.decode("utf-8")
            except UnicodeDecodeError:
                continue
            files.append(
                PipelineSourceFile(
                    path=relative,
                    language=language,
                    size_bytes=len(payload),
                    checksum=self._sha(payload),
                )
            )
        return sorted(files, key=lambda item: (item.path != "START_HERE.md", item.path))

    def _files_with_guide(self, pipeline_identifier: str, root: Path) -> list[PipelineSourceFile]:
        files = self._files(root)
        if any(item.path == "START_HERE.md" for item in files):
            return files
        guide = next(
            (
                item
                for item in self._files(self.official_root(pipeline_identifier))
                if item.path == "START_HERE.md"
            ),
            None,
        )
        if guide is None:
            return files
        return [guide, *files]

    def _metadata(self, revision_root: Path) -> dict[str, object]:
        try:
            payload = json.loads((revision_root / "revision.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("custom pipeline revision metadata is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("custom pipeline revision metadata is invalid")
        return cast(dict[str, object], payload)

    def status(self, pipeline_identifier: str) -> PipelineSourceStatus:
        display_name, _ = _PIPELINES.get(pipeline_identifier, (None, None))
        if display_name is None:
            raise ValueError("unsupported pipeline identifier")
        active = self._read_active(pipeline_identifier)
        root = self.official_root(pipeline_identifier)
        if active:
            try:
                revision_root = self._revision_root(pipeline_identifier, active)
                metadata = self._metadata(revision_root)
                return PipelineSourceStatus(
                    pipeline_identifier=pipeline_identifier,
                    display_name=display_name,
                    source_type="custom",
                    active_revision_id=active,
                    revision_id=active,
                    source_version=str(metadata.get("source_version", settings.app_version)),
                    files=self._files_with_guide(pipeline_identifier, revision_root),
                )
            except ValueError:
                # Never fall through to official execution for a declared custom revision.
                return PipelineSourceStatus(
                    pipeline_identifier=pipeline_identifier,
                    display_name=display_name,
                    source_type="custom-unavailable",
                    active_revision_id=active,
                    source_version=settings.app_version,
                    files=[],
                )
        return PipelineSourceStatus(
            pipeline_identifier=pipeline_identifier,
            display_name=display_name,
            source_type="official",
            source_version=settings.app_version,
            files=self._files_with_guide(pipeline_identifier, root),
        )

    def resolve_active_root(self, pipeline_identifier: str) -> tuple[Path, str, str | None]:
        active = self._read_active(pipeline_identifier)
        if active:
            return self._revision_root(pipeline_identifier, active), "custom", active
        return self.official_root(pipeline_identifier), "official", None

    def read(
        self, pipeline_identifier: str, path: str, revision_id: str | None = None
    ) -> PipelineSourceContent:
        root, source_type, active = (
            self.resolve_active_root(pipeline_identifier)
            if revision_id is None
            else (self._revision_root(pipeline_identifier, revision_id), "custom", revision_id)
        )
        try:
            relative = self._relative(root, path)
        except ValueError:
            if source_type != "custom" or path != "START_HERE.md":
                raise
            root = self.official_root(pipeline_identifier)
            relative = self._relative(root, path)
        data = (root / relative).read_bytes()
        if len(data) > _MAX_SOURCE_BYTES:
            raise ValueError("pipeline source file is too large")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("pipeline source file is not UTF-8 text") from exc
        return PipelineSourceContent(
            pipeline_identifier=pipeline_identifier,
            path=relative.as_posix(),
            content=content,
            checksum=self._sha(data),
            source_type=source_type,
            revision_id=active,
        )

    def save(
        self, pipeline_identifier: str, path: str, content: str, expected_revision_id: str | None
    ) -> PipelineRevision:
        if len(content.encode("utf-8")) > _MAX_SOURCE_BYTES:
            raise ValueError("pipeline source file is too large")
        active = self._read_active(pipeline_identifier)
        if expected_revision_id != active:
            raise ValueError("custom pipeline changed; reload before saving")
        source_root = (
            self._revision_root(pipeline_identifier, active)
            if active
            else self.official_root(pipeline_identifier)
        )
        try:
            relative = self._relative(source_root, path)
        except ValueError:
            if not active or path != "START_HERE.md":
                raise
            relative = self._relative(self.official_root(pipeline_identifier), path)
        if relative.name == "Output_Log_Key.md":
            raise ValueError("Output_Log_Key.md is read-only reference documentation")
        destination_parent = self._pipeline_root(pipeline_identifier) / "revisions"
        destination_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        revision_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        temporary = Path(tempfile.mkdtemp(prefix=f".{revision_id}-", dir=destination_parent))
        revision_root = destination_parent / revision_id
        try:
            shutil.copytree(source_root, temporary / "source", symlinks=False, dirs_exist_ok=True)
            target = temporary / "source" / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_text(content, encoding="utf-8", newline="")
            official_target = self.official_root(pipeline_identifier) / relative
            source_target = source_root / relative
            mode_source = official_target if official_target.is_file() else source_target
            executable = mode_source.is_file() and bool(
                stat.S_IMODE(mode_source.stat().st_mode)
                & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            )
            os.chmod(target, 0o700 if executable else 0o600)
            files = self._files_with_guide(pipeline_identifier, temporary / "source")
            metadata = {
                "revision_id": revision_id,
                "pipeline_identifier": pipeline_identifier,
                "source_version": settings.app_version,
                "created_at": datetime.now(UTC).isoformat(),
                "files": [item.model_dump() for item in files],
            }
            (temporary / "source" / "revision.json").write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(temporary / "source", revision_root)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return PipelineRevision(
            revision_id=revision_id,
            pipeline_identifier=pipeline_identifier,
            created_at=datetime.now(UTC),
            source_version=settings.app_version,
            files=self._files_with_guide(pipeline_identifier, revision_root),
            active=False,
        )

    def activate(self, pipeline_identifier: str, revision_id: str) -> PipelineSourceStatus:
        revision_root = self._revision_root(pipeline_identifier, revision_id)
        self._metadata(revision_root)
        active = self._active_path(pipeline_identifier)
        active.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".active-", dir=active.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"revision_id": revision_id}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, active)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return self.status(pipeline_identifier)

    def restore(self, pipeline_identifier: str) -> PipelineSourceStatus:
        active = self._active_path(pipeline_identifier)
        if active.exists():
            active.unlink()
        return self.status(pipeline_identifier)

    def difference(
        self, pipeline_identifier: str, path: str, revision_id: str | None = None
    ) -> PipelineDifference:
        custom = self.read(pipeline_identifier, path, revision_id)
        official_root = self.official_root(pipeline_identifier)
        relative = self._relative(official_root, path)
        official = (official_root / relative).read_text(encoding="utf-8")
        return PipelineDifference(
            path=relative.as_posix(),
            diff="".join(
                unified_diff(
                    official.splitlines(keepends=True),
                    custom.content.splitlines(keepends=True),
                    fromfile="official",
                    tofile="custom",
                )
            ),
        )


pipeline_sources = PipelineSourceService()
