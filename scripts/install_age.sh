#!/usr/bin/env bash
# Official release assets, pinned to the upstream GitHub release SHA-256 digests.
set -euo pipefail

lab_repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
lab_age_version=1.3.2
if [[ $(uname -s) != Linux ]]; then
  echo "age runtime installation supports Linux only." >&2
  exit 1
fi
case $(uname -m) in
  x86_64)
    lab_age_arch=amd64
    lab_age_sha256=cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10
    ;;
  aarch64|arm64)
    lab_age_arch=arm64
    lab_age_sha256=6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4
    ;;
  *)
    echo "Unsupported architecture for the pinned age runtime." >&2
    exit 1
    ;;
esac

lab_age_tmp=$(mktemp -d)
trap 'rm -rf "$lab_age_tmp"' EXIT
lab_age_archive="age-v${lab_age_version}-linux-${lab_age_arch}.tar.gz"
curl --proto '=https' --proto-redir '=https' --tlsv1.2 \
  --fail --location --silent --show-error --retry 3 \
  --connect-timeout 15 --max-time 180 \
  "https://github.com/FiloSottile/age/releases/download/v${lab_age_version}/${lab_age_archive}" \
  --output "$lab_age_tmp/$lab_age_archive"
if ! printf '%s  %s\n' "$lab_age_sha256" "$lab_age_tmp/$lab_age_archive" | sha256sum --check --status; then
  echo "Pinned age archive checksum verification failed." >&2
  exit 1
fi
# Verify before extracting, executing, or installing anything from the download.
tar -xzf "$lab_age_tmp/$lab_age_archive" -C "$lab_age_tmp" age/age age/age-keygen
for lab_age_binary in age age-keygen; do
  if [[ $("$lab_age_tmp/age/$lab_age_binary" --version) != "v$lab_age_version" ]]; then
    echo "Pinned age executable version verification failed." >&2
    exit 1
  fi
done
mkdir -p "$lab_repo_root/.heroku/age/bin"
install -m 0755 "$lab_age_tmp/age/age" "$lab_age_tmp/age/age-keygen" \
  "$lab_repo_root/.heroku/age/bin/"
echo "Installed verified age v$lab_age_version ($lab_age_arch)."
