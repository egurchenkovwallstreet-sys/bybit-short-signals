#!/usr/bin/env bash
# Обновление кода на VPS после push в GitHub. Рестарт только затронутых PM2-процессов.
set -euo pipefail

ROOT="${SIGNALS_ROOT:-/opt/signals}"
cd "$ROOT"

PREV=$(git rev-parse HEAD)
git pull --ff-only
NEW=$(git rev-parse HEAD)

if [[ "$PREV" == "$NEW" ]]; then
  echo "Deploy OK: $(git rev-parse --short HEAD) (already up to date)"
  exit 0
fi

CHANGED=$(git diff --name-only "$PREV" "$NEW" || true)

needs_pip=false
restart_collector=false
restart_engine=false
restart_ws=false

while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  case "$f" in
    requirements.txt)
      needs_pip=true
      restart_collector=true
      restart_engine=true
      restart_ws=true
      ;;
    config.py)
      restart_collector=true
      restart_engine=true
      restart_ws=true
      ;;
    collector/*)
      restart_collector=true
      ;;
    signal_engine/*)
      restart_engine=true
      ;;
    ws_server/*)
      restart_ws=true
      ;;
    scripts/ecosystem.config.cjs)
      restart_collector=true
      restart_engine=true
      restart_ws=true
      ;;
  esac
done <<< "$CHANGED"

if $needs_pip; then
  .venv/bin/pip install -r requirements.txt -q
fi

_stop_orphans() {
  pkill -f ".venv/bin/python -m collector" 2>/dev/null || true
  pkill -f ".venv/bin/python -m signal_engine" 2>/dev/null || true
  pkill -f ".venv/bin/python -m ws_server" 2>/dev/null || true
  pkill -f ".venv/bin/python -m strategy_test" 2>/dev/null || true
}

if command -v pm2 >/dev/null 2>&1; then
  pm2 delete btc-strategy-test >/dev/null 2>&1 || true
  if ! pm2 describe collector >/dev/null 2>&1; then
    _stop_orphans
    sleep 1
    pm2 start "$ROOT/scripts/ecosystem.config.cjs"
    pm2 save
    echo "Deploy OK: $(git rev-parse --short HEAD) (pm2 first start)"
    exit 0
  fi

  if ! $restart_collector && ! $restart_engine && ! $restart_ws; then
    echo "Deploy OK: $(git rev-parse --short HEAD) (no PM2 restart; scripts/docs only)"
    exit 0
  fi

  $restart_collector && pm2 restart collector --update-env
  $restart_engine && pm2 restart signal-engine --update-env
  $restart_ws && pm2 restart ws-server --update-env
  pm2 save
else
  bash "$ROOT/scripts/start_manual.sh"
fi

echo "Deploy OK: $(git rev-parse --short HEAD) (collector=$restart_collector engine=$restart_engine ws=$restart_ws)"
