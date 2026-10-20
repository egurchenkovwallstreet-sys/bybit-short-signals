"""EMA60 stretch: вход к EMA60 на 5m при отрыве ≥ порога (4–10%)."""

from __future__ import annotations

from dataclasses import dataclass

import config
from signal_engine.paper.detect import _check, grade_for
from signal_engine.paper.ma333_regime import ma333_regime_detail
from signal_engine.state import SymbolState

EMA60_STRETCH_MANDATORY = ("ema_ready", "stretch_min", "side_set")

EMA60_STRETCH_CHECK_LABELS = {
    "ema_ready": "EMA60 на 5m посчитана",
    "stretch_min": "Отрыв от EMA60 ≥ порога",
    "side_set": "Сторона: к EMA (ниже → лонг, выше → шорт)",
}

THRESHOLD_BY_VARIANT = {
    config.PAPER_EM4_VARIANT: config.PAPER_EM4_STRETCH_MIN_PCT,
    config.PAPER_EM5_VARIANT: config.PAPER_EM5_STRETCH_MIN_PCT,
    config.PAPER_EM6_VARIANT: config.PAPER_EM6_STRETCH_MIN_PCT,
    config.PAPER_EM7_VARIANT: config.PAPER_EM7_STRETCH_MIN_PCT,
    config.PAPER_EM8_VARIANT: config.PAPER_EM8_STRETCH_MIN_PCT,
    config.PAPER_EM9_VARIANT: config.PAPER_EM9_STRETCH_MIN_PCT,
    config.PAPER_EM10_VARIANT: config.PAPER_EM10_STRETCH_MIN_PCT,
}


@dataclass
class Ema60StretchEvaluation:
    checks: dict[str, dict]
    metrics: dict
    score: float
    side: str | None
    min_stretch_pct: float

    @property
    def passed(self) -> bool:
        return self.side in ("long", "short") and all(
            self.checks.get(k, {}).get("ok") for k in EMA60_STRETCH_MANDATORY
        )

    @property
    def failed(self) -> list[str]:
        return [k for k in EMA60_STRETCH_MANDATORY if not self.checks.get(k, {}).get("ok")]

    @property
    def passed_count(self) -> int:
        return len(EMA60_STRETCH_MANDATORY) - len(self.failed)

    def variants(self) -> list[str]:
        if not self.passed:
            return []
        out = []
        stretch = float(self.metrics.get("stretch_pct") or 0)
        for variant, thr in THRESHOLD_BY_VARIANT.items():
            if variant in config.PAPER_VARIANTS and stretch + 1e-9 >= float(thr):
                out.append(variant)
        return out

    def to_data(self) -> dict:
        return {
            "checks": self.checks,
            "metrics": self.metrics,
            "score": round(self.score, 1),
            "grade": grade_for(self.score),
            "strict_btc": False,
            "passed": self.passed,
            "passed_count": self.passed_count,
            "failed": self.failed,
            "variants": self.variants(),
            "entry_blocked": [],
            "side": self.side,
        }


def evaluate_ema60_stretch(state: SymbolState, now_ms: int) -> Ema60StretchEvaluation:
    detail = ma333_regime_detail(state, now_ms, "short", "5")
    ema = detail.get("ema60")
    price = float(state.last_price or detail.get("price") or 0)
    ema_ok = not detail.get("insufficient_data") and ema is not None and price > 0

    stretch_pct = 0.0
    side: str | None = None
    if ema_ok and float(ema) > 0:
        stretch_pct = abs(price - float(ema)) / float(ema) * 100.0
        if price < float(ema):
            side = "long"
        elif price > float(ema):
            side = "short"

    min_thr = min(THRESHOLD_BY_VARIANT.values())
    checks = {
        "ema_ready": _check(ema_ok, None if not ema_ok else round(float(ema), 6), "EMA60 5m"),
        "stretch_min": _check(
            ema_ok and stretch_pct + 1e-9 >= min_thr,
            None if not ema_ok else f"{stretch_pct:.2f}% (мин. {min_thr:g}%)",
            f"≥ {min_thr:g}%",
        ),
        "side_set": _check(side in ("long", "short"), side or "—", "лонг/шорт к EMA"),
    }
    metrics = {
        "interval": "5",
        "ema60": float(ema) if ema is not None else None,
        "stretch_pct": round(stretch_pct, 3),
        "price": price,
        "regime": detail.get("regime"),
        "pump": {
            "kind": "ema60_stretch",
            "side": side,
            "trigger": "5m",
            "stretch_pct": round(stretch_pct, 3),
        },
    }
    score = 70.0 + min(stretch_pct, 20.0) if checks["stretch_min"]["ok"] else 20.0
    return Ema60StretchEvaluation(
        checks=checks,
        metrics=metrics,
        score=score,
        side=side,
        min_stretch_pct=min_thr,
    )


def stretch_passes_variant(ev: Ema60StretchEvaluation, variant: str) -> bool:
    if not ev.passed or variant not in THRESHOLD_BY_VARIANT:
        return False
    stretch = float(ev.metrics.get("stretch_pct") or 0)
    return stretch + 1e-9 >= float(THRESHOLD_BY_VARIANT[variant])
