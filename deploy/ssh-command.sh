#!/usr/bin/env bash
set -euo pipefail
if [[ ${SSH_ORIGINAL_COMMAND:-} =~ ^deploy\ ([a-f0-9]{40})$ ]]; then
  exec sudo -n /usr/local/sbin/ledokol-deploy "${BASH_REMATCH[1]}"
fi
echo 'Only deployment of a commit SHA is permitted' >&2
exit 1
