"""Остатки по реестру ERP для конкретного склада УШК."""
from __future__ import annotations

import logging
import time
from typing import Any

LOG = logging.getLogger(__name__)

MIN_REGISTER_QUANTITY = 4

# Шины: parent_id=1, type 2/3.
REGISTER_ARTICLES_TIRES_SQL = """
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

# Диски: parent_id=2; type 1=сталь, 2=литьё, 3=ковка (груз type=4 не берём).
REGISTER_ARTICLES_WHEELS_SQL = """
select distinct r.product_id::text as article
from logistics.register r
join products p on r.product_id = p.id
join products m on p.parent_id = m.id
join products b on m.parent_id = b.id
join logistics.suppliers s on r.supplier_id = s.id
where b.parent_id = 2
  and COALESCE(m.params->>'type', b.params->>'type') in ('1', '2', '3')
  and s.name = %s
  and r.quantity >= %s
"""

# Обратная совместимость: только шины.
REGISTER_ARTICLES_AT_SUPPLIER_SQL = REGISTER_ARTICLES_TIRES_SQL

_CACHE: dict[tuple[str, int, str], tuple[float, frozenset[str]]] = {}
# Склад УШК ночью почти не меняется; длинный TTL снижает живые hit'ы в ERP с /photo/.
_CACHE_TTL_SEC = 3600.0


def _db_cfg(secrets: dict[str, Any]) -> dict:
    return secrets.get("db") or {}


def _register_via(secrets: dict[str, Any]) -> str:
    d_cfg = _db_cfg(secrets)
    return str(d_cfg.get("register_via") or d_cfg.get("via") or "auto").strip().lower()


def _normalize_product_kind(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("wheel", "wheels", "диск", "диски"):
        return "wheel"
    if raw in ("both", "all", "*"):
        return "both"
    return "tire"


def _sql_for_kind(product_kind: str) -> str:
    kind = _normalize_product_kind(product_kind)
    if kind == "wheel":
        return REGISTER_ARTICLES_WHEELS_SQL
    if kind == "both":
        return (
            f"{REGISTER_ARTICLES_TIRES_SQL.strip()}\n"
            f"union\n"
            f"{REGISTER_ARTICLES_WHEELS_SQL.strip()}"
        )
    return REGISTER_ARTICLES_TIRES_SQL


def _connect_db(secrets: dict[str, Any]):
    d_cfg = _db_cfg(secrets)
    required = ("host", "port", "database", "user", "password")
    missing = [k for k in required if not str(d_cfg.get(k, "")).strip()]
    if missing:
        raise ValueError(f"В secrets.local.yaml не заполнены db-поля: {', '.join(missing)}")
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("Установите зависимость: pip install psycopg2-binary") from exc

    connect_timeout = int(d_cfg.get("connect_timeout", 5) or 5)
    # Не даём SELECT висеть бесконечно и блокировать photo-upload worker.
    statement_timeout_ms = int(d_cfg.get("statement_timeout_ms", 8000) or 8000)
    return psycopg2.connect(
        host=str(d_cfg["host"]),
        port=int(d_cfg["port"]),
        dbname=str(d_cfg["database"]),
        user=str(d_cfg["user"]),
        password=str(d_cfg["password"]),
        connect_timeout=connect_timeout,
        options=f"-c statement_timeout={max(1000, statement_timeout_ms)}",
    )


def _fetch_articles_at_supplier_http(
    secrets: dict[str, Any],
    supplier_name: str,
    *,
    min_quantity: int,
) -> frozenset[str]:
    from avito.erp_http import DEFAULT_HTTP_BASE, iter_register_search

    d_cfg = _db_cfg(secrets)
    user = str(d_cfg.get("user") or "").strip()
    password = str(d_cfg.get("password") or "").strip()
    if not user or not password:
        raise ValueError("Для HTTP-реестра нужны db.user и db.password")
    base_url = str(d_cfg.get("http_base_url") or DEFAULT_HTTP_BASE).strip()
    rows = iter_register_search(
        user=user,
        password=password,
        body={
            "supplier.name": supplier_name,
            "quantity@gte": min_quantity,
        },
        base_url=base_url,
        page_size=int(d_cfg.get("http_page_size", 1000) or 1000),
        timeout_sec=float(d_cfg.get("http_timeout_sec", 90) or 90),
        verify_ssl=bool(d_cfg.get("http_verify_ssl", False)),
    )
    return frozenset(
        str(item.get("product_id") or "").strip()
        for item in rows
        if str(item.get("product_id") or "").strip()
    )


def _list_suppliers_by_prefix_http(
    secrets: dict[str, Any],
    *,
    name_prefix: str,
) -> list[str]:
    from avito.erp_http import DEFAULT_HTTP_BASE, iter_register_search

    d_cfg = _db_cfg(secrets)
    user = str(d_cfg.get("user") or "").strip()
    password = str(d_cfg.get("password") or "").strip()
    if not user or not password:
        raise ValueError("Для HTTP-реестра нужны db.user и db.password")
    base_url = str(d_cfg.get("http_base_url") or DEFAULT_HTTP_BASE).strip()
    rows = iter_register_search(
        user=user,
        password=password,
        body={"supplier.name@like": name_prefix},
        base_url=base_url,
        page_size=int(d_cfg.get("http_page_size", 1000) or 1000),
        timeout_sec=float(d_cfg.get("http_timeout_sec", 90) or 90),
        verify_ssl=bool(d_cfg.get("http_verify_ssl", False)),
    )
    names = sorted(
        {
            str(item.get("supplier$name") or item.get("supplier.name") or "").strip()
            for item in rows
            if str(item.get("supplier$name") or item.get("supplier.name") or "")
            .strip()
            .startswith(name_prefix)
        }
    )
    return names


def _fetch_articles_pg(
    secrets: dict[str, Any],
    supplier_name: str,
    *,
    min_quantity: int,
    product_kind: str,
) -> frozenset[str]:
    sql = _sql_for_kind(product_kind)
    conn = _connect_db(secrets)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (supplier_name, min_quantity))
            return frozenset(
                str(row[0]).strip()
                for row in cur.fetchall()
                if row and str(row[0]).strip()
            )
    finally:
        conn.close()


def fetch_articles_at_supplier(
    secrets: dict[str, Any],
    supplier_name: str,
    *,
    min_quantity: int = MIN_REGISTER_QUANTITY,
    use_cache: bool = True,
    product_kind: str = "tire",
    kind_articles: frozenset[str] | None = None,
) -> frozenset[str]:
    """Артикулы (product_id), которые есть у поставщика в реестре с qty >= min_quantity.

    product_kind: tire | wheel | both.
    kind_articles: для HTTP-режима (смешанный ответ) — пересечение с артикулами нужного kind.
    """
    name = str(supplier_name or "").strip()
    if not name:
        return frozenset()
    kind = _normalize_product_kind(product_kind)

    cache_key = (name, min_quantity, kind)
    cached = _CACHE.get(cache_key) if use_cache else None
    if cached and time.time() < cached[0]:
        articles = cached[1]
        if kind_articles is not None and kind in ("tire", "wheel"):
            return articles & kind_articles
        return articles

    def _apply_kind_filter(arts: frozenset[str]) -> frozenset[str]:
        if kind_articles is not None and kind in ("tire", "wheel"):
            return frozenset(a for a in arts if a in kind_articles)
        return arts

    via = _register_via(secrets)
    try:
        if via in ("http", "https", "api"):
            articles = _apply_kind_filter(
                _fetch_articles_at_supplier_http(
                    secrets, name, min_quantity=min_quantity
                )
            )
        elif via in ("postgres", "pg", "psycopg2", "db"):
            articles = _fetch_articles_pg(
                secrets, name, min_quantity=min_quantity, product_kind=kind
            )
        else:
            try:
                articles = _fetch_articles_pg(
                    secrets, name, min_quantity=min_quantity, product_kind=kind
                )
            except Exception as exc:  # noqa: BLE001
                LOG.warning(
                    "ERP Postgres register unavailable (%s); HTTP fallback for %s",
                    exc,
                    name,
                )
                articles = _apply_kind_filter(
                    _fetch_articles_at_supplier_http(
                        secrets, name, min_quantity=min_quantity
                    )
                )
    except Exception as exc:  # noqa: BLE001
        if cached:
            LOG.warning(
                "ERP register failed for %s (%s); using stale cache (%s arts): %s",
                name,
                kind,
                len(cached[1]),
                exc,
            )
            articles = cached[1]
            if kind_articles is not None and kind in ("tire", "wheel"):
                return articles & kind_articles
            return articles
        raise

    if use_cache:
        _CACHE[cache_key] = (time.time() + _CACHE_TTL_SEC, articles)
    LOG.debug(
        "Реестр %s (%s): %s артикулов (qty >= %s)",
        name,
        kind,
        len(articles),
        min_quantity,
    )
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

    via = _register_via(secrets)
    if via in ("http", "https", "api"):
        return _list_suppliers_by_prefix_http(secrets, name_prefix=prefix)
    if via in ("postgres", "pg", "psycopg2", "db"):
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

    try:
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
    except Exception as exc:  # noqa: BLE001
        LOG.warning(
            "ERP Postgres suppliers unavailable (%s); HTTP fallback",
            exc,
        )
        return _list_suppliers_by_prefix_http(secrets, name_prefix=prefix)
