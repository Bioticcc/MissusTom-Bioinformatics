#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --release-version SEMVER --deb PACKAGE.deb" >&2
  exit 2
}

release_version=""
deb_source=""

while (( $# > 0 )); do
  case "$1" in
    --release-version)
      (( $# >= 2 )) || usage
      release_version="$2"
      shift 2
      ;;
    --deb)
      (( $# >= 2 )) || usage
      deb_source="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

[[ -n "${release_version}" && -n "${deb_source}" ]] || usage
[[ -f "${deb_source}" ]] || {
  echo "Debian package does not exist or is not a regular file: ${deb_source}" >&2
  exit 2
}

if [[ ! "${release_version}" =~ ^([0-9]+\.[0-9]+\.[0-9]+)(-([0-9A-Za-z][0-9A-Za-z.-]*))?$ ]]; then
  echo "Release version must be SemVer MAJOR.MINOR.PATCH with an optional prerelease." >&2
  exit 2
fi

base_version="${BASH_REMATCH[1]}"
prerelease="${BASH_REMATCH[3]:-}"
debian_version="${base_version}"
if [[ -n "${prerelease}" ]]; then
  # Debian sorts '~' before the end of a version, so every SemVer prerelease
  # remains upgradeable to its corresponding final release.
  debian_version="${base_version}~${prerelease}"
fi

staging_directory="$(mktemp -d)"
rebuilt_deb="${staging_directory}/rebuilt.deb"
trap 'rm -rf "${staging_directory}"' EXIT

dpkg-deb --raw-extract "${deb_source}" "${staging_directory}/package"
sed -i "s/^Version: .*/Version: ${debian_version}/" "${staging_directory}/package/DEBIAN/control"
dpkg-deb --build --root-owner-group "${staging_directory}/package" "${rebuilt_deb}"
install -m 0644 "${rebuilt_deb}" "${deb_source}"

actual_version="$(dpkg-deb --field "${deb_source}" Version)"
if [[ "${actual_version}" != "${debian_version}" ]]; then
  echo "Debian package Version is ${actual_version}, expected ${debian_version}." >&2
  exit 1
fi

if [[ -n "${prerelease}" ]] && ! dpkg --compare-versions "${actual_version}" lt "${base_version}"; then
  echo "Debian prerelease Version ${actual_version} must sort before ${base_version}." >&2
  exit 1
fi
