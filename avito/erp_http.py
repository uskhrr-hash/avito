#!/usr/bin/env python3
"""ERP HTTPS client for product.register (no Postgres)."""
from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from base64 import b64encode
from typing import Any, Callable
from urllib.parse import urlencode

LOG = logging.getLogger(__name__)

DEFAULT_HTTP_BASE = "https://erp.shinaufa.ru/"
DEFAULT_PAGE_SIZE = 1000
DEFAULT_TIMEOUT_SEC = 90.0


def _basic_auth_header(user: str, password: str) -> str:
    token = b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def erp_http_post(
    *,
    base_url: str,
    entity: str,
    action: str,
    user: str,
    password: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    verify_ssl: bool = False,
) -> Any:
    """POST JSON to ERP entity/action API. Returns parsed JSON."""
    base = (base_url or DEFAULT_HTTP_BASE).rstrip("/") + "/"
    params = {"entity": entity, "action": action}
    if query:
        params.update({k: v for k, v in query.items() if v is not None})
    url = base + "?" + urlencode(params, doseq=True)
    payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": _basic_auth_header(user, password),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    ctx = None if verify_ssl else ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8", "replace")
    if not raw.strip():
        return None
    return json.loads(raw)


def iter_register_search(
    *,
    user: str,
    password: str,
    body: dict[str, Any],
    base_url: str = DEFAULT_HTTP_BASE,
    page_size: int = DEFAULT_PAGE_SIZE,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    verify_ssl: bool = False,
    sleep_sec: float = 0.0,
) -> list[dict[str, Any]]:
    """Paginate product.register search until a short page."""
    out: list[dict[str, Any]] = []
    offset = 0
    page_size = max(1, int(page_size))
    while True:
        chunk = erp_http_post(
            base_url=base_url,
            entity="product.register",
            action="search",
            user=user,
            password=password,
            body=body,
            query={"limit": page_size, "offset": offset},
            timeout_sec=timeout_sec,
            verify_ssl=verify_ssl,
        )
        if not isinstance(chunk, list):
            raise RuntimeError(
                f"ERP product.register search: expected list, got {type(chunk).__name__}"
            )
        out.extend(item for item in chunk if isinstance(item, dict))
        LOG.info(
            "ERP HTTP register: offset=%s got=%s total=%s filters=%s",
            offset,
            len(chunk),
            len(out),
            body,
        )
        if len(chunk) < page_size:
            break
        offset += page_size
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    return out


def fetch_register_rows_for_stock(
    *,
    user: str,
    password: str,
    allowed_suppliers: list[str] | tuple[str, ...],
    ushk_prefix: str = "УШК",
    base_url: str = DEFAULT_HTTP_BASE,
    page_size: int = DEFAULT_PAGE_SIZE,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    verify_ssl: bool = False,
    map_item: Callable[[dict[str, Any]], Any] | None = None,
) -> list[Any]:
    """
    Load register lines needed for Avito P2–P6 cascade via HTTPS.

    Fetches each allowed supplier by exact name, then USHK* via like filter.
    Does not apply the tire-tree SQL filter from REGISTER_QUERY — client filters
    by supplier allow-list / USHK prefix instead.
    """
    seen: set[tuple[Any, ...]] = set()
    mapped: list[Any] = []

    def _add(items: list[dict[str, Any]]) -> None:
        for item in items:
            key = (
                item.get("product_id"),
                item.get("supplier_id"),
                item.get("supplier$name") or item.get("supplier.name"),
                item.get("price"),
                item.get("quantity"),
            )
            if key in seen:
                continue
            seen.add(key)
            if map_item is None:
                mapped.append(item)
            else:
                row = map_item(item)
                if row is not None:
                    mapped.append(row)

    for name in allowed_suppliers:
        name = str(name or "").strip()
        if not name:
            continue
        # Prefer join field supplier.name; supplier$name also works in ERP UI.
        rows = iter_register_search(
            user=user,
            password=password,
            body={"supplier.name": name},
            base_url=base_url,
            page_size=page_size,
            timeout_sec=timeout_sec,
            verify_ssl=verify_ssl,
        )
        _add(rows)

    prefix = str(ushk_prefix or "").strip()
    if prefix:
        rows = iter_register_search(
            user=user,
            password=password,
            body={"supplier.name@like": prefix},
            base_url=base_url,
            page_size=page_size,
            timeout_sec=timeout_sec,
            verify_ssl=verify_ssl,
        )
        _add(rows)

    return mapped
