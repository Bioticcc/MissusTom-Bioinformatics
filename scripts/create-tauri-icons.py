#!/usr/bin/env python3
"""Regenerate desktop/platform icons from the supplied transparent logo."""

from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> None:
    desktop = Path(__file__).resolve().parents[1] / "desktop"
    destination = desktop / "src-tauri" / "icons"
    source = destination / "icon-source.png"
    cli = desktop / "node_modules" / ".bin" / "tauri"
    if not source.is_file() or not cli.is_file():
        raise SystemExit(
            "The source logo and installed desktop dependencies are required."
        )
    command = [str(cli), "icon", str(source), "--output", str(destination)]
    subprocess.run(command, cwd=desktop, check=True)


if __name__ == "__main__":
    main()
