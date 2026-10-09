#!/usr/bin/env bash
set -Eeuo pipefail

# Validate emitted frontend and packaged Linux assets without installing them.

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dist_root="${repository_root}/desktop/dist"
sidecar=""
debian_root=""
deb_path=""
expected_revision="${MISSUS_TOM_EXPECTED_BUILD_REVISION:-}"
release_mode=false
temporary_root=""
backend_pid=""

fail() { echo "$*" >&2; exit 1; }
usage() {
  echo "Usage: $0 [--release] [--dist DIR] [--sidecar FILE] [--debian-root DIR | --deb FILE] [--revision GIT_REVISION]" >&2
}
cleanup() {
  if [[ -n "${backend_pid}" ]] && kill -0 "${backend_pid}" 2>/dev/null; then
    kill "${backend_pid}" 2>/dev/null || true
    wait "${backend_pid}" 2>/dev/null || true
  fi
  if [[ -n "${temporary_root}" && -d "${temporary_root}" ]]; then
    rm -rf -- "${temporary_root}"
  fi
}
trap cleanup EXIT INT TERM

while (( $# > 0 )); do
  case "$1" in
    --release) release_mode=true; shift ;;
    --dist) [[ $# -ge 2 ]] || { usage; exit 2; }; dist_root=$2; shift 2 ;;
    --sidecar) [[ $# -ge 2 ]] || { usage; exit 2; }; sidecar=$2; shift 2 ;;
    --debian-root) [[ $# -ge 2 ]] || { usage; exit 2; }; debian_root=$2; shift 2 ;;
    --deb) [[ $# -ge 2 ]] || { usage; exit 2; }; deb_path=$2; shift 2 ;;
    --revision) [[ $# -ge 2 ]] || { usage; exit 2; }; expected_revision=$2; shift 2 ;;
    *) usage; exit 2 ;;
  esac
done

[[ -d "${dist_root}" ]] || fail "Frontend dist directory is missing: ${dist_root}"
if [[ "${release_mode}" == true && -z "${expected_revision}" ]]; then
  fail "Release verification requires --revision or MISSUS_TOM_EXPECTED_BUILD_REVISION."
fi

python3 - "${dist_root}" "${expected_revision}" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
expected_revision = sys.argv[2]
text = "\n".join(
    path.read_text(encoding="utf-8", errors="replace")
    for path in root.rglob("*")
    if path.suffix in {".js", ".html", ".css"} and path.is_file()
)
if "Transcriptome FASTA" not in text:
    raise SystemExit("Built UI is missing Transcriptome FASTA wording")
if "human BioMart" in text:
    raise SystemExit("Built UI still contains human BioMart wizard wording")
if expected_revision and expected_revision not in text:
    raise SystemExit(f"Built UI does not contain the injected revision {expected_revision!r}")
print("frontend bundle contract: ok")
PY

if [[ -n "${deb_path}" ]]; then
  command -v dpkg-deb >/dev/null 2>&1 || fail "dpkg-deb is required to inspect ${deb_path}."
  [[ -f "${deb_path}" ]] || fail "Debian package is missing: ${deb_path}"
  temporary_root=$(mktemp -d "${TMPDIR:-/tmp}/missus-tom-package-check.XXXXXX")
  debian_root="${temporary_root}/deb-root"
  mkdir -p "${debian_root}"
  dpkg-deb --extract "${deb_path}" "${debian_root}"
fi

if [[ -n "${debian_root}" ]]; then
  [[ -d "${debian_root}" ]] || fail "Extracted Debian tree is missing: ${debian_root}"
  workflow_script=$(find "${debian_root}" -type f -path '*/workflows/bulk_rnaseq/bin/bulk_rnaseq_analysis.R' -print -quit)
  lock_file=$(find "${debian_root}" -type f -path '*/resources/locks/bulk-rnaseq-linux-64.lock' -print -quit)
  [[ -n "${workflow_script}" ]] || fail "Packaged workflow is missing bulk_rnaseq_analysis.R"
  [[ -x "${workflow_script}" ]] || fail "Packaged workflow helper is not executable: ${workflow_script}"
  [[ -n "${lock_file}" ]] || fail "Packaged backend is missing the explicit Bulk dependency lock"
  [[ -s "${lock_file}" ]] || fail "Packaged Bulk dependency lock is empty: ${lock_file}"
  if [[ -z "${sidecar}" ]]; then
    sidecar=$(find "${debian_root}" -type f -name 'missus-tom-backend*' -perm -u+x -print -quit)
  fi
  desktop_binary=$(find "${debian_root}" -type f \( -name 'missus-tom' -o -name 'Missus Tom' \) -perm -u+x -print -quit)
  if [[ "${release_mode}" == true ]]; then
    [[ -n "${desktop_binary}" ]] || fail "Extracted Debian package is missing the desktop executable"
    # Tauri embeds frontend files as Brotli payloads, so the revision text is not
    # present as plaintext. The asset map key is plaintext and is content-addressed
    # by the Vite filename, which is enough to prove that exact bundle was packaged.
    python3 - "${dist_root}" "${expected_revision}" "${desktop_binary}" <<'PY'
import pathlib
import sys

dist_root = pathlib.Path(sys.argv[1])
expected_revision = sys.argv[2]
binary = pathlib.Path(sys.argv[3]).read_bytes()
revision_bytes = expected_revision.encode()
if revision_bytes in binary:
    print("packaged desktop frontend revision: ok")
    raise SystemExit(0)
keys = []
for path in dist_root.rglob("*"):
    if not path.is_file() or path.suffix not in {".js", ".html", ".css"}:
        continue
    if revision_bytes not in path.read_bytes():
        continue
    keys.append("/" + path.relative_to(dist_root).as_posix())
if not keys:
    raise SystemExit(
        f"Built UI no longer contains frontend revision {expected_revision}"
    )
missing = [key for key in keys if key.encode() not in binary]
if missing:
    raise SystemExit(
        "Packaged desktop does not embed the frontend asset containing revision "
        f"{expected_revision}: {', '.join(missing)}"
    )
print("packaged desktop frontend revision: ok")
PY
  fi
elif [[ "${release_mode}" == true ]]; then
  fail "Release verification requires --deb or --debian-root."
fi

if [[ -z "${sidecar}" && "${release_mode}" != true ]]; then
  sidecar="${repository_root}/desktop/src-tauri/binaries/missus-tom-backend-x86_64-unknown-linux-gnu"
fi

if [[ -x "${sidecar}" ]]; then
  [[ -n "${temporary_root}" ]] || temporary_root=$(mktemp -d "${TMPDIR:-/tmp}/missus-tom-package-check.XXXXXX")
  state_directory="${temporary_root}/state"
  backend_log="${temporary_root}/backend.log"
  health_json="${temporary_root}/health.json"
  mkdir -p "${state_directory}"
  port=$(python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
    listener.bind(("127.0.0.1", 0))
    print(listener.getsockname()[1])
PY
  )
  MISSUS_TOM_API_HOST=127.0.0.1 \
  MISSUS_TOM_API_PORT="${port}" \
  MISSUS_TOM_STATE_DIR="${state_directory}" \
  "${sidecar}" >"${backend_log}" 2>&1 &
  backend_pid=$!
  ready=false
  for _ in $(seq 1 80); do
    if python3 - "${port}" "${health_json}" <<'PY'
import json
import pathlib
import sys
from urllib.request import urlopen

with urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=0.25) as response:
    payload = json.load(response)
if response.status != 200 or payload.get("success") is not True:
    raise SystemExit(1)
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload), encoding="utf-8")
PY
    then
      ready=true
      break
    fi
    kill -0 "${backend_pid}" 2>/dev/null || { sed -n '1,120p' "${backend_log}" >&2; fail "Packaged backend exited before health verification"; }
    sleep 0.1
  done
  [[ "${ready}" == true ]] || { sed -n '1,120p' "${backend_log}" >&2; fail "Packaged backend did not become healthy"; }
  python3 - "${health_json}" "${expected_revision}" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8")).get("data", {})
if data.get("capabilities", {}).get("bulk_fasta_gtf_reference_preparation") is not True:
    raise SystemExit("Packaged backend does not advertise Bulk FASTA/GTF preparation")
expected = sys.argv[2]
if expected and data.get("build_revision") != expected:
    raise SystemExit(
        f"Packaged backend revision {data.get('build_revision')!r} does not match {expected!r}"
    )
print("packaged backend health contract: ok")
PY
elif [[ "${release_mode}" == true ]]; then
  fail "Release verification could not find an executable packaged backend sidecar."
fi
