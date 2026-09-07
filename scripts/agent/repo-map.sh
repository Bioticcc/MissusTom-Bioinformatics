#!/usr/bin/env bash
set -Eeuo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "${script_dir}/../.." && pwd)
max_paths=100

usage() {
  cat <<'EOF'
Usage: scripts/agent/repo-map.sh [--max-paths N]

Print a bounded, tracked-file overview of the Missus Tom repository. Dependency
trees, build outputs, runtime data, generated icons, and lockfiles are excluded.
EOF
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi

if [[ ${1:-} == "--max-paths" ]]; then
  if [[ $# -ne 2 || ! ${2:-} =~ ^[0-9]+$ || $2 -lt 20 || $2 -gt 300 ]]; then
    echo "--max-paths must be an integer from 20 through 300." >&2
    exit 2
  fi
  max_paths=$2
elif [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

cd "${project_root}"

printf 'Repository: %s\n' "${project_root}"
printf 'Branch: %s\n' "$(git branch --show-current)"

mapfile -t changed_paths < <(git status --short --untracked-files=all)
printf 'Changed paths: %d\n' "${#changed_paths[@]}"
if (( ${#changed_paths[@]} > 0 )); then
  printf '%s\n' "${changed_paths[@]:0:30}"
  if (( ${#changed_paths[@]} > 30 )); then
    printf '... %d additional changed paths omitted\n' "$(( ${#changed_paths[@]} - 30 ))"
  fi
fi

printf '\nTracked files by component:\n'
git ls-files | awk -F/ '{counts[$1]++} END {for (name in counts) printf "%4d  %s\n", counts[name], name}' | sort -rn

mapfile -t relevant_paths < <(
  git ls-files \
    AGENTS.md README.md Makefile \
    backend/src backend/tests backend/pyproject.toml backend/README.md \
    desktop/src desktop/src-tauri/src desktop/package.json desktop/vite.config.ts \
    docs examples schemas scripts workflows \
  | awk '
      /(^|\/)node_modules\// {next}
      /(^|\/)dist\// {next}
      /(^|\/)target\// {next}
      /(^|\/)icons\// {next}
      /(^|\/)(package-lock|Cargo\.lock)$/ {next}
      {print}
    '
)

printf '\nHigh-signal tracked paths (%d total; showing at most %d):\n' "${#relevant_paths[@]}" "${max_paths}"
printf '%s\n' "${relevant_paths[@]:0:max_paths}"
if (( ${#relevant_paths[@]} > max_paths )); then
  omitted_paths=$(( ${#relevant_paths[@]} - max_paths ))
  printf '... %d additional paths omitted; rerun with --max-paths up to 300\n' "${omitted_paths}"
fi
