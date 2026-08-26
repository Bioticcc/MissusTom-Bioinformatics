#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker build \
  --file "${project_root}/workflows/bulk_rnaseq/docker/Dockerfile.analysis" \
  --tag missus-tom/rnaseq-analysis:0.3.0 \
  "${project_root}/workflows/bulk_rnaseq/docker"
