"""Packagable entry point for the bundled ONT workflow runner."""

from __future__ import annotations

import runpy

from missus_tom.config import settings


def run() -> None:
    """Execute the staged ONT runner as its own process."""
    runner = settings.resource_root / "workflows" / "ont_analysis" / "run_pipeline.py"
    if not runner.is_file():
        raise SystemExit(f"Bundled ONT runner is unavailable: {runner}")
    runpy.run_path(str(runner), run_name="__main__")


if __name__ == "__main__":
    run()
