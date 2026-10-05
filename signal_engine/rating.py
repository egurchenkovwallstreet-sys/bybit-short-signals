"""Рейтинг, вероятность и раскладка по колонкам.

Рейтинг = (Сила × 20) + (Вероятность × 0.5) + (Качество × 10)
          + (Совпадение ТФ × 5) + (Доп × 3)

Вероятность — в процентах. Пока истории мало, её собирают экспертные веса.
Сила — это 1–5 подтверждений, она же номер колонки.
"""

from __future__ import annotations

import config


def signal_rating(
    strength: int,
    probability: float,
    quality: float,
    tf_match: int,
    extra: int,
) -> float:
    return (
        strength * config.RATING_WEIGHT_STRENGTH
        + probability * config.RATING_WEIGHT_PROBABILITY
        + quality * config.RATING_WEIGHT_QUALITY
        + tf_match * config.RATING_WEIGHT_TF
        + extra * config.RATING_WEIGHT_EXTRA
    )


def column_for(strength: int) -> dict[str, str | int]:
    level = min(5, max(1, strength))
    meta = config.SIGNAL_COLUMNS[level]
    return {
        "strength": level,
        "color": meta["color"],
        "status": meta["status"],
        "label": meta["label"],
    }


def expert_probability(
    *,
    sweep: bool,
    liquidations_faded: bool,
    oi_drop: bool,
    cvd_divergence: bool,
    round_level: bool,
    funding_extreme: bool,
) -> float:
    """Стартовая вероятность: 50% плюс веса признаков, пока мало закрытых сделок."""
    score = config.PROBABILITY_BASE
    weights = config.EXPERT_WEIGHTS
    if sweep:
        score += weights["sweep"] * 100
    if liquidations_faded:
        score += weights["liquidations_faded"] * 100
    if oi_drop:
        score += weights["oi_drop"] * 100
    if cvd_divergence:
        score += weights["cvd_divergence"] * 100
    if round_level:
        score += weights["round_level"] * 100
    if funding_extreme:
        score += weights["funding_extreme"] * 100
    return min(score, config.PROBABILITY_CAP)


def probability_pct(
    *,
    sweep: bool,
    liquidations_faded: bool,
    oi_drop: bool,
    cvd_divergence: bool,
    round_level: bool,
    funding_extreme: bool,
    history_wins: int,
    history_total: int,
) -> float:
    """После 20 закрытых сигналов вероятность — фактический Win Rate, иначе экспертная."""
    if history_total >= config.PROBABILITY_MIN_SAMPLE and history_total > 0:
        return history_wins / history_total * 100.0
    return expert_probability(
        sweep=sweep,
        liquidations_faded=liquidations_faded,
        oi_drop=oi_drop,
        cvd_divergence=cvd_divergence,
        round_level=round_level,
        funding_extreme=funding_extreme,
    )


def sort_by_rating(signals: list) -> list:
    return sorted(signals, key=lambda item: item.rating, reverse=True)
