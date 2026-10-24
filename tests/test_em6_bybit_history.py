"""EMA6 closed history merge."""

from __future__ import annotations

import unittest

from signal_engine.live.em6_bybit.history import (
    enrich_exchange_with_journal,
    merge_closed_rows,
    summary_from_closed,
)


class TestEm6ClosedHistory(unittest.TestCase):
    def test_merge_prefers_exchange(self) -> None:
        journal = [
            {
                "symbol": "X",
                "closed_at": 100,
                "entry_price": 1.0,
                "pnl_usd": 1.0,
                "source": "local",
                "exit_reason": "trailing_stop",
            }
        ]
        exchange = [
            {
                "symbol": "X",
                "closed_at": 100,
                "entry_price": 1.0,
                "pnl_usd": 2.0,
                "source": "bybit",
            }
        ]
        merged = merge_closed_rows(exchange, journal)
        self.assertEqual(len(merged), 2)
        bybit_rows = [r for r in merged if r.get("source") == "bybit"]
        self.assertEqual(len(bybit_rows), 1)
        self.assertEqual(bybit_rows[0]["pnl_usd"], 2.0)

    def test_summary(self) -> None:
        rows = [{"pnl_usd": 5}, {"pnl_usd": -1}]
        s = summary_from_closed(rows)
        self.assertEqual(s["closed_trades"], 2)
        self.assertEqual(s["win_rate"], 50.0)
        self.assertEqual(s["total_pnl_closed"], 4.0)

    def test_enrich_journal_reason_only(self) -> None:
        exchange = [
            {
                "symbol": "BTCUSDT",
                "closed_at": 1000,
                "entry_price": 100.0,
                "pnl_usd": 3.5,
                "source": "bybit",
                "exit_reason": "exchange",
            }
        ]
        journal = [
            {
                "symbol": "BTCUSDT",
                "closed_at": 1000,
                "entry_price": 100.0,
                "pnl_usd": 1.0,
                "exit_reason": "trailing_stop",
                "source": "local",
            }
        ]
        out = enrich_exchange_with_journal(exchange, journal)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["pnl_usd"], 3.5)
        self.assertEqual(out[0]["exit_reason"], "trailing_stop")


if __name__ == "__main__":
    unittest.main()
