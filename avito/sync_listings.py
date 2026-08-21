"""Синхронизация цены и остатков уже размещённых объявлений через Avito API."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

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
    stocks_skipped: int = 0
    stocks_failed: int = 0
    oos_zeroed: int = 0
    oos_skipped: int = 0
    oos_failed: int = 0
    pruned_ids: int = 0
    seeded: int = 0
    errors: list[str] = field(default_factory=list)
    deleted_avito_ids: set[int] = field(default_factory=set)


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


def _avito_id_for_sync(
    listing_id: str,
    article: str,
    avito_ids: dict[str, str],
) -> str:
    """
    AvitoId для price/stock API.

    В фид нельзя подставлять «голый» артикул на md_/pg_ (дубли AvitoId).
    Для синхронизации остатков — можно: иначе после close_oos qty так и остаётся 0.
    """
    specific = _avito_id_for_row(listing_id, article, avito_ids)
    if specific:
        return specific
    art = normalize_article_id(article) or _article_from_listing_id(listing_id)
    if art and art in avito_ids:
        return str(avito_ids[art] or "").strip()
    return ""


def _is_deleted_stock_error(err_bits) -> bool:
    text = str(err_bits or "").lower()
    return "удал" in text or "deleted" in text or "not found" in text


def build_sync_items(
    posting_df: pd.DataFrame,
    stores: StoresConfig,
    avito_ids: dict[str, str],
    *,
    max_listing_quantity: int = 12,
    manual_prices: dict[str, float] | None = None,
) -> list[SyncItem]:
    """Строки posting с известным avito_id — для обновления через API."""
    cap = max(1, int(max_listing_quantity))
    items: list[SyncItem] = []
    seen_avito: set[int] = set()
    manuals = manual_prices or {}

    for _, post in posting_df.iterrows():
        if post.get("дубликат_остаток") is True or str(post.get("дубликат_остаток")).lower() == "true":
            continue
        article = normalize_article_id(post.get("артикул", ""))
        if not article:
            continue
        price_raw = post.get("recommended_price")
        manual = manuals.get(article)
        if manual is not None and manual > 0:
            price_raw = manual
        if pd.isna(price_raw):
            continue
        price = _autoload_price(price_raw)
        quantity = _stock_quantity(post.get("количество", ""), max_quantity=cap)

        for store in stores.stores:
            listing_id = store.listing_id(article)
            avito_raw = _avito_id_for_sync(listing_id, article, avito_ids)
            avito_id = _parse_avito_id(avito_raw or "")
            if avito_id is None:
                continue
            # один AvitoId — одно обновление (в т.ч. fallback с голого артикула)
            if avito_id in seen_avito:
                continue
            seen_avito.add(avito_id)
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


def build_oos_zero_stocks(
    posting_df: pd.DataFrame,
    stores: StoresConfig,
    avito_ids: dict[str, str],
) -> list[dict]:
    """
    Объявления с известным AvitoId, которых нет в текущем posting (остатки кончились)
    → quantity=0 (снять с витрины через Stock Management).
    """
    active_articles: set[str] = set()
    for _, post in posting_df.iterrows():
        if post.get("дубликат_остаток") is True or str(post.get("дубликат_остаток")).lower() == "true":
            continue
        article = normalize_article_id(post.get("артикул", ""))
        if article:
            active_articles.add(article)

    # avito_id → external_id (предпочитаем md_/pg_)
    by_id: dict[int, str] = {}
    for key, raw in avito_ids.items():
        avito_id = _parse_avito_id(raw)
        if avito_id is None:
            continue
        article = _article_from_listing_id(key)
        if not article or article in active_articles:
            continue
        listing_id = key if "_" in normalize_article_id(key) else ""
        if not listing_id and stores.stores:
            listing_id = stores.stores[0].listing_id(article)
        if not listing_id:
            listing_id = article
        prev = by_id.get(avito_id)
        if prev is None or ("_" not in prev and "_" in listing_id):
            by_id[avito_id] = listing_id

    return [
        {"item_id": avito_id, "quantity": 0, "external_id": ext}
        for avito_id, ext in sorted(by_id.items(), key=lambda x: x[0])
    ]


def _state_price(state_map: dict[str, Any] | None, avito_id: int) -> int | None:
    if not state_map:
        return None
    row = state_map.get(str(avito_id))
    if row is None:
        return None
    return getattr(row, "last_price", None)


def _state_qty(state_map: dict[str, Any] | None, avito_id: int) -> int | None:
    if not state_map:
        return None
    row = state_map.get(str(avito_id))
    if row is None:
        return None
    return getattr(row, "last_qty", None)


def filter_price_items(
    items: list[SyncItem],
    state_map: dict[str, Any] | None,
    *,
    force_full: bool = False,
) -> tuple[list[SyncItem], int]:
    """Оставить позиции, где цена изменилась или ещё не отправлялась."""
    if force_full or not state_map:
        return list(items), 0
    out: list[SyncItem] = []
    skipped = 0
    for item in items:
        prev = _state_price(state_map, item.avito_id)
        if prev is not None and int(prev) == int(item.price):
            skipped += 1
            continue
        out.append(item)
    return out, skipped


def filter_stock_items(
    items: list[SyncItem],
    state_map: dict[str, Any] | None,
    *,
    force_full: bool = False,
) -> tuple[list[SyncItem], int]:
    """Оставить позиции, где qty изменился или ещё не отправлялся."""
    if force_full or not state_map:
        return list(items), 0
    out: list[SyncItem] = []
    skipped = 0
    for item in items:
        prev = _state_qty(state_map, item.avito_id)
        if prev is not None and int(prev) == int(item.quantity):
            skipped += 1
            continue
        out.append(item)
    return out, skipped


def filter_oos_payload(
    payload: list[dict],
    state_map: dict[str, Any] | None,
    *,
    force_full: bool = False,
) -> tuple[list[dict], int]:
    """OOS qty=0 — только если last_qty ещё не 0."""
    if force_full or not state_map:
        return list(payload), 0
    out: list[dict] = []
    skipped = 0
    for row in payload:
        try:
            avito_id = int(row["item_id"])
        except (TypeError, ValueError, KeyError):
            out.append(row)
            continue
        prev = _state_qty(state_map, avito_id)
        if prev is not None and int(prev) == 0:
            skipped += 1
            continue
        out.append(row)
    return out, skipped


def _apply_stock_batches(
    client: AvitoApiClient,
    payload: list[dict],
    *,
    batch_size: int,
    dry_run: bool,
    stats: SyncStats,
    oos: bool = False,
    on_success: list[tuple[str, str, str, int]] | None = None,
) -> None:
    if not payload:
        return
    if dry_run:
        for row in payload:
            LOG.info(
                "dry-run stock%s: avito_id=%s %s → qty %s",
                " OOS" if oos else "",
                row["item_id"],
                row["external_id"],
                row["quantity"],
            )
            if oos:
                stats.oos_zeroed += 1
            else:
                stats.stocks_updated += 1
            if on_success is not None:
                on_success.append(
                    (
                        str(row["item_id"]),
                        str(row.get("external_id") or ""),
                        "",
                        int(row["quantity"]),
                    )
                )
        return

    step = max(1, min(int(batch_size), 200))
    for i in range(0, len(payload), step):
        chunk = payload[i : i + step]
        try:
            results = update_stocks(client, chunk)
        except RuntimeError as exc:
            if oos:
                stats.oos_failed += len(chunk)
            else:
                stats.stocks_failed += len(chunk)
            stats.errors.append(f"stocks batch {i // step + 1}: {exc}")
            continue
        # API может вернуть неполный список — считаем success по item_id
        by_id: dict[int, dict] = {}
        for row in results:
            if not isinstance(row, dict):
                continue
            try:
                iid = int(row.get("item_id"))
            except (TypeError, ValueError):
                continue
            by_id[iid] = row

        for src in chunk:
            try:
                item_id_int = int(src["item_id"])
            except (TypeError, ValueError, KeyError):
                if oos:
                    stats.oos_failed += 1
                else:
                    stats.stocks_failed += 1
                continue
            row = by_id.get(item_id_int)
            if row is None:
                # пустой/неполный ответ — считаем успехом (как раньше при пустом stocks)
                if oos:
                    stats.oos_zeroed += 1
                else:
                    stats.stocks_updated += 1
                if on_success is not None:
                    art = ""
                    on_success.append(
                        (
                            str(item_id_int),
                            str(src.get("external_id") or ""),
                            art,
                            int(src["quantity"]),
                        )
                    )
                continue
            if row.get("success") is True or row.get("success") is None and not (
                row.get("errors") or row.get("error")
            ):
                if oos:
                    stats.oos_zeroed += 1
                else:
                    stats.stocks_updated += 1
                if on_success is not None:
                    on_success.append(
                        (
                            str(item_id_int),
                            str(src.get("external_id") or row.get("external_id") or ""),
                            "",
                            int(src["quantity"]),
                        )
                    )
                continue
            err_bits = row.get("errors") or row.get("error")
            lid = row.get("external_id") or row.get("item_id") or src.get("external_id")
            if _is_deleted_stock_error(err_bits):
                stats.deleted_avito_ids.add(item_id_int)
            if oos:
                stats.oos_failed += 1
                stats.errors.append(f"oos {lid}: {err_bits}")
            else:
                stats.stocks_failed += 1
                stats.errors.append(f"stock {lid}: {err_bits}")


def sync_listings(
    client: AvitoApiClient,
    items: list[SyncItem],
    *,
    dry_run: bool = False,
    stock_batch_size: int = 200,
    price_pause_sec: float = 0.4,
    oos_zero_stocks: list[dict] | None = None,
    state_map: dict[str, Any] | None = None,
    diff_prices: bool = True,
    diff_stocks: bool = True,
    force_full_sync: bool = False,
    price_max_retries: int = 4,
) -> tuple[SyncStats, list[tuple[str, str, str, int]], list[tuple[str, str, str, int]]]:
    """
    Обновить цены и остатки. Возвращает stats + списки успешных price/qty
    для записи в avito_sync_state: (avito_id, listing_id, article, value).
    """
    stats = SyncStats(candidates=len(items))
    pause = max(0.0, float(price_pause_sec))
    price_ok: list[tuple[str, str, str, int]] = []
    qty_ok: list[tuple[str, str, str, int]] = []

    price_items = items
    if diff_prices and not force_full_sync:
        price_items, skipped = filter_price_items(
            items, state_map, force_full=False
        )
        stats.prices_skipped = skipped
    else:
        stats.prices_skipped = 0

    for item in price_items:
        if dry_run:
            LOG.info(
                "dry-run price: avito_id=%s %s → %s руб",
                item.avito_id,
                item.listing_id,
                item.price,
            )
            stats.prices_updated += 1
            price_ok.append(
                (str(item.avito_id), item.listing_id, item.article, int(item.price))
            )
            continue
        try:
            update_item_price(
                client,
                item.avito_id,
                item.price,
                max_retries=price_max_retries,
            )
            stats.prices_updated += 1
            price_ok.append(
                (str(item.avito_id), item.listing_id, item.article, int(item.price))
            )
        except Exception as exc:  # noqa: BLE001 — сеть/таймаут Avito не должны рвать весь sync
            stats.prices_failed += 1
            stats.errors.append(f"price {item.listing_id} ({item.avito_id}): {exc}")
            msg = str(exc).lower()
            if "current status" in msg or "удал" in msg:
                stats.deleted_avito_ids.add(item.avito_id)
        if pause:
            time.sleep(pause)

    stock_items = items
    if diff_stocks and not force_full_sync:
        stock_items, skipped_s = filter_stock_items(
            items, state_map, force_full=False
        )
        stats.stocks_skipped = skipped_s
    stock_payload = [
        {
            "item_id": item.avito_id,
            "quantity": item.quantity,
            "external_id": item.listing_id,
        }
        for item in stock_items
    ]
    # article map for qty_ok enrichment
    art_by_avito = {str(it.avito_id): it.article for it in stock_items}
    stock_ok_buf: list[tuple[str, str, str, int]] = []
    _apply_stock_batches(
        client,
        stock_payload,
        batch_size=stock_batch_size,
        dry_run=dry_run,
        stats=stats,
        oos=False,
        on_success=stock_ok_buf,
    )
    for avito_id, lid, _art, qty in stock_ok_buf:
        qty_ok.append((avito_id, lid, art_by_avito.get(avito_id, _art), qty))

    oos_payload = list(oos_zero_stocks or [])
    if diff_stocks and not force_full_sync:
        oos_payload, oos_skip = filter_oos_payload(
            oos_payload, state_map, force_full=False
        )
        stats.oos_skipped = oos_skip
    oos_ok_buf: list[tuple[str, str, str, int]] = []
    _apply_stock_batches(
        client,
        oos_payload,
        batch_size=stock_batch_size,
        dry_run=dry_run,
        stats=stats,
        oos=True,
        on_success=oos_ok_buf,
    )
    qty_ok.extend(oos_ok_buf)

    return stats, price_ok, qty_ok


def prune_avito_ids_mapping(
    mapping: dict[str, str],
    deleted_ids: set[int],
) -> tuple[dict[str, str], int]:
    """Убрать ключи, ссылающиеся на удалённые AvitoId."""
    if not deleted_ids:
        return dict(mapping), 0
    deleted_str = {str(i) for i in deleted_ids}
    out: dict[str, str] = {}
    removed = 0
    for key, val in mapping.items():
        vid = str(val or "").strip().split(".")[0]
        if vid in deleted_str:
            removed += 1
            continue
        out[key] = val
    return out, removed


def collect_ad_ids_for_api(
    posting_df: pd.DataFrame,
    stores: StoresConfig,
    *,
    extra_keys: list[str] | None = None,
    listing_ids: list[str] | None = None,
) -> list[str]:
    """
    Кандидаты Id для GET /autoload/v2/items/avito_ids.

    Берём listing_id из БД + posting (md_/pg_/артикул). Без fan-out в ответ —
    API вернёт только реально существующие объявления.
    """
    from avito.autoload import posting_keep_sets

    out: set[str] = set()
    for lid in listing_ids or []:
        s = str(lid or "").strip()
        if s:
            out.add(s)
    _arts, _titles, lids = posting_keep_sets(posting_df, stores)
    out |= lids
    for key in extra_keys or []:
        s = str(key or "").strip()
        if s and not s.startswith("title:"):
            out.add(s)
    return sorted(out)


def refresh_avito_ids_from_api(
    client: AvitoApiClient,
    ad_ids: list[str],
    *,
    existing: dict[str, str] | None = None,
    stores: StoresConfig | None = None,
    include_report: bool = False,
) -> dict[str, str]:
    """
    Подтянуть avito_id по нашим Id (listing_id / артикул).

    Для каждого md_/pg_ также пишем голый артикул → тот же AvitoId
    (одно объявление на артикул, без копирования на другие магазины).
    """
    from avito.avito_api import fetch_avito_ids_from_report_items

    fetched = dict(fetch_avito_ids_by_ad_ids(client, ad_ids))
    if include_report:
        try:
            for ad_id, avito_id in fetch_avito_ids_from_report_items(client).items():
                fetched.setdefault(ad_id, avito_id)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("avito_ids report harvest: %s", exc)
    if not fetched:
        return dict(existing or {})
    by_listing: dict[str, str] = {}
    for ad_id, avito_id in fetched.items():
        s = str(avito_id)
        by_listing[ad_id] = s
        art = _article_from_listing_id(ad_id)
        if art and art != ad_id:
            # Не затираем чужой listing-level ключ; артикул — алиас того же объявления.
            by_listing.setdefault(art, s)
    return merge_avito_ids(existing or {}, by_listing, stores=stores)


def merge_and_save_avito_ids(
    path,
    mapping: dict[str, str],
) -> int:
    return save_avito_ids_csv(path, mapping)


def load_merged_avito_ids(path, stores: StoresConfig) -> dict[str, str]:
    return load_avito_ids(path, stores)
