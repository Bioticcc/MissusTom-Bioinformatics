from __future__ import annotations

import subprocess
from pathlib import Path


def test_release_version_metadata_are_consistent() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["bash", str(root / "scripts" / "check-version-consistency.sh")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "0.3.0-rc.28" in result.stdout
