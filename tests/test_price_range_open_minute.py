"""High/low в минуту входа не тянутся из прошлого бара."""

from __future__ import annotations

import unittest

from signal_engine.paper.strategy import _price_range
from signal_engine.state import Bar, SymbolState


class PriceRangeOpenMinuteTest(unittest.TestCase):
    def test_open_minute_ignores_pre_entry_wick(self) -> None:
        opened = 1_700_000_000_000
        state = SymbolState("X")
        state.last_price = 62.0
        state.bars_1m = [
            Bar(timestamp=opened, open=64.0, high=64.0, low=59.0, close=62.0, volume=1.0),
        ]
        low, high, last = _price_range(
            state,
            opened,
            opened_at_ms=opened + 30_000,
            entry_price=59.45,
        )
        self.assertEqual(last, 62.0)
        self.assertLessEqual(high, 62.0)
        self.assertGreaterEqual(low, 59.45)


if __name__ == "__main__":
    unittest.main()
