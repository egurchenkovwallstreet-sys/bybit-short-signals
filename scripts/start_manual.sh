#!/usr/bin/env bash
# Запуск без PM2 (fallback), все 4 процесса.
set -euo pipefail

ROOT="${SIGNALS_ROOT:-/opt/signals}"
cd "$ROOT"

pkill -f ".venv/bin/python -m ws_server" 2>/dev/null || true
pkill -f ".venv/bin/python -m strategy_test" 2>/dev/null || true
pkill -f ".venv/bin/python -m collector" 2>/dev/null || true
pkill -f ".venv/bin/python -m signal_engine" 2>/dev/null || true
sleep 1

setsid .venv/bin/python -m collector >> logs-collector.txt 2>&1 < /dev/null &
setsid .venv/bin/python -m signal_engine >> logs-engine.txt 2>&1 < /dev/null &
setsid .venv/bin/python -m ws_server >> logs-ws.txt 2>&1 < /dev/null &
setsid .venv/bin/python -m strategy_test >> logs-btc-test.txt 2>&1 < /dev/null &

echo "Запущено вручную (без PM2)."
