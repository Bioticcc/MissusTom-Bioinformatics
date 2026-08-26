#!/usr/bin/env bash
set -Eeuo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "${script_dir}/.." && pwd)
python_bin="${project_root}/backend/.venv/bin/python"
demo_root="${MISSUS_TOM_EXECUTION_ROOT:-/mnt/20TB_A/Adam/MissusTomDemo}"

if [[ ! -x "$python_bin" ]]; then
  echo "Missing backend virtual environment. See README.md setup instructions." >&2
  exit 1
fi

export MISSUS_TOM_EXECUTION_ENABLED="${MISSUS_TOM_EXECUTION_ENABLED:-1}"
export MISSUS_TOM_EXECUTION_ROOT="$demo_root"
export MISSUS_TOM_HUMAN_DEMO_MANIFEST="${MISSUS_TOM_HUMAN_DEMO_MANIFEST:-${demo_root}/project/input_manifest/project_manifest.json}"

cd "${project_root}/backend"
exec "$python_bin" -m uvicorn missus_tom.main:app --host 127.0.0.1 --port 8000
