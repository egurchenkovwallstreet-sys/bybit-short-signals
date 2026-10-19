"""Тест стратегии: сам ищет пампы, ждёт затухания, открывает и ведёт виртуальные шорты.

Кандидат — один памп одной монеты. Пока он жив, каждые 3 секунды проверяются
все обязательные условия. Три варианта с одним входом (шлюз + 5 из 9) и разными
выходами: t20 (+3%→+0.5% net / +7%→+5% / трейл 20 п.п.), p10 (+3%→+0.5% net / +10%→+2% net и пик − 10)
и Молния (−10% ROE, +2.5%→+2%, +6%→+4%, +7%→+5%, дальше трейл пик − 20 п.п.).
Копии Трейл 20+ / 10 п.п.+ / Молния+ берут тот же выход, но входят только когда
прошли все жёсткие проверки plus_detect. У каждого свой счёт. Не хватило ровно одного из 9 — теневая сделка.
Всё пишется в SQLite для анализа.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import config
from signal_engine.flow import oi_change_pct
from signal_engine.paper.analytics import compute_analytics
from signal_engine.paper.detect import (
    CHECK_LABELS,
    ENTRY_GATE_LABELS,
    MANDATORY,
    VARIANT_LABELS,
    PumpInfo,
    apply_peak_measurement,
    btc_change_4h,
    evaluate,
    find_pump,
    grade_for,
    measure_pump_peak,
    paper_entry_blocks,
    C3_CHECK_LABELS,
    C3_MANDATORY,
    MINI_CHECK_LABELS,
    MINI_MANDATORY,
    cursor3_view,
    mini_pump_floors,
    mini_view,
    mini_chart_view,
    MINI_CHART_MANDATORY,
    MINI_CHART_CHECK_LABELS,
)
from signal_engine.paper.graf_detect import GRAF_CHECK_LABELS, GRAF_MANDATORY, evaluate_grafik
from signal_engine.paper.dps_detect import DPS_CHECK_LABELS, DPS_MANDATORY, evaluate_dps
from signal_engine.paper.lh_scan_pivot import snapshot_pivot_levels
from signal_engine.vacuum_lh import hour_range_pct
from signal_engine.paper.m5_htf import (
    opposite_anchor_pivot_exit,
    opposite_appeared,
    opposite_pivot_exit_signal,
    symbols_waiting_htf_second_bar,
)
from signal_engine.paper.pivot_clock import (
    entry_on_third_bar,
    just_confirmed,
    symbols_waiting_second_bar,
    vps15_entry_confirmed,
)
from signal_engine.paper.pyl_detect import (
    PYL1_CHECK_LABELS,
    PYL1_MANDATORY_5,
    PYLBTC_CHECK_LABELS,
    PYLBTC_MANDATORY_5,
    PYL333_CHECK_LABELS,
    PYL333_MANDATORY_5,
    PYL_CHECK_LABELS,
    PYL_MANDATORY,
    evaluate_htf_pivot_entry,
    evaluate_333,
    evaluate_pyl,
    evaluate_pyl1,
    evaluate_pylbtc,
)
from signal_engine.paper.position import bab_pivot_stop_price
from signal_engine.paper.trade_side import liq_price_for_side, resolve_trade_side
from signal_engine.paper.vac_detect import VAC_CHECK_LABELS, VAC_MANDATORY, evaluate_vac
from signal_engine.paper.vac_lh_detect import VPS_CHECK_LABELS, VPS_MANDATORY
from signal_engine.paper.css_detect import (
    CSS_CHECK_LABELS,
    CSS_MANDATORY,
    CssEvaluation,
    CssPumpInfo,
    evaluate_css,
    find_css_pump,
    refresh_css_peak,
)
from signal_engine.paper.css2_detect import (
    CSS2_CHECK_LABELS,
    CSS2_MANDATORY,
    Css2Evaluation,
    Css2PumpInfo,
    closed_15m_above_peak,
    evaluate_css2,
    find_css2_pump,
    peak_on_open_15m,
)
from signal_engine.paper.sc10_detect import (
    SC10_CHECK_LABELS,
    SC10_MANDATORY,
    Sc10Evaluation,
    evaluate_sc10,
)
from signal_engine.paper.e5s_detect import (
    E5S_CHECK_LABELS,
    E5S_MANDATORY,
    evaluate_e5s,
)
from signal_engine.paper.impulse_detect import (
    IMPULSE_CHECK_LABELS,
    IMPULSE5_EXTRA_MANDATORY,
    IMPULSE_MANDATORY,
    evaluate_impulse,
    impulse_mandatory,
)
from signal_engine.paper.plus_detect import (
    PLUS_CHECK_LABELS,
    PLUS_MANDATORY,
    evaluate_plus,
    plus_hit_first_stop,
)
from signal_engine.paper.growth_detect import (
    GROWTH_CHECK_LABELS,
    GROWTH_CORE,
    GROWTH_FLEX,
    GrowthEvaluation,
    GrowthInfo,
    evaluate_growth,
    find_growth,
    refresh_growth_peak,
)
from signal_engine.paper.position import Position
from signal_engine.paper.store import PaperStore
from signal_engine.paper.tape import TapeBook, minute_start
from signal_engine.state import Bar, SymbolState

log = logging.getLogger(__name__)

BOARD_TYPE = "paper_test"
VARIANTS = config.PAPER_VARIANTS
_SHADOW_MARGIN = config.PAPER_START_BALANCE_USD * config.PAPER_MARGIN_PCT / 100.0
_REASON_CONDITIONS = "условия пампа больше не выполняются"
_MINUTES_KEEP_MS = 180 * 60_000


@dataclass
class OpenTrade:
    id: int
    variant: str
    symbol: str
    kind: str
    pos: Position
    score: float
    grade: str
    strict_btc: bool
    entry: dict
    candidate_id: int | None
    last_check: int


@dataclass
class GrowthCandidate:
    id: int
    symbol: str
    growth: GrowthInfo
    started_at: int
    scans: int = 0
    fail_counts: dict[str, int] = field(default_factory=dict)
    best_passed: int = 0
    last_eval: dict | None = None
    entered: list[str] = field(default_factory=list)
    last_trade_id: int | None = None
    note: str | None = None
    dirty: bool = True


@dataclass
class CssCandidate:
    id: int
    symbol: str
    pump: CssPumpInfo
    started_at: int
    scans: int = 0
    fail_counts: dict[str, int] = field(default_factory=dict)
    best_passed: int = 0
    last_eval: dict | None = None
    entered: list[str] = field(default_factory=list)
    last_trade_id: int | None = None
    note: str | None = None
    dirty: bool = True
    entries_used: int = 0
    rearm_needed: bool = False


@dataclass
class Css2Candidate:
    id: int
    symbol: str
    pump: Css2PumpInfo
    started_at: int
    scans: int = 0
    fail_counts: dict[str, int] = field(default_factory=dict)
    best_passed: int = 0
    last_eval: dict | None = None
    entered: list[str] = field(default_factory=list)
    last_trade_id: int | None = None
    note: str | None = None
    dirty: bool = True
    entries_used: int = 0


class _EvalView:
    """Чужой набор проверок в том виде, в каком его ждёт открытие сделки."""

    def __init__(self, data: dict):
        self.score = float(data.get("score") or 0)
        self.strict_btc = bool(data.get("strict_btc"))
        self.passed_count = int(data.get("passed_count") or 0)
        self._data = data

    def to_data(self) -> dict:
        return self._data


@dataclass
class Candidate:
    id: int
    symbol: str
    pump: PumpInfo
    started_at: int
    scans: int = 0
    fail_counts: dict[str, int] = field(default_factory=dict)
    best_passed: int = 0
    last_eval: dict | None = None
    near_miss: bool = False
    entered: list[str] = field(default_factory=list)
    last_trade_id: int | None = None
    note: str | None = None
    dirty: bool = True
    soft: bool = False


@dataclass
class Shadow:
    candidate_id: int
    symbol: str
    missing: str
    pos: Position
    last_check: int


class PaperStrategy:
    def __init__(self, store: PaperStore | None = None) -> None:
        self.store = store or PaperStore(config.PAPER_SQLITE_PATH)
        self.tape = TapeBook()
        self.klines: dict[str, dict[str, list[Bar]]] = {}
        self.kline_at: dict[str, float] = {}
        # Пустой dict: _ensure_balance подгружает из paper_kv после перезапуска.
        self.balances: dict[str, float] = {}
        self.trades: dict[tuple[str, str], OpenTrade] = {}
        self.candidates: dict[str, Candidate] = {}
        self.growth_candidates: dict[str, GrowthCandidate] = {}
        self.css_candidates: dict[str, CssCandidate] = {}
        self.css2_candidates: dict[str, Css2Candidate] = {}
        self.css2_blocked: dict[str, int] = {}
        self.plus_blocked: dict[str, set[int]] = {}
        self._sc10_used_bars: dict[str, int] = {}
        self._impulse_used_bars: dict[tuple[str, str], int] = {}
        self._pyl_prev_snap: dict[str, dict] = {}
        self._pyl_watch: list[dict] = []
        self._pyl1_prev_snap: dict[str, dict] = {}
        self._pyl1_watch: list[dict] = []
        self._pylbtc_prev_snap: dict[str, dict] = {}
        self._pylbtc_watch: list[dict] = []
        self._333_prev_snap: dict[str, dict] = {}
        self._333_watch: list[dict] = []
        self._vac_used_bars: dict[tuple[str, str], int] = {}
        self._vac_watch: list[dict] = []
        self._vps_prev_snap: dict[tuple[str, str], dict] = {}
        self._vps_used_signals: dict[tuple[str, str], str] = {}
        self._vps15_watch: list[dict] = []
        self._vps5_watch: list[dict] = []
        self._confirm_arm: set[str] = set()
        self._confirm_arm_at = 0
        self._confirm_arm_15: set[str] = set()
        self._confirm_arm_15_at = 0
        self.shadows: dict[int, Shadow] = {}
        self.last_close: dict[tuple[str, str], int] = {}
        self.expired_peaks: dict[str, int] = {}
        self.peak_snapshots: dict[str, tuple[float, int]] = {}
        self.started_ms = int(time.time() * 1000)
        self._next_detect = 0
        self._next_persist = 0
        self._next_equity = 0
        self._next_tape = 0
        self._next_analytics = 0
        self._analytics: dict = {}
        self._opened = False

    # --- жизненный цикл ---

    def open(self) -> None:
        self.store.open()
        now = int(time.time() * 1000)
        self.started_ms = now
        blocked = _loads(self.store.get_kv("css2_blocked")) or {}
        if isinstance(blocked, dict):
            self.css2_blocked = {str(k): int(v) for k, v in blocked.items() if v}
        plus_blocked = _loads(self.store.get_kv("plus_blocked_peaks")) or {}
        if isinstance(plus_blocked, dict):
            self.plus_blocked = {
                str(symbol): {int(ts) for ts in peaks if ts}
                for symbol, peaks in plus_blocked.items()
                if isinstance(peaks, list)
            }
        if self.store.get_kv("started_at") is None:
            self.store.set_kv("started_at", str(now))
        for variant in VARIANTS:
            self._ensure_balance(variant)
        if self.store.get_kv("revived_restart_expiry") is None:
            # До защиты от перезапуска кандидаты снимались, пока свечи ещё не подгрузились.
            since = now - config.PAPER_LONG_LIFETIME_HOURS * 3_600_000
            revived = self.store.revive_candidates(_REASON_CONDITIONS, since)
            self.store.set_kv("revived_restart_expiry", str(now))
            if revived:
                log.info("Тест: возвращено кандидатов после ошибочного снятия: %s", revived)
        self._retire_removed_variants(now)
        for row in self.store.open_trades():
            variant = str(row["variant"] or config.PAPER_T20_VARIANT)
            self._ensure_balance(variant)
            gap = config.paper_peak_gap_roe(variant)
            kind = str(row["kind"] or "")
            entry = _loads(row["entry_json"])
            side = resolve_trade_side(
                side=row["side"] if "side" in row.keys() else None,
                kind=kind,
                variant=variant,
                entry=entry,
            )
            entry_px = float(row["entry_price"])
            lev = int(row["leverage"])
            pos = Position(
                symbol=row["symbol"],
                opened_at=int(row["opened_at"]),
                entry_price=entry_px,
                margin=float(row["margin"]),
                leverage=lev,
                best_price=float(row["best_price"]),
                worst_price=float(row["worst_price"]),
                stop_price=float(row["stop_price"]),
                liq_price=liq_price_for_side(side, entry_px, lev),
                entry_fee=float(row["entry_fee"]),
                funding_paid=float(row["funding_paid"] or 0),
                next_funding_ts=row["next_funding_ts"],
                last_price=float(row["last_price"] or row["entry_price"]),
                peak_gap_roe=gap,
                side=side,
                stop_style=config.paper_stop_style(variant),
                scaled_half=bool((entry or {}).get("css2_half")),
            )
            # Стоп по правилу варианта: t20 — +0.5% net/лок/трейл 20, p10 — +0.5% net и пик − gap.
            pos._sync_stop(float(row["last_price"] or row["entry_price"]))
            self.trades[(variant, row["symbol"])] = OpenTrade(
                id=int(row["id"]),
                variant=variant,
                symbol=row["symbol"],
                kind=str(row["kind"] or ""),
                pos=pos,
                score=float(row["score"] or 0),
                grade=str(row["grade"] or "C"),
                strict_btc=bool(row["strict_btc"]),
                entry=_loads(row["entry_json"]),
                candidate_id=row["candidate_id"],
                last_check=now,
            )
            if variant == config.PAPER_SC10_VARIANT:
                bar_ts = int((((_loads(row["entry_json"]) or {}).get("metrics") or {}).get("pump") or {}).get("bar_ts") or 0)
                if bar_ts:
                    self._sc10_used_bars[row["symbol"]] = bar_ts
            if variant in config.PAPER_IMPULSE_VARIANTS:
                bar_ts = int((((_loads(row["entry_json"]) or {}).get("metrics") or {}).get("bar_ts")) or 0)
                if bar_ts:
                    self._impulse_used_bars[(variant, row["symbol"])] = bar_ts
            if variant == config.PAPER_VAC_VARIANT:
                bar_ts = int((((_loads(row["entry_json"]) or {}).get("metrics") or {}).get("bar_ts")) or 0)
                if bar_ts:
                    self._vac_used_bars[(variant, row["symbol"])] = bar_ts
            if variant in config.PAPER_VPS_VARIANTS or variant == "vps":
                v = variant if variant in config.PAPER_VPS_VARIANTS else config.PAPER_VPS15_VARIANT
                sk = str(((_loads(row["entry_json"]) or {}).get("metrics") or {}).get("signal_key") or "")
                if sk:
                    self._vps_used_signals[(v, row["symbol"])] = sk
        if config.PAPER_CSS_VARIANT not in VARIANTS:
            dropped_css = self.store.expire_kind_watching("css", "Cursor SS снят с теста", now)
            if dropped_css:
                log.info("Тест: сняты кандидаты Cursor SS: %s", dropped_css)
        active = sorted(self.store.active_candidates(), key=lambda r: (int(r["peak_ts"] or 0), int(r["id"])))
        for row in active:
            if str(row["kind"] or "") == "growth":
                growth = _growth_from_row(row)
                self.growth_candidates[row["symbol"]] = GrowthCandidate(
                    id=int(row["id"]),
                    symbol=row["symbol"],
                    growth=growth,
                    started_at=int(row["started_at"]),
                    scans=int(row["scans"] or 0),
                    fail_counts=_loads(row["fail_counts"]) or {},
                    best_passed=int(row["best_passed"] or 0),
                    last_eval=_loads(row["last_eval"]) or None,
                    entered=_loads_list(row["variants"]),
                    last_trade_id=row["trade_id"],
                    dirty=False,
                )
                if growth.peak_price > 0:
                    self.peak_snapshots[row["symbol"]] = (growth.peak_price, growth.peak_ts)
                continue
            if str(row["kind"] or "") == "sc10":
                continue
            if str(row["kind"] or "") == "css2":
                pump = _css2_from_row(row)
                css2_state = (_loads(row["last_eval"]) or {}).get("css2_state") or {}
                self.css2_candidates[row["symbol"]] = Css2Candidate(
                    id=int(row["id"]),
                    symbol=row["symbol"],
                    pump=pump,
                    started_at=int(row["started_at"]),
                    scans=int(row["scans"] or 0),
                    fail_counts=_loads(row["fail_counts"]) or {},
                    best_passed=int(row["best_passed"] or 0),
                    last_eval=_loads(row["last_eval"]) or None,
                    entered=_loads_list(row["variants"]),
                    last_trade_id=row["trade_id"],
                    dirty=False,
                    entries_used=int(css2_state.get("entries_used") or 0),
                )
                if pump.peak_price > 0:
                    self.peak_snapshots[row["symbol"]] = (pump.peak_price, pump.peak_ts)
                continue
            if str(row["kind"] or "") == "css":
                pump = _css_from_row(row)
                css_state = (_loads(row["last_eval"]) or {}).get("css_state") or {}
                self.css_candidates[row["symbol"]] = CssCandidate(
                    id=int(row["id"]),
                    symbol=row["symbol"],
                    pump=pump,
                    started_at=int(row["started_at"]),
                    scans=int(row["scans"] or 0),
                    fail_counts=_loads(row["fail_counts"]) or {},
                    best_passed=int(row["best_passed"] or 0),
                    last_eval=_loads(row["last_eval"]) or None,
                    entered=_loads_list(row["variants"]),
                    last_trade_id=row["trade_id"],
                    dirty=False,
                    entries_used=int(css_state.get("entries_used") or 0),
                    rearm_needed=bool(css_state.get("rearm_needed")),
                )
                if pump.peak_price > 0:
                    self.peak_snapshots[row["symbol"]] = (pump.peak_price, pump.peak_ts)
                continue
            older = self.candidates.get(row["symbol"])
            if older is not None:
                self._end_candidate(older, "дубль после перезапуска", now)
            pump = _pump_from_row(row)
            last_eval = _apply_entry_gate(_loads(row["last_eval"]) or None)
            self.candidates[row["symbol"]] = Candidate(
                id=int(row["id"]),
                symbol=row["symbol"],
                pump=pump,
                started_at=int(row["started_at"]),
                scans=int(row["scans"] or 0),
                fail_counts=_loads(row["fail_counts"]) or {},
                best_passed=int(row["best_passed"] or 0),
                last_eval=last_eval,
                near_miss=row["near_miss_at"] is not None,
                entered=_loads_list(row["variants"]),
                last_trade_id=row["trade_id"],
                dirty=False,
                soft=str(row["kind"] or "") == "mini",
            )
            if pump.peak_price > 0:
                self.peak_snapshots[row["symbol"]] = (pump.peak_price, pump.peak_ts)
        for row in self.store.open_trades():
            sym = str(row["symbol"])
            if sym not in self.peak_snapshots:
                entry = _loads(row["entry_json"]) or {}
                ep = ((entry.get("metrics") or {}).get("pump") or {})
                if ep.get("peak_price"):
                    self.peak_snapshots[sym] = (float(ep["peak_price"]), int(ep.get("peak_ts") or 0))
        for row in self.store.open_shadows():
            pos = Position(
                symbol=row["symbol"],
                opened_at=int(row["shadow_opened_at"]),
                entry_price=float(row["shadow_entry_price"]),
                margin=float(row["shadow_margin"] or _SHADOW_MARGIN),
                best_price=float(row["shadow_best"]),
                worst_price=float(row["shadow_worst"] or row["shadow_entry_price"]),
                stop_price=float(row["shadow_stop"]),
                liq_price=float(row["shadow_liq"]),
                entry_fee=float(row["shadow_entry_fee"]),
            )
            self.shadows[int(row["id"])] = Shadow(
                candidate_id=int(row["id"]),
                symbol=row["symbol"],
                missing=str(row["near_miss_missing"] or ""),
                pos=pos,
                last_check=now,
            )
        self.last_close = self.store.last_close_by_symbol()
        for row in self.store.db.execute(
            "SELECT symbol, MAX(peak_ts) AS ts FROM paper_candidates WHERE status != 'watching' GROUP BY symbol"
        ):
            if row["ts"] is not None:
                self.expired_peaks[str(row["symbol"])] = int(row["ts"])
        self._load_tape(now)
        dropped = self.store.expire_kind_watching("sc10", "скальп без претендентов", now)
        if dropped:
            log.info("Тест: снято претендентов Скальп 10: %s", dropped)
        self._analytics = compute_analytics(
            self.store.db,
            self.balances,
            now_ms=now,
            unrealized={v: self.unrealized(v) for v in VARIANTS},
        )
        self._opened = True
        log.info(
            "Тест стратегии: балансы %s, открытых %s, кандидатов %s, роста %s, Cursor SS %s, СС 2 %s, теневых %s",
            ", ".join(f"{v} {self.balances[v]:.2f}" for v in VARIANTS),
            len(self.trades),
            len(self.candidates),
            len(self.growth_candidates),
            len(self.css_candidates),
            len(self.css2_candidates),
            len(self.shadows),
        )

    def close(self) -> None:
        if self._opened:
            now = int(time.time() * 1000)
            self._persist(now, force=True)
            self._save_tape(now)
        self.store.close()

    # --- входящие данные ---

    def ingest(self, message: dict) -> None:
        self.tape.ingest(message)

    def kline_wanted(self) -> list[str]:
        return sorted(
            set(self.candidates)
            | set(self.growth_candidates)
            | set(self.css_candidates)
            | set(self.css2_candidates)
        )

    def on_klines(self, symbol: str, interval: str, candles: list[dict]) -> None:
        bars = []
        for row in candles:
            try:
                bars.append(
                    Bar(
                        int(row["timestamp"]),
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        float(row["volume"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if bars:
            self.klines.setdefault(symbol, {})[interval] = bars
            self.kline_at[symbol] = time.time()

    # --- скан ---

    def bab_open_symbols(self) -> set[str]:
        desk = {
            config.PAPER_PYL_VARIANT,
            config.PAPER_PYL1_VARIANT,
            config.PAPER_PYLBTC_VARIANT,
            config.PAPER_333_VARIANT,
            config.PAPER_VPS5_VARIANT,
            config.PAPER_VPS15_VARIANT,
        }
        return {t.symbol for t in self.trades.values() if t.variant in desk and t.variant in VARIANTS}

    def process_bab_opposite_exits(self, states: dict[str, SymbolState], now_ms: int) -> None:
        """Жёсткое закрытие по противоп. pivot — каждый тик скана, не только окно 5m."""
        self._process_bab_opposite_exits(states, now_ms)

    def scan(self, states: dict[str, SymbolState], now_ms: int, *, pivots: bool = True) -> dict:
        btc_4h = btc_change_4h(states.get(config.PAPER_BTC_SYMBOL), now_ms)
        self._process_bab_opposite_exits(states, now_ms)
        self._process_manual_closes(states, now_ms)
        self._refresh_peaks(states, now_ms)
        if config.PAPER_LT20_VARIANT in VARIANTS:
            self._refresh_growth_peaks(states, now_ms)
        if config.PAPER_CSS_VARIANT in VARIANTS:
            self._refresh_css_peaks(states, now_ms)
        self._update_trades(states, now_ms)
        self._update_shadows(states, now_ms)
        if now_ms >= self._next_detect:
            self._detect(states, now_ms)
            if config.PAPER_LT20_VARIANT in VARIANTS:
                self._detect_growth(states, now_ms)
            if config.PAPER_CSS_VARIANT in VARIANTS:
                self._detect_css(states, now_ms)
            if config.PAPER_CSS2_VARIANT in VARIANTS:
                self._detect_css2(states, now_ms)
            self._next_detect = now_ms + config.PAPER_DETECT_INTERVAL_SEC * 1000
        self._evaluate(states, btc_4h, now_ms)
        if config.PAPER_LT20_VARIANT in VARIANTS:
            self._evaluate_growth(states, now_ms)
        if config.PAPER_CSS_VARIANT in VARIANTS:
            self._evaluate_css(states, now_ms)
        if config.PAPER_CSS2_VARIANT in VARIANTS:
            self._evaluate_css2(states, btc_state=states.get(config.PAPER_BTC_SYMBOL), now_ms=now_ms)
        if config.PAPER_SC10_VARIANT in VARIANTS:
            self._evaluate_sc10(states, now_ms)
        self._evaluate_impulse(states, now_ms)
        if (
            config.PAPER_PYL_VARIANT in VARIANTS
            or config.PAPER_PYL1_VARIANT in VARIANTS
            or config.PAPER_PYLBTC_VARIANT in VARIANTS
            or config.PAPER_333_VARIANT in VARIANTS
            or config.PAPER_VPS5_VARIANT in VARIANTS
        ):
            self._refresh_five_min_arm(states, now_ms)
        if config.PAPER_VPS15_VARIANT in VARIANTS:
            self._refresh_fifteen_min_arm(states, now_ms)
        if pivots:
            if config.PAPER_PYL_VARIANT in VARIANTS:
                self._evaluate_pyl(states, now_ms)
            if config.PAPER_PYL1_VARIANT in VARIANTS:
                self._evaluate_pyl1(states, now_ms)
            if config.PAPER_PYLBTC_VARIANT in VARIANTS:
                self._evaluate_pylbtc(states, now_ms)
            if config.PAPER_333_VARIANT in VARIANTS:
                self._evaluate_333(states, now_ms)
            if config.PAPER_VAC_VARIANT in VARIANTS:
                self._evaluate_vac(states, now_ms)
            self._evaluate_vps_variants(states, now_ms)
        self._persist(now_ms)
        if now_ms >= self._next_equity:
            for variant in VARIANTS:
                self._snapshot_equity(variant, now_ms)
            self._next_equity = now_ms + config.PAPER_EQUITY_SNAPSHOT_SEC * 1000
        if now_ms >= self._next_tape:
            self._save_tape(now_ms)
            self._next_tape = now_ms + 300_000
        if now_ms >= self._next_analytics:
            self._analytics = compute_analytics(
                self.store.db,
                self.balances,
                now_ms=now_ms,
                unrealized={v: self.unrealized(v) for v in VARIANTS},
            )
            self._next_analytics = now_ms + 30_000
        return {"type": BOARD_TYPE, "timestamp": now_ms, "data": self.view(now_ms, btc_4h)}

    def _variant_trades(self, variant: str) -> list[OpenTrade]:
        return [t for t in self.trades.values() if t.variant == variant]

    def _ensure_balance(self, variant: str) -> None:
        if variant in self.balances:
            return
        saved = self.store.get_kv(f"balance:{variant}")
        self.balances[variant] = float(saved) if saved is not None else config.PAPER_START_BALANCE_USD
        if saved is None:
            self.store.set_kv(f"balance:{variant}", str(self.balances[variant]))

    def _retire_removed_variants(self, now_ms: int) -> None:
        retired: set[str] = set()
        for row in list(self.store.open_trades()):
            variant = str(row["variant"] or config.PAPER_T20_VARIANT)
            if variant in VARIANTS:
                continue
            retired.add(variant)
            self._force_close_retired_trade(row, now_ms)
        for kind, var in (
            ("css", config.PAPER_CSS_VARIANT),
            ("css2", config.PAPER_CSS2_VARIANT),
            ("growth", config.PAPER_LT20_VARIANT),
            ("sc10", config.PAPER_SC10_VARIANT),
        ):
            if var not in VARIANTS:
                dropped = self.store.expire_kind_watching(kind, f"вариант {var} снят", now_ms)
                if dropped:
                    log.info("Тест: снято кандидатов %s: %s", kind, dropped)
        if retired:
            self.store.db.commit()
            log.info("Тест: закрыты открытые сделки снятых вариантов: %s", sorted(retired))

    def _force_close_retired_trade(self, row, now_ms: int) -> None:
        variant = str(row["variant"] or config.PAPER_T20_VARIANT)
        self._ensure_balance(variant)
        gap = config.paper_peak_gap_roe(variant)
        kind = str(row["kind"] or "")
        entry = _loads(row["entry_json"])
        side = resolve_trade_side(
            side=row["side"] if "side" in row.keys() else None,
            kind=kind,
            variant=variant,
            entry=entry,
        )
        entry_px = float(row["entry_price"])
        lev = int(row["leverage"])
        pos = Position(
            symbol=row["symbol"],
            opened_at=int(row["opened_at"]),
            entry_price=entry_px,
            margin=float(row["margin"]),
            leverage=lev,
            best_price=float(row["best_price"]),
            worst_price=float(row["worst_price"]),
            stop_price=float(row["stop_price"]),
            liq_price=liq_price_for_side(side, entry_px, lev),
            entry_fee=float(row["entry_fee"]),
            funding_paid=float(row["funding_paid"] or 0),
            next_funding_ts=row["next_funding_ts"],
            last_price=float(row["last_price"] or row["entry_price"]),
            peak_gap_roe=gap,
            side=side,
            stop_style=config.paper_stop_style(variant),
            scaled_half=bool((entry or {}).get("css2_half")),
        )
        last = float(row["last_price"] or row["entry_price"])
        pos.update(last, last, last)
        reason = "вариант снят (баланс ≤ $1000)"
        result = pos.close_result(reason)
        self.balances[variant] += result["pnl_usd"]
        exit_json = {
            "duration_min": round((now_ms - pos.opened_at) / 60_000),
            "last_price": pos.last_price,
            "best_price": pos.best_price,
            "worst_price": pos.worst_price,
            "funding_paid": pos.funding_paid,
        }
        self.store.update_trade(
            int(row["id"]),
            {
                "status": "closed",
                "closed_at": now_ms,
                "exit_price": result["exit_price"],
                "exit_reason": reason,
                "exit_fee": result["exit_fee"],
                "pnl_usd": result["pnl_usd"],
                "roe_pct": result["roe_pct"],
                "max_roe": pos.max_roe(),
                "min_roe": pos.min_roe(),
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "stop_price": pos.stop_price,
                "last_price": pos.last_price,
                "funding_paid": pos.funding_paid,
                "balance_after": self.balances[variant],
                "exit_json": exit_json,
            },
            commit=False,
        )
        self.store.set_kv(f"balance:{variant}", str(self.balances[variant]))

    def used_margin(self, variant: str) -> float:
        return sum(t.pos.margin for t in self._variant_trades(variant))

    def unrealized(self, variant: str) -> float:
        return sum(t.pos.net_pnl(t.pos.last_price) for t in self._variant_trades(variant))

    def equity(self, variant: str) -> float:
        return self.balances[variant] + self.unrealized(variant)

    def _snapshot_equity(self, variant: str, now_ms: int) -> None:
        self.store.add_equity(
            variant, now_ms, self.balances[variant], self.equity(variant), len(self._variant_trades(variant))
        )

    def _refresh_peaks(self, states: dict[str, SymbolState], now_ms: int) -> None:
        symbols = set(self.candidates.keys())
        for trade in self.trades.values():
            symbols.add(trade.symbol)
        for symbol in symbols:
            state = states.get(symbol)
            if state is None:
                continue
            measured = measure_pump_peak(state, now_ms)
            if measured is None:
                continue
            peak, peak_ts = measured
            prev = self.peak_snapshots.get(symbol)
            if prev is None or peak >= prev[0] - 1e-12:
                self.peak_snapshots[symbol] = (peak, peak_ts)
            cand = self.candidates.get(symbol)
            if cand is not None and apply_peak_measurement(cand.pump, state, now_ms):
                cand.dirty = True

    def _refresh_growth_peaks(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for symbol, cand in self.growth_candidates.items():
            state = states.get(symbol)
            if state is None:
                continue
            if refresh_growth_peak(cand.growth, state, now_ms, self.klines.get(symbol, {})):
                cand.dirty = True
                self.peak_snapshots[symbol] = (cand.growth.peak_price, cand.growth.peak_ts)

    def _refresh_css_peaks(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for symbol, cand in self.css_candidates.items():
            state = states.get(symbol)
            if state is None:
                continue
            tape = self.tape.symbols.get(symbol)
            if refresh_css_peak(cand.pump, state, tape, now_ms):
                cand.rearm_needed = False
                cand.dirty = True
                cand.note = "вторая нога: новый пик"
                self.peak_snapshots[symbol] = (cand.pump.peak_price, cand.pump.peak_ts)

    def _process_manual_closes(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for trade_id in self.store.drain_manual_closes():
            trade = next((t for t in self.trades.values() if t.id == trade_id), None)
            if trade is None:
                continue
            state = states.get(trade.symbol)
            if state is None or not state.last_price:
                continue
            trade.pos.last_price = float(state.last_price)
            self._close_trade(trade, "manual", state, now_ms)

    def _update_trades(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for trade in list(self.trades.values()):
            state = states.get(trade.symbol)
            if state is None or not state.last_price:
                continue
            pos = trade.pos
            low, high, last = _price_range(state, trade.last_check)
            trade.last_check = now_ms
            self._funding(pos, trade.symbol, state, now_ms)
            if trade.variant == config.PAPER_CSS2_VARIANT and high < pos.stop_price and high < pos.liq_price:
                managed = self._css2_favorable(trade, state, low, last, now_ms)
                if managed:
                    self._close_trade(trade, managed, state, now_ms)
                    continue
            reason = pos.update(low, high, last)
            if reason:
                self._close_trade(trade, reason, state, now_ms)

    def _funding(self, pos: Position, symbol: str, state: SymbolState, now_ms: int) -> None:
        tape = self.tape.symbols.get(symbol)
        if pos.next_funding_ts is None and tape is not None and tape.next_funding_ts:
            if tape.next_funding_ts > now_ms:
                pos.next_funding_ts = tape.next_funding_ts
        if pos.next_funding_ts is not None and now_ms >= pos.next_funding_ts:
            paid = pos.apply_funding(now_ms, state.funding_rate, float(state.last_price or pos.last_price))
            if paid:
                log.info("Funding %s: %+.4f USD", symbol, paid)

    def _close_trade(self, trade: OpenTrade, reason: str, state: SymbolState, now_ms: int) -> None:
        pos = trade.pos
        variant = trade.variant
        if reason in ("opposite_pivot", "manual") and state.last_price:
            pos.last_price = float(state.last_price)
        result = pos.close_result(reason)
        balance_before_close = self.balances[variant]
        self.balances[variant] += result["pnl_usd"]
        points = state.oi_points()
        exit_json = {
            "duration_min": round((now_ms - pos.opened_at) / 60_000),
            "last_price": pos.last_price,
            "best_price": pos.best_price,
            "worst_price": pos.worst_price,
            "funding_paid": pos.funding_paid,
            "oi_1h_pct": _r(oi_change_pct(points, 60)) if len(points) >= 2 else None,
            "funding_rate": state.funding_rate,
        }
        self.store.update_trade(
            trade.id,
            {
                "status": "closed",
                "closed_at": now_ms,
                "exit_price": result["exit_price"],
                "exit_reason": reason,
                "exit_fee": result["exit_fee"],
                "pnl_usd": result["pnl_usd"],
                "roe_pct": result["roe_pct"],
                "max_roe": pos.max_roe(),
                "min_roe": pos.min_roe(),
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "stop_price": pos.stop_price,
                "last_price": pos.last_price,
                "funding_paid": pos.funding_paid,
                "side": pos.side,
                "liq_price": pos.liq_price,
                "balance_before": balance_before_close,
                "balance_after": self.balances[variant],
                "exit_json": exit_json,
            },
            commit=False,
        )
        self.trades.pop((variant, trade.symbol), None)
        self.store.set_kv(f"balance:{variant}", str(self.balances[variant]))
        self._snapshot_equity(variant, now_ms)
        self.last_close[(variant, trade.symbol)] = now_ms
        self._next_analytics = 0
        if variant == config.PAPER_CSS_VARIANT:
            self._on_css_trade_closed(trade, pos, now_ms)
        if variant == config.PAPER_CSS2_VARIANT:
            self._on_css2_trade_closed(trade, now_ms)
        if variant in config.PAPER_PLUS_VARIANTS:
            self._on_plus_trade_closed(trade, result)
        log.info(
            "Тест [%s]: закрыт шорт %s (%s), P&L %+.2f USD (%+.1f%%), баланс %.2f",
            variant,
            trade.symbol,
            reason,
            result["pnl_usd"],
            result["roe_pct"],
            self.balances[variant],
        )

    def _update_shadows(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for cid, shadow in list(self.shadows.items()):
            state = states.get(shadow.symbol)
            if state is None or not state.last_price:
                continue
            low, high, last = _price_range(state, shadow.last_check)
            shadow.last_check = now_ms
            reason = shadow.pos.update(low, high, last)
            if reason:
                result = shadow.pos.close_result(reason)
                self.store.update_candidate(
                    cid,
                    {
                        "shadow_status": "closed",
                        "shadow_closed_at": now_ms,
                        "shadow_exit_price": result["exit_price"],
                        "shadow_exit_reason": reason,
                        "shadow_pnl_usd": result["pnl_usd"],
                        "shadow_roe": result["roe_pct"],
                        "shadow_max_roe": shadow.pos.max_roe(),
                        "shadow_best": shadow.pos.best_price,
                        "shadow_worst": shadow.pos.worst_price,
                        "shadow_stop": shadow.pos.stop_price,
                    },
                )
                self.shadows.pop(cid, None)
                self._next_analytics = 0

    def _detect(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for symbol, state in states.items():
            if symbol in self.candidates or not state.last_price:
                continue
            pump = find_pump(state, self.tape.symbols.get(symbol), now_ms)
            soft = False
            if pump is None:
                pump = find_pump(state, self.tape.symbols.get(symbol), now_ms, mini_pump_floors())
                soft = pump is not None
            if pump is None:
                continue
            if self.expired_peaks.get(symbol) == pump.peak_ts:
                continue
            fields = _pump_fields(pump)
            if soft:
                fields["kind"] = "mini"
            cid = self.store.insert_candidate(
                {
                    "symbol": symbol,
                    "status": "watching",
                    "started_at": now_ms,
                    "updated_at": now_ms,
                    **fields,
                    "fail_counts": {},
                }
            )
            self.candidates[symbol] = Candidate(
                id=cid, symbol=symbol, pump=pump, started_at=now_ms, soft=soft
            )
            log.info(
                "Тест: кандидат %s — %s памп +%.1f%% (%s)",
                symbol,
                pump.kind,
                pump.growth_pct,
                pump.trigger,
            )

    def _detect_growth(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for symbol, state in states.items():
            if symbol in self.growth_candidates or not state.last_price:
                continue
            growth = find_growth(state, self.tape.symbols.get(symbol), now_ms, self.klines.get(symbol, {}))
            if growth is None:
                continue
            cid = self.store.insert_candidate(
                {
                    "symbol": symbol,
                    "kind": "growth",
                    "status": "watching",
                    "started_at": now_ms,
                    "updated_at": now_ms,
                    **_growth_fields(growth),
                    "fail_counts": {},
                }
            )
            self.growth_candidates[symbol] = GrowthCandidate(
                id=cid, symbol=symbol, growth=growth, started_at=now_ms
            )
            log.info("Тест: кандидат роста %s — ралли +%.1f%%", symbol, growth.rally_pct)

    def _detect_css(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for symbol, state in states.items():
            if symbol in self.css_candidates or not state.last_price:
                continue
            pump = find_css_pump(state, self.tape.symbols.get(symbol), now_ms)
            if pump is None:
                continue
            cid = self.store.insert_candidate(
                {
                    "symbol": symbol,
                    "kind": "css",
                    "status": "watching",
                    "started_at": now_ms,
                    "updated_at": now_ms,
                    **_css_fields(pump),
                    "fail_counts": {},
                }
            )
            self.css_candidates[symbol] = CssCandidate(id=cid, symbol=symbol, pump=pump, started_at=now_ms)
            log.info("Тест: кандидат Cursor SS %s — быстрый памп +%.1f%%", symbol, pump.growth_pct)

    def _ready(self, state: SymbolState, cand: Candidate, now_ms: int) -> bool:
        """Хватает ли истории в памяти, чтобы честно решить, что памп кончился."""
        if now_ms - self.started_ms < config.PAPER_STARTUP_GRACE_MIN * 60_000:
            return False
        if len(state.bars_htf.get("15") or []) < config.PAPER_READY_15M_BARS:
            return False
        if cand.pump.kind == "long" and len(state.bars_htf.get("240") or []) < config.PAPER_READY_4H_BARS:
            return False
        return True

    def _evaluate(self, states: dict[str, SymbolState], btc_4h: float | None, now_ms: int) -> None:
        cooldown = config.PAPER_REENTRY_COOLDOWN_SEC * 1000
        for symbol, cand in list(self.candidates.items()):
            state = states.get(symbol)
            if state is None or not state.last_price:
                continue
            tape = self.tape.get(symbol)
            pump = find_pump(state, tape, now_ms, mini_pump_floors() if cand.soft else None)
            if pump is None:
                reason = _expire_reason(cand.pump, state, now_ms)
                if reason == _REASON_CONDITIONS and not self._ready(state, cand, now_ms):
                    continue
                self._end_candidate(cand, reason, now_ms)
                continue
            cand.pump = pump
            ev = evaluate(state, tape, pump, self.klines.get(symbol, {}), btc_4h, now_ms)
            e5s_ev = evaluate_e5s(state, tape, pump, self.klines.get(symbol, {}), now_ms)
            plus_ev = evaluate_plus(state, tape, self.klines.get(symbol, {}), now_ms, ev)
            cand.scans += 1
            for key in ev.failed:
                cand.fail_counts[key] = cand.fail_counts.get(key, 0) + 1
            cand.best_passed = max(cand.best_passed, ev.passed_count)
            data = ev.to_data()
            data["e5s"] = e5s_ev.to_data()
            data["plus"] = plus_ev.to_data()
            c3 = cursor3_view(ev.metrics, ev.score, ev.strict_btc)
            data["c3"] = c3
            data["mini"] = mini_view(ev)
            data["mini_chart"] = mini_chart_view(ev)
            data["graf"] = evaluate_grafik(state, cand.pump, now_ms, ev.score, ev.strict_btc)
            data["dps"] = evaluate_dps(state, tape, cand.pump, now_ms, ev.score, ev.strict_btc)
            if cand.soft:
                data["variants"] = []
            cand.last_eval = data
            cand.dirty = True
            notes = []
            if ev.entry_blocked:
                notes.append(
                    "Вход закрыт: " + "; ".join(ENTRY_GATE_LABELS.get(k, k) for k in ev.entry_blocked)
                )
            if cand.soft:
                notes.append("мягкий памп: только Мини тест")
            for variant in () if cand.soft else ev.variants:
                if variant not in VARIANTS:
                    continue
                if (variant, symbol) in self.trades:
                    continue
                if now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                    continue
                balance = self.balances[variant]
                margin = balance * config.PAPER_MARGIN_PCT / 100.0
                if margin <= 0 or balance - self.used_margin(variant) < margin:
                    notes.append(f"{VARIANT_LABELS.get(variant, variant)}: нет свободной маржи")
                    continue
                self._open_trade(variant, cand, state, ev, margin, now_ms)
            if e5s_ev.passed and not cand.soft:
                for variant in e5s_ev.to_data()["variants"]:
                    if variant not in VARIANTS:
                        continue
                    label = VARIANT_LABELS.get(variant, variant)
                    if (variant, symbol) in self.trades:
                        continue
                    if now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                        notes.append(f"{label}: пауза после сделки")
                        continue
                    balance = self.balances[variant]
                    margin = balance * config.PAPER_MARGIN_PCT / 100.0
                    if margin <= 0 or balance - self.used_margin(variant) < margin:
                        notes.append(f"{label}: нет свободной маржи")
                        continue
                    self._open_trade(variant, cand, state, e5s_ev, margin, now_ms)
            if plus_ev.passed and not cand.soft:
                peak_ts = int(cand.pump.peak_ts or 0)
                if peak_ts and peak_ts in self.plus_blocked.get(symbol, ()):
                    notes.append("копии: этот пик уже закрыт первым стопом")
                else:
                    for variant in config.PAPER_PLUS_VARIANTS:
                        if variant not in VARIANTS:
                            continue
                        label = VARIANT_LABELS.get(variant, variant)
                        if (variant, symbol) in self.trades:
                            continue
                        if now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                            notes.append(f"{label}: пауза после сделки")
                            continue
                        balance = self.balances[variant]
                        margin = balance * config.PAPER_MARGIN_PCT / 100.0
                        if margin <= 0 or balance - self.used_margin(variant) < margin:
                            notes.append(f"{label}: нет свободной маржи")
                            continue
                        self._open_trade(variant, cand, state, plus_ev, margin, now_ms)
            if c3["passed"] and not cand.soft and config.PAPER_C3_VARIANT in VARIANTS:
                variant = config.PAPER_C3_VARIANT
                label = VARIANT_LABELS.get(variant, variant)
                if (variant, symbol) in self.trades:
                    pass
                elif now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                    notes.append(f"{label}: пауза после сделки")
                else:
                    balance = self.balances[variant]
                    margin = balance * config.PAPER_MARGIN_PCT / 100.0
                    if margin <= 0 or balance - self.used_margin(variant) < margin:
                        notes.append(f"{label}: нет свободной маржи")
                    else:
                        self._open_trade(variant, cand, state, _EvalView(c3), margin, now_ms)
            if data["mini"]["passed"]:
                for variant in config.PAPER_MINI_VARIANTS:
                    label = VARIANT_LABELS.get(variant, variant)
                    if (variant, symbol) in self.trades:
                        continue
                    if now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                        notes.append(f"{label}: пауза после сделки")
                        continue
                    balance = self.balances[variant]
                    margin = balance * config.PAPER_MARGIN_PCT / 100.0
                    if margin <= 0 or balance - self.used_margin(variant) < margin:
                        notes.append(f"{label}: нет свободной маржи")
                        continue
                    self._open_trade(variant, cand, state, _EvalView(data["mini"]), margin, now_ms)
            if data["mini_chart"]["passed"] and config.PAPER_MT2C_VARIANT in VARIANTS:
                variant = config.PAPER_MT2C_VARIANT
                label = VARIANT_LABELS.get(variant, variant)
                if (variant, symbol) in self.trades:
                    pass
                elif now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                    notes.append(f"{label}: пауза после сделки")
                else:
                    balance = self.balances[variant]
                    margin = balance * config.PAPER_MARGIN_PCT / 100.0
                    if margin <= 0 or balance - self.used_margin(variant) < margin:
                        notes.append(f"{label}: нет свободной маржи")
                    else:
                        self._open_trade(
                            variant, cand, state, _EvalView(data["mini_chart"]), margin, now_ms
                        )
            if data["graf"]["passed"] and config.PAPER_GRAF_VARIANT in VARIANTS:
                variant = config.PAPER_GRAF_VARIANT
                label = VARIANT_LABELS.get(variant, variant)
                if (variant, symbol) in self.trades:
                    pass
                elif now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                    notes.append(f"{label}: пауза после сделки")
                else:
                    balance = self.balances[variant]
                    margin = balance * config.PAPER_MARGIN_PCT / 100.0
                    if margin <= 0 or balance - self.used_margin(variant) < margin:
                        notes.append(f"{label}: нет свободной маржи")
                    else:
                        self._open_trade(
                            variant, cand, state, _EvalView(data["graf"]), margin, now_ms
                        )
            if data["dps"]["passed"] and config.PAPER_DPS_VARIANT in VARIANTS:
                variant = config.PAPER_DPS_VARIANT
                label = VARIANT_LABELS.get(variant, variant)
                open_dps = sum(1 for t in self.trades.values() if t.variant == variant)
                dps_cd = config.PAPER_DPS_COOLDOWN_SEC * 1000
                if (variant, symbol) in self.trades:
                    pass
                elif open_dps >= config.PAPER_DPS_MAX_OPEN:
                    notes.append(f"{label}: лимит {config.PAPER_DPS_MAX_OPEN} открытых")
                elif now_ms - self.last_close.get((variant, symbol), 0) < dps_cd:
                    notes.append(f"{label}: пауза {config.PAPER_DPS_COOLDOWN_SEC // 60} мин")
                else:
                    balance = self.balances[variant]
                    margin = balance * config.PAPER_MARGIN_PCT / 100.0
                    if margin <= 0 or balance - self.used_margin(variant) < margin:
                        notes.append(f"{label}: нет свободной маржи")
                    else:
                        self._open_trade(
                            variant, cand, state, _EvalView(data["dps"]), margin, now_ms
                        )
            cand.note = "; ".join(notes) or None
            if not cand.soft and not ev.entry_blocked and len(ev.failed) == 1 and not cand.near_miss:
                self._start_shadow(cand, state, ev.failed[0], now_ms)

    def _evaluate_growth(self, states: dict[str, SymbolState], now_ms: int) -> None:
        variant = config.PAPER_LT20_VARIANT
        cooldown = config.PAPER_REENTRY_COOLDOWN_SEC * 1000
        for symbol, cand in list(self.growth_candidates.items()):
            state = states.get(symbol)
            if state is None or not state.last_price:
                continue
            tape = self.tape.get(symbol)
            growth = find_growth(state, tape, now_ms, self.klines.get(symbol, {}))
            if growth is None:
                last = float(state.last_price)
                peak = cand.growth.peak_price
                dd = (peak - last) / peak * 100.0 if peak > 0 else 999.0
                if dd > config.PAPER_GROWTH_MAX_PULLBACK_PCT or last <= cand.growth.anchor_price:
                    self._end_growth_candidate(cand, "условия роста больше не выполняются", now_ms)
                    continue
                growth = cand.growth
            cand.growth = growth
            ev = evaluate_growth(state, tape, growth, self.klines.get(symbol, {}), now_ms)
            cand.scans += 1
            for key in ev.failed:
                cand.fail_counts[key] = cand.fail_counts.get(key, 0) + 1
            cand.best_passed = max(cand.best_passed, ev.passed_count)
            cand.last_eval = ev.to_data()
            cand.dirty = True
            if not ev.passed:
                cand.note = "ждём условия" + (" (турбо)" if ev.turbo else "")
                continue
            if (variant, symbol) in self.trades:
                continue
            if now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                continue
            balance = self.balances[variant]
            margin = balance * config.PAPER_MARGIN_PCT / 100.0
            if margin <= 0 or balance - self.used_margin(variant) < margin:
                cand.note = "нет свободной маржи"
                continue
            self._open_growth_trade(cand, state, ev, margin, now_ms)

    def _open_growth_trade(
        self, cand: GrowthCandidate, state: SymbolState, ev: GrowthEvaluation, margin: float, now_ms: int
    ) -> None:
        variant = config.PAPER_LT20_VARIANT
        price = float(state.last_price)
        tape = self.tape.symbols.get(cand.symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(
            symbol=cand.symbol,
            opened_at=now_ms,
            entry_price=price,
            margin=margin,
            next_funding_ts=nft,
            side="long",
        )
        entry = ev.to_data()
        trade_id = self.store.insert_trade(
            {
                "symbol": cand.symbol,
                "variant": variant,
                "candidate_id": cand.id,
                "kind": "growth",
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": ev.score,
                "grade": grade_for(ev.score),
                "strict_btc": False,
                "balance_before": self.balances[variant],
                "entry_json": entry,
            }
        )
        self.trades[(variant, cand.symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=cand.symbol,
            kind="growth",
            pos=pos,
            score=ev.score,
            grade=grade_for(ev.score),
            strict_btc=False,
            entry=entry,
            candidate_id=cand.id,
            last_check=now_ms,
        )
        if variant not in cand.entered:
            cand.entered.append(variant)
        cand.last_trade_id = trade_id
        cand.dirty = True
        cand.note = "турбо" if ev.turbo else None
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт лонг %s по %s, маржа %.2f USD, турбо=%s, балл %.1f",
            variant,
            cand.symbol,
            price,
            margin,
            ev.turbo,
            ev.score,
        )

    def _evaluate_css(self, states: dict[str, SymbolState], now_ms: int) -> None:
        variant = config.PAPER_CSS_VARIANT
        cooldown = config.PAPER_REENTRY_COOLDOWN_SEC * 1000
        for symbol, cand in list(self.css_candidates.items()):
            state = states.get(symbol)
            if state is None or not state.last_price:
                continue
            tape = self.tape.get(symbol)
            pump = find_css_pump(state, tape, now_ms)
            if pump is None:
                last = float(state.last_price)
                peak = cand.pump.peak_price
                dd = (1.0 - last / peak) * 100.0 if peak > 0 else 999.0
                age_ms = now_ms - cand.pump.peak_ts
                if dd > config.PAPER_CSS_MAX_DRAWDOWN_PCT or age_ms > int(
                    config.PAPER_CSS_LIFETIME_HOURS * 3_600_000
                ):
                    self._end_css_candidate(cand, "условия Cursor SS больше не выполняются", now_ms)
                    continue
                pump = cand.pump
            if pump.peak_price > cand.pump.peak_price + 1e-12:
                cand.rearm_needed = False
            pump.stall_frozen = cand.pump.stall_frozen and pump.peak_price <= cand.pump.peak_price + 1e-12
            if pump.stall_frozen:
                pump.stall_low = cand.pump.stall_low
                pump.stall_high = cand.pump.stall_high
            cand.pump = pump
            ev = evaluate_css(state, tape, pump, self.klines.get(symbol, {}), now_ms)
            cand.pump.stall_frozen = pump.stall_frozen
            cand.pump.stall_low = pump.stall_low
            cand.pump.stall_high = pump.stall_high
            cand.scans += 1
            for key in ev.failed:
                cand.fail_counts[key] = cand.fail_counts.get(key, 0) + 1
            cand.best_passed = max(cand.best_passed, ev.passed_count)
            cand.last_eval = _css_eval_with_state(ev.to_data(), cand)
            cand.dirty = True
            dump_ok = bool((ev.checks.get("dump_break") or {}).get("ok"))
            if cand.rearm_needed:
                if dump_ok:
                    cand.note = "ждём новый слив после стопа"
                    continue
                cand.rearm_needed = False
                cand.last_eval = _css_eval_with_state(ev.to_data(), cand)
            if cand.entries_used >= config.PAPER_CSS_MAX_ENTRIES:
                self._end_css_candidate(cand, "лимит входов Cursor SS", now_ms)
                continue
            if not ev.passed:
                cand.note = "ждём затихание и дамп"
                continue
            if (variant, symbol) in self.trades:
                continue
            if now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                cand.note = "пауза после стопа"
                continue
            balance = self.balances[variant]
            margin = balance * config.PAPER_MARGIN_PCT / 100.0
            if margin <= 0 or balance - self.used_margin(variant) < margin:
                cand.note = "нет свободной маржи"
                continue
            self._open_css_trade(cand, state, ev, margin, now_ms)

    def _open_css_trade(
        self, cand: CssCandidate, state: SymbolState, ev: CssEvaluation, margin: float, now_ms: int
    ) -> None:
        variant = config.PAPER_CSS_VARIANT
        price = float(state.last_price)
        tape = self.tape.symbols.get(cand.symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(
            symbol=cand.symbol,
            opened_at=now_ms,
            entry_price=price,
            margin=margin,
            next_funding_ts=nft,
            stop_style="css",
        )
        entry = _css_eval_with_state(ev.to_data(), cand)
        trade_id = self.store.insert_trade(
            {
                "symbol": cand.symbol,
                "variant": variant,
                "candidate_id": cand.id,
                "kind": "css",
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": ev.score,
                "grade": grade_for(ev.score),
                "strict_btc": False,
                "balance_before": self.balances[variant],
                "entry_json": entry,
            }
        )
        self.trades[(variant, cand.symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=cand.symbol,
            kind="css",
            pos=pos,
            score=ev.score,
            grade=grade_for(ev.score),
            strict_btc=False,
            entry=entry,
            candidate_id=cand.id,
            last_check=now_ms,
        )
        cand.entries_used += 1
        if variant not in cand.entered:
            cand.entered.append(variant)
        cand.last_trade_id = trade_id
        cand.dirty = True
        cand.note = f"вход {cand.entries_used}/{config.PAPER_CSS_MAX_ENTRIES}"
        cand.last_eval = _css_eval_with_state(ev.to_data(), cand)
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт шорт %s по %s, маржа %.2f USD, вход %s/%s, балл %.1f",
            variant,
            cand.symbol,
            price,
            margin,
            cand.entries_used,
            config.PAPER_CSS_MAX_ENTRIES,
            ev.score,
        )

    def _on_css_trade_closed(self, trade: OpenTrade, pos: Position, now_ms: int) -> None:
        cand = self.css_candidates.get(trade.symbol)
        if cand is None:
            return
        if pos.max_roe() >= config.PAPER_CSS_BE_ARM_ROE:
            self._end_css_candidate(cand, "Cursor SS: был плюс +10% ROE", now_ms)
            return
        cand.rearm_needed = True
        cand.dirty = True
        cand.note = "стоп −15% ROE, ждём новый слив"
        if cand.entries_used >= config.PAPER_CSS_MAX_ENTRIES:
            self._end_css_candidate(cand, "лимит входов Cursor SS", now_ms)

    def _end_css_candidate(self, cand: CssCandidate, reason: str, now_ms: int) -> None:
        status = "entered" if cand.entered else "expired"
        fields = {
            "status": status,
            "ended_at": now_ms,
            "end_reason": reason,
            "updated_at": now_ms,
            "scans": cand.scans,
            "fail_counts": cand.fail_counts,
            "best_passed": cand.best_passed,
            "last_eval": _css_eval_with_state(cand.last_eval or {}, cand),
            "variants": cand.entered,
            "trade_id": cand.last_trade_id,
            **_css_fields(cand.pump),
        }
        self.store.update_candidate(cand.id, fields)
        self.css_candidates.pop(cand.symbol, None)

    def _detect_css2(self, states: dict[str, SymbolState], now_ms: int) -> None:
        for symbol, state in states.items():
            if symbol in self.css2_candidates or not state.last_price:
                continue
            pump = find_css2_pump(state, now_ms)
            if pump is None:
                continue
            blocked = self.css2_blocked.get(symbol, 0)
            if blocked and pump.valley_ts <= blocked:
                continue
            cid = self.store.insert_candidate(
                {
                    "symbol": symbol,
                    "kind": "css2",
                    "status": "watching",
                    "started_at": now_ms,
                    "updated_at": now_ms,
                    **_css2_fields(pump),
                    "fail_counts": {},
                }
            )
            self.css2_candidates[symbol] = Css2Candidate(id=cid, symbol=symbol, pump=pump, started_at=now_ms)
            log.info("Тест: кандидат Курсор СС 2 %s — быстрый памп +%.1f%%", symbol, pump.growth_pct)

    def _evaluate_css2(self, states: dict[str, SymbolState], btc_state: SymbolState | None, now_ms: int) -> None:
        variant = config.PAPER_CSS2_VARIANT
        for symbol, cand in list(self.css2_candidates.items()):
            state = states.get(symbol)
            if state is None or not state.last_price:
                continue
            if (variant, symbol) in self.trades:
                continue
            pump = find_css2_pump(state, now_ms)
            if pump is None or pump.valley_ts != cand.pump.valley_ts:
                last = float(state.last_price or 0)
                dd = (1.0 - last / cand.pump.peak_price) * 100.0 if cand.pump.peak_price > 0 and last > 0 else 0.0
                since = (now_ms - cand.pump.peak_ts) / 60_000
                if dd > config.PAPER_CSS2_WATCH_MAX_DD_PCT or since > config.PAPER_CSS2_SINCE_PEAK_MAX:
                    self._end_css2_candidate(cand, "окно Курсор СС 2 закрыто", now_ms)
                continue
            if pump.peak_price > cand.pump.peak_price:
                cand.pump = pump
                cand.dirty = True
            else:
                cand.pump.growth_pct = pump.growth_pct
                cand.pump.volume_ratio = pump.volume_ratio
            tape = self.tape.symbols.get(symbol)
            ev = evaluate_css2(state, tape, btc_state, cand.pump, self.klines.get(symbol, {}), now_ms)
            cand.scans += 1
            cand.best_passed = max(cand.best_passed, ev.passed_count)
            for key in ev.failed:
                cand.fail_counts[key] = cand.fail_counts.get(key, 0) + 1
            cand.last_eval = _css2_eval_with_state(ev.to_data(), cand)
            cand.dirty = True
            if cand.entries_used >= 1:
                continue
            if not ev.passed:
                cand.note = None
                continue
            balance = self.balances[variant]
            margin = balance * config.PAPER_MARGIN_PCT / 100.0
            if margin <= 0 or balance - self.used_margin(variant) < margin:
                cand.note = "нет свободной маржи"
                continue
            self._open_css2_trade(cand, state, ev, margin, now_ms)

    def _open_css2_trade(
        self, cand: Css2Candidate, state: SymbolState, ev: Css2Evaluation, margin: float, now_ms: int
    ) -> None:
        variant = config.PAPER_CSS2_VARIANT
        price = float(state.last_price)
        tape = self.tape.symbols.get(cand.symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(
            symbol=cand.symbol,
            opened_at=now_ms,
            entry_price=price,
            margin=margin,
            next_funding_ts=nft,
            stop_style="css2",
        )
        entry = _css2_eval_with_state(ev.to_data(), cand)
        trade_id = self.store.insert_trade(
            {
                "symbol": cand.symbol,
                "variant": variant,
                "candidate_id": cand.id,
                "kind": "css2",
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": ev.score,
                "grade": grade_for(ev.score),
                "strict_btc": False,
                "balance_before": self.balances[variant],
                "entry_json": entry,
            }
        )
        self.trades[(variant, cand.symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=cand.symbol,
            kind="css2",
            pos=pos,
            score=ev.score,
            grade=grade_for(ev.score),
            strict_btc=False,
            entry=entry,
            candidate_id=cand.id,
            last_check=now_ms,
        )
        cand.entries_used = 1
        if variant not in cand.entered:
            cand.entered.append(variant)
        cand.last_trade_id = trade_id
        cand.dirty = True
        cand.note = "вход 1/1"
        cand.last_eval = _css2_eval_with_state(ev.to_data(), cand)
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт шорт %s по %s, маржа %.2f USD, стоп −60%% ROE",
            variant,
            cand.symbol,
            price,
            margin,
        )

    def _css2_peak(self, trade: OpenTrade) -> float:
        pump = ((trade.entry.get("metrics") or {}).get("pump") or {})
        return float(pump.get("peak_price") or 0)

    def _css2_favorable(
        self, trade: OpenTrade, state: SymbolState, low: float, last: float, now_ms: int
    ) -> str | None:
        """Цели и плоский выход. Стоп уже не задет в этом тике."""
        pos = trade.pos
        peak = self._css2_peak(trade)
        if peak <= 0 or low <= 0:
            return None
        if closed_15m_above_peak(state, peak, pos.opened_at, now_ms) or peak_on_open_15m(state, peak, now_ms):
            pos.stop_price = last
            pos.last_price = last
            return "peak_reclaimed"
        target = peak * (1.0 - config.PAPER_CSS2_TARGET_DD_PCT / 100.0)
        if low <= target:
            pos.stop_price = target
            pos.last_price = target
            if low < pos.best_price:
                pos.best_price = low
            return "target_20"
        half = peak * (1.0 - config.PAPER_CSS2_HALF_DD_PCT / 100.0)
        if not pos.scaled_half and low <= half:
            pnl = pos.realize_half(half)
            self.balances[trade.variant] += pnl
            self.store.set_kv(f"balance:{trade.variant}", str(self.balances[trade.variant]))
            trade.entry["css2_half"] = True
            self.store.update_trade(
                trade.id,
                {
                    "margin": pos.margin,
                    "notional": pos.notional,
                    "qty": pos.qty,
                    "entry_fee": pos.entry_fee,
                    "funding_paid": pos.funding_paid,
                    "stop_price": pos.stop_price,
                    "best_price": min(pos.best_price, half),
                    "entry_json": trade.entry,
                },
            )
            log.info(
                "Тест [%s]: %s половина на откате %.0f%%, P&L %+.2f USD",
                trade.variant,
                trade.symbol,
                config.PAPER_CSS2_HALF_DD_PCT,
                pnl,
            )
        age_min = (now_ms - pos.opened_at) / 60_000
        band = abs(last / pos.entry_price - 1.0) * 100.0
        no_new_low = low >= pos.entry_price * 0.999 and pos.best_price >= pos.entry_price * 0.999
        if (
            age_min >= config.PAPER_CSS2_TIME_FLAT_MIN
            and band <= config.PAPER_CSS2_TIME_FLAT_BAND_PCT
            and no_new_low
        ):
            pos.stop_price = last
            pos.last_price = last
            return "time_flat"
        return None

    def _on_css2_trade_closed(self, trade: OpenTrade, now_ms: int) -> None:
        cand = self.css2_candidates.get(trade.symbol)
        valley = 0
        if cand is not None:
            valley = cand.pump.valley_ts
            self._end_css2_candidate(cand, "Курсор СС 2: один вход на долину", now_ms)
        else:
            pump = ((trade.entry.get("metrics") or {}).get("pump") or {})
            valley = int(pump.get("valley_ts") or 0)
        if valley:
            self.css2_blocked[trade.symbol] = max(self.css2_blocked.get(trade.symbol, 0), valley)
            self.store.set_kv("css2_blocked", json.dumps(self.css2_blocked))

    def _on_plus_trade_closed(self, trade: OpenTrade, result: dict) -> None:
        roe = float(result.get("roe_pct") or 0.0)
        if not plus_hit_first_stop(trade.variant, roe, trade.pos.max_roe()):
            return
        pump = (trade.entry.get("metrics") or {}).get("pump") or {}
        peak_ts = int(pump.get("peak_ts") or 0)
        if peak_ts <= 0:
            return
        peaks = self.plus_blocked.setdefault(trade.symbol, set())
        if peak_ts in peaks:
            return
        peaks.add(peak_ts)
        payload = {symbol: sorted(values)[-30:] for symbol, values in self.plus_blocked.items() if values}
        self.store.set_kv("plus_blocked_peaks", json.dumps(payload))

    def _end_css2_candidate(self, cand: Css2Candidate, reason: str, now_ms: int) -> None:
        status = "entered" if cand.entered else "expired"
        self.store.update_candidate(
            cand.id,
            {
                "status": status,
                "ended_at": now_ms,
                "end_reason": reason,
                "updated_at": now_ms,
                "scans": cand.scans,
                "fail_counts": cand.fail_counts,
                "best_passed": cand.best_passed,
                "last_eval": _css2_eval_with_state(cand.last_eval or {}, cand),
                "variants": cand.entered,
                "trade_id": cand.last_trade_id,
                **_css2_fields(cand.pump),
            },
        )
        self.css2_candidates.pop(cand.symbol, None)

    def _evaluate_sc10(self, states: dict[str, SymbolState], now_ms: int) -> None:
        variant = config.PAPER_SC10_VARIANT
        btc = states.get(config.PAPER_BTC_SYMBOL)
        cooldown = config.PAPER_SC10_REENTRY_SEC * 1000
        for symbol, state in states.items():
            if not state.last_price:
                continue
            if (variant, symbol) in self.trades:
                continue
            if now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                continue
            tape = self.tape.get(symbol)
            ev = evaluate_sc10(state, tape, btc, now_ms)
            if not ev.passed:
                continue
            bar_ts = int(((ev.metrics.get("pump") or {}).get("bar_ts")) or 0)
            if bar_ts and self._sc10_used_bars.get(symbol) == bar_ts:
                continue
            balance = self.balances[variant]
            margin = balance * config.PAPER_MARGIN_PCT / 100.0
            if margin <= 0 or balance - self.used_margin(variant) < margin:
                continue
            self._open_sc10_trade(symbol, state, ev, margin, now_ms)

    def _open_sc10_trade(
        self, symbol: str, state: SymbolState, ev: Sc10Evaluation, margin: float, now_ms: int
    ) -> None:
        variant = config.PAPER_SC10_VARIANT
        side = ev.side or "long"
        price = float(state.last_price)
        tape = self.tape.symbols.get(symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(
            symbol=symbol,
            opened_at=now_ms,
            entry_price=price,
            margin=margin,
            next_funding_ts=nft,
            side=side,
            stop_style="sc10",
        )
        entry = ev.to_data()
        trade_id = self.store.insert_trade(
            {
                "symbol": symbol,
                "variant": variant,
                "candidate_id": None,
                "kind": f"sc10_{side}",
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": ev.score,
                "grade": grade_for(ev.score),
                "strict_btc": False,
                "balance_before": self.balances[variant],
                "entry_json": entry,
            }
        )
        self.trades[(variant, symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=symbol,
            kind=f"sc10_{side}",
            pos=pos,
            score=ev.score,
            grade=grade_for(ev.score),
            strict_btc=False,
            entry=entry,
            candidate_id=None,
            last_check=now_ms,
        )
        bar_ts = int(((ev.metrics.get("pump") or {}).get("bar_ts")) or 0)
        if bar_ts:
            self._sc10_used_bars[symbol] = bar_ts
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт %s %s по %s, маржа %.2f USD, балл %.1f",
            variant,
            side,
            symbol,
            price,
            margin,
            ev.score,
        )

    def _evaluate_impulse(self, states: dict[str, SymbolState], now_ms: int) -> None:
        frames = (
            (config.PAPER_IMP5_VARIANT, 5),
            (config.PAPER_IMP15_VARIANT, 15),
        )
        for variant, minutes in frames:
            if variant not in VARIANTS:
                continue
            for symbol, state in states.items():
                if not state.last_price or not state.bars_1m:
                    continue
                if (variant, symbol) in self.trades:
                    continue
                tape = self.tape.symbols.get(symbol)
                ev = evaluate_impulse(state, tape, now_ms, minutes)
                if not ev.passed:
                    continue
                bar_ts = int(ev.metrics.get("bar_ts") or 0)
                if bar_ts and self._impulse_used_bars.get((variant, symbol)) == bar_ts:
                    continue
                balance = self.balances[variant]
                margin = balance * config.PAPER_MARGIN_PCT / 100.0
                if margin <= 0 or balance - self.used_margin(variant) < margin:
                    continue
                self._open_impulse_trade(variant, symbol, state, ev, margin, now_ms)

    def _open_impulse_trade(
        self, variant: str, symbol: str, state: SymbolState, ev, margin: float, now_ms: int
    ) -> None:
        side = ev.side or "short"
        price = float(state.last_price)
        tape = self.tape.symbols.get(symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(
            symbol=symbol,
            opened_at=now_ms,
            entry_price=price,
            margin=margin,
            next_funding_ts=nft,
            side=side,
            stop_style="impulse",
        )
        entry = ev.to_data()
        trade_id = self.store.insert_trade(
            {
                "symbol": symbol,
                "variant": variant,
                "candidate_id": None,
                "kind": f"impulse_{side}",
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": ev.score,
                "grade": grade_for(ev.score),
                "strict_btc": False,
                "balance_before": self.balances[variant],
                "entry_json": entry,
            }
        )
        self.trades[(variant, symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=symbol,
            kind=f"impulse_{side}",
            pos=pos,
            score=ev.score,
            grade=grade_for(ev.score),
            strict_btc=False,
            entry=entry,
            candidate_id=None,
            last_check=now_ms,
        )
        bar_ts = int(ev.metrics.get("bar_ts") or 0)
        if bar_ts:
            self._impulse_used_bars[(variant, symbol)] = bar_ts
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт %s %s по %s, маржа %.2f USD, условий %s/%s",
            variant,
            side,
            symbol,
            price,
            margin,
            ev.passed_count,
            len(impulse_mandatory(ev.minutes)),
        )

    def confirm_fetch_symbols(self) -> list[str]:
        """Монеты, которым в момент закрытия 5м нужна свежая свеча: ожидание второй или открытая сделка."""
        return sorted(self._confirm_arm)

    def confirm_fetch_symbols_15(self) -> list[str]:
        """Монеты Пылесоса 15: первая 15м подтверждения уже закрыта или есть открытая сделка."""
        return sorted(self._confirm_arm_15)

    def _refresh_fifteen_min_arm(self, states: dict[str, SymbolState], now_ms: int) -> None:
        opens = {
            symbol
            for variant, symbol in self.trades
            if variant == config.PAPER_VPS15_VARIANT
        }
        if self._confirm_arm_15 and now_ms < self._confirm_arm_15_at + 30_000:
            self._confirm_arm_15 |= opens
            return
        self._confirm_arm_15_at = now_ms
        armed = symbols_waiting_second_bar(states, now_ms, config.PAPER_VPS15_INTERVAL)
        armed |= opens
        self._confirm_arm_15 = armed

    def _refresh_five_min_arm(self, states: dict[str, SymbolState], now_ms: int) -> None:
        opens = {
            symbol
            for variant, symbol in self.trades
            if variant
            in (
                config.PAPER_PYL_VARIANT,
                config.PAPER_PYL1_VARIANT,
                config.PAPER_PYLBTC_VARIANT,
                config.PAPER_VPS5_VARIANT,
            )
        }
        if self._confirm_arm and now_ms < self._confirm_arm_at + 30_000:
            self._confirm_arm |= opens
            return
        self._confirm_arm_at = now_ms
        armed = symbols_waiting_htf_second_bar(states, now_ms)
        armed |= opens
        self._confirm_arm = armed

    def _pivot_entry_window(self, entry: dict, now_ms: int, interval: str) -> bool:
        if not entry.get("passed"):
            return False
        metrics = entry.get("metrics") or {}
        pivot_time = metrics.get("pivot_time_ms")
        if not pivot_time:
            return False
        if interval == "5":
            return entry_on_third_bar(int(pivot_time), now_ms, "5")
        if interval == "15":
            return vps15_entry_confirmed(int(pivot_time), now_ms)
        return just_confirmed(int(pivot_time), now_ms, interval)

    def _five_min_entry_window(self, entry: dict, now_ms: int) -> bool:
        return self._pivot_entry_window(entry, now_ms, config.PAPER_PYL_INTERVAL)

    def _process_bab_opposite_exits(self, states: dict[str, SymbolState], now_ms: int) -> None:
        specs: list[tuple[str, str, str]] = []
        if config.PAPER_PYL_VARIANT in VARIANTS:
            specs.append((config.PAPER_PYL_VARIANT, config.PAPER_PYL_INTERVAL, "pyl"))
        if config.PAPER_PYL1_VARIANT in VARIANTS:
            specs.append((config.PAPER_PYL1_VARIANT, config.PAPER_PYL_INTERVAL, "pyl1"))
        if config.PAPER_PYLBTC_VARIANT in VARIANTS:
            specs.append((config.PAPER_PYLBTC_VARIANT, config.PAPER_PYL_INTERVAL, "pylbtc"))
        if config.PAPER_333_VARIANT in VARIANTS:
            specs.append((config.PAPER_333_VARIANT, config.PAPER_PYL_INTERVAL, "333"))
        if config.PAPER_VPS5_VARIANT in VARIANTS:
            specs.append((config.PAPER_VPS5_VARIANT, config.PAPER_VPS5_INTERVAL, "vps5"))
        if config.PAPER_VPS15_VARIANT in VARIANTS:
            specs.append((config.PAPER_VPS15_VARIANT, config.PAPER_VPS15_INTERVAL, "vps15"))
        for variant, interval, _kind in specs:
            for (v, symbol), trade in list(self.trades.items()):
                if v != variant:
                    continue
                state = states.get(symbol)
                if state is None or not state.last_price:
                    continue
                closed_side = trade.pos.side
                exit_hit: dict | None = None
                if interval == "15":
                    exit_hit = opposite_anchor_pivot_exit(
                        state, now_ms, closed_side, trade.pos.opened_at, interval
                    )
                else:
                    exit_hit = opposite_pivot_exit_signal(
                        state, now_ms, closed_side, trade.pos.opened_at, interval
                    )
                if exit_hit:
                    self._close_trade(trade, "opposite_pivot", state, now_ms)

    def _evaluate_pyl(self, states: dict[str, SymbolState], now_ms: int) -> None:
        self._evaluate_bab_pivot_desk(
            states,
            now_ms,
            config.PAPER_PYL_VARIANT,
            evaluate_pyl,
            self._pyl_prev_snap,
            "pyl",
            lambda w: setattr(self, "_pyl_watch", w),
        )

    def _evaluate_pyl1(self, states: dict[str, SymbolState], now_ms: int) -> None:
        self._evaluate_bab_pivot_desk(
            states,
            now_ms,
            config.PAPER_PYL1_VARIANT,
            evaluate_pyl1,
            self._pyl1_prev_snap,
            "pyl1",
            lambda w: setattr(self, "_pyl1_watch", w),
        )

    def _evaluate_pylbtc(self, states: dict[str, SymbolState], now_ms: int) -> None:
        btc = states.get(config.PAPER_BTC_SYMBOL)

        def evaluate_fn(state: SymbolState, now_ms: int, prev: dict | None) -> dict:
            return evaluate_pylbtc(state, now_ms, prev, btc)

        self._evaluate_bab_pivot_desk(
            states,
            now_ms,
            config.PAPER_PYLBTC_VARIANT,
            evaluate_fn,
            self._pylbtc_prev_snap,
            "pylbtc",
            lambda w: setattr(self, "_pylbtc_watch", w),
        )

    def _evaluate_333(self, states: dict[str, SymbolState], now_ms: int) -> None:
        self._evaluate_bab_pivot_desk(
            states,
            now_ms,
            config.PAPER_333_VARIANT,
            evaluate_333,
            self._333_prev_snap,
            "333",
            lambda w: setattr(self, "_333_watch", w),
        )

    def _evaluate_bab_pivot_desk(
        self,
        states: dict[str, SymbolState],
        now_ms: int,
        variant: str,
        evaluate_fn,
        prev_snaps: dict[str, dict],
        eval_key: str,
        set_watch,
    ) -> None:
        if variant not in VARIANTS:
            return
        interval = config.PAPER_PYL_INTERVAL
        if variant == config.PAPER_PYL1_VARIANT:
            trade_kind = "pyl1"
        elif variant == config.PAPER_PYLBTC_VARIANT:
            trade_kind = "pylbtc"
        elif variant == config.PAPER_333_VARIANT:
            trade_kind = "333"
        else:
            trade_kind = "pyl"
        watch: list[dict] = []
        pyl1 = variant == config.PAPER_PYL1_VARIANT
        open_symbols = {t.symbol for t in self.trades.values() if t.variant == variant}
        scan_symbols = sorted(set(states.keys()) | open_symbols)
        for symbol in scan_symbols:
            state = states.get(symbol)
            if state is None or not state.last_price:
                continue
            track = True
            if pyl1:
                hr_gate = hour_range_pct(state, now_ms)
                track = hr_gate is not None and hr_gate + 1e-12 >= config.PAPER_PYL1_HOUR_RANGE_PCT
            prev = prev_snaps.get(symbol)
            snap = snapshot_pivot_levels(state, interval, now_ms)
            if snap is not None:
                prev_snaps[symbol] = snap
            ev_data = evaluate_fn(state, now_ms, prev)
            ev_clean = {k: v for k, v in ev_data.items() if not str(k).startswith("_")}
            pc = int(ev_clean.get("passed_count") or 0)
            side = ev_clean.get("side")
            fresh = self._five_min_entry_window(ev_clean, now_ms)
            if track and (pc > 0 or (ev_clean.get("metrics") or {}).get("peaks")):
                watch.append(
                    {
                        "symbol": symbol,
                        "passed_count": pc,
                        "failed": list(ev_clean.get("failed") or []),
                        "eval": {eval_key: ev_clean},
                        "grade": ev_clean.get("grade"),
                        "score": ev_clean.get("score"),
                        "ready": fresh,
                        "side": side,
                    }
                )
            open_key = (variant, symbol)
            if open_key in self.trades:
                trade = self.trades[open_key]
                closed_side = trade.pos.side
                exit_hit = opposite_pivot_exit_signal(
                    state, now_ms, closed_side, trade.pos.opened_at, interval
                )
                if exit_hit:
                    opp_ts = int(exit_hit["pivot_time_ms"])
                    self._close_trade(trade, "opposite_pivot", state, now_ms)
                    m = ev_clean.get("metrics") or {}
                    new_side = ev_clean.get("side") or m.get("side")
                    same_pivot = int(m.get("pivot_time_ms") or 0) == opp_ts
                    if (
                        same_pivot
                        and ev_clean.get("passed")
                        and new_side
                        and new_side != closed_side
                        and entry_on_third_bar(opp_ts, now_ms, interval)
                    ):
                        balance = self.balances[variant]
                        margin = balance * config.PAPER_MARGIN_PCT / 100.0
                        if margin > 0 and balance - self.used_margin(variant) >= margin:
                            self._open_pyl_trade(
                                variant, symbol, state, ev_clean, margin, now_ms, kind=trade_kind
                            )
                continue
            if not track or not fresh or not ev_clean.get("passed"):
                continue
            balance = self.balances[variant]
            margin = balance * config.PAPER_MARGIN_PCT / 100.0
            if margin <= 0 or balance - self.used_margin(variant) < margin:
                continue
            self._open_pyl_trade(variant, symbol, state, ev_clean, margin, now_ms, kind=trade_kind)
        watch.sort(key=lambda r: (-int(r["passed_count"]), r["symbol"]))
        set_watch(watch[:100])

    def _open_pyl_trade(
        self,
        variant: str,
        symbol: str,
        state: SymbolState,
        entry: dict,
        margin: float,
        now_ms: int,
        *,
        kind: str = "pyl",
    ) -> None:
        price = float(state.last_price)
        m = entry.get("metrics") or {}
        side = str(m.get("side") or entry.get("side") or "short")
        pivot_high = float(m.get("pivot_high") or 0)
        pivot_low = float(m.get("pivot_low") or 0)
        stop = bab_pivot_stop_price(side, pivot_high, pivot_low)
        tape = self.tape.symbols.get(symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(
            symbol=symbol,
            opened_at=now_ms,
            entry_price=price,
            margin=margin,
            next_funding_ts=nft,
            side=side,
            stop_style=config.paper_stop_style(variant),
            stop_price=stop,
        )
        trade_id = self.store.insert_trade(
            {
                "symbol": symbol,
                "variant": variant,
                "candidate_id": None,
                "kind": kind,
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": entry.get("score", 0),
                "grade": entry.get("grade", "C"),
                "strict_btc": False,
                "balance_before": self.balances[variant],
                "entry_json": entry,
                "side": side,
            }
        )
        self.trades[(variant, symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=symbol,
            kind=kind,
            pos=pos,
            score=float(entry.get("score") or 0),
            grade=str(entry.get("grade") or "C"),
            strict_btc=False,
            entry=entry,
            candidate_id=None,
            last_check=now_ms,
        )
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт %s %s по %s, стоп %s, маржа %.2f USD",
            variant,
            side,
            symbol,
            price,
            stop,
            margin,
        )

    def _evaluate_vac(self, states: dict[str, SymbolState], now_ms: int) -> None:
        variant = config.PAPER_VAC_VARIANT
        if variant not in VARIANTS:
            return
        cooldown = config.PAPER_REENTRY_COOLDOWN_SEC * 1000
        watch: list[dict] = []
        for symbol, state in states.items():
            if not state.last_price or len(state.bars_htf.get("5") or []) < 10:
                continue
            ev_data = evaluate_vac(state, now_ms)
            pc = int(ev_data.get("passed_count") or 0)
            if pc > 0:
                watch.append(
                    {
                        "symbol": symbol,
                        "passed_count": pc,
                        "failed": list(ev_data.get("failed") or []),
                        "eval": {"vac": ev_data},
                        "grade": ev_data.get("grade"),
                        "score": ev_data.get("score"),
                        "ready": bool(ev_data.get("passed")),
                    }
                )
            if (variant, symbol) in self.trades:
                continue
            if now_ms - self.last_close.get((variant, symbol), 0) < cooldown:
                continue
            if not ev_data.get("passed"):
                continue
            bar_ts = int(ev_data.get("metrics", {}).get("bar_ts") or 0)
            if bar_ts and self._vac_used_bars.get((variant, symbol)) == bar_ts:
                continue
            balance = self.balances[variant]
            margin = balance * config.PAPER_MARGIN_PCT / 100.0
            if margin <= 0 or balance - self.used_margin(variant) < margin:
                continue
            self._open_vac_trade(variant, symbol, state, ev_data, margin, now_ms)
        watch.sort(key=lambda r: (-int(r["passed_count"]), r["symbol"]))
        self._vac_watch = watch[:100]

    def _open_vac_trade(
        self, variant: str, symbol: str, state: SymbolState, entry: dict, margin: float, now_ms: int
    ) -> None:
        price = float(state.last_price)
        tape = self.tape.symbols.get(symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(
            symbol=symbol,
            opened_at=now_ms,
            entry_price=price,
            margin=margin,
            next_funding_ts=nft,
            side="short",
            stop_style=config.paper_stop_style(variant),
        )
        trade_id = self.store.insert_trade(
            {
                "symbol": symbol,
                "variant": variant,
                "candidate_id": None,
                "kind": "vac",
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": entry.get("score", 0),
                "grade": entry.get("grade", "C"),
                "strict_btc": False,
                "balance_before": self.balances[variant],
                "entry_json": entry,
            }
        )
        self.trades[(variant, symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=symbol,
            kind="vac",
            pos=pos,
            score=float(entry.get("score") or 0),
            grade=str(entry.get("grade") or "C"),
            strict_btc=False,
            entry=entry,
            candidate_id=None,
            last_check=now_ms,
        )
        bar_ts = int(entry.get("metrics", {}).get("bar_ts") or 0)
        if bar_ts:
            self._vac_used_bars[(variant, symbol)] = bar_ts
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт шорт %s по %s, маржа %.2f USD, условий %s/%s",
            variant,
            symbol,
            price,
            margin,
            entry.get("passed_count"),
            len(VAC_MANDATORY),
        )

    def _evaluate_vps_variants(self, states: dict[str, SymbolState], now_ms: int) -> None:
        specs = [
            (config.PAPER_VPS15_VARIANT, config.PAPER_VPS15_INTERVAL, "_vps15_watch"),
            (config.PAPER_VPS5_VARIANT, config.PAPER_VPS5_INTERVAL, "_vps5_watch"),
        ]
        for variant, interval, watch_attr in specs:
            if variant not in VARIANTS:
                continue
            watch: list[dict] = []
            for symbol, state in states.items():
                prev = self._vps_prev_snap.get((variant, symbol))
                ev_data = evaluate_htf_pivot_entry(
                    state, now_ms, prev, interval, kind=variant, variant=variant
                )
                ev_data = {k: v for k, v in ev_data.items() if not str(k).startswith("_")}
                m = ev_data.get("metrics") or {}
                snap = snapshot_pivot_levels(state, interval, now_ms)
                if snap is not None:
                    self._vps_prev_snap[(variant, symbol)] = snap
                fresh = self._pivot_entry_window(ev_data, now_ms, interval)
                pc = int(ev_data.get("passed_count") or 0)
                if pc > 0 or m.get("peaks") or m.get("troughs"):
                    watch.append(
                        {
                            "symbol": symbol,
                            "passed_count": pc,
                            "failed": list(ev_data.get("failed") or []),
                            "eval": {variant: ev_data},
                            "grade": ev_data.get("grade"),
                            "score": ev_data.get("score"),
                            "ready": fresh,
                            "side": ev_data.get("side") or m.get("side"),
                        }
                    )
                open_key = (variant, symbol)
                if open_key in self.trades:
                    trade = self.trades[open_key]
                    closed_side = trade.pos.side
                    side = ev_data.get("side") or m.get("side")
                    if interval == "15":
                        opp_exit = opposite_anchor_pivot_exit(
                            state, now_ms, closed_side, trade.pos.opened_at, interval
                        )
                        raw_exit = None
                        confirmed_exit = opp_exit is not None
                    else:
                        opp_exit = None
                        confirmed_exit = bool(fresh and side and side != closed_side)
                        raw_exit = opposite_appeared(
                            state, now_ms, closed_side, trade.pos.opened_at, interval
                        )
                    if raw_exit or confirmed_exit:
                        self._close_trade(trade, "opposite_pivot", state, now_ms)
                        reenter = (
                            confirmed_exit
                            and ev_data.get("passed")
                            and side
                            and side != closed_side
                            and (fresh if interval == "15" else True)
                        )
                        if reenter:
                            balance = self.balances[variant]
                            margin = balance * config.PAPER_MARGIN_PCT / 100.0
                            if margin > 0 and balance - self.used_margin(variant) >= margin:
                                self._open_vps_trade(variant, symbol, state, ev_data, margin, now_ms)
                    continue
                if not fresh:
                    continue
                signal_key = str(m.get("signal_key") or "")
                if signal_key and self._vps_used_signals.get((variant, symbol)) == signal_key:
                    continue
                balance = self.balances[variant]
                margin = balance * config.PAPER_MARGIN_PCT / 100.0
                if margin <= 0 or balance - self.used_margin(variant) < margin:
                    continue
                self._open_vps_trade(variant, symbol, state, ev_data, margin, now_ms)
            watch.sort(key=lambda r: (-int(r["passed_count"]), r["symbol"]))
            setattr(self, watch_attr, watch[:100])

    def _open_vps_trade(
        self, variant: str, symbol: str, state: SymbolState, entry: dict, margin: float, now_ms: int
    ) -> None:
        price = float(state.last_price)
        side = str((entry.get("metrics") or {}).get("side") or "short")
        tape = self.tape.symbols.get(symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(
            symbol=symbol,
            opened_at=now_ms,
            entry_price=price,
            margin=margin,
            next_funding_ts=nft,
            side=side,
            stop_style=config.paper_stop_style(variant),
        )
        trade_id = self.store.insert_trade(
            {
                "symbol": symbol,
                "variant": variant,
                "candidate_id": None,
                "kind": variant,
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": entry.get("score", 0),
                "grade": entry.get("grade", "C"),
                "strict_btc": False,
                "balance_before": self.balances[variant],
                "entry_json": entry,
                "side": side,
            }
        )
        self.trades[(variant, symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=symbol,
            kind=variant,
            pos=pos,
            score=float(entry.get("score") or 0),
            grade=str(entry.get("grade") or "C"),
            strict_btc=False,
            entry=entry,
            candidate_id=None,
            last_check=now_ms,
        )
        signal_key = str((entry.get("metrics") or {}).get("signal_key") or "")
        if signal_key:
            self._vps_used_signals[(variant, symbol)] = signal_key
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт %s %s по %s, маржа %.2f USD, сигнал %s",
            variant,
            side,
            symbol,
            price,
            margin,
            signal_key or "?",
        )

    def _open_trade(self, variant: str, cand: Candidate, state: SymbolState, ev, margin: float, now_ms: int) -> None:
        price = float(state.last_price)
        tape = self.tape.symbols.get(cand.symbol)
        nft = tape.next_funding_ts if tape is not None and tape.next_funding_ts and tape.next_funding_ts > now_ms else None
        pos = Position(
            symbol=cand.symbol,
            opened_at=now_ms,
            entry_price=price,
            margin=margin,
            next_funding_ts=nft,
            peak_gap_roe=config.paper_peak_gap_roe(variant),
            stop_style=config.paper_stop_style(variant),
        )
        entry = ev.to_data()
        trade_id = self.store.insert_trade(
            {
                "symbol": cand.symbol,
                "variant": variant,
                "candidate_id": cand.id,
                "kind": cand.pump.kind,
                "status": "open",
                "opened_at": now_ms,
                "entry_price": price,
                "margin": margin,
                "leverage": pos.leverage,
                "notional": pos.notional,
                "qty": pos.qty,
                "liq_price": pos.liq_price,
                "stop_price": pos.stop_price,
                "best_price": pos.best_price,
                "worst_price": pos.worst_price,
                "last_price": price,
                "entry_fee": pos.entry_fee,
                "funding_paid": 0.0,
                "next_funding_ts": nft,
                "score": ev.score,
                "grade": grade_for(ev.score),
                "strict_btc": ev.strict_btc,
                "balance_before": self.balances[variant],
                "entry_json": entry,
            }
        )
        self.trades[(variant, cand.symbol)] = OpenTrade(
            id=trade_id,
            variant=variant,
            symbol=cand.symbol,
            kind=cand.pump.kind,
            pos=pos,
            score=ev.score,
            grade=grade_for(ev.score),
            strict_btc=ev.strict_btc,
            entry=entry,
            candidate_id=cand.id,
            last_check=now_ms,
        )
        if variant not in cand.entered:
            cand.entered.append(variant)
        cand.last_trade_id = trade_id
        cand.dirty = True
        self._next_analytics = 0
        log.info(
            "Тест [%s]: открыт шорт %s по %s, маржа %.2f USD, условий %s/%s, балл %.1f",
            variant,
            cand.symbol,
            price,
            margin,
            ev.passed_count,
            (
                len(MINI_MANDATORY)
                if variant in config.PAPER_MINI_VARIANTS
                else len(MINI_CHART_MANDATORY)
                if variant == config.PAPER_MT2C_VARIANT
                else len(GRAF_MANDATORY)
                if variant == config.PAPER_GRAF_VARIANT
                else len(DPS_MANDATORY)
                if variant == config.PAPER_DPS_VARIANT
                else len(C3_MANDATORY)
                if variant == config.PAPER_C3_VARIANT
                else len(E5S_MANDATORY)
                if variant in (config.PAPER_E5S_VARIANT, config.PAPER_E5P_VARIANT)
                else len(PLUS_MANDATORY)
                if variant in config.PAPER_PLUS_VARIANTS
                else len(MANDATORY)
            ),
            ev.score,
        )

    def _start_shadow(self, cand: Candidate, state: SymbolState, missing: str, now_ms: int) -> None:
        price = float(state.last_price)
        pos = Position(symbol=cand.symbol, opened_at=now_ms, entry_price=price, margin=_SHADOW_MARGIN)
        cand.near_miss = True
        self.store.update_candidate(
            cand.id,
            {
                "near_miss_at": now_ms,
                "near_miss_missing": missing,
                "near_miss_json": cand.last_eval,
                "shadow_status": "open",
                "shadow_entry_price": price,
                "shadow_opened_at": now_ms,
                "shadow_stop": pos.stop_price,
                "shadow_best": pos.best_price,
                "shadow_worst": pos.worst_price,
                "shadow_liq": pos.liq_price,
                "shadow_entry_fee": pos.entry_fee,
                "shadow_margin": pos.margin,
            },
        )
        self.shadows[cand.id] = Shadow(cand.id, cand.symbol, missing, pos, now_ms)

    def _end_candidate(self, cand: Candidate, reason: str, now_ms: int) -> None:
        status = "entered" if cand.entered else "expired"
        fields = {
            "status": status,
            "ended_at": now_ms,
            "end_reason": reason,
            "updated_at": now_ms,
            "scans": cand.scans,
            "fail_counts": cand.fail_counts,
            "best_passed": cand.best_passed,
            "last_eval": cand.last_eval or {},
            "variants": cand.entered,
            "trade_id": cand.last_trade_id,
            **_pump_fields(cand.pump),
        }
        self.store.update_candidate(cand.id, fields)
        self.expired_peaks[cand.symbol] = cand.pump.peak_ts
        self.candidates.pop(cand.symbol, None)

    def _end_growth_candidate(self, cand: GrowthCandidate, reason: str, now_ms: int) -> None:
        status = "entered" if cand.entered else "expired"
        fields = {
            "status": status,
            "ended_at": now_ms,
            "end_reason": reason,
            "updated_at": now_ms,
            "scans": cand.scans,
            "fail_counts": cand.fail_counts,
            "best_passed": cand.best_passed,
            "last_eval": cand.last_eval or {},
            "variants": cand.entered,
            "trade_id": cand.last_trade_id,
            **_growth_fields(cand.growth),
        }
        self.store.update_candidate(cand.id, fields)
        self.growth_candidates.pop(cand.symbol, None)

    def _persist(self, now_ms: int, force: bool = False) -> None:
        if not force and now_ms < self._next_persist:
            return
        self._next_persist = now_ms + config.PAPER_PERSIST_INTERVAL_SEC * 1000
        for trade in self.trades.values():
            pos = trade.pos
            self.store.update_trade(
                trade.id,
                {
                    "side": pos.side,
                    "stop_price": pos.stop_price,
                    "liq_price": pos.liq_price,
                    "best_price": pos.best_price,
                    "worst_price": pos.worst_price,
                    "last_price": pos.last_price,
                    "funding_paid": pos.funding_paid,
                    "next_funding_ts": pos.next_funding_ts,
                    "max_roe": pos.max_roe(),
                    "min_roe": pos.min_roe(),
                },
                commit=False,
            )
        for cand in self.candidates.values():
            if not cand.dirty:
                continue
            self.store.update_candidate(
                cand.id,
                {
                    "updated_at": now_ms,
                    "scans": cand.scans,
                    "fail_counts": cand.fail_counts,
                    "best_passed": cand.best_passed,
                    "last_eval": cand.last_eval or {},
                    "variants": cand.entered,
                    "trade_id": cand.last_trade_id,
                    **_pump_fields(cand.pump, soft=cand.soft),
                },
                commit=False,
            )
            cand.dirty = False
        for cand in self.growth_candidates.values():
            if not cand.dirty:
                continue
            self.store.update_candidate(
                cand.id,
                {
                    "updated_at": now_ms,
                    "scans": cand.scans,
                    "fail_counts": cand.fail_counts,
                    "best_passed": cand.best_passed,
                    "last_eval": cand.last_eval or {},
                    "variants": cand.entered,
                    "trade_id": cand.last_trade_id,
                    **_growth_fields(cand.growth),
                },
                commit=False,
            )
            cand.dirty = False
        for cand in self.css_candidates.values():
            if not cand.dirty:
                continue
            self.store.update_candidate(
                cand.id,
                {
                    "updated_at": now_ms,
                    "scans": cand.scans,
                    "fail_counts": cand.fail_counts,
                    "best_passed": cand.best_passed,
                    "last_eval": _css_eval_with_state(cand.last_eval or {}, cand),
                    "variants": cand.entered,
                    "trade_id": cand.last_trade_id,
                    **_css_fields(cand.pump),
                },
                commit=False,
            )
            cand.dirty = False
        for cand in self.css2_candidates.values():
            if not cand.dirty:
                continue
            self.store.update_candidate(
                cand.id,
                {
                    "updated_at": now_ms,
                    "scans": cand.scans,
                    "fail_counts": cand.fail_counts,
                    "best_passed": cand.best_passed,
                    "last_eval": _css2_eval_with_state(cand.last_eval or {}, cand),
                    "variants": cand.entered,
                    "trade_id": cand.last_trade_id,
                    **_css2_fields(cand.pump),
                },
                commit=False,
            )
            cand.dirty = False
        for shadow in self.shadows.values():
            self.store.update_candidate(
                shadow.candidate_id,
                {
                    "shadow_stop": shadow.pos.stop_price,
                    "shadow_best": shadow.pos.best_price,
                    "shadow_worst": shadow.pos.worst_price,
                    "shadow_max_roe": shadow.pos.max_roe(),
                },
                commit=False,
            )
        self.store.commit()

    def _save_tape(self, now_ms: int) -> None:
        since = now_ms - 15 * 60_000
        rows: list[tuple[str, int, float, float]] = []
        minute_rows: list[tuple[str, int, float, float, float, float]] = []
        for symbol, tape in self.tape.symbols.items():
            for ts, (buy, sell) in tape.buckets.items():
                if ts >= since:
                    rows.append((symbol, ts, buy, sell))
            keys = {k for k in tape.minutes if k >= since}
            keys |= {k for k in tape.liq_long if k >= since}
            keys |= {k for k in tape.liq_short if k >= since}
            for ts in keys:
                buy, sell = tape.minutes.get(ts) or (0.0, 0.0)
                minute_rows.append(
                    (symbol, ts, buy, sell, tape.liq_long.get(ts, 0.0), tape.liq_short.get(ts, 0.0))
                )
        self.store.save_tape(rows, now_ms - config.PAPER_TAPE_RETENTION_HOURS * 3_600_000)
        self.store.save_tape_minutes(minute_rows, now_ms - _MINUTES_KEEP_MS)

    def _load_tape(self, now_ms: int) -> None:
        cutoff = now_ms - config.PAPER_TAPE_RETENTION_HOURS * 3_600_000
        for row in self.store.load_tape(cutoff):
            tape = self.tape.get(str(row["symbol"]))
            ts = int(row["ts"])
            tape.buckets[ts] = [float(row["buy"]), float(row["sell"])]
            if tape.first_ts is None or ts < tape.first_ts:
                tape.first_ts = ts
        for row in self.store.load_tape_minutes(now_ms - _MINUTES_KEEP_MS):
            tape = self.tape.get(str(row["symbol"]))
            ts = int(row["ts"])
            if row["buy"] or row["sell"]:
                tape.minutes[ts] = [float(row["buy"]), float(row["sell"])]
            if row["liq_long"]:
                tape.liq_long[ts] = float(row["liq_long"])
            if row["liq_short"]:
                tape.liq_short[ts] = float(row["liq_short"])

    # --- вид для браузера ---

    def view(self, now_ms: int, btc_4h: float | None) -> dict:
        trades = sorted(self.trades.values(), key=lambda t: t.pos.opened_at, reverse=True)
        cands = sorted(
            self.candidates.values(),
            key=lambda c: (-((c.last_eval or {}).get("passed_count") or 0), -c.pump.growth_pct),
        )
        gcands = sorted(
            self.growth_candidates.values(),
            key=lambda c: (-((c.last_eval or {}).get("passed_count") or 0), -c.growth.rally_pct),
        )
        ccands = sorted(
            self.css_candidates.values(),
            key=lambda c: (-((c.last_eval or {}).get("passed_count") or 0), -c.pump.growth_pct),
        )
        c2cands = sorted(
            self.css2_candidates.values(),
            key=lambda c: (-((c.last_eval or {}).get("passed_count") or 0), -c.pump.growth_pct),
        )
        accounts = {}
        for variant in VARIANTS:
            used = self.used_margin(variant)
            unreal = self.unrealized(variant)
            balance = self.balances[variant]
            accounts[variant] = {
                "label": VARIANT_LABELS[variant],
                "balance": round(balance, 2),
                "equity": round(balance + unreal, 2),
                "unrealized": round(unreal, 2),
                "used_margin": round(used, 2),
                "free_margin": round(balance - used, 2),
                "open_trades": len(self._variant_trades(variant)),
            }
        return {
            "updated_at": now_ms,
            "summary": {
                "start_balance": config.PAPER_START_BALANCE_USD,
                "accounts": accounts,
                "candidates": len(self.candidates)
                + len(self.growth_candidates)
                + len(self.css_candidates)
                + len(self.css2_candidates),
                "shadows_open": len(self.shadows),
                "btc_4h_pct": _r(btc_4h),
                "btc_strict": btc_4h is not None and btc_4h >= config.PAPER_BTC_STRICT_4H_PCT,
                "margin_pct": config.PAPER_MARGIN_PCT,
                "leverage": config.PAPER_LEVERAGE,
                "fee_rate": config.PAPER_FEE_RATE_TAKER,
            },
            "variants": list(VARIANTS),
            "test_variants": [v for v in VARIANTS if v not in config.PAPER_DESK_VARIANTS],
            "desk_variants": list(config.PAPER_DESK_VARIANTS),
            "variant_labels": VARIANT_LABELS,
            "entry_gate_labels": ENTRY_GATE_LABELS,
            "open_trades": [self._trade_view(t, now_ms) for t in trades],
            "candidates": [self._candidate_view(c, now_ms) for c in cands]
            + [self._growth_candidate_view(c, now_ms) for c in gcands]
            + [self._css_candidate_view(c, now_ms) for c in ccands]
            + [self._css2_candidate_view(c, now_ms) for c in c2cands],
            "check_labels": CHECK_LABELS,
            "growth_check_labels": GROWTH_CHECK_LABELS,
            "css_check_labels": CSS_CHECK_LABELS,
            "css2_check_labels": CSS2_CHECK_LABELS,
            "sc10_check_labels": SC10_CHECK_LABELS,
            "e5s_check_labels": E5S_CHECK_LABELS,
            "plus_check_labels": PLUS_CHECK_LABELS,
            "c3_check_labels": C3_CHECK_LABELS,
            "mini_check_labels": MINI_CHECK_LABELS,
            "mini_chart_check_labels": MINI_CHART_CHECK_LABELS,
            "graf_check_labels": GRAF_CHECK_LABELS,
            "dps_check_labels": DPS_CHECK_LABELS,
            "impulse_check_labels": IMPULSE_CHECK_LABELS,
            "mandatory": list(MANDATORY),
            "growth_mandatory": list(GROWTH_CORE),
            "growth_flex": list(GROWTH_FLEX),
            "css_mandatory": list(CSS_MANDATORY),
            "css2_mandatory": list(CSS2_MANDATORY),
            "sc10_mandatory": list(SC10_MANDATORY),
            "e5s_mandatory": list(E5S_MANDATORY),
            "plus_mandatory": list(PLUS_MANDATORY),
            "c3_mandatory": list(C3_MANDATORY),
            "mini_mandatory": list(MINI_MANDATORY),
            "mini_chart_mandatory": list(MINI_CHART_MANDATORY),
            "graf_mandatory": list(GRAF_MANDATORY),
            "dps_mandatory": list(DPS_MANDATORY),
            "pyl_check_labels": PYL_CHECK_LABELS,
            "pyl_mandatory": list(PYL_MANDATORY),
            "pyl_watch": list(self._pyl_watch),
            "pyl1_check_labels": PYL1_CHECK_LABELS,
            "pyl1_mandatory": list(PYL1_MANDATORY_5),
            "pyl1_watch": list(self._pyl1_watch),
            "pylbtc_check_labels": PYLBTC_CHECK_LABELS,
            "pylbtc_mandatory": list(PYLBTC_MANDATORY_5),
            "pylbtc_watch": list(self._pylbtc_watch),
            "333_check_labels": PYL333_CHECK_LABELS,
            "333_mandatory": list(PYL333_MANDATORY_5),
            "333_watch": list(self._333_watch),
            "vac_check_labels": VAC_CHECK_LABELS,
            "vac_mandatory": list(VAC_MANDATORY),
            "vac_watch": list(self._vac_watch),
            "vps_check_labels": VPS_CHECK_LABELS,
            "vps_mandatory": list(VPS_MANDATORY),
            "vps15_watch": list(self._vps15_watch),
            "vps5_watch": list(self._vps5_watch),
            "impulse_mandatory": list(IMPULSE_MANDATORY),
            "impulse5_mandatory": list(IMPULSE5_EXTRA_MANDATORY),
            "analytics": self._analytics,
        }

    def _trade_view(self, trade: OpenTrade, now_ms: int) -> dict:
        pos = trade.pos
        price = pos.last_price
        metrics = trade.entry.get("metrics") or {}
        pump = dict(metrics.get("pump") or metrics.get("growth") or {})
        live = self.peak_snapshots.get(trade.symbol)
        if live:
            pump["peak_price"] = live[0]
            pump["peak_ts"] = live[1]
        return {
            "id": trade.id,
            "variant": trade.variant,
            "symbol": trade.symbol,
            "kind": trade.kind,
            "side": trade.pos.side,
            "pump": pump,
            "opened_at": pos.opened_at,
            "duration_min": round((now_ms - pos.opened_at) / 60_000),
            "entry_price": pos.entry_price,
            "last_price": price,
            "stop_price": pos.stop_price,
            "liq_price": pos.liq_price,
            "best_price": pos.best_price,
            "worst_price": pos.worst_price,
            "margin": round(pos.margin, 2),
            "notional": round(pos.notional, 2),
            "qty": pos.qty,
            "price_change_pct": _r((price / pos.entry_price - 1) * 100.0),
            "roe_pct": _r(pos.net_roe(price)),
            "pnl_usd": _r(pos.net_pnl(price)),
            "max_roe": _r(pos.max_roe()),
            "min_roe": _r(pos.min_roe()),
            "entry_fee": _r(pos.entry_fee, 4),
            "funding_paid": _r(pos.funding_paid, 4),
            "next_funding_ts": pos.next_funding_ts,
            "score": _r(trade.score, 1),
            "grade": trade.grade,
            "strict_btc": trade.strict_btc,
            "entry": trade.entry,
        }

    def _candidate_view(self, cand: Candidate, now_ms: int) -> dict:
        shadow = self.shadows.get(cand.id)
        ev = _apply_entry_gate(cand.last_eval)
        blocked = (ev or {}).get("entry_blocked") or []
        note = cand.note
        if blocked and not note:
            note = "Вход закрыт: " + "; ".join(ENTRY_GATE_LABELS.get(k, k) for k in blocked)
        return {
            "id": cand.id,
            "symbol": cand.symbol,
            "pump": cand.pump.to_data(),
            "started_at": cand.started_at,
            "watch_min": round((now_ms - cand.started_at) / 60_000),
            "scans": cand.scans,
            "best_passed": cand.best_passed,
            "entered": cand.entered,
            "open_in": [v for v in VARIANTS if (v, cand.symbol) in self.trades],
            "note": note,
            "eval": ev,
            "shadow": (
                {
                    "entry_price": shadow.pos.entry_price,
                    "roe_pct": _r(shadow.pos.net_roe(shadow.pos.last_price)),
                    "missing": shadow.missing,
                }
                if shadow
                else None
            ),
        }

    def _growth_candidate_view(self, cand: GrowthCandidate, now_ms: int) -> dict:
        ev = cand.last_eval
        return {
            "id": cand.id,
            "symbol": cand.symbol,
            "episode": "growth",
            "pump": cand.growth.to_data(),
            "started_at": cand.started_at,
            "watch_min": round((now_ms - cand.started_at) / 60_000),
            "scans": cand.scans,
            "best_passed": cand.best_passed,
            "entered": cand.entered,
            "open_in": [v for v in VARIANTS if (v, cand.symbol) in self.trades],
            "note": cand.note,
            "eval": ev,
            "shadow": None,
        }

    def _css_candidate_view(self, cand: CssCandidate, now_ms: int) -> dict:
        ev = cand.last_eval
        return {
            "id": cand.id,
            "symbol": cand.symbol,
            "episode": "css",
            "pump": cand.pump.to_data(),
            "started_at": cand.started_at,
            "watch_min": round((now_ms - cand.started_at) / 60_000),
            "scans": cand.scans,
            "best_passed": cand.best_passed,
            "entered": cand.entered,
            "open_in": [v for v in VARIANTS if (v, cand.symbol) in self.trades],
            "note": cand.note,
            "eval": ev,
            "shadow": None,
            "entries_used": cand.entries_used,
            "rearm_needed": cand.rearm_needed,
        }

    def _css2_candidate_view(self, cand: Css2Candidate, now_ms: int) -> dict:
        return {
            "id": cand.id,
            "symbol": cand.symbol,
            "episode": "css2",
            "pump": cand.pump.to_data(),
            "started_at": cand.started_at,
            "watch_min": round((now_ms - cand.started_at) / 60_000),
            "scans": cand.scans,
            "best_passed": cand.best_passed,
            "entered": cand.entered,
            "open_in": [v for v in VARIANTS if (v, cand.symbol) in self.trades],
            "note": cand.note,
            "eval": cand.last_eval,
            "shadow": None,
            "entries_used": cand.entries_used,
        }


def _price_range(state: SymbolState, since_ms: int) -> tuple[float, float, float]:
    last = float(state.last_price or 0)
    low = high = last
    start = minute_start(since_ms)
    for bar in state.bars_1m:
        if bar.timestamp > start:
            low = min(low, bar.low)
            high = max(high, bar.high)
    return low, high, last


def _expire_reason(pump: PumpInfo, state: SymbolState, now_ms: int) -> str:
    last = float(state.last_price or 0)
    if pump.peak_price > 0 and last > 0:
        if (1 - last / pump.peak_price) * 100.0 > config.PAPER_MAX_DRAWDOWN_FROM_PEAK_PCT:
            return "откат от пика"
    hours = config.PAPER_SHORT_LIFETIME_HOURS if pump.kind == "short" else config.PAPER_LONG_LIFETIME_HOURS
    if now_ms - pump.peak_ts > hours * 3_600_000:
        return "истекло время после пика"
    return _REASON_CONDITIONS


def _css2_fields(pump: Css2PumpInfo) -> dict:
    return {
        "kind": "css2",
        "peak_price": pump.peak_price,
        "peak_ts": pump.peak_ts,
        "valley_price": pump.valley_price,
        "valley_ts": pump.valley_ts,
        "growth_pct": pump.growth_pct,
    }


def _css2_from_row(row) -> Css2PumpInfo:
    last_eval = _loads(row["last_eval"]) or {}
    data = (last_eval.get("metrics") or {}).get("pump") or {}
    return Css2PumpInfo(
        valley_price=float(row["valley_price"] or data.get("valley_price") or 0),
        valley_ts=int(row["valley_ts"] or data.get("valley_ts") or 0),
        peak_price=float(row["peak_price"] or 0),
        peak_ts=int(row["peak_ts"] or 0),
        growth_pct=float(row["growth_pct"] or data.get("growth_pct") or 0),
        volume_ratio=data.get("volume_ratio"),
    )


def _css2_eval_with_state(ev: dict, cand: Css2Candidate) -> dict:
    out = dict(ev)
    out["css2_state"] = {"entries_used": cand.entries_used}
    return out


def _css_fields(pump: CssPumpInfo) -> dict:
    return {
        "kind": "css",
        "peak_price": pump.peak_price,
        "peak_ts": pump.peak_ts,
        "valley_price": pump.valley_price,
        "valley_ts": pump.valley_ts,
        "growth_pct": pump.growth_pct,
    }


def _css_from_row(row) -> CssPumpInfo:
    last_eval = _loads(row["last_eval"]) or {}
    data = (last_eval.get("metrics") or {}).get("pump") or {}
    css_state = last_eval.get("css_state") or {}
    return CssPumpInfo(
        valley_price=float(row["valley_price"] or data.get("valley_price") or 0),
        valley_ts=int(row["valley_ts"] or data.get("valley_ts") or 0),
        peak_price=float(row["peak_price"] or 0),
        peak_ts=int(row["peak_ts"] or 0),
        growth_pct=float(row["growth_pct"] or data.get("growth_pct") or 0),
        volume_ratio=data.get("volume_ratio"),
        volume_avg_ratio=data.get("volume_avg_ratio"),
        buy_share_pct=data.get("buy_share_pct"),
        tape_minutes=int(data.get("tape_minutes") or 0),
        stall_low=data.get("stall_low"),
        stall_high=data.get("stall_high"),
        stall_frozen=bool(css_state.get("stall_frozen", data.get("stall_frozen"))),
    )


def _css_eval_with_state(ev: dict, cand: CssCandidate) -> dict:
    out = dict(ev)
    out["css_state"] = {
        "entries_used": cand.entries_used,
        "rearm_needed": cand.rearm_needed,
        "stall_frozen": cand.pump.stall_frozen,
    }
    return out


def _growth_fields(growth: GrowthInfo) -> dict:
    return {
        "kind": "growth",
        "peak_price": growth.peak_price,
        "peak_ts": growth.peak_ts,
        "valley_price": growth.anchor_price,
        "valley_ts": growth.anchor_ts,
        "growth_pct": growth.rally_pct,
    }


def _growth_from_row(row) -> GrowthInfo:
    last_eval = _loads(row["last_eval"]) or {}
    data = (last_eval.get("metrics") or {}).get("growth") or {}
    return GrowthInfo(
        anchor_price=float(row["valley_price"] or data.get("anchor_price") or 0),
        anchor_ts=int(row["valley_ts"] or data.get("anchor_ts") or 0),
        rally_pct=float(row["growth_pct"] or data.get("rally_pct") or 0),
        peak_price=float(row["peak_price"] or 0),
        peak_ts=int(row["peak_ts"] or 0),
        volume_ratio_4h=data.get("volume_ratio_4h"),
        buy_share_pct=data.get("buy_share_pct"),
    )


def _pump_fields(pump: PumpInfo, soft: bool = False) -> dict:
    return {
        "kind": "mini" if soft else pump.kind,
        "peak_price": pump.peak_price,
        "peak_ts": pump.peak_ts,
        "valley_price": pump.valley_price,
        "valley_ts": pump.valley_ts,
        "growth_pct": pump.growth_pct,
    }


def _pump_from_row(row) -> PumpInfo:
    last_eval = _loads(row["last_eval"]) or {}
    data = (last_eval.get("metrics") or {}).get("pump") or {}
    return PumpInfo(
        kind=str(row["kind"] or "short"),
        trigger=str(data.get("trigger") or ""),
        growth_pct=float(row["growth_pct"] or 0),
        valley_price=float(row["valley_price"] or 0),
        valley_ts=int(row["valley_ts"] or 0),
        peak_price=float(row["peak_price"] or 0),
        peak_ts=int(row["peak_ts"] or 0),
        growth=data.get("growth") or {},
        volume_ratio=data.get("volume_ratio"),
        volume_avg_ratio=data.get("volume_avg_ratio"),
        buy_share_pct=data.get("buy_share_pct"),
        tape_minutes=int(data.get("tape_minutes") or 0),
    )


def _apply_entry_gate(ev: dict | None) -> dict | None:
    """Пересчитать шлюз на сохранённом last_eval — после рестарта оценка может быть старой."""
    if not isinstance(ev, dict) or not ev:
        return ev
    blocked = paper_entry_blocks(ev.get("metrics") or {})
    if ev.get("entry_blocked") == blocked and (not blocked or not ev.get("variants")):
        return ev
    out = dict(ev)
    out["entry_blocked"] = blocked
    if blocked:
        out["variants"] = []
    return out


def _loads(raw) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _loads_list(raw) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _r(value, digits: int = 2):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None
