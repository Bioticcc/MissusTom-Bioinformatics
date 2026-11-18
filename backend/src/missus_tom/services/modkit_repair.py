"""Identity checks for the reviewed native Modkit ambiguity repair."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from missus_tom.config import settings


def recipe() -> dict[str, Any]:
    return dict(
        json.loads((settings.packaged_resources_root / "modkit-repair/recipe.json").read_text())
    )


def artifact_directory() -> Path:
    packaged = settings.packaged_resources_root / "analysis-tools/modkit-repair"
    if packaged.is_dir():
        return packaged
    return settings.resource_root / "backend/build/analysis-tools/modkit-repair"


def binary_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate(binary: Path, manifest: Path) -> dict[str, Any]:
    """Require both the reviewed source identity and matching binary bytes."""
    observed = dict(json.loads(manifest.read_text()))
    expected = recipe()
    if any(observed.get(key) != value for key, value in expected.items()):
        raise ValueError("Modkit repair source identity does not match this application")
    if observed.get("binary_sha256") != binary_sha256(binary):
        raise ValueError("Modkit repair binary checksum mismatch")
    return observed


def problems(prefix: Path) -> list[str]:
    try:
        validate(prefix / "bin/modkit", prefix / "modkit-repair.json")
    except (OSError, ValueError, TypeError) as exc:
        return [f"Modkit ambiguity repair is missing or invalid ({exc})"]
    return []
