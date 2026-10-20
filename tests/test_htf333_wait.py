"""333 HTF waitlist helpers."""
from __future__ import annotations

import unittest

from signal_engine.paper.htf333_wait import (
    _nearest_opposing_in_band,
    htf_wait_pivots_broken,
)
from signal_engine.state import SymbolState


class Htf333WaitTest(unittest.TestCase):
    def test_nearest_trough_within_band(self) -> None:
        pivots = [{"price": 96.0, "time": 1}]
        hit = _nearest_opposing_in_band(pivots, "short", 100.0, 4.0)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit["dist_pct"], 4.0)

    def test_trough_too_far(self) -> None:
        pivots = [{"price": 90.0, "time": 1}]
        self.assertIsNone(_nearest_opposing_in_band(pivots, "short", 100.0, 4.0))

    def test_broken_trough(self) -> None:
        state = SymbolState("X", last_price=95.0)
        wait = {"h1": {"kind": "trough", "price": 96.0}, "h4": {"kind": "trough", "price": 96.0}}
        self.assertTrue(htf_wait_pivots_broken(state, wait))

    def test_unbroken_trough(self) -> None:
        state = SymbolState("X", last_price=97.0)
        wait = {"h1": {"kind": "trough", "price": 96.0}, "h4": {"kind": "trough", "price": 96.0}}
        self.assertFalse(htf_wait_pivots_broken(state, wait))


if __name__ == "__main__":
    unittest.main()
