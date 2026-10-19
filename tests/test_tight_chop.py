from signal_engine.paper.tight_chop import is_tight_chop, tight_chop_detail
from signal_engine.state import Bar, SymbolState


def _bars(closes, spread_pct=0.3):
    out = []
    t = 1_700_000_000_000
    for i, c in enumerate(closes):
        half = c * spread_pct / 100 / 2
        out.append(
            Bar(
                timestamp=t + i * 300_000,
                open=c,
                high=c + half,
                low=c - half,
                close=c,
                volume=1.0,
                from_kline=True,
            )
        )
    return out


def test_tight_chop_narrow_range():
    state = SymbolState(symbol="TEST")
    # ~0.3% total range over 20 bars
    state.bars_htf["5"] = _bars([100.0] * 20, spread_pct=0.25)
    state.last_price = 100.0
    now_ms = state.bars_htf["5"][-1].timestamp + 300_000
    tight, _ = is_tight_chop(state, now_ms)
    assert tight is True


def test_tight_chop_wide_range():
    state = SymbolState(symbol="TEST")
    closes = [100 + (i % 5) * 1.5 for i in range(24)]
    state.bars_htf["5"] = _bars(closes, spread_pct=1.2)
    state.last_price = closes[-1]
    now_ms = state.bars_htf["5"][-1].timestamp + 300_000
    d = tight_chop_detail(state, now_ms)
    assert d.get("tight") is False
