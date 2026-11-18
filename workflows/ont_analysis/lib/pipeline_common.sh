#!/usr/bin/env bash
# Shared restart/atomic primitives for the vendored ONT stages.
set -Eeuo pipefail
[[ -n "${PIPELINE_ENV:-}" && -r "${PIPELINE_ENV}" ]] || { echo 'PIPELINE_ENV must name the generated project.env' >&2; exit 2; }
source "${PIPELINE_ENV}"
PIPELINE_RUN_STAMP="$(date '+%Y%m%d_%H%M%S')_${BASHPID}"
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }
require_executable() { [[ -x "$1" ]] || { log "ERROR: executable not found: $1"; exit 1; }; }
lock_stage() { mkdir -p "${SAMPLE_OUTPUT}/tmp"; exec 9>"${SAMPLE_OUTPUT}/tmp/$1.lock"; flock -n 9 || { log "ERROR: stage is already running: $1"; exit 1; }; }
check_tags() { python3 "${WORKFLOW_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}/lib/check_modbam_tags.py" "$SAMTOOLS_BIN" "$1"; }
complete() { local marker="$1"; shift; local tmp="${marker}.partial.${BASHPID}"; { printf 'status\tcomplete\n'; printf 'completed_at\t%s\n' "$(date --iso-8601=seconds)"; for item in "$@"; do printf 'input\t%s\n' "$item"; done; } > "$tmp"; mv "$tmp" "$marker"; }
fresh_complete() { local marker="$1"; shift; [[ -s "$marker" && "$marker" -nt "$0" && "$marker" -nt "${BASH_SOURCE[0]}" ]] || return 1; local input; for input in "$@"; do [[ "$marker" -nt "$input" ]] || return 1; done; }
