# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

import config
from signal_engine.paper.position import Position
from signal_engine.paper.store import PaperStore
from signal_engine.paper.strategy import PaperStrategy
from signal_engine.paper.trade_side import liq_price_for_side, resolve_trade_side
from signal_engine.paper.vps_replay import replay_position_on_bars, replay_variant_trades
from signal_engine.state import Bar, SymbolState

NOW = 1_800_000_000_000
MIN = 60_000


def _row(**kwargs):
    base = {
        "id": 1,
        "symbol": "XUSDT",
        "kind": "vps15",
        "variant": "vps15",
        "side": "long",
        "opened_at": NOW,
        "entry_price": 10.0,
        "margin": 50.0,
        "leverage": 10,
        "funding_paid": 0.0,
        "entry_fee": 0.275,
        "stop_price": 9.9,
        "entry_json": json.dumps({"metrics": {"side": "long"}, "side": "long"}),
    }
    base.update(kwargs)
    return base


class ResolveTradeSideTest(unittest.TestCase):
    def test_entry_json_long_beats_variant_default(self) -> None:
        self.assertEqual(
            resolve_trade_side(kind="vps15", variant="vps15", entry={"metrics": {"side": "long"}}),
            "long",
        )

    def test_kind_suffix_long(self) -> None:
        self.assertEqual(resolve_trade_side(kind="impulse_long", variant="i5"), "long")

    def test_column_wins(self) -> None:
        self.assertEqual(
            resolve_trade_side(side="short", kind="vps15", entry={"metrics": {"side": "long"}}),
            "short",
        )


class VpsRestartKeepsLongTest(unittest.TestCase):
    def test_long_not_flipped_and_not_wiped_on_tiny_dip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.db"
            store = PaperStore(path)
            store.open()
            pos = Position(
                symbol="CAKEUSDT",
                opened_at=NOW,
                entry_price=2.1647,
                margin=50.0,
                side="long",
                stop_style="vps",
            )
            store.insert_trade(
                {
                    "symbol": "CAKEUSDT",
                    "variant": "vps15",
                    "kind": "vps15",
                    "status": "open",
                    "opened_at": NOW,
                    "entry_price": pos.entry_price,
                    "margin": pos.margin,
                    "leverage": pos.leverage,
                    "notional": pos.notional,
                    "qty": pos.qty,
                    "liq_price": pos.liq_price,
                    "stop_price": pos.stop_price,
                    "best_price": pos.best_price,
                    "worst_price": pos.worst_price,
                    "last_price": pos.entry_price,
                    "entry_fee": pos.entry_fee,
                    "funding_paid": 0.0,
                    "side": "long",
                    "entry_json": {
                        "metrics": {"side": "long", "signal_key": "long:1:2.1647"},
                        "side": "long",
                    },
                }
            )
            store.close()

            strategy = PaperStrategy(PaperStore(path))
            strategy.open()
            trade = strategy.trades[("vps15", "CAKEUSDT")]
            self.assertEqual(trade.pos.side, "long")
            self.assertLess(trade.pos.liq_price, pos.entry_price)
            self.assertLess(trade.pos.stop_price, pos.entry_price)
            self.assertAlmostEqual(
                trade.pos.liq_price,
                liq_price_for_side("long", pos.entry_price, pos.leverage),
            )

            dip = pos.entry_price * 0.996
            state = SymbolState("CAKEUSDT", last_price=dip)
            state.bars_1m = [Bar(NOW + MIN, pos.entry_price, pos.entry_price, dip, dip, 1.0)]
            strategy._update_trades({"CAKEUSDT": state}, NOW + 2 * MIN)
            self.assertIn(("vps15", "CAKEUSDT"), strategy.trades)
            strategy.close()


class VpsReplayRulesTest(unittest.TestCase):
    def test_long_small_move_stays_open(self) -> None:
        bars = [
            (NOW + MIN, 10.0, 10.02, 9.97, 9.99),
            (NOW + 2 * MIN, 9.99, 10.01, 9.96, 9.98),
        ]
        pos, reason, closed_at = replay_position_on_bars(
            symbol="X",
            side="long",
            opened_at=NOW,
            entry_price=10.0,
            margin=50.0,
            leverage=10,
            bars=bars,
            now_ms=NOW + 10 * MIN,
            variant="vps15",
        )
        self.assertIsNone(reason)
        self.assertIsNone(closed_at)
        self.assertEqual(pos.side, "long")
        self.assertGreater(pos.last_price, 9.9)

    def test_long_one_percent_down_hits_stop_not_liq(self) -> None:
        bars = [(NOW + MIN, 10.0, 10.0, 9.88, 9.88)]
        pos, reason, closed_at = replay_position_on_bars(
            symbol="X",
            side="long",
            opened_at=NOW,
            entry_price=10.0,
            margin=50.0,
            leverage=10,
            bars=bars,
            now_ms=NOW + 2 * MIN,
            variant="vps15",
        )
        self.assertEqual(reason, "trailing_stop")
        self.assertIsNotNone(closed_at)
        packed = pos.close_result(reason)
        self.assertGreater(packed["roe_pct"], -15.0)
        self.assertLess(packed["roe_pct"], -8.0)
        self.assertGreater(packed["exit_price"], pos.liq_price)

    def test_occupancy_skips_second_while_first_open(self) -> None:
        bars = {
            "XUSDT": [
                (NOW + MIN, 10.0, 10.02, 9.97, 9.99),
                (NOW + 10 * MIN, 9.99, 10.01, 9.96, 9.98),
            ]
        }
        first = _row(id=1, opened_at=NOW)
        second = _row(id=2, opened_at=NOW + 5 * MIN, entry_price=9.98)
        out = replay_variant_trades([first, second], bars, NOW + 20 * MIN)
        self.assertEqual(out[0].status, "open")
        self.assertTrue(out[1].skipped)
        self.assertEqual(out[1].reason, "слот занят")
        self.assertEqual(out[1].pnl_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
