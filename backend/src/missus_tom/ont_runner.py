"""Packagable entry point for the bundled ONT workflow runner."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

from missus_tom.config import settings


def run() -> None:
    """Execute the staged ONT runner as its own process."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source-root")
    options, remaining = parser.parse_known_args()
    root = (
        Path(options.source_root).resolve(strict=True)
        if options.source_root
        else settings.resource_root / "workflows" / "ont_analysis"
    )
    runner = root / "run_pipeline.py"
    if not runner.is_file():
        raise SystemExit(f"Bundled ONT runner is unavailable: {runner}")
    sys.argv = [str(runner), *remaining]
    runpy.run_path(str(runner), run_name="__main__")


if __name__ == "__main__":
    run()
