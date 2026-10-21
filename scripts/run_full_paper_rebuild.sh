#!/bin/bash
set -euo pipefail
cd /opt/signals
PY=".venv/bin/python"
export PYTHONPATH=/opt/signals

BK=$(ls -t data/paper_strategy.pre_rebuild_*.db 2>/dev/null | head -1 || true)
if [[ -n "${RESTORE_BACKUP:-}" && -n "$BK" ]]; then
  echo "restore from $BK"
  cp "$BK" data/paper_strategy.db
fi

echo "=== before ==="
$PY scripts/rebuild_paper_history.py report

echo "=== apply all closed ==="
$PY scripts/rebuild_paper_history.py apply --backup --all

echo "=== after ==="
$PY scripts/rebuild_paper_history.py report

pm2 restart signal-engine
echo "signal-engine restarted"
