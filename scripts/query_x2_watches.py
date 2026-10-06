import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config

c = sqlite3.connect(config.SQLITE_PATH)
rows = c.execute(
    "SELECT symbol, dismissed, confirmed_stage FROM board_watches WHERE board='x2_retrace' ORDER BY symbol"
).fetchall()
for row in rows:
    print(row)
