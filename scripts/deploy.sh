#!/usr/bin/env bash
# Обновление кода на VPS после push в GitHub. Запускать на сервере (Timeweb).
set -euo pipefail

ROOT="${SIGNALS_ROOT:-/opt/signals}"
cd "$ROOT"

git pull --ff-only

.venv/bin/pip install -r requirements.txt -q

# Имена процессов PM2 задаются на этапе 6; если pm2 ещё нет — шаг пропускается.
if command -v pm2 >/dev/null 2>&1; then
  pm2 restart collector signal-engine ws-server btc-strategy-test || pm2 restart all
else
  pkill -f ".venv/bin/python -m ws_server" 2>/dev/null || true
  pkill -f ".venv/bin/python -m strategy_test" 2>/dev/null || true
  cd "$ROOT"
  setsid .venv/bin/python -m ws_server >> logs-ws.txt 2>&1 < /dev/null &
  setsid .venv/bin/python -m strategy_test >> logs-btc-test.txt 2>&1 < /dev/null &
fi

echo "Deploy OK: $(git rev-parse --short HEAD)"
