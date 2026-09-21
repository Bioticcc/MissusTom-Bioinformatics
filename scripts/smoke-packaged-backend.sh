#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <packaged-backend> <resource-root>" >&2
  exit 2
fi

backend=$1
resource_root=$2

if [[ ! -x "${backend}" ]]; then
  echo "Packaged backend is not executable: ${backend}" >&2
  exit 2
fi
if [[ ! -d "${resource_root}" ]]; then
  echo "Resource root is not a directory: ${resource_root}" >&2
  exit 2
fi

temporary_root=$(mktemp -d "${TMPDIR:-/tmp}/missus-tom-sidecar-smoke.XXXXXX")
state_directory="${temporary_root}/state"
log_file="${temporary_root}/backend.log"
backend_pid=

cleanup() {
  if [[ -n "${backend_pid}" ]] && kill -0 "${backend_pid}" 2>/dev/null; then
    kill "${backend_pid}" 2>/dev/null || true
    wait "${backend_pid}" 2>/dev/null || true
  fi
  rm -rf "${temporary_root}"
}
trap cleanup EXIT INT TERM

port=$(
  python3 - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
    listener.bind(("127.0.0.1", 0))
    print(listener.getsockname()[1])
PY
)
mkdir -p "${state_directory}"
chmod 700 "${temporary_root}" "${state_directory}"

MISSUS_TOM_API_HOST=127.0.0.1 \
MISSUS_TOM_API_PORT="${port}" \
MISSUS_TOM_RESOURCE_ROOT="${resource_root}" \
MISSUS_TOM_STATE_DIR="${state_directory}" \
"${backend}" >"${log_file}" 2>&1 &
backend_pid=$!

for _ in $(seq 1 50); do
  if python3 - "${port}" <<'PY'
import json
import sys
from urllib.request import urlopen

port = sys.argv[1]
with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.25) as response:
    payload = json.load(response)
if (
    response.status == 200
    and payload.get("success") is True
    and payload.get("data", {}).get("status") == "ok"
):
    raise SystemExit(0)
raise SystemExit(1)
PY
  then
    exit 0
  fi
  if ! kill -0 "${backend_pid}" 2>/dev/null; then
    cat "${log_file}" >&2
    exit 1
  fi
  sleep 0.1
done

echo "Packaged backend did not become healthy on loopback port ${port}." >&2
cat "${log_file}" >&2
exit 1
