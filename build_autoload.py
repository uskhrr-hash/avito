#!/usr/bin/env python3
"""posting (SQLite) → listings → XML-фиды автозагрузки Avito."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from avito.autoload import (
    avito_ids_for_posting,
    load_avito_ids,
    resolve_photos_folder,
    save_avito_ids_csv,
)
from avito.build_listings import build_listings_from_posting, write_listing_feeds
from avito.photo_convert import compress_folder_photos, convert_folder_to_jpeg
from avito.config import load_config
from avito.model_descriptions import resolve_model_descriptions

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("build_autoload")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Сборка автозагрузки Avito (listings → XML)")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("-o", "--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--date", default=None)
    p.add_argument(
        "--write-avito-ids",
        action="store_true",
        help="Сохранить номера объявлений в SQLite (+ дубль CSV)",
    )
    return p.parse_args()


def _feed_xml_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    path = Path(path)
    if path.suffix.lower() != ".xml":
        return path.with_suffix(".xml")
    return path


def _norm_id(value: object) -> str:
    return str(value or "").strip()


def _is_wheel_row(row, product_type: str) -> bool:
    pt = _norm_id(getattr(row, "product_type", "") or "")
    return pt == product_type or pt == "Диски"


def _gate_wheel_publish_rows(rows: list, wheels_cfg) -> tuple[list, int]:
    """Keep all tires; apply publish_ids / include_in_publish / publish_limit to wheels."""
    allow = {_norm_id(x) for x in (getattr(wheels_cfg, "publish_ids", ()) or ()) if _norm_id(x)}
    include_all = bool(getattr(wheels_cfg, "include_in_publish", False))
    limit = getattr(wheels_cfg, "publish_limit", None)
    product_type = _norm_id(getattr(wheels_cfg, "product_type", "Диски") or "Диски") or "Диски"

    out: list = []
    wheels_kept = 0
    for row in rows:
        if not _is_wheel_row(row, product_type):
            out.append(row)
            continue
        lid = _norm_id(getattr(row, "listing_id", ""))
        art = _norm_id(getattr(row, "article_id", ""))
        if allow:
            if lid not in allow and art not in allow:
                continue
        elif not include_all:
            continue
        if limit is not None and wheels_kept >= int(limit):
            continue
        out.append(row)
        wheels_kept += 1
    return out, wheels_kept


def _prepare_photos(app_cfg, cfg, stores) -> None:
    photos_folder = resolve_photos_folder(cfg, ROOT)
    if photos_folder and cfg.manager_inbox_subdir:
        from avito.manager_inbox import import_manager_inbox, resolve_inbox_folder

        inbox = resolve_inbox_folder(photos_folder, cfg.manager_inbox_subdir)
        if inbox:
            inbox.mkdir(parents=True, exist_ok=True)
            imp = import_manager_inbox(
                inbox,
                photos_folder,
                store_prefixes=stores.prefixes,
                jpeg_quality=cfg.jpeg_quality,
                photo_layout=cfg.photo_layout,
                prefix_in_filename=cfg.photo_store_prefix_in_filename,
            )
            if imp.imported:
                LOG.info("Входящие фото: импортировано %s", imp.imported)

    if photos_folder and cfg.convert_photos_to_jpeg:
        conv = convert_folder_to_jpeg(
            photos_folder,
            quality=cfg.jpeg_quality,
            max_dimension=cfg.jpeg_max_dimension if cfg.compress_photos else 0,
        )
        if conv.converted or conv.skipped or conv.errors:
            LOG.info(
                "HEIC/WebP → JPEG: сконвертировано %s, актуальный jpg уже был %s, ошибок %s",
                conv.converted,
                conv.skipped,
                len(conv.errors),
            )
    if photos_folder and cfg.compress_photos:
        comp = compress_folder_photos(
            photos_folder,
            quality=cfg.jpeg_quality,
            max_dimension=cfg.jpeg_max_dimension,
            min_bytes=cfg.compress_min_kb * 1024,
        )
        if comp.compressed or comp.saved_bytes or comp.errors:
            LOG.info(
                "Сжатие фото: обработано %s, пропущено %s, сэкономлено ~%s MB, ошибок %s",
                comp.compressed,
                comp.skipped,
                round(comp.saved_bytes / (1024 * 1024), 1),
                len(comp.errors),
            )


def _should_full_ids_refresh(sync_cfg, conn) -> tuple[bool, str]:
    """Полный refresh AvitoId ≤1×/сутки (или force). Missing/new — всегда отдельно."""
    from datetime import datetime, timedelta, timezone
    from avito.stock_db import get_meta

    if bool(getattr(sync_cfg, "force_full_ids_refresh", False)):
        return True, "force_full_ids_refresh"
    if not bool(getattr(sync_cfg, "full_ids_refresh", True)):
        return False, "full_ids_refresh=false"

    raw = get_meta(conn, "avito_ids_full_refresh_at", "")
    if not raw:
        return True, "never_refreshed"
    try:
        # store UTC ISO
        last = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except ValueError:
        return True, "bad_meta_timestamp"

    min_hours = max(1, int(getattr(sync_cfg, "full_ids_min_interval_hours", 24)))
    now = datetime.now(timezone.utc)
    if now - last < timedelta(hours=min_hours):
        return False, f"interval<{min_hours}h"

    # Опционально: не раньше full_ids_daily_hour по локальной TZ пайплайна
    try:
        from zoneinfo import ZoneInfo

        local = now.astimezone(ZoneInfo("Asia/Yekaterinburg"))
    except Exception:  # noqa: BLE001
        local = now
    hour = int(getattr(sync_cfg, "full_ids_daily_hour", 3))
    if local.hour < hour and (now - last) < timedelta(hours=min_hours + 6):
        return False, f"before_daily_hour={hour}"
    return True, "due"


def _missing_ad_ids(ad_ids: list[str], existing: dict[str, str]) -> list[str]:
    out: list[str] = []
    for ad_id in ad_ids:
        key = str(ad_id or "").strip()
        if not key:
            continue
        if not str(existing.get(key) or "").strip():
            out.append(key)
    return out


def _refresh_avito_ids_api(app_cfg, stores, posting_df, existing: dict[str, str]) -> dict[str, str]:
    """JSON API: GET /autoload/v2/items/avito_ids (+ опционально отчёт)."""
    from avito.avito_api import AvitoApiClient, load_avito_api_config
    from avito.db import load_secrets
    from avito.stock_db import load_listings, set_meta, stock_connection
    from avito.sync_listings import collect_ad_ids_for_api, refresh_avito_ids_from_api

    secrets_path = app_cfg.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = ROOT / secrets_path
    if not secrets_path.is_file():
        raise FileNotFoundError(f"нет secrets: {secrets_path}")

    listing_ids: list[str] = []
    missing_listing_ids: list[str] = []
    try:
        with stock_connection(
            app_cfg.stock_db.path, schema_path=app_cfg.stock_db.schema_sql
        ) as conn:
            rows = list(load_listings(conn))
            listing_ids = [r.listing_id for r in rows if r.listing_id]
            missing_listing_ids = [
                r.listing_id
                for r in rows
                if r.listing_id and not str(r.avito_id or "").strip()
            ]
            do_full, reason = _should_full_ids_refresh(app_cfg.avito_sync, conn)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("listings для avito_ids API: %s", exc)
        do_full, reason = True, f"fallback:{exc}"

    ad_ids = collect_ad_ids_for_api(
        posting_df,
        stores,
        extra_keys=list(existing.keys()),
        listing_ids=listing_ids,
    )
    client = AvitoApiClient(load_avito_api_config(load_secrets(secrets_path)))

    if do_full:
        query_ids = ad_ids
        LOG.info(
            "AvitoId refresh: FULL %s Id (reason=%s)",
            len(query_ids),
            reason,
        )
        merged = refresh_avito_ids_from_api(
            client,
            query_ids,
            existing=existing,
            stores=stores,
            include_report=True,
        )
        try:
            from datetime import datetime, timezone

            with stock_connection(
                app_cfg.stock_db.path, schema_path=app_cfg.stock_db.schema_sql
            ) as conn:
                set_meta(
                    conn,
                    "avito_ids_full_refresh_at",
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                set_meta(conn, "avito_ids_full_refresh_count", str(len(query_ids)))
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("avito_ids_full_refresh_at meta: %s", exc)
        return merged

    # Missing/new: только listings без AvitoId (+ пустые ключи existing).
    # Не гоняем весь posting-universe без объявлений.
    query_set: set[str] = set(missing_listing_ids)
    query_set.update(_missing_ad_ids(list(existing.keys()), existing))
    query_ids = sorted(x for x in query_set if x)
    LOG.info(
        "AvitoId refresh: MISSING/NEW only %s Id (full skipped: %s; universe=%s)",
        len(query_ids),
        reason,
        len(ad_ids),
    )
    if not query_ids:
        return dict(existing)
    return refresh_avito_ids_from_api(
        client,
        query_ids,
        existing=existing,
        stores=stores,
        include_report=False,
    )


def _load_avito_ids(app_cfg, cfg, stores, posting_df):
    from avito.stock_db import load_avito_ids_map, replace_avito_ids, stock_connection

    avito_ids_path = ROOT / cfg.avito_ids_file
    with stock_connection(
        app_cfg.stock_db.path, schema_path=app_cfg.stock_db.schema_sql
    ) as conn:
        ids_from_db = load_avito_ids_map(conn, stores)
        try:
            from avito.stock_db import load_listings

            for row in load_listings(conn):
                if row.avito_id:
                    ids_from_db[row.listing_id] = row.avito_id
        except Exception:  # noqa: BLE001
            pass
    ids_from_csv = (
        load_avito_ids(avito_ids_path, stores) if avito_ids_path.exists() else {}
    )
    avito_ids = avito_ids_for_posting(
        posting_df,
        stores,
        ids_from_xlsx=None,
        titles_from_xlsx=None,
        ids_from_csv={**ids_from_csv, **ids_from_db},
    )
    before = len(avito_ids)
    try:
        avito_ids = _refresh_avito_ids_api(app_cfg, stores, posting_df, avito_ids)
        LOG.info("AvitoId API: было %s ключей → %s", before, len(avito_ids))
    except Exception as exc:  # noqa: BLE001
        LOG.warning("AvitoId API недоступен, оставляем db/csv: %s", exc)
    if avito_ids:
        LOG.info(
            "AvitoId: db=%s csv=%s итого ключей=%s",
            len(ids_from_db),
            len(ids_from_csv),
            len(avito_ids),
        )
        with stock_connection(
            app_cfg.stock_db.path, schema_path=app_cfg.stock_db.schema_sql
        ) as conn:
            n = replace_avito_ids(conn, avito_ids)
        LOG.info("avito_ids → sqlite: %s ключей", n)
    return avito_ids, avito_ids_path


def main() -> int:
    from avito.stock_db import (
        load_posting_dataframe,
        replace_missing_models,
        stock_connection,
    )

    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    app_cfg = load_config(args.config)
    cfg = app_cfg.autoload
    stores = app_cfg.stores

    try:
        with stock_connection(
            app_cfg.stock_db.path, schema_path=app_cfg.stock_db.schema_sql
        ) as conn:
            posting_df = load_posting_dataframe(conn)
    except Exception as exc:  # noqa: BLE001
        LOG.error("Не удалось прочитать posting из БД: %s", exc)
        return 1
    if posting_df.empty:
        LOG.error("Нет posting в БД — сначала: python compare_prices.py")
        return 1

    LOG.info("AvitoId: JSON API + sqlite/csv (cabinet Excel не используется)")
    avito_ids, avito_ids_path = _load_avito_ids(app_cfg, cfg, stores, posting_df)
    if args.write_avito_ids and avito_ids:
        n_csv = save_avito_ids_csv(avito_ids_path, avito_ids)
        LOG.info("Дубль CSV: %s → %s", n_csv, avito_ids_path)

    secrets_path = app_cfg.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = ROOT / secrets_path
    model_descriptions = resolve_model_descriptions(
        descriptions_db_enabled=app_cfg.descriptions_db.enabled,
        secrets_path=secrets_path,
        pg_schema=app_cfg.descriptions_db.pg_schema,
        project_root=ROOT,
    )
    if app_cfg.descriptions_db.enabled:
        LOG.info("Описания моделей: из БД %s ключей", len(model_descriptions))

    if cfg.verify_photos_on_disk and not cfg.photos_local_dir:
        LOG.warning(
            "verify_photos_on_disk включён, но photos_local_dir не задан — "
            "фото не проверяются"
        )
    elif cfg.verify_photos_on_disk:
        probe = ROOT / cfg.photos_local_dir
        if cfg.photos_local_dir and cfg.photos_local_dir.is_absolute():
            probe = cfg.photos_local_dir
        if not probe.is_dir():
            LOG.warning("Папка фото не найдена: %s", probe)

    _prepare_photos(app_cfg, cfg, stores)

    with stock_connection(
        app_cfg.stock_db.path, schema_path=app_cfg.stock_db.schema_sql
    ) as conn:
        stats = build_listings_from_posting(
            conn=conn,
            posting_df=posting_df,
            cfg=cfg,
            stores=stores,
            model_descriptions=model_descriptions,
            avito_ids=avito_ids,
            project_root=ROOT,
            wheels_cfg=app_cfg.wheels,
        )
        if stats.get("missing_models"):
            replace_missing_models(conn, stats["missing_models"])

        # Avito autoload XML = FULL catalog replace (missing Ids → removed_from_file).
        # NEVER shrink photo_rows before write_listing_feeds / publish.
        # photo_updates_diff_only used to filter here and wiped ~2800 ads (2026-08-12).
        photo_rows = list(stats.get("photo_rows") or [])
        photo_skipped = 0
        sync_cfg = app_cfg.avito_sync
        if bool(getattr(sync_cfg, "photo_updates_diff_only", False)):
            LOG.warning(
                "avito_sync.photo_updates_diff_only ignored for XML feed "
                "(Avito full-replace). Keeping full photo_rows=%s in feed.",
                len(photo_rows),
            )
            # Optional: measure how many would have been delta-only (metrics only).
            try:
                from avito.build_listings import filter_photo_update_rows
                from avito.stock_db import (
                    load_sync_state_by_listing,
                    load_sync_state_map,
                )

                state_avito = load_sync_state_map(conn)
                state_lid = load_sync_state_by_listing(conn)
                _delta, photo_skipped, _seed_marks, _seeded = filter_photo_update_rows(
                    photo_rows,
                    state_avito,
                    state_lid,
                    force_full=True,  # do not seed/mark; full feed always
                    seed_on_empty=False,
                )
                LOG.info(
                    "photo_updates metrics: full=%s would_delta=%s skip=%s",
                    len(photo_rows),
                    len(_delta),
                    photo_skipped,
                )
            except Exception as exc:  # noqa: BLE001
                LOG.warning("photo_updates metrics: %s", exc)
            stats["photo_updates_count"] = len(photo_rows)
            stats["photo_updates_skipped"] = 0
        else:
            stats["photo_updates_count"] = len(photo_rows)
            stats["photo_updates_skipped"] = photo_skipped

    new_feed = _feed_xml_path(
        ROOT / cfg.new_listings_feed
        if cfg.new_listings_feed and not cfg.new_listings_feed.is_absolute()
        else cfg.new_listings_feed
    )
    photo_feed = _feed_xml_path(
        ROOT / cfg.photo_updates_feed
        if cfg.photo_updates_feed and not cfg.photo_updates_feed.is_absolute()
        else cfg.photo_updates_feed
    )
    new_rows, wheels_new = _gate_wheel_publish_rows(
        list(stats.get("new_rows") or []), app_cfg.wheels
    )
    photo_rows, wheels_photo = _gate_wheel_publish_rows(
        list(stats.get("photo_rows") or []), app_cfg.wheels
    )
    allow_ids = [
        str(x).strip()
        for x in (getattr(app_cfg.wheels, "publish_ids", ()) or ())
        if str(x).strip()
    ]
    if allow_ids:
        LOG.info(
            "Publish gate: wheels.publish_ids=%s → new_wheels=%s photo_wheels=%s "
            "(include_in_publish=%s)",
            allow_ids,
            wheels_new,
            wheels_photo,
            app_cfg.wheels.include_in_publish,
        )
    elif not app_cfg.wheels.include_in_publish:
        LOG.info(
            "Publish gate: wheels.include_in_publish=false → XML без дисков"
        )
    elif getattr(app_cfg.wheels, "publish_limit", None) is not None:
        LOG.info(
            "Publish gate: wheels.publish_limit=%s → new_wheels=%s photo_wheels=%s",
            app_cfg.wheels.publish_limit,
            wheels_new,
            wheels_photo,
        )
    stats["new_rows"] = new_rows
    stats["photo_rows"] = photo_rows
    n_new, n_photo = write_listing_feeds(
        new_rows=new_rows,
        photo_rows=photo_rows,
        new_feed_path=new_feed,
        photo_updates_path=photo_feed,
        exclude_product_types=None,
    )

    # Fingerprints: mark full feed contents so future metrics stay consistent.
    if n_photo > 0:
        try:
            from avito.build_listings import listing_content_fingerprint
            from avito.stock_db import mark_sync_photos, stock_connection as _sc

            marks = []
            for row in stats.get("photo_rows") or []:
                aid = str(row.avito_id or "").strip() or f"lid:{row.listing_id}"
                marks.append(
                    (
                        aid,
                        row.listing_id,
                        row.article_id,
                        listing_content_fingerprint(row),
                    )
                )
            with _sc(
                app_cfg.stock_db.path, schema_path=app_cfg.stock_db.schema_sql
            ) as conn:
                mark_sync_photos(conn, marks)
            LOG.info("photo_updates: marked fingerprints %s", len(marks))
        except Exception as exc:  # noqa: BLE001
            LOG.warning("photo_updates fingerprint mark: %s", exc)

    LOG.info("Моделей без качественного описания: %s", len(stats.get("missing_models") or []))
    LOG.info("Posting: sqlite posting_items (%s строк)", len(posting_df))
    LOG.info(
        "Готово (listings→XML): обновлено %s, добавлено %s, снято %s, "
        "без фото %s, фото модели %s, фото сохранено %s; "
        "new XML=%s, photo XML=%s (photo skip=%s)",
        stats["updated"],
        stats["appended"],
        stats.get("removed", 0),
        stats.get("skipped_no_photos", 0),
        stats.get("model_photo_fallback", 0),
        stats.get("photos_preserved", 0),
        n_new,
        n_photo,
        stats.get("photo_updates_skipped", 0),
    )
    if stats.get("photos_dir"):
        LOG.info("Проверка фото: %s", stats["photos_dir"])
    LOG.info(
        "Фото: https (%s)",
        cfg.photos_public_base_url or "photos_public_base_url не задан",
    )
    try:
        from avito.autoload import _shinaufa_photo_settings
        from avito.shinaufa_photos import flush_shinaufa_photo_cache

        flush_shinaufa_photo_cache(
            _shinaufa_photo_settings(cfg, project_root=ROOT)
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("shinaufa photo cache flush: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
