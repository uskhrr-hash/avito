"""Расчёт рекомендуемой цены для выкладки на Avito."""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class PriceRecommendation:
    recommended_price: int
    price_rule: str
    avito_min: float | None
    floor_price: float
    discount_pct: int | None


def recommend_price(
    incoming: float,
    avito_min: float | None,
    *,
    seed: str,
    date_key: str,
    no_avito_multiplier: float = 1.15,
    floor_multiplier: float = 1.10,
    discounts: tuple[float, ...] = (0.01, 0.02, 0.03),
) -> PriceRecommendation:
    """
    Нет на Avito → входящая × 1.15.
    Есть → avito_min − (1|2|3)%, но не ниже входящая × 1.10.
    """
    floor_price = incoming * floor_multiplier
    if avito_min is None:
        return PriceRecommendation(
            recommended_price=_round_price(incoming * no_avito_multiplier),
            price_rule="no_avito_x1.15",
            avito_min=None,
            floor_price=floor_price,
            discount_pct=None,
        )

    rng = random.Random(f"{date_key}:{seed}")
    discount = rng.choice(discounts)
    discount_pct = int(round(discount * 100))
    candidate = avito_min * (1.0 - discount)

    if candidate < floor_price:
        return PriceRecommendation(
            recommended_price=_round_price(floor_price),
            price_rule=f"avito_minus_{discount_pct}pct_floor_x1.1",
            avito_min=avito_min,
            floor_price=floor_price,
            discount_pct=discount_pct,
        )

    return PriceRecommendation(
        recommended_price=_round_price(candidate),
        price_rule=f"avito_minus_{discount_pct}pct",
        avito_min=avito_min,
        floor_price=floor_price,
        discount_pct=discount_pct,
    )


def _round_price(value: float) -> int:
    return int(round(value))
