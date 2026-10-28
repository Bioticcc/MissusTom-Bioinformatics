#!/usr/bin/env bash
set -euo pipefail

# Generate the Linux x86-64 explicit Micromamba lock for ONT Analysis.
# Do not hand-edit the emitted lock file.
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
spec="${repository_root}/backend/src/missus_tom/resources/locks/ont-analysis-linux-64.env.yaml"
lock="${repository_root}/backend/src/missus_tom/resources/locks/ont-analysis-linux-64.lock"
mamba="${MISSUS_TOM_MICROMAMBA:-$(command -v micromamba || true)}"
if [[ -z "${mamba}" ]]; then
  echo "micromamba is required to generate the ONT Analysis lock." >&2
  exit 1
fi
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/missus-tom-ont-lock.XXXXXX")"
trap 'rm -rf "${work_dir}"' EXIT HUP INT TERM
"${mamba}" create --yes --no-rc --strict-channel-priority --prefix "${work_dir}/environment" \
  --override-channels --channel conda-forge --channel bioconda --file "${spec}"
"${mamba}" env export --explicit --md5 --prefix "${work_dir}/environment" > "${lock}.tmp"
mv "${lock}.tmp" "${lock}"
echo "Wrote ${lock}"
