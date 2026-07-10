#!/usr/bin/env python3
"""Проверка фото артикула по магазинам (префикс в имени файла)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from avito.autoload import resolve_photos_folder
from avito.config import load_config
from avito.photos import (
    PhotoNamingSettings,
    build_store_photo_urls,
    human_model_photo_hint,
    human_photo_hint_for_store,
    model_photo_label,
    resolve_listing_photo_sets,
)
from avito.title_parse import parse_title_fields

ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Фото на Диске по префиксу магазина")
    p.add_argument("article", help="Артикул, например 103926")
    p.add_argument(
        "-n",
        "--nomenclature",
        default="",
        help="Название шины — для поиска фото модели, если нет по артикулу",
    )
    p.add_argument("-d", "--dir", type=Path, help="Папка Авито")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    app = load_config(args.config)
    cfg = app.autoload
    stores = app.stores

    folder = args.dir or resolve_photos_folder(cfg, ROOT)
    if folder is None or not folder.is_dir():
        print("Укажите photos_local_dir в config.yaml или -d ПАПКА")
        return 1

    article = str(args.article).strip()
    photo_cfg = PhotoNamingSettings(
        cfg.yandex_disk_root,
        cfg.image_count,
        cfg.image_ext,
        cfg.photo_layout,
    )

    print(f"Артикул: {article}")
    print(f"Папка: {folder}")
    print("Магазины:", ", ".join(f"{s.prefix} ({s.label})" for s in stores.stores))
    print()

    fields = parse_title_fields(args.nomenclature) if args.nomenclature else {}
    resolved = resolve_listing_photo_sets(
        folder,
        article,
        stores.prefixes,
        layout=cfg.photo_layout,
        prefix_in_filename=cfg.photo_store_prefix_in_filename,
        brand=fields.get("brand", ""),
        model=fields.get("model", ""),
        model_fallback=cfg.model_photo_fallback,
        legacy_unprefixed_prefix=stores.legacy_unprefixed_store,
        max_count=int(cfg.image_count or 0),
        jpeg_quality=cfg.jpeg_quality,
    )
    found = list(resolved.store_sets)

    if resolved.source == "model":
        print(f"Источник: фото модели «{model_photo_label(fields.get('brand', ''), fields.get('model', ''))}»")
        print()

    if not found:
        print("Фото не найдено.")
        print("Имена: ПРЕФИКС+АРТИКУЛ.jpg или ПРЕФИКС+АРТИКУЛ-1.jpg")
        for s in stores.stores:
            print(
                f"  {s.prefix}: "
                f"{human_photo_hint_for_store(s.prefix, article, layout=cfg.photo_layout, prefix_in_filename=cfg.photo_store_prefix_in_filename)}"
            )
        if cfg.model_photo_fallback and fields:
            hint = human_model_photo_hint(fields.get("brand", ""), fields.get("model", ""))
            if hint:
                print(f"  модель: {hint}")
        return 1

    for sp in found:
        store = stores.get(sp.prefix)
        label = store.label if store else sp.prefix
        print(f"[{sp.prefix}] {label}")
        for p in sp.files:
            print(f"  + {p.name}")
        urls = build_store_photo_urls(
            sp, photo_cfg, article=article, layout=cfg.photo_layout
        )
        print(f"  автозагрузка: {urls}")
        print(f"  Id в Excel: {store.listing_id(article) if store else '—'}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
