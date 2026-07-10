"""Каскад базовой цены по реестру ERP (П2–П6). П1 — Google в merge_rows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

DEFAULT_EXCLUDED_SUPPLIERS = frozenset(
    {
        "Сам МБ прочие",
        "Вектра Екб",
        "Вектра Уфа",
        "Колобокс Нижний",
        "Колобокс Уфа",
    }
)

REGISTER_QUERY = """
select p.name as product, r.product_id, s.name as supplier, r.price, r.quantity
from logistics.register r
join products p on r.product_id = p.id
join products m on p.parent_id = m.id
join products b on m.parent_id = b.id
join logistics.suppliers s on r.supplier_id = s.id
where b.parent_id = 1 and m.params->>'type' in ('2', '3')
"""


@dataclass(frozen=True)
class RegisterLine:
    article: str
    name: str
    supplier: str
    price: float
    quantity: float


@dataclass(frozen=True)
class StockPriorityConfig:
    min_quantity: int = 4
    moscow_min_quantity: int = 40
    supplier_ufa: str = "Сам МБ Уфа"
    supplier_moscow: str = "Сам МБ Москва"
    ushk_prefix: str = "УШК"
    ufa_multiplier: float = 0.9
    moscow_multiplier: float = 0.9
    excluded_suppliers: frozenset[str] = DEFAULT_EXCLUDED_SUPPLIERS


@dataclass(frozen=True)
class PriorityResult:
    article: str
    name: str
    base_price: float
    quantity: str
    priority: str
    supplier: str


def is_ushk_supplier(supplier: str, *, prefix: str = "УШК") -> bool:
    return str(supplier or "").strip().startswith(prefix)


def is_excluded_supplier(supplier: str, excluded: Iterable[str]) -> bool:
    return str(supplier or "").strip() in set(excluded)


def _qty_str(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def resolve_register_article(
    article: str,
    name: str,
    lines: list[RegisterLine],
    cfg: StockPriorityConfig,
) -> PriorityResult | None:
    """Возвращает базовую цену по каскаду П2–П6 для одного артикула."""
    active = [
        line
        for line in lines
        if not is_excluded_supplier(line.supplier, cfg.excluded_suppliers)
    ]
    if not active:
        return None

    ushk_ok = [
        line
        for line in active
        if is_ushk_supplier(line.supplier, prefix=cfg.ushk_prefix)
        and line.quantity >= cfg.min_quantity
    ]
    ufa_ok = [
        line
        for line in active
        if line.supplier == cfg.supplier_ufa and line.quantity >= cfg.min_quantity
    ]
    moscow_ok = [
        line
        for line in active
        if line.supplier == cfg.supplier_moscow
        and line.quantity > cfg.moscow_min_quantity
    ]
    eligible = [line for line in active if line.quantity >= cfg.min_quantity]

    has_ushk = bool(ushk_ok)
    has_ufa = bool(ufa_ok)
    has_moscow = bool(moscow_ok)

    if has_ushk and has_ufa:
        row = ufa_ok[0]
        return PriorityResult(
            article=article,
            name=name,
            base_price=round(row.price * cfg.ufa_multiplier, 2),
            quantity=_qty_str(row.quantity),
            priority="p2",
            supplier=row.supplier,
        )

    if has_ufa:
        row = ufa_ok[0]
        return PriorityResult(
            article=article,
            name=name,
            base_price=round(row.price * cfg.ufa_multiplier, 2),
            quantity=_qty_str(row.quantity),
            priority="p3",
            supplier=row.supplier,
        )

    if has_moscow and has_ushk:
        row = moscow_ok[0]
        return PriorityResult(
            article=article,
            name=name,
            base_price=round(row.price * cfg.moscow_multiplier, 2),
            quantity=_qty_str(row.quantity),
            priority="p4",
            supplier=row.supplier,
        )

    if has_ushk:
        row = ushk_ok[0]
        return PriorityResult(
            article=article,
            name=name,
            base_price=round(row.price, 2),
            quantity=_qty_str(row.quantity),
            priority="p5",
            supplier=row.supplier,
        )

    if not eligible:
        return None

    row = min(eligible, key=lambda line: line.price)
    return PriorityResult(
        article=article,
        name=name,
        base_price=round(row.price, 2),
        quantity=_qty_str(row.quantity),
        priority="p6",
        supplier=row.supplier,
    )


def resolve_register_stock(
    lines: list[RegisterLine],
    cfg: StockPriorityConfig,
) -> list[PriorityResult]:
    by_article: dict[str, list[RegisterLine]] = {}
    names: dict[str, str] = {}
    for line in lines:
        art = str(line.article).strip()
        if not art:
            continue
        by_article.setdefault(art, []).append(line)
        if line.name.strip():
            names[art] = line.name.strip()

    out: list[PriorityResult] = []
    for article in sorted(by_article):
        resolved = resolve_register_article(
            article,
            names.get(article, ""),
            by_article[article],
            cfg,
        )
        if resolved is not None:
            out.append(resolved)
    return out
