#!/usr/bin/env bash
# Обновление кода на VPS после push в GitHub. Запускать на сервере (Timeweb).
set -euo pipefail

ROOT="${SIGNALS_ROOT:-/opt/signals}"
cd "$ROOT"

git pull --ff-only

.venv/bin/pip install -r requirements.txt -q

_stop_orphans() {
  pkill -f ".venv/bin/python -m collector" 2>/dev/null || true
  pkill -f ".venv/bin/python -m signal_engine" 2>/dev/null || true
  pkill -f ".venv/bin/python -m ws_server" 2>/dev/null || true
  pkill -f ".venv/bin/python -m strategy_test" 2>/dev/null || true
}

if command -v pm2 >/dev/null 2>&1; then
  _stop_orphans
  sleep 1
  ECOSYSTEM="$ROOT/scripts/ecosystem.config.cjs"
  if pm2 describe collector >/dev/null 2>&1; then
    pm2 restart "$ECOSYSTEM" --update-env
  else
    pm2 start "$ECOSYSTEM"
  fi
  pm2 save
else
  bash "$ROOT/scripts/start_manual.sh"
fi

echo "Deploy OK: $(git rev-parse --short HEAD)"
