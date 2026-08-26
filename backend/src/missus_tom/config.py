from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from missus_tom import __version__


@dataclass(frozen=True)
class Settings:
    app_name: str = "Missus Tom"
    app_version: str = __version__
    api_prefix: str = "/api/v1"

    @property
    def execution_enabled(self) -> bool:
        return os.getenv("MISSUS_TOM_EXECUTION_ENABLED", "0").strip().lower() in {
            "1",
            "true",
            "yes",
        }

    @property
    def execution_root(self) -> Path | None:
        configured = os.getenv("MISSUS_TOM_EXECUTION_ROOT")
        return Path(configured).expanduser().resolve(strict=False) if configured else None

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
