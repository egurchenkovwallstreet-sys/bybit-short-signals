"""EMA6 closed history merge."""

from __future__ import annotations

import unittest

from signal_engine.live.em6_bybit.history import merge_closed_rows, summary_from_closed


class TestEm6ClosedHistory(unittest.TestCase):
    def test_merge_prefers_exchange(self) -> None:
        journal = [
            {
                "symbol": "X",
                "closed_at": 100,
                "entry_price": 1.0,
                "pnl_usd": 1.0,
                "source": "local",
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
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["pnl_usd"], 2.0)

    def test_summary(self) -> None:
        rows = [{"pnl_usd": 5}, {"pnl_usd": -1}]
        s = summary_from_closed(rows)
        self.assertEqual(s["closed_trades"], 2)
        self.assertEqual(s["win_rate"], 50.0)
        self.assertEqual(s["total_pnl_closed"], 4.0)


if __name__ == "__main__":
    unittest.main()
