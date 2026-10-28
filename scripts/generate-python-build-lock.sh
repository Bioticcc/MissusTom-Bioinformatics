#!/usr/bin/env bash
set -euo pipefail

# Generate the hash-checked Python sidecar build lock in an isolated environment.
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/missus-tom-pip-lock.XXXXXX")"
trap 'rm -rf "${work_dir}"' EXIT HUP INT TERM
python3 -m venv "${work_dir}/venv"
"${work_dir}/venv/bin/pip" install --quiet 'pip-tools==7.5.2'
"${work_dir}/venv/bin/pip-compile" --generate-hashes --strip-extras \
  --output-file "${repository_root}/backend/requirements-build.lock" \
  "${repository_root}/backend/requirements-build.in"
