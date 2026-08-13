"""Сборка объявлений: posting → listings SQLite → XML (без working xlsx)."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from avito.autoload import (
    AUTOLOAD_PRICE_QUANTITY,
    _article_from_listing_id,
    _avito_id_for_row,
    _autoload_price,
    _format_description,
    _listing_id_for_article,
    _photo_cfg,
    _posting_sam_mb_cash_price,
    _posting_ushk_in_stock,
    _quantity_label,
    _should_replace_photo_urls,
    _shinaufa_photo_settings,
    normalize_article_id,
    posting_keep_sets,
    resolve_photos_folder,
)
from avito.autoload_xml import write_ads_xml
from avito.config import AutoloadSettings
from avito.model_descriptions import lookup_model_description
from avito.photos import (
    StorePhotos,
    assign_store_by_photo_share,
    build_store_photo_urls,
    count_own_articles_by_store,
    photo_urls_look_like_article,
    photo_urls_ok_for_avito_update,
    resolve_listing_photo_sets,
)
from avito.stock_db import (
    ListingDbRow,
    delete_listings_not_in,
    load_listings_map,
    replace_no_photos,
    sync_avito_ids_from_listings,
    upsert_listings,
)
from avito.stores import StoresConfig, merge_defaults
from avito.title_parse import build_multi_name_from_title, parse_title_fields
from avito.tire_catalog import load_tire_catalog, normalize_title_fields
from avito.wheel_parse import (
    AVITO_WHEEL_HEADERS,
    is_wheel_kind,
    map_wheel_fields,
)

LOG = logging.getLogger(__name__)

def listing_content_fingerprint(row: ListingDbRow) -> str:
    """
    Fingerprint для diff-only photo_updates: фото + ключевые поля объявления.
    Цена/qty не входят — они идут через API.
    """
    parts = [
        str(row.photo_urls or "").strip(),
        str(row.title or "").strip(),
        str(row.description_html or "").strip(),
        str(row.multi_name or "").strip(),
        str(row.brand or "").strip(),
        str(row.model or "").strip(),
        str(row.width or "").strip(),
        str(row.profile or "").strip(),
        str(row.diameter or "").strip(),
        str(row.season or "").strip(),
        str(row.load_index or "").strip(),
        str(row.speed_index or "").strip(),
        str(row.address or "").strip(),
        str(row.contact_person or "").strip(),
        str(row.phone or "").strip(),
    ]
    raw = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def filter_photo_update_rows(
    rows: list[ListingDbRow],
    state_by_avito: dict[str, Any] | None,
    state_by_listing: dict[str, Any] | None,
    *,
    force_full: bool = False,
    seed_on_empty: bool = True,
) -> tuple[list[ListingDbRow], int, list[tuple[str, str, str, str]], bool]:
    """
    Diff-only для XML photo_updates.

    Returns: (rows_to_send, skipped, seed_marks, seeded)
    seed_marks: (avito_id, listing_id, article, hash) — записать как already-sent.
    """
    if force_full or not rows:
        return list(rows), 0, [], False

    state_by_avito = state_by_avito or {}
    state_by_listing = state_by_listing or {}

    # Есть ли хоть один сохранённый photo hash?
    has_any_hash = any(
        str(getattr(s, "last_photo_hash", "") or "").strip()
        for s in list(state_by_avito.values()) + list(state_by_listing.values())
    )
    if not has_any_hash and seed_on_empty:
        seed_marks: list[tuple[str, str, str, str]] = []
        for row in rows:
            fp = listing_content_fingerprint(row)
            aid = str(row.avito_id or "").strip() or f"lid:{row.listing_id}"
            seed_marks.append((aid, row.listing_id, row.article_id, fp))
        return [], 0, seed_marks, True

    out: list[ListingDbRow] = []
    skipped = 0
    for row in rows:
        fp = listing_content_fingerprint(row)
        aid = str(row.avito_id or "").strip()
        prev = None
        if aid and aid in state_by_avito:
            prev = str(getattr(state_by_avito[aid], "last_photo_hash", "") or "").strip()
        elif row.listing_id in state_by_listing:
            prev = str(
                getattr(state_by_listing[row.listing_id], "last_photo_hash", "") or ""
            ).strip()
        if prev and prev == fp:
            skipped += 1
            continue
        out.append(row)
    return out, skipped, [], False



def listing_to_feed_row(row: ListingDbRow | dict[str, Any]) -> dict[str, Any]:
    """Listing → dict с русскими заголовками для write_ads_xml."""
    if isinstance(row, ListingDbRow):
        get = lambda k, default="": getattr(row, k, default)  # noqa: E731
        price = row.price
        in_feed = row.in_feed
    else:
        get = lambda k, default="": row.get(k, default)  # noqa: E731
        price = row.get("price")
        in_feed = bool(row.get("in_feed", True))
    del in_feed
    product_type = str(get("product_type") or "").strip()
    is_wheel = product_type == "Диски" or is_wheel_kind(product_type)
    out: dict[str, Any] = {
        "Уникальный идентификатор объявления": get("listing_id"),
        "Название объявления": get("title"),
        "Ссылки на фото": get("photo_urls"),
        "Описание объявления": get("description_html"),
        "Диаметр": get("diameter"),
        "Состояние": get("condition_val"),
        "Название мультиобъявления": get("multi_name"),
        "Соединять это объявление с другими объявлениями": get("multi_item") or "Да",
        "Количество": get("quantity") or AUTOLOAD_PRICE_QUANTITY,
        "Контактное лицо": get("contact_person"),
        "Номер телефона": get("phone"),
        "Адрес": get("address"),
        "Способ связи": get("contact_method"),
        "Название компании": get("company"),
        "Почта": get("email"),
        "Способ размещения": get("listing_fee"),
        "Категория": get("category"),
        "Вид товара": get("goods_type"),
        "Вид объявления": get("ad_type"),
        "Тип товара": product_type,
        "Целевая аудитория": get("audience"),
    }
    if is_wheel:
        # Колонки ListingDbRow переиспользуем: run_flat=тип, width=обод,
        # load/speed/season/profile = болты/PCD/ET/DIA
        out[AVITO_WHEEL_HEADERS["brand"]] = get("brand")
        out[AVITO_WHEEL_HEADERS["model"]] = get("model")
        out[AVITO_WHEEL_HEADERS["disk_type"]] = get("run_flat")
        out[AVITO_WHEEL_HEADERS["rim_width"]] = get("width")
        out[AVITO_WHEEL_HEADERS["bolt_count"]] = get("load_index")
        out[AVITO_WHEEL_HEADERS["pcd"]] = get("speed_index")
        out[AVITO_WHEEL_HEADERS["offset"]] = get("season")
        out[AVITO_WHEEL_HEADERS["dia"]] = get("profile")
    else:
        out["Производитель"] = get("brand")
        out["Модель"] = get("model")
        out["Ширина профиля"] = get("width")
        out["Высота профиля"] = get("profile")
        out["Сезонность"] = get("season")
        out["Индекс нагрузки"] = get("load_index")
        out["Индекс скорости"] = get("speed_index")
        out["Run Flat"] = get("run_flat")
        out["Бесплатный шиномонтаж"] = get("free_tire_fitting")
    avito_id = str(get("avito_id") or "").strip()
    if avito_id and avito_id.lower() != "nan":
        out["Номер объявления на Авито"] = avito_id.split(".")[0]
    if price is not None and str(price).strip() != "":
        try:
            out["Цена"] = int(float(price))
        except (TypeError, ValueError):
            pass
    return {k: v for k, v in out.items() if v is not None and str(v).strip() != ""}


def _merge_photo_urls(
    *,
    existing: str,
    resolved: str,
    source: str,
) -> tuple[str, str]:
    """
    Не затираем сохранённые CDN/наши URL пустым resolver'ом.
    Фото артикула всегда побеждает; модель не трогает Avito CDN.
    """
    existing = str(existing or "").strip()
    resolved = str(resolved or "").strip()
    if resolved:
        if not existing or _should_replace_photo_urls(existing, source=source):
            return resolved, source or "resolved"
        return existing, "preserved"
    if existing:
        return existing, "preserved"
    return "", ""


def build_listings_from_posting(
    *,
    conn,
    posting_df: pd.DataFrame,
    cfg: AutoloadSettings,
    stores: StoresConfig,
    model_descriptions: dict[str, str],
    avito_ids: dict[str, str],
    project_root: Path,
    wheels_cfg=None,
) -> dict[str, Any]:
    """
    Пересобрать listings из posting + photos + descriptions.
    Возвращает stats и списки new / photo_updates (ListingDbRow).
    """
    root = project_root
    local_photos = resolve_photos_folder(cfg, root)
    tire_cat = load_tire_catalog(str(root / "data" / "avito_tire_catalog.json"))
    existing_map = load_listings_map(conn)

    # kind в posting мог быть потерян до миграции колонки — подстрахуемся goods.xlsx
    goods_kind: dict[str, str] = {}
    try:
        from avito.compare import load_stock
        from avito.config import load_config as _load_full_cfg

        full_cfg = _load_full_cfg(root / "config.yaml")
        goods_path = Path(full_cfg.compare.stock_file)
        if not goods_path.is_absolute():
            goods_path = root / goods_path
        for r in load_stock(goods_path, full_cfg.compare):
            art = str(r.article).strip()
            if art:
                k = str(getattr(r, "kind", "") or "tire").strip().lower() or "tire"
                goods_kind[art] = "wheel" if is_wheel_kind(k) else "tire"
    except Exception as exc:  # noqa: BLE001
        LOG.warning("goods kind map unavailable: %s", exc)

    photos_missing: list[dict] = []
    missing_models: dict[str, dict] = {}
    built: list[ListingDbRow] = []
    keep_ids: set[str] = set()

    wheels_enabled = True
    wheels_in_autoload = True
    wheels_skip_photos = False
    wheels_product_type = "Диски"
    wheels_desc_html = ""
    if wheels_cfg is not None:
        wheels_enabled = bool(getattr(wheels_cfg, "enabled", True))
        wheels_in_autoload = bool(getattr(wheels_cfg, "include_in_autoload", True))
        wheels_skip_photos = bool(getattr(wheels_cfg, "skip_without_photos", False))
        wheels_product_type = str(
            getattr(wheels_cfg, "product_type", "Диски") or "Диски"
        ).strip() or "Диски"
        wheels_desc_html = str(getattr(wheels_cfg, "description_html", "") or "")

    stats = {
        "updated": 0,
        "appended": 0,
        "skipped": 0,
        "skipped_no_photos": 0,
        "model_photo_fallback": 0,
        "removed": 0,
        "photos_preserved": 0,
        "wheels": 0,
        "tires": 0,
        "model_store_reassigned": 0,
    }

    prefixes = tuple(stores.prefixes)
    photo_share_tire = count_own_articles_by_store(
        local_photos, prefixes, product_kind="tire"
    )
    photo_share_wheel = count_own_articles_by_store(
        local_photos, prefixes, product_kind="wheel"
    )
    stats["photo_share_tire"] = dict(photo_share_tire)
    stats["photo_share_wheel"] = dict(photo_share_wheel)
    LOG.info(
        "Доля своих фото (для shinaufa/model): tire=%s wheel=%s",
        photo_share_tire,
        photo_share_wheel,
    )

    for _, post in posting_df.iterrows():
        if post.get("дубликат_остаток") is True or str(
            post.get("дубликат_остаток")
        ).lower() == "true":
            stats["skipped"] += 1
            continue

        nom = str(post.get("номенклатура", "")).strip()
        if not nom:
            stats["skipped"] += 1
            continue

        article = normalize_article_id(post.get("артикул", ""))
        price = post.get("recommended_price")
        if not article or pd.isna(price):
            stats["skipped"] += 1
            continue
        price_int = _autoload_price(price)

        kind = str(post.get("kind", "") or "tire").strip() or "tire"
        if article in goods_kind:
            kind = goods_kind[article]
        is_wheel = is_wheel_kind(kind)
        if is_wheel and (not wheels_enabled or not wheels_in_autoload):
            stats["skipped"] += 1
            continue

        if is_wheel:
            wfields = map_wheel_fields(
                brand=str(post.get("brand", "") or ""),
                model=str(post.get("model", "") or ""),
                wheel_type=str(post.get("wheel_type", "") or ""),
                width=str(post.get("width", "") or ""),
                diameter=str(post.get("diameter", "") or ""),
                studs=str(post.get("studs", "") or ""),
                circle=str(post.get("circle", "") or ""),
                et=str(post.get("et", "") or ""),
                hub=str(post.get("hub", "") or ""),
                title=nom,
            )
            fields = {
                "brand": wfields["brand"],
                "model": wfields["model"],
                "width": wfields["rim_width"],
                "profile": wfields["dia"],
                "diameter": wfields["rim_diameter"],
                "season": wfields["offset"],
                "load_index": wfields["bolt_count"],
                "speed_index": wfields["pcd"],
                "run_flat": wfields["disk_type"],
            }
            product_type_value = wheels_product_type
        else:
            fields = normalize_title_fields(
                parse_title_fields(nom), title=nom, catalog=tire_cat
            )
            product_type_value = str(
                cfg.defaults.get("product_type") or "Шины"
            )
            if not str(fields.get("brand") or "").strip() or not str(
                fields.get("model") or ""
            ).strip():
                stats["skipped_bad_params"] = stats.get("skipped_bad_params", 0) + 1
                continue

        resolved_photos = resolve_listing_photo_sets(
            local_photos,
            article,
            stores.prefixes,
            layout=cfg.photo_layout,
            prefix_in_filename=cfg.photo_store_prefix_in_filename,
            brand=fields.get("brand", ""),
            model=fields.get("model", ""),
            model_fallback=cfg.model_photo_fallback,
            article_first=cfg.photo_article_first,
            legacy_unprefixed_prefix=stores.legacy_unprefixed_store,
            max_count=int(cfg.image_count or 0),
            jpeg_quality=cfg.jpeg_quality,
            contributors_prefix=cfg.contributors_prefix,
            shinaufa_model_photos=_shinaufa_photo_settings(
                cfg, project_root=root, product_kind=kind
            ),
            product_kind=kind,
            photos_root=local_photos,
            title=nom,
        )
        store_photo_sets = list(resolved_photos.store_sets)
        if resolved_photos.source == "model":
            stats["model_photo_fallback"] += 1

        # Один артикул → одно объявление (победитель фото / доля съёмки для shinaufa)
        if store_photo_sets:
            sp = store_photo_sets[0]
            if resolved_photos.source == "model":
                weights = photo_share_wheel if is_wheel else photo_share_tire
                assigned = assign_store_by_photo_share(article, weights, prefixes)
                if assigned != sp.prefix:
                    sp = StorePhotos(prefix=assigned, files=sp.files, urls=sp.urls)
                    stats["model_store_reassigned"] = (
                        stats.get("model_store_reassigned", 0) + 1
                    )
            store = stores.get(sp.prefix)
            if not store and stores.stores:
                store = stores.stores[0]
            if not store:
                stats["skipped"] += 1
                continue
            listing_id = store.listing_id(article)
            photos_resolved = build_store_photo_urls(
                sp,
                _photo_cfg(cfg),
                article=article,
                layout=cfg.photo_layout,
                photos_root=local_photos,
            )
            photo_source = resolved_photos.source
        else:
            listing_id = _listing_id_for_article(article, stores)
            photos_resolved = ""
            photo_source = ""
            prefix = listing_id.split("_", 1)[0] if "_" in listing_id else ""
            store = stores.get(prefix) if prefix else None
            if not store and stores.stores:
                store = stores.stores[0]
            if not store:
                stats["skipped"] += 1
                continue

        prev = existing_map.get(listing_id)
        # Avito навсегда привязывает AvitoId к Id (md_…/pg_…). Смена префикса
        # при shinaufa/model → error 1013 («номер уже связан с md_…»).
        # Id всегда sticky; магазин контакта можно сменить отдельно (store ниже).
        if prev is None:
            for lid, row in existing_map.items():
                if row.article_id == article:
                    prev = row
                    listing_id = lid
                    # Контакты: если source=model и store уже выбран по доле съёмки —
                    # оставляем его. Иначе оставляем магазин из sticky Id.
                    if photo_source != "model":
                        stuck = (
                            stores.get(lid.split("_", 1)[0]) if "_" in lid else None
                        )
                        if stuck:
                            store = stuck
                    break

        photo_urls, photos_kind = _merge_photo_urls(
            existing=prev.photo_urls if prev else "",
            resolved=photos_resolved,
            source=photo_source,
        )
        if photos_kind == "preserved":
            stats["photos_preserved"] += 1

        skip_no_photos = wheels_skip_photos if is_wheel else cfg.skip_without_photos
        # Свои фото артикула (съёмка) ≠ shinaufa/model fallback для публикации.
        has_own_article_photos = photo_source == "article" or (
            bool(photo_urls) and photo_urls_look_like_article(photo_urls, article)
            and not str(photo_source).startswith("model")
            and photos_kind != "model"
        )
        if not has_own_article_photos:
            # Очередь фотографа: продолжаем снимать, даже если в фид уже ушёл shinaufa.
            if not photo_urls:
                reason = "нет фото (артикул / модель на диске / shinaufa)"
            elif photo_source == "model" or photos_kind == "model":
                reason = "нет своих фото (в фиде shinaufa/model)"
            else:
                reason = "нет локальных фото артикула"
            if cfg.verify_photos_on_disk and not local_photos:
                reason = "папка фото не найдена"
            photos_missing.append(
                {
                    "артикул": article,
                    "номенклатура": nom,
                    "магазины": ", ".join(stores.prefixes),
                    "проблема": reason,
                    "kind": kind,
                }
            )
            stats["queued_no_photos"] = stats.get("queued_no_photos", 0) + 1

        if not photo_urls and skip_no_photos:
            # В фид без любого фото не пускаем (shinaufa уже дал бы photo_urls).
            stats["skipped"] += 1
            stats["skipped_no_photos"] += 1
            continue

        model_key = " ".join(
            x for x in (fields.get("brand", ""), fields.get("model", "")) if x
        ).strip()
        model_desc = ""
        if not is_wheel:
            model_desc = lookup_model_description(
                model_descriptions,
                nomenclature=nom,
                brand=fields.get("brand", ""),
                model=fields.get("model", ""),
            )
            if model_key and not model_desc:
                missing_models[model_key] = {
                    "модель": model_key,
                    "бренд": fields.get("brand", ""),
                    "model": fields.get("model", ""),
                    "пример_номенклатуры": nom,
                }

        stock_qty = _quantity_label(
            str(post.get("количество", "")),
            max_quantity=cfg.max_listing_quantity,
        )
        row_defaults = dict(merge_defaults(cfg.defaults, store))
        row_defaults["product_type"] = product_type_value
        desc_template = (
            wheels_desc_html
            if is_wheel and wheels_desc_html
            else cfg.description_html
        )
        if is_wheel and not wheels_desc_html:
            desc_template = (
                "<p><strong>{availability_headline}</strong></p>"
                '<p>Новые диски &quot;{nomenclature}&quot;</p>'
                "<p><br></p>"
                "<p><strong>{payment_terms}</strong></p>"
                "<p>{model_description}</p>"
                "<p>Артикул: {article}. Цена за 1 шт: {price_human} руб.</p>"
                "<ul>"
                "<li>Количество на складе: {quantity}</li>"
                "<li>Самовывоз: {address}</li>"
                "<li>Контакт: {contact_person}, {phone}</li>"
                "<li>Связь: {contact_method}</li>"
                "</ul>"
            )
        description = _format_description(
            desc_template,
            nomenclature=nom,
            article=article,
            price=price_int,
            quantity=stock_qty,
            model_description=model_desc,
            store_pitch="" if is_wheel else cfg.store_pitch_html,
            store_defaults=row_defaults,
            ushk_in_stock=_posting_ushk_in_stock(post),
            sam_mb_cash_price=_posting_sam_mb_cash_price(post),
        )
        multi_name = build_multi_name_from_title(nom)
        avito_id = _avito_id_for_row(listing_id, article, avito_ids)
        if not avito_id and prev and prev.avito_id:
            avito_id = prev.avito_id

        listing = ListingDbRow(
            listing_id=listing_id,
            article_id=article,
            avito_id=avito_id or "",
            title=nom,
            price=float(price_int),
            photo_urls=photo_urls,
            description_html=description,
            store_key=store.prefix,
            brand=fields.get("brand", ""),
            model=fields.get("model", ""),
            width=fields.get("width", ""),
            profile=fields.get("profile", ""),
            diameter=fields.get("diameter", ""),
            season=fields.get("season", ""),
            load_index=fields.get("load_index", ""),
            speed_index=fields.get("speed_index", ""),
            run_flat=(
                fields.get("run_flat", "")
                if is_wheel
                else row_defaults.get("run_flat", "Нет")
            ),
            condition_val=row_defaults.get("condition", "Новое"),
            multi_name=multi_name,
            multi_item="Да",
            quantity=AUTOLOAD_PRICE_QUANTITY,
            photos_kind=photos_kind or photo_source,
            contact_person=row_defaults.get("contact_person", ""),
            phone=row_defaults.get("phone", ""),
            address=row_defaults.get("address", ""),
            contact_method=row_defaults.get("contact_method", ""),
            company=row_defaults.get("company", ""),
            email=row_defaults.get("email", ""),
            listing_fee=row_defaults.get("listing_type", ""),
            category=row_defaults.get("category", ""),
            goods_type=row_defaults.get("goods_type", ""),
            ad_type=row_defaults.get("ad_type", ""),
            product_type=product_type_value,
            free_tire_fitting="" if is_wheel else row_defaults.get("free_mounting", ""),
            audience=row_defaults.get("audience", ""),
            in_feed=True,
        )
        keep_ids.add(listing_id)
        if prev is None:
            stats["appended"] += 1
        else:
            stats["updated"] += 1
        if is_wheel:
            stats["wheels"] += 1
        else:
            stats["tires"] += 1
        built.append(listing)

    if cfg.close_not_in_goods:
        keep_articles, _keep_titles, keep_listing_ids = posting_keep_sets(
            posting_df, stores
        )
        # Оставить только то, что собрали из posting (+ id из keep sets)
        keep_ids |= {lid for lid in keep_listing_ids if lid in existing_map}
        # Не оставляем строки без фото вне built
        keep_ids = {r.listing_id for r in built}
        removed_n = delete_listings_not_in(conn, keep_ids)
        stats["removed"] = removed_n
    else:
        keep_ids = {r.listing_id for r in built}
        # не трогаем чужие listing_id

    n_up = upsert_listings(conn, built)
    sync_avito_ids_from_listings(conn)
    replace_no_photos(conn, photos_missing)

    new_rows: list[ListingDbRow] = []
    photo_rows: list[ListingDbRow] = []
    article_photo_updates = 0
    for row in built:
        if not (row.photo_urls or "").strip():
            continue
        if not row.avito_id:
            new_rows.append(row)
        else:
            # Avito autoload = full catalog: Ids missing from the file are archived
            # (removed_from_file / removed_complete). Keep ALL existing ads with photos.
            # article-URL check is only a metric for true photo refreshes.
            photo_rows.append(row)
            if photo_urls_ok_for_avito_update(row.photo_urls, row.article_id):
                article_photo_updates += 1

    stats["listings_upserted"] = n_up
    stats["new_count"] = len(new_rows)
    stats["photo_updates_count"] = len(photo_rows)
    stats["article_photo_updates"] = article_photo_updates
    stats["photos_missing"] = photos_missing
    stats["missing_models"] = list(missing_models.values())
    stats["photos_dir"] = str(local_photos) if local_photos else ""
    stats["new_rows"] = new_rows
    stats["photo_rows"] = photo_rows
    stats["all_rows"] = built
    return stats


def write_listing_feeds(
    *,
    new_rows: list[ListingDbRow],
    photo_rows: list[ListingDbRow],
    new_feed_path: Path | None,
    photo_updates_path: Path | None,
    exclude_product_types: set[str] | None = None,
) -> tuple[int, int]:
    """Записать XML-фиды new / photo_updates."""
    skip = {str(x).strip() for x in (exclude_product_types or set()) if str(x).strip()}

    def _keep(row: ListingDbRow) -> bool:
        if not skip:
            return True
        return str(row.product_type or "").strip() not in skip

    new_rows = [r for r in new_rows if _keep(r)]
    photo_rows = [r for r in photo_rows if _keep(r)]
    n_new = 0
    n_photo = 0
    if new_feed_path:
        new_feed_path = Path(new_feed_path)
        if new_feed_path.suffix.lower() != ".xml":
            new_feed_path = new_feed_path.with_suffix(".xml")
        n_new = write_ads_xml([listing_to_feed_row(r) for r in new_rows], new_feed_path)
        LOG.info("XML новые: %s → %s", n_new, new_feed_path)
    if photo_updates_path:
        photo_updates_path = Path(photo_updates_path)
        if photo_updates_path.suffix.lower() != ".xml":
            photo_updates_path = photo_updates_path.with_suffix(".xml")
        n_photo = write_ads_xml(
            [listing_to_feed_row(r) for r in photo_rows], photo_updates_path
        )
        LOG.info("XML обновление фото: %s → %s", n_photo, photo_updates_path)
    return n_new, n_photo


def merge_listing_xml_feeds(
    sources: list[Path],
    output_path: Path,
    *,
    skip_ids: set[str] | None = None,
) -> int:
    """Склеить XML-фиды (уникальность по Id, последний побеждает)."""
    from xml.etree import ElementTree as ET

    skip = {normalize_article_id(x) for x in (skip_ids or set()) if str(x).strip()}
    skipped_n = 0
    by_id: dict[str, dict[str, Any]] = {}
    orphan: list[dict[str, Any]] = []
    for path in sources:
        p = Path(path)
        if not p.is_file():
            continue
        if p.suffix.lower() == ".xml":
            try:
                tree = ET.parse(p)
            except ET.ParseError:
                continue
            for ad in tree.getroot().findall("Ad"):
                row: dict[str, Any] = {}
                lid = ""
                for child in list(ad):
                    tag = child.tag
                    if tag == "Images":
                        urls = [
                            (img.get("url") or "").strip()
                            for img in child.findall("Image")
                            if (img.get("url") or "").strip()
                        ]
                        if urls:
                            row["Ссылки на фото"] = " | ".join(urls)
                        continue
                    text = (child.text or "").strip()
                    if not text:
                        continue
                    # обратный map минимальный — write_ads_xml понимает английские через aliases?
                    # Проще: передаём английские теги как ключи, если _HEADER_TO_TAG их знает
                    row[tag] = text
                    if tag == "Id":
                        lid = normalize_article_id(text)
                # write_ads_xml/_row_to_tags ожидает русские ИЛИ ключи из _HEADER_TO_TAG
                # Английские теги не в _HEADER_TO_TAG как ключи (кроме MultiItem/MultiName/AvitoId)
                # Переложим в русские через обратный словарь:
                row = _english_tags_to_russian(row)
                if lid and lid in skip:
                    skipped_n += 1
                    continue
                if not _row_has_brand_and_model(row):
                    skipped_n += 1
                    continue
                if lid:
                    by_id[lid] = row
                else:
                    orphan.append(row)
        else:
            from avito.autoload_xml import rows_from_xlsx

            for row in rows_from_xlsx(p):
                lid = normalize_article_id(
                    row.get("Уникальный идентификатор объявления")
                )
                if lid and lid in skip:
                    skipped_n += 1
                    continue
                if not _row_has_brand_and_model(row):
                    skipped_n += 1
                    continue
                if lid:
                    by_id[lid] = row
                else:
                    orphan.append(row)
    if skipped_n:
        LOG.info("merge XML: пропущено skip_ids=%s", skipped_n)
    rows = list(by_id.values()) + orphan
    return write_ads_xml(rows, output_path)


_TAG_TO_RU: dict[str, str] = {
    "Id": "Уникальный идентификатор объявления",
    "AvitoId": "Номер объявления на Авито",
    "ListingFee": "Способ размещения",
    "ManagerName": "Контактное лицо",
    "ContactPhone": "Номер телефона",
    "Address": "Адрес",
    "ContactMethod": "Способ связи",
    "Category": "Категория",
    "Description": "Описание объявления",
    "Title": "Название объявления",
    "Price": "Цена",
    "FreeTireFitting": "Бесплатный шиномонтаж",
    "GoodsType": "Вид товара",
    "AdType": "Вид объявления",
    "ProductType": "Тип товара",
    "MultiItem": "Соединять это объявление с другими объявлениями",
    "MultiName": "Название мультиобъявления",
    "Brand": "Производитель",
    "Model": "Модель",
    "TireSectionWidth": "Ширина профиля",
    "TireAspectRatio": "Высота профиля",
    "RimDiameter": "Диаметр",
    "TireType": "Сезонность",
    "LoadIndex": "Индекс нагрузки",
    "Quantity": "Количество",
    "SpeedIndex": "Индекс скорости",
    "RunFlat": "Run Flat",
    "Condition": "Состояние",
    "Audience": "Целевая аудитория",
    "Email": "Почта",
    "CompanyName": "Название компании",
    # Диски (formatVersion=3)
    "RimType": "Тип диска",
    "RimBrand": "Производитель диска",
    "RimModel": "Модель диска",
    "RimWidth": "Ширина обода",
    "RimBolts": "Количество отверстий",
    "RimBoltsDiameter": "Диаметр расположения отверстий",
    "RimOffset": "Вылет (ET)",
    "RimDIA": "Центральное отверстие (DIA)",
}


def _row_has_brand_and_model(row: dict[str, Any]) -> bool:
    """Шины: Производитель/Модель; диски: Производитель диска/Модель диска."""
    brand = (
        str(row.get("Производитель") or "").strip()
        or str(row.get("Производитель диска") or "").strip()
        or str(row.get("RimBrand") or "").strip()
    )
    model = (
        str(row.get("Модель") or "").strip()
        or str(row.get("Модель диска") or "").strip()
        or str(row.get("RimModel") or "").strip()
    )
    return bool(brand and model)


def _english_tags_to_russian(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k == "Ссылки на фото":
            out[k] = v
            continue
        ru = _TAG_TO_RU.get(k, k)
        out[ru] = v
    return out
