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
        "Шинсервис",
        "Римэкс",
    }
)

DEFAULT_ALLOWED_SUPPLIERS = frozenset(
    {
        "Сам МБ Уфа",
        "Сам МБ Москва",
        "Бринэкс",
        "Пауэр Уфа",
        "Шининвест",
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
    allowed_suppliers: frozenset[str] = DEFAULT_ALLOWED_SUPPLIERS


@dataclass(frozen=True)
class PriorityResult:
    article: str
    name: str
    base_price: float
    quantity: str
    priority: str
    supplier: str
    ushk_in_stock: bool = False
    sam_mb_cash_price: bool = False


def is_ushk_supplier(supplier: str, *, prefix: str = "УШК") -> bool:
    return str(supplier or "").strip().startswith(prefix)


def is_excluded_supplier(supplier: str, excluded: Iterable[str]) -> bool:
    return str(supplier or "").strip() in set(excluded)


def is_other_power_supplier(supplier: str, *, allowed: str = "Пауэр Уфа") -> bool:
    """Пауэр Москва, Пауэр Екб и т.д. — не обрабатываем, только Пауэр Уфа."""
    name = str(supplier or "").strip()
    if not name.startswith("Пауэр"):
        return False
    return name != allowed


def is_allowed_supplier(supplier: str, cfg: StockPriorityConfig) -> bool:
    name = str(supplier or "").strip()
    if not name:
        return False
    if is_excluded_supplier(name, cfg.excluded_suppliers):
        return False
    if is_other_power_supplier(name):
        return False
    if is_ushk_supplier(name, prefix=cfg.ushk_prefix):
        return True
    return name in cfg.allowed_suppliers


def articles_with_ushk_stock(
    lines: list[RegisterLine],
    cfg: StockPriorityConfig,
) -> frozenset[str]:
    out: set[str] = set()
    for line in lines:
        if not is_allowed_supplier(line.supplier, cfg):
            continue
        if (
            is_ushk_supplier(line.supplier, prefix=cfg.ushk_prefix)
            and line.quantity >= cfg.min_quantity
        ):
            art = str(line.article).strip()
            if art:
                out.add(art)
    return frozenset(out)


def article_has_sam_mb_cash_stock(
    article: str,
    lines: list[RegisterLine],
    cfg: StockPriorityConfig,
) -> bool:
    """Сам МБ Уфа ≥ min_quantity (4) или Сам МБ Москва ≥ moscow_min_quantity (40)."""
    art = str(article).strip()
    if not art:
        return False
    ufa_min = max(1, int(cfg.min_quantity))
    moscow_min = max(1, int(cfg.moscow_min_quantity))
    for line in lines:
        if str(line.article).strip() != art:
            continue
        if line.supplier == cfg.supplier_ufa and line.quantity >= ufa_min:
            return True
        if line.supplier == cfg.supplier_moscow and line.quantity >= moscow_min:
            return True
    return False


def articles_with_sam_mb_cash_stock(
    lines: list[RegisterLine],
    cfg: StockPriorityConfig,
) -> frozenset[str]:
    out: set[str] = set()
    for line in lines:
        if article_has_sam_mb_cash_stock(line.article, lines, cfg):
            art = str(line.article).strip()
            if art:
                out.add(art)
    return frozenset(out)


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
        if is_allowed_supplier(line.supplier, cfg)
    ]
    if not active:
        return None

    ushk_ok = [
        line
        for line in active
        if is_ushk_supplier(line.supplier, prefix=cfg.ushk_prefix)
        and line.quantity >= cfg.min_quantity
    ]
    ushk_in_stock = bool(ushk_ok)
    sam_mb_cash_price = article_has_sam_mb_cash_stock(article, lines, cfg)
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
            ushk_in_stock=ushk_in_stock,
            sam_mb_cash_price=sam_mb_cash_price,
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
            ushk_in_stock=ushk_in_stock,
            sam_mb_cash_price=sam_mb_cash_price,
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
            ushk_in_stock=ushk_in_stock,
            sam_mb_cash_price=sam_mb_cash_price,
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
            ushk_in_stock=ushk_in_stock,
            sam_mb_cash_price=sam_mb_cash_price,
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
        ushk_in_stock=ushk_in_stock,
        sam_mb_cash_price=sam_mb_cash_price,
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
