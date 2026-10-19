import unittest

from signal_engine.paper.m5_htf import _body_fully_engulfs, _engulfing_first_bar
from signal_engine.state import Bar


def _bar(ts: int, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(timestamp=ts, open=o, high=h, low=l, close=c, volume=1.0)


class PivotEngulfTests(unittest.TestCase):
    def test_bearish_engulf_pivot_body(self) -> None:
        pivot = _bar(0, 100, 105, 99, 101)
        first = _bar(300_000, 102, 103, 98, 98)
        self.assertTrue(_body_fully_engulfs(first, pivot))
        self.assertTrue(_engulfing_first_bar(first, pivot, "short"))

    def test_bullish_engulf_prev_body(self) -> None:
        prev = _bar(0, 50, 51, 48, 49)
        first = _bar(300_000, 48, 52, 47, 51)
        self.assertTrue(_engulfing_first_bar(first, prev, "long"))

    def test_same_body_not_engulf(self) -> None:
        a = _bar(0, 10, 11, 9, 10.5)
        b = _bar(300_000, 10, 11, 9, 10.5)
        self.assertFalse(_body_fully_engulfs(b, a))


if __name__ == "__main__":
    unittest.main()
