import unittest

from strategy_test.volatility import volatility_pct_24h


class VolatilityTest(unittest.TestCase):
    def test_range_and_change(self) -> None:
        candles = []
        for i in range(24):
            candles.append(
                {
                    "open": 100 + i,
                    "high": 110 + i,
                    "low": 90,
                    "close": 105 + i,
                    "volume": 1,
                }
            )
        vol = volatility_pct_24h(candles)
        self.assertIsNotNone(vol)
        assert vol is not None
        self.assertGreater(vol, 15)


if __name__ == "__main__":
    unittest.main()
