#!/usr/bin/env bash
# Обновление кода на VPS после push в GitHub. Запускать на сервере (Timeweb).
set -euo pipefail

ROOT="${SIGNALS_ROOT:-/opt/signals}"
cd "$ROOT"

git pull --ff-only

.venv/bin/pip install -r requirements.txt -q

# Имена процессов PM2 задаются на этапе 6; если pm2 ещё нет — шаг пропускается.
if command -v pm2 >/dev/null 2>&1; then
  pm2 restart collector signal-engine ws-server || pm2 restart all
fi

echo "Deploy OK: $(git rev-parse --short HEAD)"
