#!/usr/bin/env bash
# One-process encrypted handoff for an explicitly authorized provisioning/rotation.
set -euo pipefail
umask 077

lab_execute_present=false
for lab_argument in "$@"; do
  if [[ "$lab_argument" == "--execute" ]]; then
    lab_execute_present=true
  fi
done
if [[ "$lab_execute_present" != true ]]; then
  echo "Use the management command directly for read-only previews; handoff requires --execute." >&2
  exit 2
fi
if ! command -v age >/dev/null; then
  echo "Credential handoff requires the age encryption CLI on PATH." >&2
  exit 1
fi

lab_handoff_dir=$(mktemp -d /tmp/motionmate-lab-handoff.XXXXXXXX)
trap 'rm -f "$lab_handoff_dir/credentials.age"; rmdir "$lab_handoff_dir"' EXIT
python src/manage.py setup_logistics_test_lab "$@" \
  --credential-file "$lab_handoff_dir/credentials.age" >&2
if [[ ! -s "$lab_handoff_dir/credentials.age" ]] \
  || [[ $(head -n 1 "$lab_handoff_dir/credentials.age") != '-----BEGIN AGE ENCRYPTED FILE-----' ]] \
  || [[ $(tail -n 1 "$lab_handoff_dir/credentials.age") != '-----END AGE ENCRYPTED FILE-----' ]]; then
  echo "Credential handoff failed: no armored encrypted artifact is available." >&2
  exit 1
fi
# Only ciphertext reaches stdout. The private identity remains with the recipient.
cat "$lab_handoff_dir/credentials.age"
