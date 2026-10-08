#!/usr/bin/env bash
# Cloud Agent: write VPS deploy key from Environment secret (not stored in git).
set -euo pipefail
if [[ -z "${VPS_SSH_PRIVATE_KEY:-}" ]]; then
  exit 0
fi
mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"
printf '%s\n' "$VPS_SSH_PRIVATE_KEY" > "${HOME}/.ssh/id_ed25519"
chmod 600 "${HOME}/.ssh/id_ed25519"
ssh-keyscan -H 129.101.127.78 >> "${HOME}/.ssh/known_hosts" 2>/dev/null || true
