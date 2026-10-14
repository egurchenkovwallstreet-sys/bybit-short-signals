"""Вход копий Трейл 20+ / 10 п.п.+ / Молния+.

Тот же памп, что у t20/p10/mln, и тот же шлюз. Дальше не «5 из 9», а все
проверки сразу: 7 закрытых 5м без нового хая, продажи >55% на 5/10/15,
рост объёма продаж на 5 и 15 мин, объём торгов упал (без «раздачи»),
OI 1ч не растёт, и запрет входа позже 3 ч при откате от пика больше 15%.
Повтор на том же пике после первого стопа решает стратегия, не детектор.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from signal_engine.paper.detect import ENTRY_GATE_LABELS, Evaluation
from signal_engine.paper.e5s_detect import closed_5m, merged_5m
from signal_engine.paper.tape import MINUTE_MS, SymbolTape, minute_start
from signal_engine.state import Bar, SymbolState

PLUS_MANDATORY = (
    "no_new_high",
    "sells_55",
    "sell_volume_up",
    "volume_falling",
    "oi_not_rising",
    "not_late_deep",
    "entry_gate",
)

PLUS_CHECK_LABELS = {
    "no_new_high": "7 свечей 5м без нового хая",
    "sells_55": "продажи >55% на 5, 10 и 15 мин",
    "sell_volume_up": "объём продаж растёт на 5 и 15 мин",
    "volume_falling": "объём торгов падает",
    "oi_not_rising": "OI 1ч не растёт",
    "not_late_deep": "не позже 3 ч с откатом >15%",
    "entry_gate": "шлюз пампа",
}


def plus_hit_first_stop(variant: str, roe_pct: float, max_roe: float) -> bool:
    """Первый стоп в минус: пик не дошёл до лока, выход у красного стопа или ликвидации."""
    if variant == config.PAPER_MLNP_VARIANT:
        return max_roe < config.PAPER_MLN_LOCK2_ARM_ROE and roe_pct <= config.PAPER_MLN_INITIAL_STOP_ROE + 2.0
    if variant in (config.PAPER_T20P_VARIANT, config.PAPER_P10P_VARIANT):
        return max_roe < config.PAPER_BE_ARM_ROE and roe_pct <= config.PAPER_LOSS_CAP_ROE + 2.0
    return False


def _sell_share(buy: float, sell: float) -> float | None:
    total = buy + sell
    if total <= 0:
        return None
    return sell / total * 100.0


def _window(tape: SymbolTape | None, now_ms: int, minutes: int, shift_min: int = 0) -> tuple[float, float]:
    if tape is None or minutes <= 0:
        return 0.0, 0.0
    current = minute_start(now_ms) - shift_min * MINUTE_MS
    start = current - (minutes - 1) * MINUTE_MS
    buy = sell = 0.0
    for key, row in tape.minutes.items():
        if start <= key <= current:
            buy += float(row[0])
            sell += float(row[1])
    return buy, sell


def _fmt_share(pct: float | None) -> str:
    return "нет ленты" if pct is None else f"{pct:.0f}%"


@dataclass
class PlusEvaluation:
    checks: dict[str, dict] = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    score: float = 0.0
    strict_btc: bool = False

    @property
    def failed(self) -> list[str]:
        return [key for key in PLUS_MANDATORY if not self.checks.get(key, {}).get("ok")]

    @property
    def passed_count(self) -> int:
        return len(PLUS_MANDATORY) - len(self.failed)

    @property
    def passed(self) -> bool:
        return not self.failed

    def to_data(self) -> dict:
        return {
            "checks": self.checks,
            "metrics": self.metrics,
            "score": round(self.score, 1),
            "strict_btc": self.strict_btc,
            "passed": self.passed,
            "passed_count": self.passed_count,
            "failed": self.failed,
            "variants": list(config.PAPER_PLUS_VARIANTS) if self.passed else [],
        }


def evaluate_plus(
    state: SymbolState,
    tape: SymbolTape | None,
    klines: dict[str, list[Bar]],
    now_ms: int,
    base: Evaluation,
) -> PlusEvaluation:
    metrics = dict(base.metrics)
    checks: dict[str, dict] = {}

    bars = closed_5m(merged_5m(state, klines), now_ms)
    need = config.PAPER_PLUS_NO_HIGH_BARS
    if len(bars) < need + 1:
        checks["no_new_high"] = {"ok": False, "value": f"мало свечей {len(bars)}"}
    else:
        window = bars[-need:]
        prior_high = max(bar.high for bar in bars[:-need])
        window_high = max(bar.high for bar in window)
        checks["no_new_high"] = {
            "ok": window_high <= prior_high,
            "value": f"хай окна {window_high:.6g} / раньше {prior_high:.6g}",
        }
        metrics["plus_window_high"] = window_high
        metrics["plus_prior_high"] = prior_high

    share_floor = config.PAPER_PLUS_SELL_SHARE_MIN_PCT
    shares: dict[int, float | None] = {}
    sells_ok = True
    for minutes in (5, 10, 15):
        buy, sell = _window(tape, now_ms, minutes, 0)
        pct = _sell_share(buy, sell)
        shares[minutes] = pct
        if pct is None or pct <= share_floor:
            sells_ok = False
    checks["sells_55"] = {
        "ok": sells_ok,
        "value": " / ".join(f"{m}м {_fmt_share(shares[m])}" for m in (5, 10, 15)),
    }

    buy5, sell5 = _window(tape, now_ms, 5, 0)
    _, prev5 = _window(tape, now_ms, 5, 5)
    buy15, sell15 = _window(tape, now_ms, 15, 0)
    _, prev15 = _window(tape, now_ms, 15, 15)
    share5 = _sell_share(buy5, sell5)
    share15 = _sell_share(buy15, sell15)
    growing = (
        sell5 > prev5
        and sell15 > prev15
        and share5 is not None
        and share5 > share_floor
        and share15 is not None
        and share15 > share_floor
    )
    checks["sell_volume_up"] = {
        "ok": growing,
        "value": f"5м {sell5:.0f}>{prev5:.0f}, 15м {sell15:.0f}>{prev15:.0f}",
    }
    metrics["plus_sell_5"] = round(sell5, 2)
    metrics["plus_sell_prev_5"] = round(prev5, 2)
    metrics["plus_sell_15"] = round(sell15, 2)
    metrics["plus_sell_prev_15"] = round(prev15, 2)

    ratio = metrics.get("volume_ratio_20m")
    checks["volume_falling"] = {
        "ok": ratio is not None and float(ratio) <= config.PAPER_VOLUME_FADE_MAX_RATIO,
        "value": "нет объёма" if ratio is None else f"{float(ratio):.0%} от пика",
    }

    oi = metrics.get("oi_1h_pct")
    checks["oi_not_rising"] = {
        "ok": oi is not None and float(oi) <= 0,
        "value": "нет OI" if oi is None else f"{float(oi):+.2f}%",
    }

    since = metrics.get("since_peak_min")
    dd = metrics.get("drawdown_from_peak_pct")
    late_min = config.PAPER_PLUS_LATE_SINCE_MIN
    late_dd = config.PAPER_PLUS_LATE_MAX_DD_PCT
    if since is None or dd is None:
        late_ok = False
        late_value = "нет данных пика"
    else:
        late_ok = not (float(since) > late_min and float(dd) > late_dd)
        late_value = f"{float(since):.0f} мин, откат {float(dd):.1f}%"
    checks["not_late_deep"] = {"ok": late_ok, "value": late_value}

    blocked = list(base.entry_blocked)
    checks["entry_gate"] = {
        "ok": not blocked,
        "value": "открыт" if not blocked else "; ".join(ENTRY_GATE_LABELS.get(key, key) for key in blocked),
    }

    return PlusEvaluation(
        checks=checks,
        metrics=metrics,
        score=base.score,
        strict_btc=base.strict_btc,
    )
