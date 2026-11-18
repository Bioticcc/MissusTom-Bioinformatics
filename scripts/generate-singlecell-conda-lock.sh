#!/usr/bin/env bash
set -euo pipefail
# Resolve in an isolated temporary prefix, check packages, export exact artifacts.
# This downloads packages; it never modifies Bulk, ONT, or the system R library.
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workflow_root="${repository_root}/workflows/singlecell_rnaseq"
mamba="${MISSUS_TOM_MICROMAMBA:-$(command -v micromamba || true)}"
if [[ -z "${mamba}" ]]; then
  echo "micromamba is required to resolve the SingleCell candidate environment." >&2
  exit 1
fi
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "This lock-generation script supports Linux x86_64 only." >&2
  exit 1
fi
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/missus-tom-singlecell-lock.XXXXXX")"
trap 'rm -rf "${work_dir}"' EXIT
"${mamba}" create --yes --no-rc --strict-channel-priority \
  --prefix "${work_dir}/environment" --override-channels \
  --file "${workflow_root}/environment.yaml"
"${mamba}" run --prefix "${work_dir}/environment" \
  Rscript --vanilla "${workflow_root}/bin/check_dependencies.R"
"${mamba}" run --prefix "${work_dir}/environment" nextflow -version
"${mamba}" env export --explicit --md5 --prefix "${work_dir}/environment" \
  > "${work_dir}/singlecell-linux-64.lock"
mv "${work_dir}/singlecell-linux-64.lock" "${workflow_root}/singlecell-linux-64.lock"
echo "Wrote SingleCell explicit lock. Scientific validation is still required."
