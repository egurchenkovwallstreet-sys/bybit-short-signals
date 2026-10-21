"""Удалить данные снятой вкладки «Анализ пампа» (pump_lab.db, board_watches)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import config

DATA = Path(config.DATA_DIR)


def main() -> None:
    lab = Path(config.PUMP_LAB_SQLITE_PATH)
    if lab.is_file():
        lab.unlink()
        print(f"removed {lab}")
    else:
        print(f"no file {lab}")

    sig = Path(config.SQLITE_PATH)
    if sig.is_file():
        conn = sqlite3.connect(sig)
        try:
            cur = conn.execute("DELETE FROM board_watches")
            conn.commit()
            print(f"board_watches deleted: {cur.rowcount} rows in {sig}")
        except sqlite3.OperationalError as e:
            print(f"board_watches skip: {e}")
        finally:
            conn.close()

    for pattern in ("pump_lab.db-wal", "pump_lab.db-shm"):
        p = DATA / pattern
        if p.is_file():
            p.unlink()
            print(f"removed {p}")


if __name__ == "__main__":
    main()
