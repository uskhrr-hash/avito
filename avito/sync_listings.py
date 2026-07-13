"""Синхронизация цены и остатков уже размещённых объявлений через Avito API."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import pandas as pd

from avito.autoload import (
    _article_from_listing_id,
    _autoload_price,
    _avito_id_for_row,
    _quantity_label,
    load_avito_ids,
    merge_avito_ids,
    normalize_article_id,
    save_avito_ids_csv,
)
from avito.avito_api import (
    AvitoApiClient,
    fetch_avito_ids_by_ad_ids,
    update_item_price,
    update_stocks,
)
from avito.stores import StoresConfig

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncItem:
    listing_id: str
    article: str
    avito_id: int
    price: int
    quantity: int


@dataclass
class SyncStats:
    candidates: int = 0
    prices_updated: int = 0
    prices_skipped: int = 0
    prices_failed: int = 0
    stocks_updated: int = 0
    stocks_failed: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_avito_id(value: str) -> int | None:
    s = str(value or "").strip().split(".")[0]
    if not s or s.lower() == "nan":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _stock_quantity(raw_qty, *, max_quantity: int) -> int:
    label = _quantity_label(str(raw_qty or ""), max_quantity=max_quantity)
    try:
        return max(0, min(int(label), max_quantity))
    except ValueError:
        return 1


def build_sync_items(
    posting_df: pd.DataFrame,
    stores: StoresConfig,
    avito_ids: dict[str, str],
    *,
    max_listing_quantity: int = 12,
) -> list[SyncItem]:
    """Строки posting с известным avito_id — для обновления через API."""
    cap = max(1, int(max_listing_quantity))
    items: list[SyncItem] = []
    seen: set[tuple[int, str]] = set()

    for _, post in posting_df.iterrows():
        if post.get("дубликат_остаток") is True or str(post.get("дубликат_остаток")).lower() == "true":
            continue
        article = normalize_article_id(post.get("артикул", ""))
        if not article:
            continue
        price_raw = post.get("recommended_price")
        if pd.isna(price_raw):
            continue
        price = _autoload_price(price_raw)
        quantity = _stock_quantity(post.get("количество", ""), max_quantity=cap)

        for store in stores.stores:
            listing_id = store.listing_id(article)
            avito_raw = _avito_id_for_row(listing_id, article, avito_ids)
            avito_id = _parse_avito_id(avito_raw or "")
            if avito_id is None:
                continue
            key = (avito_id, listing_id)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                SyncItem(
                    listing_id=listing_id,
                    article=article,
                    avito_id=avito_id,
                    price=price,
                    quantity=quantity,
                )
            )
    return items


def sync_listings(
    client: AvitoApiClient,
    items: list[SyncItem],
    *,
    dry_run: bool = False,
    stock_batch_size: int = 200,
    price_pause_sec: float = 0.4,
) -> SyncStats:
    stats = SyncStats(candidates=len(items))
    if not items:
        return stats

    batch_size = max(1, min(int(stock_batch_size), 200))
    pause = max(0.0, float(price_pause_sec))

    for item in items:
        if dry_run:
            LOG.info(
                "dry-run price: avito_id=%s %s → %s руб",
                item.avito_id,
                item.listing_id,
                item.price,
            )
            stats.prices_updated += 1
            continue
        try:
            update_item_price(client, item.avito_id, item.price)
            stats.prices_updated += 1
        except RuntimeError as exc:
            stats.prices_failed += 1
            stats.errors.append(f"price {item.listing_id} ({item.avito_id}): {exc}")
        if pause:
            time.sleep(pause)

    stock_payload = [
        {
            "item_id": item.avito_id,
            "quantity": item.quantity,
            "external_id": item.listing_id,
        }
        for item in items
    ]
    if dry_run:
        for row in stock_payload:
            LOG.info(
                "dry-run stock: avito_id=%s %s → qty %s",
                row["item_id"],
                row["external_id"],
                row["quantity"],
            )
        stats.stocks_updated = len(stock_payload)
        return stats

    for i in range(0, len(stock_payload), batch_size):
        chunk = stock_payload[i : i + batch_size]
        try:
            results = update_stocks(client, chunk)
        except RuntimeError as exc:
            stats.stocks_failed += len(chunk)
            stats.errors.append(f"stocks batch {i // batch_size + 1}: {exc}")
            continue
        for row in results:
            if not isinstance(row, dict):
                continue
            if row.get("success") is True:
                stats.stocks_updated += 1
            else:
                stats.stocks_failed += 1
                err_bits = row.get("errors") or row.get("error")
                lid = row.get("external_id") or row.get("item_id")
                stats.errors.append(f"stock {lid}: {err_bits}")

    return stats


def refresh_avito_ids_from_api(
    client: AvitoApiClient,
    ad_ids: list[str],
    *,
    existing: dict[str, str] | None = None,
    stores: StoresConfig | None = None,
) -> dict[str, str]:
    """Подтянуть avito_id по нашим Id после публикации новых объявлений."""
    fetched = fetch_avito_ids_by_ad_ids(client, ad_ids)
    if not fetched:
        return dict(existing or {})
    by_listing = {ad_id: str(avito_id) for ad_id, avito_id in fetched.items()}
    return merge_avito_ids(existing or {}, by_listing, stores=stores)


def merge_and_save_avito_ids(
    path,
    mapping: dict[str, str],
) -> int:
    return save_avito_ids_csv(path, mapping)


def load_merged_avito_ids(path, stores: StoresConfig) -> dict[str, str]:
    return load_avito_ids(path, stores)
