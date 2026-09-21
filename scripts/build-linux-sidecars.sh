#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_root="${repository_root}/backend"
desktop_binaries="${repository_root}/desktop/src-tauri/binaries"
target="${1:-x86_64-unknown-linux-gnu}"

case "${target}" in
  x86_64-unknown-linux-gnu)
    ;;
  *)
    echo "Only the Tauri Linux target x86_64-unknown-linux-gnu is supported." >&2
    exit 2
    ;;
esac

resource_stage="${backend_root}/build/sidecar-resources"
rm -rf "${resource_stage}"
mkdir -p "${resource_stage}/scripts"
cp -a "${repository_root}/workflows" "${resource_stage}/workflows"
cp -a "${repository_root}/scripts/build-analysis-image.sh" "${resource_stage}/scripts/"

export MISSUS_TOM_SIDECAR_TARGET="${target}"
export MISSUS_TOM_SIDECAR_RESOURCE_STAGE="${resource_stage}"

cd "${backend_root}"
python -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "${backend_root}/dist/sidecars" \
  --workpath "${backend_root}/build/pyinstaller" \
  "${backend_root}/packaging/missus_tom_sidecars.spec"

mkdir -p "${desktop_binaries}"
install -m 0755 \
  "${backend_root}/dist/sidecars/missus-tom-backend-${target}" \
  "${desktop_binaries}/missus-tom-backend-${target}"
install -m 0755 \
  "${backend_root}/dist/sidecars/ont-analysis-runner-${target}" \
  "${desktop_binaries}/ont-analysis-runner-${target}"
