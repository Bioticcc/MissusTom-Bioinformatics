#!/usr/bin/env bash
# Capture read-only performance evidence while an operator exercises Missus Tom.
#
# Usage: ./scripts/collect-desktop-performance.sh <label> [seconds]
# Example: ./scripts/collect-desktop-performance.sh linux-large-log 60
#
# Start this after the desktop application is open. During the capture, perform
# the same navigation/scrolling action on each host. Results are written below
# /tmp so no project, workflow, or application state is changed.
set -Eeuo pipefail

label=${1:-}
duration=${2:-60}

if [[ -z "$label" || ! "$label" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Usage: $0 <label-with-letters-numbers-_-only> [seconds]" >&2
  exit 2
fi
if [[ ! "$duration" =~ ^[1-9][0-9]*$ ]]; then
  echo "seconds must be a positive integer" >&2
  exit 2
fi

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
output_dir="/tmp/missus-tom-desktop-performance/${timestamp}-${label}"
mkdir -p "$output_dir"

command_exists() { command -v "$1" >/dev/null 2>&1; }

pids_for_pattern() {
  local pattern=$1
  pgrep -f "$pattern" 2>/dev/null | paste -sd, - || true
}

pids_for_app() {
  local roots queue parent children child all
  roots=$(pids_for_pattern '[Mm]issus[ -][Tt]om')
  [[ -n "$roots" ]] || return
  all=",${roots},"
  queue=${roots//,/ }
  while [[ -n "$queue" ]]; do
    parent=${queue%% *}
    queue=${queue#* }
    [[ "$parent" == "$queue" ]] && queue=
    children=$(pgrep -P "$parent" 2>/dev/null || true)
    for child in $children; do
      if [[ "$all" != *",${child},"* ]]; then
        all+="${child},"
        if [[ -n "$queue" ]]; then
          queue+=" ${child}"
        else
          queue=$child
        fi
      fi
    done
  done
  printf '%s\n' "${all#,}" | sed 's/,$//'
}

metrics_for_pids() {
  local pids=$1
  if [[ -z "$pids" ]]; then
    printf '0,0.00,0\n'
    return
  fi
  ps -o pcpu=,rss= -p "$pids" 2>/dev/null | awk '
    { count += 1; cpu += $1; rss += $2 }
    END { printf "%d,%.2f,%d\\n", count, cpu, rss + 0 }
  '
}

{
  echo "label=$label"
  echo "started_utc=$(date -u --iso-8601=seconds)"
  echo "host=$(hostname)"
  echo "kernel=$(uname -srmo)"
  echo "git_revision=$(git -C "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" rev-parse --short HEAD 2>/dev/null || echo unavailable)"
  if command_exists dpkg-query && dpkg-query -W -f='${Version}' missus-tom >/dev/null 2>&1; then
    echo "installed_missus_tom_version=$(dpkg-query -W -f='${Version}' missus-tom)"
  else
    echo "installed_missus_tom_version=unavailable"
  fi
  if command_exists systemd-detect-virt; then
    echo "virtualization=$(systemd-detect-virt || true)"
  fi
  if command_exists nvidia-smi; then
    echo "nvidia_smi=available"
  else
    echo "nvidia_smi=unavailable"
  fi
  if command_exists glxinfo; then
    echo "glxinfo=available"
    glxinfo -B 2>&1 || true
  else
    echo "glxinfo=unavailable"
  fi
} >"$output_dir/environment.txt"

if command_exists nvidia-smi; then
  nvidia-smi --query-gpu=name,driver_version,utilization.gpu,utilization.memory,memory.used,memory.total \
    --format=csv,noheader,nounits >"$output_dir/gpu-start.csv" 2>&1 || true
fi

echo "utc,app_processes,app_cpu_percent,app_rss_kib,backend_processes,backend_cpu_percent,backend_rss_kib,health_status,health_seconds" >"$output_dir/samples.csv"
echo "Capturing ${duration}s to $output_dir"
echo "Exercise the requested state now; this collector only reads process, GPU, and health data."

for ((second = 1; second <= duration; second += 1)); do
  now=$(date -u --iso-8601=seconds)
  # Include the Tauri parent and its WebKit child processes. The backend is
  # recorded separately because it is a distinct process.
  app_pids=$(pids_for_app)
  backend_pids=$(pids_for_pattern '[Mm]issus_tom\.main')
  app_metrics=$(metrics_for_pids "$app_pids")
  backend_metrics=$(metrics_for_pids "$backend_pids")
  health=$(curl --silent --output /dev/null --write-out '%{http_code},%{time_total}' --max-time 2 \
    http://127.0.0.1:8000/health 2>/dev/null || printf 'unavailable,')
  printf '%s,%s,%s,%s\n' "$now" "$app_metrics" "$backend_metrics" "$health" >>"$output_dir/samples.csv"
  ps -o pid=,ppid=,pcpu=,rss=,comm=,args= -p "${app_pids}${app_pids:+,}${backend_pids}" \
    >"$output_dir/processes-${second}.txt" 2>&1 || true
  if command_exists nvidia-smi; then
    nvidia-smi --query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total \
      --format=csv,noheader,nounits 2>/dev/null | sed "s/^/${now},/" >>"$output_dir/gpu-samples.csv" || true
  fi
  if (( second < duration )); then sleep 1; fi
done

if command_exists nvidia-smi; then
  nvidia-smi --query-gpu=name,driver_version,utilization.gpu,utilization.memory,memory.used,memory.total \
    --format=csv,noheader,nounits >"$output_dir/gpu-end.csv" 2>&1 || true
fi

echo "Finished. Attach or retain: $output_dir"
echo "Also record the WebKit GPU report from the running app if available; glxinfo alone does not prove its renderer."
