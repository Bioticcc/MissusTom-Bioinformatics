#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

recipe="${project_root}/workflows/bulk_rnaseq/docker/Dockerfile.analysis"
lock="${project_root}/backend/src/missus_tom/resources/locks/bulk-rnaseq-linux-64.lock"
[[ -f "$lock" ]] || lock="${project_root}/resources/locks/bulk-rnaseq-linux-64.lock"
identity=$(python3 - "$recipe" "$lock" <<'PY'
import hashlib, sys
from pathlib import Path
print(hashlib.sha256(Path(sys.argv[1]).read_bytes() + b'\0' + Path(sys.argv[2]).read_bytes()).hexdigest())
PY
)
image="missus-tom/rnaseq-analysis:locked-${identity}"
if [[ "${1:-}" == --print-tag ]]; then printf '%s\n' "$image"; exit 0; fi
context=$(mktemp -d)
trap 'rm -rf "$context"' EXIT
cp "$recipe" "$context/Dockerfile"
cp "$lock" "$context/bulk-rnaseq-linux-64.lock"
docker build --tag "$image" "$context"
