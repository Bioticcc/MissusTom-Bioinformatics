#!/usr/bin/env bash
set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${repository_root}" <<'PY'
import json
import re
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
backend_init = (root / "backend/src/missus_tom/__init__.py").read_text(encoding="utf-8")
match = re.search(r'^__version__\s*=\s*"([^"]+)"$', backend_init, re.M)
if not match:
    raise SystemExit("Could not read backend __version__.")
versions = {
    "backend __version__": match.group(1),
    "backend pyproject": tomllib.loads((root / "backend/pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
    "desktop package": json.loads((root / "desktop/package.json").read_text(encoding="utf-8"))["version"],
    "Tauri config": json.loads((root / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))["version"],
}
cargo = tomllib.loads((root / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
versions["Cargo package"] = cargo["package"]["version"]
if len(set(versions.values())) != 1:
    raise SystemExit("Release version metadata disagree: " + "; ".join(f"{key}={value}" for key, value in versions.items()))
print(f"release version consistency: ok ({next(iter(versions.values()))})")
PY
