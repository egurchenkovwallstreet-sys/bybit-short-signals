from __future__ import annotations

import time
import unittest

from ws_server.cache import MarketCache


class LiquidationsByBarTests(unittest.TestCase):
    def test_buckets_last_two_bars(self) -> None:
        cache = MarketCache()
        symbol = "TESTUSDT"
        now = int(time.time() * 1000)
        t0 = now - 7_200_000
        t1 = now - 3_600_000
        cache.klines[(symbol, "60")] = [
            {"timestamp": t0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"timestamp": t1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ]
        cache.liquidations[symbol] = [
            {"time": t0 + 500_000, "price": 2.0, "size": 100.0, "side": "Buy"},
            {"time": t1 + 100_000, "price": 1.0, "size": 200.0, "side": "Sell"},
        ]
        out = cache.liquidations_by_bar(symbol, "60", bar_count=2)
        self.assertEqual(len(out["bars"]), 2)
        self.assertEqual(out["bars"][0]["long_usd"], 200.0)
        self.assertEqual(out["bars"][0]["short_usd"], 0.0)
        self.assertEqual(out["bars"][1]["short_usd"], 200.0)


if __name__ == "__main__":
    unittest.main()
