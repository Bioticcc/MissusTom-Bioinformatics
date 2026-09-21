"""Build the Linux backend and ONT runner sidecars from staged resources."""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.building.build_main import Analysis, EXE, PYZ


target = os.environ["MISSUS_TOM_SIDECAR_TARGET"]
resource_stage = Path(os.environ["MISSUS_TOM_SIDECAR_RESOURCE_STAGE"])
if not resource_stage.is_dir():
    raise SystemExit(f"Resource staging directory is missing: {resource_stage}")

backend_root = Path(SPECPATH).resolve().parent
source_root = backend_root / "src"

common = {
    "pathex": [str(source_root)],
    "binaries": [],
    "datas": [(str(resource_stage), "resources")],
    "hiddenimports": [],
    "hookspath": [],
    "hooksconfig": {},
    "runtime_hooks": [],
    "excludes": [],
    "noarchive": False,
}

api_analysis = Analysis([str(source_root / "missus_tom" / "main.py")], **common)
api_pyz = PYZ(api_analysis.pure)
EXE(
    api_pyz,
    api_analysis.scripts,
    api_analysis.binaries,
    api_analysis.zipfiles,
    api_analysis.datas,
    name=f"missus-tom-backend-{target}",
    console=True,
)

runner_analysis = Analysis([str(source_root / "missus_tom" / "ont_runner.py")], **common)
runner_pyz = PYZ(runner_analysis.pure)
EXE(
    runner_pyz,
    runner_analysis.scripts,
    runner_analysis.binaries,
    runner_analysis.zipfiles,
    runner_analysis.datas,
    name=f"ont-analysis-runner-{target}",
    console=True,
)
