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

# Шины: parent_id=1, type 2/3 (как раньше).
_REGISTER_TIRES_SELECT = """
select p.name as product, r.product_id, s.name as supplier, r.price, r.quantity,
       'tire'::text as kind,
       null::text as brand,
       null::text as model,
       null::text as wheel_type,
       null::text as width,
       null::text as diameter,
       null::text as studs,
       null::text as circle,
       null::text as et,
       null::text as hub
from logistics.register r
join products p on r.product_id = p.id
join products m on p.parent_id = m.id
join products b on m.parent_id = b.id
join logistics.suppliers s on r.supplier_id = s.id
where b.parent_id = 1 and m.params->>'type' in ('2', '3')
"""

# Диски: parent_id=2; type 1=сталь, 2=литьё, 3=ковка (опционально), 4=груз — не берём.
_REGISTER_WHEELS_SELECT = """
select p.name as product, r.product_id, s.name as supplier, r.price, r.quantity,
       'wheel'::text as kind,
       b.name as brand,
       m.name as model,
       COALESCE(m.params->>'type', b.params->>'type') as wheel_type,
       p.params->>'width' as width,
       p.params->>'diameter' as diameter,
       p.params->>'studs' as studs,
       p.params->>'circle' as circle,
       p.params->>'et' as et,
       p.params->>'hub' as hub
from logistics.register r
join products p on r.product_id = p.id
join products m on p.parent_id = m.id
join products b on m.parent_id = b.id
join logistics.suppliers s on r.supplier_id = s.id
where b.parent_id = 2
  and COALESCE(m.params->>'type', b.params->>'type') in ({wheel_types})
"""

# Обратная совместимость: только шины (если wheels.enabled=false).
REGISTER_QUERY = _REGISTER_TIRES_SELECT.strip()


def build_register_query(
    *,
    wheels_enabled: bool = False,
    wheel_types: tuple[str, ...] = ("1", "2", "3"),
) -> str:
    """SQL реестра: шины и опционально диски (сталь/литьё/ковка)."""
    tires = _REGISTER_TIRES_SELECT.strip()
    if not wheels_enabled:
        return tires
    return f"{tires}\nunion all\n{register_wheels_query(wheel_types=wheel_types)}"


def register_wheels_query(*, wheel_types: tuple[str, ...] = ("1", "2", "3")) -> str:
    types = tuple(str(t).strip() for t in wheel_types if str(t).strip())
    if not types:
        types = ("1", "2")
    types_sql = ", ".join(f"'{t}'" for t in types)
    return _REGISTER_WHEELS_SELECT.format(wheel_types=types_sql).strip()


def register_tires_query() -> str:
    return _REGISTER_TIRES_SELECT.strip()


@dataclass(frozen=True)
class RegisterLine:
    article: str
    name: str
    supplier: str
    price: float
    quantity: float
    kind: str = "tire"
    brand: str = ""
    model: str = ""
    wheel_type: str = ""
    width: str = ""
    diameter: str = ""
    studs: str = ""
    circle: str = ""
    et: str = ""
    hub: str = ""


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
    kind: str = "tire"
    brand: str = ""
    model: str = ""
    wheel_type: str = ""
    width: str = ""
    diameter: str = ""
    studs: str = ""
    circle: str = ""
    et: str = ""
    hub: str = ""


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
    by_article: dict[str, list[RegisterLine]] = {}
    for line in lines:
        art = str(line.article).strip()
        if art:
            by_article.setdefault(art, []).append(line)
    out: set[str] = set()
    for art, art_lines in by_article.items():
        if article_has_sam_mb_cash_stock(art, art_lines, cfg):
            out.add(art)
    return frozenset(out)


def _qty_str(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)


SELLER_STAR_PRIORITIES = frozenset({"p2", "p3", "p4"})


def is_seller_star_source(source: str) -> bool:
    """П1 (Google) и П2–П4: визуальная метка * для продавцов на сайте загрузки фото."""
    s = str(source or "").strip().lower()
    if s in ("google", "p1"):
        return True
    if not s.startswith("db:"):
        return False
    return s[3:] in SELLER_STAR_PRIORITIES


def _meta_from_lines(lines: list[RegisterLine]) -> dict[str, str]:
    """kind/brand/params — с любой строки артикула (одинаковый product)."""
    for line in lines:
        kind = str(line.kind or "tire").strip() or "tire"
        if kind == "wheel" or line.brand or line.width or line.diameter:
            return {
                "kind": kind if kind in ("tire", "wheel") else "wheel",
                "brand": str(line.brand or "").strip(),
                "model": str(line.model or "").strip(),
                "wheel_type": str(line.wheel_type or "").strip(),
                "width": str(line.width or "").strip(),
                "diameter": str(line.diameter or "").strip(),
                "studs": str(line.studs or "").strip(),
                "circle": str(line.circle or "").strip(),
                "et": str(line.et or "").strip(),
                "hub": str(line.hub or "").strip(),
            }
    kind0 = str(lines[0].kind or "tire").strip() or "tire" if lines else "tire"
    return {
        "kind": kind0 if kind0 in ("tire", "wheel") else "tire",
        "brand": "",
        "model": "",
        "wheel_type": "",
        "width": "",
        "diameter": "",
        "studs": "",
        "circle": "",
        "et": "",
        "hub": "",
    }


def _priority_result(
    *,
    article: str,
    name: str,
    base_price: float,
    quantity: str,
    priority: str,
    supplier: str,
    ushk_in_stock: bool,
    sam_mb_cash_price: bool,
    meta: dict[str, str],
) -> PriorityResult:
    return PriorityResult(
        article=article,
        name=name,
        base_price=base_price,
        quantity=quantity,
        priority=priority,
        supplier=supplier,
        ushk_in_stock=ushk_in_stock,
        sam_mb_cash_price=sam_mb_cash_price,
        kind=meta.get("kind", "tire"),
        brand=meta.get("brand", ""),
        model=meta.get("model", ""),
        wheel_type=meta.get("wheel_type", ""),
        width=meta.get("width", ""),
        diameter=meta.get("diameter", ""),
        studs=meta.get("studs", ""),
        circle=meta.get("circle", ""),
        et=meta.get("et", ""),
        hub=meta.get("hub", ""),
    )


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

    meta = _meta_from_lines(lines)
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
        return _priority_result(
            article=article,
            name=name,
            base_price=round(row.price * cfg.ufa_multiplier, 2),
            quantity=_qty_str(row.quantity),
            priority="p2",
            supplier=row.supplier,
            ushk_in_stock=ushk_in_stock,
            sam_mb_cash_price=sam_mb_cash_price,
            meta=meta,
        )

    if has_ufa:
        row = ufa_ok[0]
        return _priority_result(
            article=article,
            name=name,
            base_price=round(row.price * cfg.ufa_multiplier, 2),
            quantity=_qty_str(row.quantity),
            priority="p3",
            supplier=row.supplier,
            ushk_in_stock=ushk_in_stock,
            sam_mb_cash_price=sam_mb_cash_price,
            meta=meta,
        )

    if has_moscow and has_ushk:
        row = moscow_ok[0]
        return _priority_result(
            article=article,
            name=name,
            base_price=round(row.price * cfg.moscow_multiplier, 2),
            quantity=_qty_str(row.quantity),
            priority="p4",
            supplier=row.supplier,
            ushk_in_stock=ushk_in_stock,
            sam_mb_cash_price=sam_mb_cash_price,
            meta=meta,
        )

    if has_ushk:
        row = ushk_ok[0]
        return _priority_result(
            article=article,
            name=name,
            base_price=round(row.price, 2),
            quantity=_qty_str(row.quantity),
            priority="p5",
            supplier=row.supplier,
            ushk_in_stock=ushk_in_stock,
            sam_mb_cash_price=sam_mb_cash_price,
            meta=meta,
        )

    if not eligible:
        return None

    row = min(eligible, key=lambda line: line.price)
    return _priority_result(
        article=article,
        name=name,
        base_price=round(row.price, 2),
        quantity=_qty_str(row.quantity),
        priority="p6",
        supplier=row.supplier,
        ushk_in_stock=ushk_in_stock,
        sam_mb_cash_price=sam_mb_cash_price,
        meta=meta,
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
