"""Доска «Памп сигналы»: красная / жёлтая / зелёная колонки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import config
from signal_engine.evaluate import evaluate as evaluate_reading
from signal_engine.flow import taker_sellers_control
from signal_engine.paper.detect import (
    MANDATORY,
    find_pump,
    merged_15m,
    paper_entry_blocks,
    paper_t20_p10_tri_blocks,
)
from signal_engine.paper.tape import SymbolTape
from signal_engine.pump_scan import _weakening_score
from signal_engine.pump_unified import (
    detect_unified_episode,
    should_remove_after_peak_drawdown,
    symbol_has_unified_pump,
)
from signal_engine.stage_debounce import resolve_stage
from signal_engine.watch_store import WatchRow, WatchStore, growth_pct_negative

if TYPE_CHECKING:
    from signal_engine.paper.strategy import PaperStrategy
    from signal_engine.state import SymbolState

BOARD_ID = "pump_signals"
MSK = ZoneInfo("Europe/Moscow")
MIN_MS = 60_000

COLUMN_RED = "red"
COLUMN_YELLOW = "yellow"
COLUMN_GREEN = "green"
_COLUMN_RANK = {COLUMN_RED: 1, COLUMN_YELLOW: 2, COLUMN_GREEN: 3}
_RANK_COLUMN = {1: COLUMN_RED, 2: COLUMN_YELLOW, 3: COLUMN_GREEN}


def fmt_msk(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=MSK).strftime("%d.%m.%Y %H:%M")


def elapsed_label(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    m = int(max(0, minutes))
    if m < 60:
        return f"{m} мин"
    h, r = divmod(m, 60)
    if r == 0:
        return f"{h} ч"
    return f"{h} ч {r} мин"


def _passed_nine(checks: dict[str, dict]) -> int:
    return sum(1 for key in MANDATORY if (checks.get(key) or {}).get("ok"))


def _minutes_no_new_high(state: SymbolState, peak_ts: int, now_ms: int) -> float | None:
    peak = float(state.last_price or 0)
    if peak <= 0:
        return None
    hi_ts = peak_ts
    for bar in state.bars_1m:
        if bar.timestamp >= peak_ts and bar.high >= peak * 0.999:
            hi_ts = max(hi_ts, bar.timestamp)
    return max(0.0, (now_ms - hi_ts) / MIN_MS)


def raw_column(
    *,
    checks: dict[str, dict],
    metrics: dict,
    reading,
    weaken: int,
    drawdown: float | None,
    since_peak: float | None,
    minutes_no_high: float | None,
) -> str:
    stall = bool((checks.get("stall") or {}).get("ok"))
    oi = bool((checks.get("oi_1h_negative") or {}).get("ok"))
    sells = bool((checks.get("sells_dominate") or {}).get("ok"))
    faded = bool((checks.get("buys_faded") or {}).get("ok"))
    vol_f = bool((checks.get("volume_fade") or {}).get("ok"))
    liq = bool((checks.get("short_liq_faded") or {}).get("ok"))
    p9 = _passed_nine(checks)
    gate = not paper_entry_blocks(metrics)
    tri = not paper_t20_p10_tri_blocks(metrics, checks)
    cvd = bool(reading.cvd_divergence)
    taker_sell = taker_sellers_control(reading.taker_ratio)

    green_dd_max = config.PUMP_SIGNALS_GREEN_MAX_DRAWDOWN_PCT
    green_dd_min = config.PUMP_SIGNALS_GREEN_MIN_DRAWDOWN_PCT
    if (
        gate
        and tri
        and stall
        and oi
        and (sells or vol_f)
        and liq
        and (faded or sells)
        and p9 >= config.PUMP_SIGNALS_GREEN_MIN_PASSED
        and drawdown is not None
        and green_dd_min <= drawdown <= green_dd_max
        and since_peak is not None
        and config.PAPER_ENTRY_SINCE_PEAK_MIN <= since_peak <= config.PAPER_ENTRY_SINCE_PEAK_MAX
    ):
        return COLUMN_GREEN

    red_min = config.PUMP_SIGNALS_RED_MAX_SINCE_PEAK_MIN
    if not stall and since_peak is not None and since_peak < red_min:
        return COLUMN_RED
    if minutes_no_high is not None and minutes_no_high < config.PAPER_STALL_MIN_MINUTES:
        if p9 < 5 or not stall:
            return COLUMN_RED
    if drawdown is not None and drawdown < 2.0 and not stall:
        return COLUMN_RED
    if weaken <= 1 and not stall and (reading.oi_change_1h_pct or 0) > 0:
        return COLUMN_RED

    if drawdown is not None and drawdown > green_dd_max:
        return COLUMN_RED

    return COLUMN_YELLOW


def _column_rank(name: str) -> int:
    return _COLUMN_RANK.get(name, 1)


def _rank_to_column(rank: int) -> str:
    return _RANK_COLUMN.get(rank, COLUMN_RED)


@dataclass
class PumpSignalCard:
    symbol: str
    column: str
    last_price: float
    growth_start_ts: int
    growth_start_msk: str
    elapsed_min: float
    growth_pct: float
    volume_ratio: float | None
    taker_buy_pct: float | None
    taker_sell_pct: float | None
    taker_ratio: float | None
    oi_1h_pct: float | None
    oi_4h_pct: float | None
    drawdown_pct: float | None
    since_peak_min: float | None
    passed_count: int
    weaken_score: int
    trigger: str
    cvd_divergence: bool
    updated_at: int

    def to_data(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "column": self.column,
            "last_price": self.last_price,
            "growth_start_ts": self.growth_start_ts,
            "growth_start_msk": self.growth_start_msk,
            "elapsed_min": round(self.elapsed_min, 1),
            "elapsed_label": elapsed_label(self.elapsed_min),
            "growth_pct": round(self.growth_pct, 2),
            "volume_ratio": self.volume_ratio,
            "taker_buy_pct": self.taker_buy_pct,
            "taker_sell_pct": self.taker_sell_pct,
            "taker_ratio": self.taker_ratio,
            "oi_1h_pct": self.oi_1h_pct,
            "oi_4h_pct": self.oi_4h_pct,
            "drawdown_from_peak_pct": self.drawdown_pct,
            "since_peak_min": None if self.since_peak_min is None else round(self.since_peak_min),
            "passed_count": self.passed_count,
            "weaken_score": self.weaken_score,
            "trigger": self.trigger,
            "cvd_divergence": self.cvd_divergence,
            "updated_at": self.updated_at,
        }


def _tape_for(paper: PaperStrategy | None, symbol: str) -> SymbolTape | None:
    if paper is None:
        return None
    return paper.tape.symbols.get(symbol)


def _klines_for(paper: PaperStrategy | None, symbol: str) -> dict:
    if paper is None:
        return {}
    return paper.klines.get(symbol, {})


def _taker_pcts(taker_ratio: float | None) -> tuple[float | None, float | None]:
    if taker_ratio is None or taker_ratio == float("inf"):
        return None, None
    buy_pct = round(taker_ratio / (1 + taker_ratio) * 100, 1) if taker_ratio >= 0 else None
    if buy_pct is None:
        return None, None
    return buy_pct, round(100 - buy_pct, 1)


def build_pump_signals_board(
    states: dict[str, SymbolState],
    now_ms: int,
    watches: WatchStore,
    paper: PaperStrategy | None = None,
) -> dict:
    active = watches.active(BOARD_ID)
    for symbol, state in states.items():
        if symbol in active:
            continue
        row = watches.get(BOARD_ID, symbol)
        if row is not None and row.dismissed:
            continue
        if not symbol_has_unified_pump(state, now_ms):
            continue
        draft = detect_unified_episode(state, now_ms)
        if draft is None:
            continue
        row = WatchRow(
            board=BOARD_ID,
            symbol=symbol,
            entered_at=now_ms,
            dismissed=False,
            confirmed_stage=1,
            pending_stage=None,
            pending_since=None,
            meta={
                "peak_price": draft.peak_price,
                "valley_ts": draft.valley_ts,
                "column": COLUMN_RED,
            },
        )
        watches.upsert(row)
        active[symbol] = row

    cards: list[PumpSignalCard] = []
    for symbol, watch in list(active.items()):
        state = states.get(symbol)
        if state is None or state.last_price is None or state.last_price <= 0:
            continue
        peak = float(watch.meta.get("peak_price") or 0)
        if state.last_price > peak:
            peak = float(state.last_price)
            watch.meta["peak_price"] = peak
        if should_remove_after_peak_drawdown(state, peak):
            watches.remove(BOARD_ID, symbol)
            continue
        if growth_pct_negative(state):
            watches.remove(BOARD_ID, symbol)
            continue

        tape = _tape_for(paper, symbol)
        pump = find_pump(state, tape, now_ms)
        if pump is None:
            continue

        klines = _klines_for(paper, symbol)
        if not klines.get("15"):
            klines = {"15": merged_15m(state)}
        btc_pct = None
        from signal_engine.paper.detect import evaluate as eval_entry

        ev = eval_entry(state, tape or SymbolTape(), pump, klines, btc_pct, now_ms)
        reading = evaluate_reading(state, now_ms)
        weaken = _weakening_score(reading, now_ms, state)
        metrics = dict(ev.metrics)
        since_peak = (now_ms - pump.peak_ts) / MIN_MS
        metrics["since_peak_min"] = round(since_peak, 1)
        drawdown = metrics.get("drawdown_from_peak_pct")
        minutes_no_high = _minutes_no_new_high(state, pump.peak_ts, now_ms)
        candidate = raw_column(
            checks=ev.checks,
            metrics=metrics,
            reading=reading,
            weaken=weaken,
            drawdown=float(drawdown) if drawdown is not None else None,
            since_peak=since_peak,
            minutes_no_high=minutes_no_high,
        )
        prev = str(watch.meta.get("column") or COLUMN_RED)
        confirmed_rank, pending, pending_since = resolve_stage(
            confirmed=_column_rank(prev),
            candidate=_column_rank(candidate),
            pending_stage=watch.pending_stage,
            pending_since=watch.pending_since,
            now_ms=now_ms,
            continued_pump=False,
        )
        confirmed_col = _rank_to_column(confirmed_rank)
        watch.confirmed_stage = confirmed_rank
        watch.pending_stage = pending
        watch.pending_since = pending_since
        watch.meta["column"] = confirmed_col
        watch.meta["valley_ts"] = pump.valley_ts
        watches.upsert(watch)

        buy_pct, sell_pct = _taker_pcts(reading.taker_ratio)
        elapsed = max(0.0, (now_ms - pump.valley_ts) / MIN_MS)
        tr = reading.taker_ratio
        cards.append(
            PumpSignalCard(
                symbol=symbol,
                column=confirmed_col,
                last_price=float(state.last_price or pump.peak_price),
                growth_start_ts=pump.valley_ts,
                growth_start_msk=fmt_msk(pump.valley_ts),
                elapsed_min=elapsed,
                growth_pct=float(pump.growth_pct),
                volume_ratio=pump.volume_ratio,
                taker_buy_pct=buy_pct,
                taker_sell_pct=sell_pct,
                taker_ratio=round(tr, 3) if tr is not None else None,
                oi_1h_pct=reading.oi_change_1h_pct,
                oi_4h_pct=reading.oi_change_4h_pct,
                drawdown_pct=float(drawdown) if drawdown is not None else None,
                since_peak_min=since_peak,
                passed_count=ev.passed_count,
                weaken_score=weaken,
                trigger=str(pump.trigger or ""),
                cvd_divergence=reading.cvd_divergence,
                updated_at=now_ms,
            )
        )

    grouped: dict[str, list[PumpSignalCard]] = {
        COLUMN_GREEN: [],
        COLUMN_YELLOW: [],
        COLUMN_RED: [],
    }
    for card in cards:
        grouped[card.column].append(card)

    columns = []
    for col_id, title, hint in (
        (COLUMN_GREEN, "Готовы к шорту", "Памп остановился, разворот, откат от пика ≤15%"),
        (COLUMN_YELLOW, "Затухание", "Нет новых пиков, ослабление пампа"),
        (COLUMN_RED, "Активный рост", "Памп идёт, затухания мало"),
    ):
        ordered = sorted(
            grouped[col_id],
            key=lambda c: (c.passed_count, c.weaken_score, c.growth_pct),
            reverse=True,
        )
        columns.append(
            {
                "id": col_id,
                "title": title,
                "hint": hint,
                "signals": [c.to_data() for c in ordered],
            }
        )

    return {
        "type": "pump_signals_board",
        "timestamp": now_ms,
        "data": {"columns": columns},
    }
