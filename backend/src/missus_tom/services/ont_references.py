"""Load the bundled ONT reference contract, independent of custom source selection."""

from __future__ import annotations

import runpy
from functools import lru_cache
from pathlib import Path
from typing import Any

from missus_tom.config import settings


@lru_cache(maxsize=1)
def _contract() -> dict[str, Any]:
    return runpy.run_path(
        str(settings.resource_root / "workflows" / "ont_analysis" / "reference_contract.py")
    )


def supported_ont_reference(organism: str, reference: str) -> bool:
    try:
        _contract()["reference_profile"](organism, reference)
    except ValueError:
        return False
    return True


def ont_main_chromosomes(fai: Path, organism: str, reference: str) -> list[str]:
    return list(_contract()["main_chromosomes"](fai, organism, reference))
