#!/usr/bin/env python3
"""Публикует XML-фид Avito (new + photo_updates) и запускает upload через API."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from avito.autoload import (  # noqa: E402
    avito_ids_for_posting,
    load_avito_ids,
    normalize_article_id,
    save_avito_ids_csv,
)
from avito.autoload_xml import count_ads_in_xml, write_ads_xml  # noqa: E402
from avito.build_listings import (  # noqa: E402
    listing_to_feed_row,
    merge_listing_xml_feeds,
)
from avito.avito_api import (  # noqa: E402
    AvitoApiClient,
    DEFAULT_AUTOLOAD_SCHEDULE,
    get_autoload_profile,
    get_last_successful_upload,
    load_avito_api_config,
    trigger_autoload_upload,
    update_autoload_profile,
)
from avito.config import load_config, load_merged_yaml  # noqa: E402
from avito.db import load_secrets  # noqa: E402
from avito.feed_skip import (  # noqa: E402
    default_skip_meta_path,
    default_skip_path,
    harvest_failed_ad_ids,
    load_skip_ids,
    merge_skip_ids,
    save_skip_meta,
)
from avito.sync_listings import (  # noqa: E402
    build_oos_zero_stocks,
    build_sync_items,
    prune_avito_ids_mapping,
    refresh_avito_ids_from_api,
    sync_listings,
)

LOG = logging.getLogger("publish_avito_feed")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Публикация фида Avito (файл + API upload)")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "--source",
        type=Path,
        default=None,
        help="исходный XML (по умолчанию new + photo_updates)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--no-profile", action="store_true")
    p.add_argument("--no-sync", action="store_true", help="Не обновлять цены/остатки через API")
    p.add_argument(
        "--no-harvest-skip",
        action="store_true",
        help="Не подмешивать error_* из последнего отчёта в skip_ids",
    )
    return p.parse_args()


def _load_publish_cfg(config_path: Path) -> dict:
    raw = load_merged_yaml(config_path)
    return dict(raw.get("avito_publish") or {})


def _resolve_report_email(profile: dict, pub: dict) -> str:
    return str(profile.get("report_email") or pub.get("report_email") or "").strip()


def _resolve_schedule(profile: dict, pub: dict) -> list[dict]:
    sched = profile.get("schedule") or pub.get("schedule")
    if sched:
        return list(sched)
    return list(DEFAULT_AUTOLOAD_SCHEDULE)


def _resolve_feed_path(config_parent: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    if not path.is_absolute():
        path = config_parent / path
    return path


def _xml_sibling(path: Path | None) -> Path | None:
    if path is None:
        return None
    if path.suffix.lower() == ".xml":
        return path
    return path.with_suffix(".xml")


def _count_ads(path: Path | None) -> int:
    if not path or not path.is_file():
        return 0
    if path.suffix.lower() == ".xml":
        return count_ads_in_xml(path)
    LOG.warning("Пропуск не-XML фида: %s", path)
    return 0


def _collect_publish_sources(app, config_path: Path) -> tuple[list[Path], int, int]:
    """Новые + обновления фото (XML; fallback — listings SQLite)."""
    parent = config_path.parent
    new_cfg = _resolve_feed_path(parent, app.autoload.new_listings_feed)
    photo_cfg = _resolve_feed_path(parent, app.autoload.photo_updates_feed)

    new_path = None
    for candidate in (_xml_sibling(new_cfg), new_cfg):
        if candidate and candidate.is_file() and candidate.suffix.lower() == ".xml":
            new_path = candidate
            break
    photo_path = None
    for candidate in (_xml_sibling(photo_cfg), photo_cfg):
        if candidate and candidate.is_file() and candidate.suffix.lower() == ".xml":
            photo_path = candidate
            break

    new_count = _count_ads(new_path)
    photo_count = _count_ads(photo_path)
    sources: list[Path] = []
    if new_count > 0 and new_path:
        sources.append(new_path)
    if photo_count > 0 and photo_path:
        sources.append(photo_path)

    # Fallback: listings в SQLite, если XML пусты
    if not sources:
        try:
            from avito.stock_db import load_listings, stock_connection

            db_path = ROOT / "data" / "avito_stock.db"
            schema = ROOT / "sql" / "avito_stock_sqlite.sql"
            if hasattr(app, "stock_db") and app.stock_db:
                db_path = app.stock_db.path
                if not db_path.is_absolute():
                    db_path = parent / db_path
                schema = app.stock_db.schema_sql
                if not schema.is_absolute():
                    schema = parent / schema
            if db_path.is_file():
                with stock_connection(db_path, schema_path=schema) as conn:
                    rows = [r for r in load_listings(conn, in_feed_only=True) if r.photo_urls]
                new_rows = [r for r in rows if not r.avito_id]
                photo_rows = [
                    r
                    for r in rows
                    if r.avito_id
                    and (
                        "shinaufa.ru" in (r.photo_urls or "")
                        or "avito.shinaufa.ru/photos" in (r.photo_urls or "")
                    )
                ]
                tmp_dir = parent / "input"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                if new_rows:
                    new_xml = tmp_dir / "autoload_new.xml"
                    write_ads_xml([listing_to_feed_row(r) for r in new_rows], new_xml)
                    sources.append(new_xml)
                    new_count = len(new_rows)
                if photo_rows:
                    photo_xml = tmp_dir / "autoload_photo_updates.xml"
                    write_ads_xml([listing_to_feed_row(r) for r in photo_rows], photo_xml)
                    sources.append(photo_xml)
                    photo_count = len(photo_rows)
                if sources:
                    LOG.info(
                        "Фид из listings SQLite: new=%s photo=%s",
                        new_count,
                        photo_count,
                    )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("listings fallback: %s", exc)

    return sources, new_count, photo_count


def _listing_ids_from_feed(path: Path) -> list[str]:
    if not path.is_file() or path.suffix.lower() != ".xml":
        return []
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []
    out: list[str] = []
    for ad in tree.getroot().findall("Ad"):
        node = ad.find("Id")
        if node is None or not (node.text or "").strip():
            continue
        listing_id = normalize_article_id(node.text)
        if listing_id and "_" in listing_id:
            out.append(listing_id)
    return out


def _load_posting_df(app, config_path: Path):
    """Posting только из SQLite. Пустой posting — ошибка (без Excel fallback)."""
    from avito.stock_db import load_posting_dataframe, stock_connection

    db_path = ROOT / "data" / "avito_stock.db"
    schema = ROOT / "sql" / "avito_stock_sqlite.sql"
    if hasattr(app, "stock_db") and app.stock_db:
        db_path = app.stock_db.path
        if not db_path.is_absolute():
            db_path = config_path.parent / db_path
        schema = app.stock_db.schema_sql
        if not schema.is_absolute():
            schema = config_path.parent / schema
    if not db_path.is_file():
        raise FileNotFoundError(
            f"Нет SQLite posting: {db_path}. Сначала: python compare_prices.py"
        )
    with stock_connection(db_path, schema_path=schema) as conn:
        df = load_posting_dataframe(conn)
    if df is None or df.empty:
        raise RuntimeError(
            "posting_items пуст в SQLite — сначала: python compare_prices.py "
            "(Excel posting_*.xlsx fallback удалён)"
        )
    LOG.info("Posting: sqlite posting_items (%s строк)", len(df))
    return df


def _run_api_sync(app, config_path: Path, *, dry_run: bool) -> int:
    sync_cfg = app.avito_sync
    if not sync_cfg.enabled:
        LOG.info("avito_sync.enabled=false — пропуск API-синхронизации")
        return 0

    posting_df = _load_posting_df(app, config_path)

    avito_ids_path = ROOT / app.autoload.avito_ids_file
    ids_from_csv = load_avito_ids(avito_ids_path, app.stores) if avito_ids_path.exists() else {}
    # listings SQLite (+ CSV)
    db_path = ROOT / "data" / "avito_stock.db"
    schema = ROOT / "sql" / "avito_stock_sqlite.sql"
    if hasattr(app, "stock_db") and app.stock_db:
        db_path = app.stock_db.path
        if not db_path.is_absolute():
            db_path = config_path.parent / db_path
        schema = app.stock_db.schema_sql
        if not schema.is_absolute():
            schema = config_path.parent / schema
    manuals: dict[str, float] = {}
    try:
        from avito.stock_db import (
            load_avito_ids_map,
            load_listings,
            load_manual_prices_map,
            stock_connection,
        )

        with stock_connection(db_path, schema_path=schema) as conn:
            ids_from_csv = {**ids_from_csv, **load_avito_ids_map(conn)}
            manuals = load_manual_prices_map(conn)
            for row in load_listings(conn):
                if row.avito_id:
                    ids_from_csv[row.listing_id] = row.avito_id
    except Exception as exc:  # noqa: BLE001
        LOG.warning("listings avito_ids: %s", exc)

    avito_ids = avito_ids_for_posting(
        posting_df,
        app.stores,
        ids_from_csv=ids_from_csv,
    )
    skip_ids = load_skip_ids(default_skip_path(ROOT))
    items = build_sync_items(
        posting_df,
        app.stores,
        avito_ids,
        max_listing_quantity=app.autoload.max_listing_quantity,
        manual_prices=manuals,
    )
    if skip_ids:
        before = len(items)
        items = [it for it in items if it.listing_id not in skip_ids]
        dropped = before - len(items)
        if dropped:
            LOG.info("API sync: skip_ids исключили %s позиций (цена/остаток)", dropped)
    oos_payload: list[dict] = []
    close_oos = bool(getattr(sync_cfg, "close_oos", True))
    if close_oos:
        oos_payload = build_oos_zero_stocks(posting_df, app.stores, avito_ids)
        if skip_ids:
            oos_payload = [
                row
                for row in oos_payload
                if str(row.get("external_id") or "") not in skip_ids
            ]
        LOG.info(
            "OOS: снять с витрины (qty=0) %s объявлений вне posting",
            len(oos_payload),
        )

    if not items and not oos_payload:
        LOG.info("Нет объявлений для API-синхронизации")
        return 0

    from avito.stock_db import (
        load_sync_state_map,
        mark_sync_prices,
        mark_sync_qtys,
        seed_sync_state_price_qty,
        stock_connection,
        sync_state_count,
    )

    state_map = None
    force_full = bool(getattr(sync_cfg, "force_full_sync", False))
    diff_only = bool(getattr(sync_cfg, "diff_only", True))
    seed_on_empty = bool(getattr(sync_cfg, "seed_on_empty", True))

    if diff_only and db_path.is_file():
        with stock_connection(db_path, schema_path=schema) as conn:
            n_state = sync_state_count(conn)
            if n_state == 0 and seed_on_empty and not force_full:
                seed_rows: list[tuple[str, str, str, int, int]] = [
                    (
                        str(it.avito_id),
                        it.listing_id,
                        it.article,
                        int(it.price),
                        int(it.quantity),
                    )
                    for it in items
                ]
                for row in oos_payload:
                    seed_rows.append(
                        (
                            str(row["item_id"]),
                            str(row.get("external_id") or ""),
                            "",
                            0,
                            0,
                        )
                    )
                seeded = seed_sync_state_price_qty(conn, seed_rows)
                LOG.info(
                    "avito_sync_state: seed %s строк (текущие price/qty = already-sent; "
                    "первый прогон без blast). Для полного синка: avito_sync.force_full_sync=true",
                    seeded,
                )
                return 0
            state_map = load_sync_state_map(conn) if n_state else None
            LOG.info("avito_sync_state: загружено %s записей (diff_only=%s)", n_state, diff_only)

    LOG.info(
        "API: цена/остаток для %s размещённых + OOS zero %s (force_full=%s)",
        len(items),
        len(oos_payload),
        force_full,
    )
    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = config_path.parent / secrets_path
    client = AvitoApiClient(load_avito_api_config(load_secrets(secrets_path)))
    stats, price_ok, qty_ok = sync_listings(
        client,
        items,
        dry_run=dry_run or sync_cfg.dry_run,
        stock_batch_size=sync_cfg.stock_batch_size,
        price_pause_sec=sync_cfg.price_pause_sec,
        oos_zero_stocks=oos_payload,
        state_map=state_map if diff_only else None,
        diff_prices=diff_only,
        diff_stocks=diff_only,
        force_full_sync=force_full,
        price_max_retries=int(getattr(sync_cfg, "price_max_retries", 4)),
    )
    LOG.info(
        "API sync: цены ok=%s skip=%s fail=%s | остатки ok=%s skip=%s fail=%s | "
        "oos zero ok=%s skip=%s fail=%s",
        stats.prices_updated,
        stats.prices_skipped,
        stats.prices_failed,
        stats.stocks_updated,
        stats.stocks_skipped,
        stats.stocks_failed,
        stats.oos_zeroed,
        stats.oos_skipped,
        stats.oos_failed,
    )
    for err in stats.errors[:10]:
        LOG.warning("%s", err)

    if (price_ok or qty_ok) and not (dry_run or sync_cfg.dry_run) and db_path.is_file():
        try:
            with stock_connection(db_path, schema_path=schema) as conn:
                if price_ok:
                    mark_sync_prices(conn, price_ok)
                if qty_ok:
                    mark_sync_qtys(conn, qty_ok)
            LOG.info(
                "avito_sync_state: записано price=%s qty=%s",
                len(price_ok),
                len(qty_ok),
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("avito_sync_state write: %s", exc)

    if stats.deleted_avito_ids:
        existing = load_avito_ids(avito_ids_path, app.stores) if avito_ids_path.exists() else {}
        pruned, removed_n = prune_avito_ids_mapping(existing, stats.deleted_avito_ids)
        if removed_n:
            save_avito_ids_csv(avito_ids_path, pruned)
            LOG.info(
                "avito_ids: удалены мёртвые Id %s (записей ключей: %s)",
                sorted(stats.deleted_avito_ids),
                removed_n,
            )
            try:
                from avito.stock_db import replace_avito_ids, stock_connection

                if db_path.is_file():
                    with stock_connection(db_path, schema_path=schema) as conn:
                        replace_avito_ids(conn, pruned)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("sqlite avito_ids prune: %s", exc)

    if stats.prices_failed or stats.stocks_failed or stats.oos_failed:
        LOG.warning(
            "API sync: частичные ошибки (цены fail=%s, остатки fail=%s, oos fail=%s) — пайплайн не останавливаем",
            stats.prices_failed,
            stats.stocks_failed,
            stats.oos_failed,
        )
    return 0


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    pub = _load_publish_cfg(args.config)
    if not pub.get("enabled", False) and not args.dry_run:
        LOG.error(
            "avito_publish.enabled=false (проверьте config.yaml и config.local.yaml)"
        )
        return 1

    feed_url = str(pub.get("feed_public_url", "")).strip()
    feed_name = str(pub.get("feed_name", "shinaufa")).strip()
    feed_dir = Path(str(pub.get("feed_local_dir", "/var/www/avito-feed/feeds")))
    if not feed_url:
        LOG.error("Задайте avito_publish.feed_public_url")
        return 1

    app = load_config(args.config)
    new_feed_for_ids: Path | None = None
    if args.source is not None:
        source = args.source
        if not source.is_absolute():
            source = args.config.parent / source
        if not source.is_file():
            LOG.error("Нет файла фида: %s", source)
            return 1
        publish_sources = [source]
        new_count = _count_ads(source)
        photo_count = 0
        new_feed_for_ids = source
    else:
        publish_sources, new_count, photo_count = _collect_publish_sources(
            app, args.config
        )
        new_path = _resolve_feed_path(
            args.config.parent, app.autoload.new_listings_feed
        )
        new_xml = _xml_sibling(new_path)
        if new_xml and new_xml.is_file():
            new_feed_for_ids = new_xml
        elif new_path and new_path.is_file():
            new_feed_for_ids = new_path
        if not publish_sources:
            LOG.error(
                "Нет файлов для публикации (сначала build_autoload.py: "
                "autoload_new.xml / autoload_photo_updates.xml)"
            )
            return 1

    if args.dry_run:
        LOG.info(
            "dry-run: новых=%s, обновление фото=%s → %s",
            new_count,
            photo_count,
            feed_url,
        )
        return 0

    sync_rc = 0
    if not args.no_sync:
        sync_rc = _run_api_sync(app, args.config, dry_run=False)

    if new_count == 0 and photo_count == 0:
        LOG.info(
            "Новых объявлений и обновлений фото нет — upload пропущен (дубли не создаём)"
        )
        return sync_rc

    feed_name_from_url = Path(urlparse(feed_url).path).name
    feed_filename = str(pub.get("feed_filename") or "").strip() or feed_name_from_url or "autoload.xml"
    if not feed_filename.lower().endswith(".xml"):
        feed_filename = "autoload.xml"
    target = feed_dir / feed_filename
    feed_dir.mkdir(parents=True, exist_ok=True)
    skip_path = default_skip_path(ROOT)
    skip_ids = load_skip_ids(skip_path)
    if skip_ids:
        LOG.info("feed_skip: %s Id из %s", len(skip_ids), skip_path)
    # Пишем во временный файл — пустой merge не затирает публичный фид
    tmp_target = target.with_suffix(target.suffix + ".tmp")
    row_count = merge_listing_xml_feeds(
        publish_sources, tmp_target, skip_ids=skip_ids
    )
    LOG.info(
        "XML-фид: новых=%s, обновление фото=%s, всего=%s объявлений → %s",
        new_count,
        photo_count,
        row_count,
        target,
    )
    if row_count <= 0:
        if tmp_target.is_file():
            tmp_target.unlink(missing_ok=True)
        LOG.info(
            "После skip_ids фид пуст — публичный XML не трогаем, upload пропущен"
        )
        return sync_rc
    tmp_target.replace(target)
    LOG.info("Записано (%s байт)", target.stat().st_size)

    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = args.config.parent / secrets_path
    client = AvitoApiClient(load_avito_api_config(load_secrets(secrets_path)))

    # Подтянуть свежие ошибки в skip до upload — не слать те же fail каждые 3ч.
    # Один и тот же upload_id не харвестим повторно (иначе clear после фикса справочника
    # снова затрётся старым отчётом до появления нового upload).
    if not args.no_harvest_skip:
        try:
            meta_path = default_skip_meta_path(ROOT)
            harvested, hid = harvest_failed_ad_ids(client, meta_path=meta_path)
            if harvested:
                skip_ids, added = merge_skip_ids(skip_path, harvested)
                if added:
                    LOG.info(
                        "feed_skip: +%s Id из отчёта upload_id=%s (всего %s)",
                        added,
                        hid,
                        len(skip_ids),
                    )
                    row_count2 = merge_listing_xml_feeds(
                        publish_sources, tmp_target, skip_ids=skip_ids
                    )
                    if row_count2 > 0:
                        tmp_target.replace(target)
                        row_count = row_count2
                        LOG.info(
                            "XML-фид пересобран с учётом skip: %s объявлений → %s",
                            row_count,
                            target,
                        )
                    else:
                        if tmp_target.is_file():
                            tmp_target.unlink(missing_ok=True)
                        LOG.info(
                            "После harvest skip фид пуст — оставляем предыдущий XML (%s)",
                            row_count,
                        )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("feed_skip harvest: %s", exc)
    else:
        LOG.info("feed_skip harvest: пропуск (--no-harvest-skip)")
        # Пометить текущий last upload как уже учтённый, чтобы следующий timer
        # не вернул старые fail Id после ручного clear.
        try:
            last = get_last_successful_upload(client)
            rid = last.get("upload_id") or last.get("report_id")
            if rid:
                meta_path = default_skip_meta_path(ROOT)
                save_skip_meta(meta_path, {"last_harvest_upload_id": int(rid)})
                LOG.info(
                    "feed_skip meta: last_harvest_upload_id=%s (старый отчёт не вернём)",
                    rid,
                )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("feed_skip meta: %s", exc)

    if row_count <= 0:
        LOG.info("После skip_ids фид пуст — upload пропущен")
        return sync_rc

    profile = get_autoload_profile(client)
    report_email = _resolve_report_email(profile, pub)
    schedule = _resolve_schedule(profile, pub)
    feeds = profile.get("feeds_data") or []
    need_profile = not feeds or not any(
        str(f.get("feed_url", "")).strip() == feed_url for f in feeds if isinstance(f, dict)
    )

    if need_profile and not args.no_profile and pub.get("auto_set_profile", True):
        if not report_email:
            LOG.error(
                "Нет report_email — добавьте в config.local.yaml:\n"
                "  avito_publish:\n"
                "    report_email: ваш@email.ru"
            )
            LOG.warning("Пропускаем обновление профиля (фид на сервере уже скопирован)")
        else:
            LOG.info("Обновляем профиль автозагрузки → %s", feed_url)
            try:
                update_autoload_profile(
                    client,
                    feed_name=feed_name,
                    feed_url=feed_url,
                    report_email=report_email,
                    schedule=schedule,
                )
            except (RuntimeError, ValueError) as exc:
                LOG.error("Профиль не обновлён: %s", exc)
                LOG.warning(
                    "Фид уже на %s — можно задать URL вручную в ЛК Авито "
                    "или исправить report_email/schedule",
                    feed_url,
                )
    elif need_profile:
        LOG.warning("feeds_data пустой — включите auto_set_profile или настройте URL в ЛК")

    if not args.no_upload and pub.get("auto_upload", True):
        LOG.info("Запуск upload (новые + обновление фото)…")
        try:
            trigger_autoload_upload(client)
            LOG.info("upload принят Avito")
        except RuntimeError as exc:
            if "429" in str(exc) or "час" in str(exc).lower():
                LOG.warning("%s (лимит 1 раз/час — нормально)", exc)
            else:
                raise
        try:
            last = get_last_successful_upload(client)
            if last:
                LOG.info(
                    "Последняя успешная загрузка:\n%s",
                    json.dumps(last, ensure_ascii=False, indent=2)[:2000],
                )
        except Exception as exc:
            LOG.warning("last_successful upload: %s", exc)

        if app.avito_sync.refresh_ids_after_publish and new_feed_for_ids:
            ad_ids = _listing_ids_from_feed(new_feed_for_ids)
            if ad_ids:
                avito_ids_path = ROOT / app.autoload.avito_ids_file
                existing = (
                    load_avito_ids(avito_ids_path, app.stores)
                    if avito_ids_path.exists()
                    else {}
                )
                merged = refresh_avito_ids_from_api(
                    client,
                    ad_ids,
                    existing=existing,
                    stores=app.stores,
                )
                new_ids_n = sum(1 for k in merged if k not in existing)
                if merged:
                    save_avito_ids_csv(avito_ids_path, merged)
                    LOG.info(
                        "avito_ids.csv: %s записей (новых с API: %s)",
                        len(merged),
                        new_ids_n,
                    )
                    try:
                        from avito.stock_db import replace_avito_ids, stock_connection

                        db_path = ROOT / "data" / "avito_stock.db"
                        schema = ROOT / "sql" / "avito_stock_sqlite.sql"
                        if db_path.is_file():
                            with stock_connection(db_path, schema_path=schema) as conn:
                                replace_avito_ids(conn, merged)
                    except Exception as exc:  # noqa: BLE001
                        LOG.warning("sqlite avito_ids refresh: %s", exc)

    return sync_rc


if __name__ == "__main__":
    raise SystemExit(main())
