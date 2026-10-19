from signal_engine.paper.ma333_regime import ma333_price_entry_ok, ma333_regime_detail
from signal_engine.state import Bar, SymbolState


def _bars_from_closes(closes: list[float], step_ms: int = 300_000) -> list[Bar]:
    t0 = 1_700_000_000_000
    out = []
    for i, c in enumerate(closes):
        out.append(
            Bar(
                timestamp=t0 + i * step_ms,
                open=c,
                high=c * 1.001,
                low=c * 0.999,
                close=c,
                volume=1.0,
                from_kline=True,
            )
        )
    return out


def _state_with_closes(closes: list[float], price: float | None = None) -> tuple[SymbolState, int]:
    state = SymbolState(symbol="TEST")
    state.bars_htf["5"] = _bars_from_closes(closes)
    state.last_price = price if price is not None else closes[-1]
    now_ms = state.bars_htf["5"][-1].timestamp + 300_000
    return state, now_ms


def _trend_closes(start: float, step: float, n: int) -> list[float]:
    return [start + i * step for i in range(n)]


def test_ma333_down_allows_short_blocks_long():
    closes = _trend_closes(100.0, -0.15, 150)
    state, now_ms = _state_with_closes(closes)
    d_short = ma333_regime_detail(state, now_ms, "short")
    d_long = ma333_regime_detail(state, now_ms, "long")
    assert d_short["regime"] == "down"
    assert d_short["ok"] is True
    assert d_long["ok"] is False


def test_ma333_up_allows_long_blocks_short():
    closes = _trend_closes(100.0, 0.15, 150)
    state, now_ms = _state_with_closes(closes)
    d_long = ma333_regime_detail(state, now_ms, "long")
    d_short = ma333_regime_detail(state, now_ms, "short")
    assert d_long["regime"] == "up"
    assert d_long["ok"] is True
    assert d_short["ok"] is False


def test_ma333_sideways_blocks_both():
    closes = [100.0 + (0.02 if i % 2 else -0.02) for i in range(150)]
    state, now_ms = _state_with_closes(closes)
    d_short = ma333_regime_detail(state, now_ms, "short")
    d_long = ma333_regime_detail(state, now_ms, "long")
    assert d_short["regime"] == "sideways"
    assert d_short["ok"] is False
    assert d_long["ok"] is False


def test_ma333_short_blocks_price_above_ema60():
    closes = _trend_closes(100.0, -0.15, 150)
    ema_zone = closes[-1]
    state, now_ms = _state_with_closes(closes, price=ema_zone + 5.0)
    d = ma333_regime_detail(state, now_ms, "short")
    assert d["regime"] == "down"
    assert d["ok"] is False


def test_ma333_long_blocks_price_below_ema60():
    closes = _trend_closes(100.0, 0.15, 150)
    ema_zone = closes[-1]
    state, now_ms = _state_with_closes(closes, price=ema_zone - 5.0)
    d = ma333_regime_detail(state, now_ms, "long")
    assert d["regime"] == "up"
    assert d["ok"] is False


def test_ma333_long_dead_zone_below_ema_in_downtrend():
    ok, _, zone = ma333_price_entry_ok("down", "long", 97.0, 100.0)
    assert ok is False
    assert zone is None


def test_ma333_long_stretch_below_ema_in_downtrend():
    ok, _, zone = ma333_price_entry_ok("down", "long", 95.0, 100.0)
    assert ok is True
    assert zone == "stretch"


def test_ma333_short_stretch_above_ema_in_uptrend():
    ok, _, zone = ma333_price_entry_ok("up", "short", 105.0, 100.0)
    assert ok is True
    assert zone == "stretch"


def test_ma333_short_dead_zone_above_ema_in_uptrend():
    ok, _, zone = ma333_price_entry_ok("up", "short", 102.0, 100.0)
    assert ok is False
    assert zone is None
