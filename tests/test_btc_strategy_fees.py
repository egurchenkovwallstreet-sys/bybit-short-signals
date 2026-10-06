import unittest

import config
from strategy_test.fees import net_pnl_pct, round_trip_fee_pct


class BtcStrategyFeesTest(unittest.TestCase):
    def test_round_trip_fee(self) -> None:
        self.assertAlmostEqual(round_trip_fee_pct(), 2 * config.BTC_TEST_FEE_RATE_TAKER * 100)

    def test_net_pnl_subtracts_fees(self) -> None:
        gross = 5.0
        net = net_pnl_pct(gross)
        self.assertLess(net, gross)
        self.assertAlmostEqual(net, gross - round_trip_fee_pct() * config.PNL_LEVERAGE)


if __name__ == "__main__":
    unittest.main()
