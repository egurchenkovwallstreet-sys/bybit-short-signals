"""333: лист ожидания у H1/H4 — близкий противоположный pivot, вход после согласования по направлению."""

from __future__ import annotations

import config
from signal_engine.paper.vacuum_senior_gate import _confirms_down, _confirms_up, _unbroken_pivots
from signal_engine.state import SymbolState
from signal_engine.swing_highs import closed_bars

_HTF = ("60", "240")
_HTF_LABEL = {"60": "h1", "240": "h4"}


def _dist_pct(from_price: float, to_price: float) -> float:
    if from_price <= 0:
        return 999.0
    return abs(to_price - from_price) / from_price * 100.0


def _nearest_opposing_in_band(
    pivots: list[dict],
    side: str,
    price: float,
    max_pct: float,
) -> dict | None:
    """short — trough ниже цены в пределах max_pct; long — peak выше."""
    best: dict | None = None
    best_dist = max_pct + 1.0
    for p in pivots:
        level = float(p["price"])
        if side == "short":
            if level >= price:
                continue
            dist = _dist_pct(price, level)
        else:
            if level <= price:
                continue
            dist = _dist_pct(price, level)
        if dist <= max_pct and dist < best_dist:
            best_dist = dist
            best = {
                "price": level,
                "time": int(p["time"]),
                "kind": "trough" if side == "short" else "peak",
                "dist_pct": round(dist, 3),
            }
    return best


def htf_opposing_too_close(
    state: SymbolState,
    now_ms: int,
    side: str,
) -> tuple[bool, dict]:
    """
    И short, и long: на 1H и 4H есть непробитый противоположный pivot
    в направлении движения ближе PAPER_333_HTF_OPPOSE_MAX_DIST_PCT %.
    """
    if side not in ("short", "long"):
        return False, {}
    price = float(state.last_price or 0)
    if price <= 0:
        return False, {}
    max_pct = float(config.PAPER_333_HTF_OPPOSE_MAX_DIST_PCT)
    kind = "trough" if side == "short" else "peak"
    meta: dict = {"side": side, "price": price}
    for tf in _HTF:
        bars = closed_bars(state.bars_htf.get(tf) or [], tf, now_ms)
        if len(bars) < 40:
            return False, {}
        pivots = _unbroken_pivots(bars, kind)
        hit = _nearest_opposing_in_band(pivots, side, price, max_pct)
        if hit is None:
            return False, {}
        meta[_HTF_LABEL[tf]] = hit
    return True, meta


def htf_senior_direction_ok(state: SymbolState, now_ms: int, side: str) -> tuple[bool, str]:
    """1H и 4H подтверждают сторону (LH↓ для шорта, HL↑ для лонга), как senior gate."""
    if side not in ("short", "long"):
        return False, "нет стороны"
    parts: list[str] = []
    for tf in _HTF:
        bars = closed_bars(state.bars_htf.get(tf) or [], tf, now_ms)
        if len(bars) < 40:
            return False, f"мало {tf}m"
        if side == "short":
            pivots = _unbroken_pivots(bars, "peak")
            prices = [float(p["price"]) for p in pivots]
            if not _confirms_down(prices):
                return False, f"{tf}m LH не ↓"
            parts.append(f"{tf}m↓")
        else:
            pivots = _unbroken_pivots(bars, "trough")
            prices = [float(p["price"]) for p in pivots]
            if not _confirms_up(prices):
                return False, f"{tf}m HL не ↑"
            parts.append(f"{tf}m↑")
    return True, " ".join(parts)


def htf_wait_pivots_broken(state: SymbolState, wait: dict) -> bool:
    """Снять с листа: цена пробила сохранённые старшие уровни."""
    price = float(state.last_price or 0)
    if price <= 0:
        return False
    for key in ("h1", "h4"):
        p = wait.get(key)
        if not p:
            return True
        level = float(p["price"])
        kind = str(p.get("kind") or "")
        if kind == "trough":
            if price < level * (1.0 - 1e-9):
                return True
        elif kind == "peak":
            if price > level * (1.0 + 1e-9):
                return True
    return False


def wait_record_from_meta(side: str, meta: dict, now_ms: int) -> dict:
    return {
        "side": side,
        "added_at_ms": int(now_ms),
        "h1": dict(meta.get("h1") or {}),
        "h4": dict(meta.get("h4") or {}),
    }
