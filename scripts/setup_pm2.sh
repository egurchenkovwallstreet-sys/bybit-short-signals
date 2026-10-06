#!/usr/bin/env bash
# Однократная установка PM2 на VPS и автозапуск после reboot.
set -euo pipefail

ROOT="${SIGNALS_ROOT:-/opt/signals}"
cd "$ROOT"

if ! command -v pm2 >/dev/null 2>&1; then
  echo "Устанавливаю Node.js и PM2…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq nodejs npm
  npm install -g pm2
fi

bash "$ROOT/scripts/deploy.sh"

pm2 startup systemd -u root --hp /root || true
pm2 save

echo "PM2 готов. Статус:"
pm2 status
