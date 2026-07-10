#!/usr/bin/env python3
"""posting_*.xlsx + шаблон Avito → autoload_*.xlsx для загрузки в ЛК."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from avito.autoload import (
    _extract_avito_export_maps,
    avito_ids_for_posting,
    fill_autoload_template,
    load_avito_ids,
    load_posting,
    resolve_autoload_base,
    resolve_photos_folder,
    save_avito_ids_csv,
)
from avito.photo_convert import compress_folder_photos, convert_folder_to_jpeg
from avito.config import load_config
from avito.model_descriptions import resolve_model_descriptions
from avito.no_photos_export import export_no_photos_excel

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("build_autoload")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Заполнение шаблона автозагрузки Avito")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--posting", type=Path, default=None, help="posting_*.xlsx")
    p.add_argument(
        "--template",
        type=Path,
        default=None,
        help="Базовый xlsx (иначе — последняя выгрузка 432801655_*.xlsx в input/)",
    )
    p.add_argument("-o", "--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--date", default=None)
    p.add_argument(
        "--use-working",
        action="store_true",
        help="Брать накопленный autoload_working.xlsx вместо свежей выгрузки Авито",
    )
    p.add_argument(
        "--from-avito-export",
        type=Path,
        default=None,
        help="(устар.) То же, что --template",
    )
    p.add_argument(
        "--write-avito-ids",
        action="store_true",
        help="Сохранить номера объявлений из базового xlsx в input/avito_ids.csv",
    )
    return p.parse_args()


def find_latest_posting(output_dir: Path) -> Path | None:
    files = sorted(output_dir.glob("posting_*.xlsx"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    app_cfg = load_config(args.config)
    cfg = app_cfg.autoload
    stores = app_cfg.stores
    stamp = args.date or date.today().isoformat()

    posting_path = args.posting or find_latest_posting(args.output_dir)
    if not posting_path or not posting_path.exists():
        LOG.error("Нет posting_*.xlsx — сначала: python compare_prices.py")
        return 1

    template_override = args.template
    if args.from_avito_export:
        template_override = args.from_avito_export
    template_path, base_label = resolve_autoload_base(
        cfg,
        root=ROOT,
        override=template_override,
        use_working=args.use_working,
    )
    if not template_path.is_absolute():
        template_path = ROOT / template_path
    if not template_path.exists():
        LOG.error("Базовый файл не найден: %s", template_path)
        return 1

    posting_df = load_posting(posting_path)

    avito_ids_path = ROOT / cfg.avito_ids_file
    ids_from_xlsx, titles_from_xlsx = _extract_avito_export_maps(template_path)
    ids_from_csv = load_avito_ids(avito_ids_path, stores)
    avito_ids = avito_ids_for_posting(
        posting_df,
        stores,
        ids_from_xlsx=ids_from_xlsx,
        titles_from_xlsx=titles_from_xlsx,
        ids_from_csv=ids_from_csv,
    )
    if titles_from_xlsx:
        LOG.info(
            "Выгрузка Авито: %s активных объявлений по названию",
            len(titles_from_xlsx),
        )
    if not avito_ids_path.exists() and avito_ids:
        LOG.info(
            "Файл %s не найден — номера объявлений собраны из xlsx/posting (%s шт.)",
            avito_ids_path.name,
            len(avito_ids),
        )
    elif avito_ids:
        LOG.info(
            "Avito ID: csv=%s, сопоставлено для автозагрузки=%s",
            len(ids_from_csv),
            len(avito_ids),
        )
    if args.write_avito_ids and avito_ids:
        n = save_avito_ids_csv(avito_ids_path, avito_ids)
        LOG.info("Записано %s артикулов → %s", n, avito_ids_path)

    models_path = cfg.model_descriptions_file
    if not models_path.is_absolute():
        models_path = ROOT / models_path
    secrets_path = app_cfg.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = ROOT / secrets_path
    model_descriptions = resolve_model_descriptions(
        xlsx_path=models_path,
        descriptions_db_enabled=app_cfg.descriptions_db.enabled,
        secrets_path=secrets_path,
        fallback_to_xlsx=app_cfg.descriptions_db.fallback_to_xlsx,
        pg_schema=app_cfg.descriptions_db.pg_schema,
        project_root=ROOT,
    )
    if app_cfg.descriptions_db.enabled:
        LOG.info("Описания моделей: из БД %s ключей (xlsx fallback=%s)", len(model_descriptions), app_cfg.descriptions_db.fallback_to_xlsx)
    out_path = args.output_dir / f"autoload_{stamp}.xlsx"

    if cfg.verify_photos_on_disk and not cfg.photos_local_dir:
        LOG.warning(
            "verify_photos_on_disk включён, но photos_local_dir не задан — "
            "фото не проверяются (укажите путь к папке «Авито» на Диске)"
        )
    elif cfg.verify_photos_on_disk:
        probe = ROOT / cfg.photos_local_dir
        if cfg.photos_local_dir and cfg.photos_local_dir.is_absolute():
            probe = cfg.photos_local_dir
        if not probe.is_dir():
            LOG.warning("Папка фото не найдена: %s", probe)

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

    sec_path = app_cfg.stock_sources.secrets_file
    if not sec_path.is_absolute():
        sec_path = ROOT / sec_path

    stats = fill_autoload_template(
        template_path=template_path,
        posting_df=posting_df,
        cfg=cfg,
        stores=stores,
        model_descriptions=model_descriptions,
        avito_ids=avito_ids,
        output_path=out_path,
        project_root=ROOT,
        secrets_file=sec_path,
    )
    out_path = Path(stats.get("output_path", out_path))

    working_path = ROOT / cfg.working_file
    working_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(out_path, working_path)
    except PermissionError:
        alt_working = working_path.with_name(
            f"{working_path.stem}_{stamp}{working_path.suffix}"
        )
        LOG.warning(
            "Не удалось обновить %s — файл занят. Копия: %s",
            working_path,
            alt_working.name,
        )
        shutil.copy2(out_path, alt_working)
        working_path = alt_working

    removed = stats.pop("removed_rows", [])
    removed_path = args.output_dir / f"autoload_removed_{stamp}.csv"
    if removed:
        pd.DataFrame(removed).to_csv(removed_path, index=False, encoding="utf-8-sig")

    photos_missing = stats.pop("photos_missing", [])
    missing_models = stats.pop("missing_models", [])
    photos_dir = stats.pop("photos_dir", "")
    if photos_dir:
        LOG.info("Проверка фото: %s", photos_dir)
    no_photo_path = args.output_dir / f"autoload_no_photos_{stamp}.csv"
    pd.DataFrame(photos_missing or []).to_csv(
        no_photo_path, index=False, encoding="utf-8-sig"
    )
    LOG.info("Без фото на диске: %s → %s", len(photos_missing), no_photo_path)
    missing_models_path = args.output_dir / cfg.missing_models_file
    pd.DataFrame(missing_models or []).to_excel(
        missing_models_path, sheet_name="без описаний", index=False
    )
    LOG.info(
        "Моделей без качественного описания: %s → %s",
        len(missing_models),
        missing_models_path,
    )

    photos_folder = resolve_photos_folder(cfg, ROOT)
    if photos_folder:
        disk_xlsx = export_no_photos_excel(
            photos_folder,
            cfg.no_photos_file,
            photos_missing,
        )
        LOG.info("Список без фото на Диске: %s", disk_xlsx)
    elif photos_missing:
        LOG.warning(
            "photos_local_dir недоступна — no_photos.xlsx на Диск не записан"
        )

    LOG.info("Posting: %s (%s строк)", posting_path.name, len(posting_df))
    LOG.info("База: %s (%s)", template_path.name, base_label)
    LOG.info(
        "Готово: обновлено %s, добавлено %s, снято (нет в goods) %s, "
        "без фото (не в файл) %s, фото модели (временно) %s, прочие пропуски %s",
        stats["updated"],
        stats["appended"],
        stats.get("removed", 0),
        stats.get("skipped_no_photos", 0),
        stats.get("model_photo_fallback", 0),
        stats["skipped"] - stats.get("skipped_no_photos", 0),
    )
    if removed:
        LOG.info("Снятые объявления → %s", removed_path)
    LOG.info("Выгрузка: %s", out_path)
    LOG.info("Накопленный файл: %s", working_path)
    if cfg.image_mode == "yandex_https":
        LOG.info(
            "Фото: https-ссылки с Яндекс.Диска (папка «%s» на Диске)",
            cfg.yandex_disk_root,
        )
    elif cfg.image_mode == "server_https":
        LOG.info(
            "Фото: https-ссылки с сервера (%s)",
            cfg.photos_public_base_url or "photos_public_base_url не задан",
        )
    else:
        LOG.info(
            "Фото (пример): yandex_disk://%s/АРТИКУЛ.%s",
            cfg.yandex_disk_root,
            cfg.image_ext,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
