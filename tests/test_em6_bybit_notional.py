"""EMA6 Bybit: жёсткий номинал $500."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import config
from signal_engine.live.em6_bybit.broker import Em6BybitBroker


class TestFixedNotional(unittest.TestCase):
    def test_notional_default_500(self) -> None:
        self.assertAlmostEqual(config.em6_bybit_notional_usd(), 500.0)

    @patch.object(Em6BybitBroker, "_instrument", return_value=(1.0, 0.01))
    def test_ceil_meets_500(self, _inst: object) -> None:
        b = Em6BybitBroker()
        prep = b.prepare_fixed_notional_order("XUSDT", 100.0)
        self.assertIsNotNone(prep)
        _, qty, margin, notional = prep
        self.assertGreaterEqual(notional, 500.0)
        self.assertAlmostEqual(margin, notional / 10.0, places=2)


if __name__ == "__main__":
    unittest.main()
