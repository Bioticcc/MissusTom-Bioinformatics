from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

from missus_tom import __version__

DEVELOPMENT_BUILD_REVISION = "development"
MANIFEST_SCHEMA_VERSIONS: tuple[str, ...] = ("1.0.0", "1.1.0")
BULK_PIPELINE_VERSIONS: tuple[str, ...] = ("0.5.0",)


def read_build_revision() -> str:
    injected = os.getenv("MISSUS_TOM_BUILD_REVISION", "").strip()
    if injected:
        return injected
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        packaged = Path(frozen_root) / "resources" / "build_revision.txt"
        try:
            value = packaged.read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        if value:
            return value
    return DEVELOPMENT_BUILD_REVISION


@dataclass(frozen=True)
class Settings:
    app_name: str = "Missus Tom"
    app_version: str = __version__
    api_prefix: str = "/api/v1"

    @property
    def build_revision(self) -> str:
        return read_build_revision()

    @property
    def manifest_schema_versions(self) -> tuple[str, ...]:
        return MANIFEST_SCHEMA_VERSIONS

    @property
    def bulk_pipeline_versions(self) -> tuple[str, ...]:
        return BULK_PIPELINE_VERSIONS

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "bulk_fasta_gtf_reference_preparation": True,
            "bulk_managed_kallisto_index": True,
            "bulk_legacy_biomart_execution": False,
        }

    @property
    def execution_enabled(self) -> bool:
        return os.getenv("MISSUS_TOM_EXECUTION_ENABLED", "1").strip().lower() in {
            "1",
            "true",
            "yes",
        }

    @property
    def execution_root(self) -> Path | None:
        configured = os.getenv("MISSUS_TOM_EXECUTION_ROOT")
        return Path(configured).expanduser().resolve(strict=False) if configured else None

    @property
    def resource_root(self) -> Path:
        """Return the source tree or PyInstaller resource directory."""
        configured = os.getenv("MISSUS_TOM_RESOURCE_ROOT")
        if configured:
            return Path(configured).expanduser().resolve(strict=False)
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            return (Path(frozen_root) / "resources").resolve(strict=False)
        return Path(__file__).resolve().parents[3]

    @property
    def ont_runner(self) -> Path | None:
        configured = os.getenv("MISSUS_TOM_ONT_RUNNER")
        return Path(configured).expanduser().resolve(strict=False) if configured else None

    @property
    def api_host(self) -> str:
        configured = os.getenv("MISSUS_TOM_API_HOST", "127.0.0.1").strip()
        if configured.lower() == "localhost":
            return "localhost"
        try:
            address = ip_address(configured)
        except ValueError as exc:
            raise ValueError(
                "MISSUS_TOM_API_HOST must be localhost or a loopback IP address"
            ) from exc
        if not address.is_loopback:
            raise ValueError("MISSUS_TOM_API_HOST must be a loopback IP address")
        return configured

    @property
    def api_port(self) -> int:
        configured = os.getenv("MISSUS_TOM_API_PORT", "8000").strip()
        try:
            port = int(configured)
        except ValueError as exc:
            raise ValueError("MISSUS_TOM_API_PORT must be an integer from 1 through 65535") from exc
        if not 1 <= port <= 65535:
            raise ValueError("MISSUS_TOM_API_PORT must be an integer from 1 through 65535")
        return port

    @property
    def human_demo_manifest(self) -> Path | None:
        configured = os.getenv("MISSUS_TOM_HUMAN_DEMO_MANIFEST")
        return Path(configured).expanduser().resolve(strict=False) if configured else None

    @property
    def state_directory(self) -> Path:
        configured = os.getenv("MISSUS_TOM_STATE_DIR")
        if configured:
            return Path(configured).expanduser().resolve(strict=False)
        return (Path.home() / ".local" / "share" / "missus-tom").resolve(strict=False)


settings = Settings()
