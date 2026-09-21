#!/usr/bin/env bash
set -Eeuo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "${script_dir}/.." && pwd)
venv_bin="${project_root}/backend/.venv/bin"

if [[ ! -x "${venv_bin}/pytest" ]]; then
  echo "Missing backend development environment." >&2
  exit 1
fi
if [[ ! -d "${project_root}/desktop/node_modules" ]]; then
  echo "Missing frontend dependencies." >&2
  exit 1
fi

cd "${project_root}/backend"
"${venv_bin}/ruff" check . ../scripts/prepare_human_demo.py
"${venv_bin}/ruff" format --check . ../scripts/prepare_human_demo.py
"${venv_bin}/mypy" src
"${venv_bin}/pytest"

cd "${project_root}/desktop"
npm run lint
npm test
npm run typecheck
npm run build

cd "${project_root}"
PYTHONDONTWRITEBYTECODE=1 "${venv_bin}/python" -m unittest discover -s workflows/ont_analysis/tests
for stage in workflows/ont_analysis/stages/*.sh workflows/ont_analysis/lib/pipeline_common.sh; do
  bash -n "$stage"
done
