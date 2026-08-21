"""Расчёт цены для выкладки на Avito.

Приоритет: ручная цена (админка) → иначе входящая × multiplier.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceRecommendation:
    recommended_price: int
    price_rule: str
    floor_price: float
    discount_pct: int | None = None


def recommend_price(
    incoming: float,
    *,
    no_avito_multiplier: float = 1.15,
    floor_multiplier: float = 1.10,
) -> PriceRecommendation:
    """Расчётная цена: входящая × multiplier (по умолчанию 1.15)."""
    floor_price = incoming * floor_multiplier
    return PriceRecommendation(
        recommended_price=_round_price(incoming * no_avito_multiplier),
        price_rule=f"markup_x{no_avito_multiplier:g}",
        floor_price=floor_price,
        discount_pct=None,
    )


def round_price_to_tens(value: float) -> int:
    """Округление цены выкладки до десятков рублей."""
    return int(round(value / 10) * 10)


def _round_price(value: float) -> int:
    return round_price_to_tens(value)


def fixed_price_recommendation(
    fixed_price: float,
    incoming: float,
    *,
    price_rule: str = "manual",
    floor_multiplier: float = 1.10,
) -> PriceRecommendation:
    """Ручная цена — в объявление как есть (только округление до десятков)."""
    return PriceRecommendation(
        recommended_price=round_price_to_tens(fixed_price),
        price_rule=price_rule,
        floor_price=incoming * floor_multiplier,
        discount_pct=None,
    )
