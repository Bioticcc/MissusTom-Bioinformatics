#!/usr/bin/env bash
set -Eeuo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "${script_dir}/.." && pwd)

if [[ ! -d "${project_root}/desktop/node_modules" ]]; then
  echo "Missing frontend dependencies. Run 'cd desktop && npm install'." >&2
  exit 1
fi

cd "${project_root}/desktop"
exec npm run dev

