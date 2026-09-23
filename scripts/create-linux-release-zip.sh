#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --version VERSION --deb PACKAGE.deb --output-dir DIRECTORY" >&2
  exit 2
}

release_version=""
deb_source=""
output_directory=""

while (( $# > 0 )); do
  case "$1" in
    --version)
      (( $# >= 2 )) || usage
      release_version="$2"
      shift 2
      ;;
    --deb)
      (( $# >= 2 )) || usage
      deb_source="$2"
      shift 2
      ;;
    --output-dir)
      (( $# >= 2 )) || usage
      output_directory="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

[[ -n "${release_version}" && -n "${deb_source}" && -n "${output_directory}" ]] || usage

if [[ ! "${release_version}" =~ ^[0-9][0-9A-Za-z.+-]*$ ]]; then
  echo "Release version must start with a digit and contain only letters, digits, '.', '+', or '-'." >&2
  exit 2
fi
if [[ ! -f "${deb_source}" ]]; then
  echo "Debian package does not exist or is not a regular file: ${deb_source}" >&2
  exit 2
fi

mkdir -p "${output_directory}"
if [[ ! -d "${output_directory}" ]]; then
  echo "Release output path is not a directory: ${output_directory}" >&2
  exit 2
fi
output_directory="$(cd "${output_directory}" && pwd -P)"

zip_name="ver${release_version}_Linux-x86_64_Ubuntu-Debian.zip"
zip_path="${output_directory}/${zip_name}"
if [[ -e "${zip_path}" ]] || find "${output_directory}" -maxdepth 1 -type f -name '*.zip' -print -quit | grep -q .; then
  echo "Release output directory must not already contain a ZIP: ${output_directory}" >&2
  exit 2
fi

staging_directory="$(mktemp -d)"
trap 'rm -rf "${staging_directory}"' EXIT
deb_name="missus-tom_${release_version}_linux-x86_64.deb"

install -m 0644 "${deb_source}" "${staging_directory}/${deb_name}"
(
  cd "${staging_directory}"
  sha256sum "${deb_name}" >SHA256SUMS
  cat >installation.md <<EOF
# Install Missus Tom on Ubuntu or Debian

1. Verify the installer checksum:

   \`\`\`bash
   sha256sum --check SHA256SUMS
   \`\`\`

2. Install the verified package:

   \`\`\`bash
   sudo apt install ./${deb_name}
   \`\`\`
EOF
  zip -q "${zip_path}" "${deb_name}" SHA256SUMS installation.md
)
