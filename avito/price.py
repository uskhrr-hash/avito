"""Нормализация цены до стоимости за 1 шину."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

PriceConfidence = Literal["exact", "inferred", "needs_review"]


@dataclass(frozen=True)
class PriceResult:
    price_raw: str
    price_rub: int | None
    price_unit_count: int | None
    price_per_tire: float | None
    price_confidence: PriceConfidence
    price_note: str = ""


_RE_PRICE = re.compile(
    r"(?P<amount>\d[\d\s]*)\s*₽",
    re.UNICODE,
)
_RE_PER_UNIT = re.compile(
    r"за\s*(?P<count>\d+)\s*шт",
    re.IGNORECASE | re.UNICODE,
)
_RE_KIT_HINT = re.compile(
    r"комплект|комплектом|кратно\s*по\s*\d|прода[её]тся\s+комплект",
    re.IGNORECASE | re.UNICODE,
)


def _parse_amount(text: str) -> int | None:
    m = _RE_PRICE.search(text.replace("\u00a0", " "))
    if not m:
        return None
    digits = re.sub(r"\s+", "", m.group("amount"))
    try:
        return int(digits)
    except ValueError:
        return None


def parse_price(price_text: str, extra_text: str = "") -> PriceResult:
    """
    price_text — блок цены с карточки (например «5 400 ₽ за 1 шт.»).
    extra_text — заголовок/описание для эвристик при неполной цене.
    """
    combined = f"{price_text} {extra_text}".strip()
    raw = price_text.strip() or combined.strip()
    amount = _parse_amount(combined)
    if amount is None:
        return PriceResult(
            price_raw=raw,
            price_rub=None,
            price_unit_count=None,
            price_per_tire=None,
            price_confidence="needs_review",
            price_note="не удалось извлечь сумму в рублях",
        )

    unit_m = _RE_PER_UNIT.search(combined)
    if unit_m:
        count = int(unit_m.group("count"))
        if count <= 0:
            count = 1
        per = round(amount / count, 2)
        conf: PriceConfidence = "exact" if count == 1 else "exact"
        return PriceResult(
            price_raw=raw,
            price_rub=amount,
            price_unit_count=count,
            price_per_tire=per,
            price_confidence=conf,
            price_note="" if count > 1 else "",
        )

    if _RE_KIT_HINT.search(extra_text) and not unit_m:
        return PriceResult(
            price_raw=raw,
            price_rub=amount,
            price_unit_count=None,
            price_per_tire=None,
            price_confidence="needs_review",
            price_note="упоминание комплекта без «за N шт.»",
        )

    # Цена без «за N шт.» — считаем за 1, но помечаем для проверки
    return PriceResult(
        price_raw=raw,
        price_rub=amount,
        price_unit_count=1,
        price_per_tire=float(amount),
        price_confidence="inferred",
        price_note="нет «за N шт.», принято за 1 шт.",
    )
