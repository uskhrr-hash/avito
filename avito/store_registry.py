"""Остатки по реестру ERP для конкретного склада УШК."""
from __future__ import annotations

import logging
import time
from typing import Any

LOG = logging.getLogger(__name__)

MIN_REGISTER_QUANTITY = 4

REGISTER_ARTICLES_AT_SUPPLIER_SQL = """
select distinct r.product_id::text as article
from logistics.register r
join products p on r.product_id = p.id
join products m on p.parent_id = m.id
join products b on m.parent_id = b.id
join logistics.suppliers s on r.supplier_id = s.id
where b.parent_id = 1
  and m.params->>'type' in ('2', '3')
  and s.name = %s
  and r.quantity >= %s
"""

_CACHE: dict[tuple[str, int], tuple[float, frozenset[str]]] = {}
_CACHE_TTL_SEC = 300.0


def _connect_db(secrets: dict[str, Any]):
    d_cfg = secrets.get("db") or {}
    required = ("host", "port", "database", "user", "password")
    missing = [k for k in required if not str(d_cfg.get(k, "")).strip()]
    if missing:
        raise ValueError(f"В secrets.local.yaml не заполнены db-поля: {', '.join(missing)}")
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("Установите зависимость: pip install psycopg2-binary") from exc

    return psycopg2.connect(
        host=str(d_cfg["host"]),
        port=int(d_cfg["port"]),
        dbname=str(d_cfg["database"]),
        user=str(d_cfg["user"]),
        password=str(d_cfg["password"]),
    )


def fetch_articles_at_supplier(
    secrets: dict[str, Any],
    supplier_name: str,
    *,
    min_quantity: int = MIN_REGISTER_QUANTITY,
    use_cache: bool = True,
) -> frozenset[str]:
    """Артикулы (product_id), которые есть у поставщика в реестре с qty >= min_quantity."""
    name = str(supplier_name or "").strip()
    if not name:
        return frozenset()

    cache_key = (name, min_quantity)
    if use_cache:
        cached = _CACHE.get(cache_key)
        if cached and time.time() < cached[0]:
            return cached[1]

    conn = _connect_db(secrets)
    try:
        with conn.cursor() as cur:
            cur.execute(
                REGISTER_ARTICLES_AT_SUPPLIER_SQL,
                (name, min_quantity),
            )
            articles = frozenset(
                str(row[0]).strip()
                for row in cur.fetchall()
                if row and str(row[0]).strip()
            )
    finally:
        conn.close()

    if use_cache:
        _CACHE[cache_key] = (time.time() + _CACHE_TTL_SEC, articles)
    LOG.debug("Реестр %s: %s артикулов (qty >= %s)", name, len(articles), min_quantity)
    return articles


def clear_register_cache() -> None:
    _CACHE.clear()


LIST_SUPPLIERS_BY_PREFIX_SQL = """
select distinct s.name
from logistics.suppliers s
where s.name like %s
order by s.name
"""


def list_suppliers_by_prefix(
    secrets: dict[str, Any],
    *,
    name_prefix: str = "УШК",
) -> list[str]:
    """Имена складов/поставщиков из ERP с префиксом (для выбора магазина сотрудника)."""
    prefix = str(name_prefix or "").strip()
    if not prefix:
        return []
    conn = _connect_db(secrets)
    try:
        with conn.cursor() as cur:
            cur.execute(LIST_SUPPLIERS_BY_PREFIX_SQL, (f"{prefix}%",))
            return [
                str(row[0]).strip()
                for row in cur.fetchall()
                if row and str(row[0]).strip()
            ]
    finally:
        conn.close()
