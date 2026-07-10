#!/usr/bin/env python3
"""Перенос фото из папки «входящие» (менеджеры с телефона) → Авито."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from avito.autoload import resolve_photos_folder
from avito.config import load_config
from avito.manager_inbox import import_manager_inbox, resolve_inbox_folder
from avito.photo_convert import compress_folder_photos, convert_folder_to_jpeg

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("process_manager_inbox")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Импорт фото из папки «входящие» на Яндекс.Диске"
    )
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "-d",
        "--dir",
        type=Path,
        default=None,
        help="Папка Авито (по умолчанию photos_local_dir)",
    )
    p.add_argument(
        "--keep-source",
        action="store_true",
        help="Не удалять файлы из входящих после копирования",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    app = load_config(args.config)
    cfg = app.autoload
    photos_dir = args.dir or resolve_photos_folder(cfg, ROOT)
    if not photos_dir or not photos_dir.is_dir():
        LOG.error("Папка фото не найдена — укажите photos_local_dir")
        return 1

    inbox = resolve_inbox_folder(photos_dir, cfg.manager_inbox_subdir)
    if not inbox:
        LOG.error("Не задан manager_inbox_subdir в config")
        return 1
    inbox.mkdir(parents=True, exist_ok=True)

    stats = import_manager_inbox(
        inbox,
        photos_dir,
        store_prefixes=app.stores.prefixes,
        remove_source=not args.keep_source,
        jpeg_quality=cfg.jpeg_quality,
        photo_layout=cfg.photo_layout,
        prefix_in_filename=cfg.photo_store_prefix_in_filename,
    )
    if cfg.convert_photos_to_jpeg:
        convert_folder_to_jpeg(
            photos_dir,
            quality=cfg.jpeg_quality,
            max_dimension=cfg.jpeg_max_dimension if cfg.compress_photos else 0,
        )
    if cfg.compress_photos:
        compress_folder_photos(
            photos_dir,
            quality=cfg.jpeg_quality,
            max_dimension=cfg.jpeg_max_dimension,
            min_bytes=cfg.compress_min_kb * 1024,
        )

    LOG.info(
        "Входящие: импортировано %s, пропущено %s, ошибок %s, по магазинам %s → %s",
        stats.imported,
        stats.skipped,
        len(stats.errors),
        stats.by_store,
        photos_dir,
    )
    for name, err in stats.errors:
        LOG.error("%s: %s", name, err)
    return 1 if stats.errors else 0


if __name__ == "__main__":
    sys.exit(main())
