#!/usr/bin/env python3
"""Конвертация HEIC/HEIF/WebP → JPEG в папке фото на Диске."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from avito.autoload import resolve_photos_folder
from avito.config import load_config
from avito.photo_convert import compress_folder_photos, convert_folder_to_jpeg

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("convert_photos")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="HEIC/HEIF/WebP → .jpg для автозагрузки Avito"
    )
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "-d",
        "--dir",
        type=Path,
        default=None,
        help="Папка фото (по умолчанию photos_local_dir из config)",
    )
    p.add_argument(
        "--quality",
        type=int,
        default=None,
        help="Качество JPEG 1–95 (по умолчанию из config)",
    )
    p.add_argument(
        "--remove-source",
        action="store_true",
        help="Удалить исходный HEIC/WebP после успешной конвертации",
    )
    p.add_argument(
        "--compress",
        action="store_true",
        help="Сжать крупные JPG после конвертации (по умолчанию — из config)",
    )
    p.add_argument(
        "--no-compress",
        action="store_true",
        help="Не сжимать JPG",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    app_cfg = load_config(args.config)
    cfg = app_cfg.autoload
    folder = args.dir or resolve_photos_folder(cfg, ROOT)
    if not folder or not folder.is_dir():
        LOG.error("Папка фото не найдена — укажите photos_local_dir или -d")
        return 1

    quality = args.quality if args.quality is not None else cfg.jpeg_quality
    do_compress = cfg.compress_photos
    if args.compress:
        do_compress = True
    if args.no_compress:
        do_compress = False

    conv = convert_folder_to_jpeg(
        folder,
        quality=quality,
        max_dimension=cfg.jpeg_max_dimension if do_compress else 0,
        remove_source=args.remove_source,
    )
    LOG.info(
        "Конвертация: сконвертировано %s, пропущено %s, ошибок %s",
        conv.converted,
        conv.skipped,
        len(conv.errors),
    )
    if do_compress:
        comp = compress_folder_photos(
            folder,
            quality=quality,
            max_dimension=cfg.jpeg_max_dimension,
            min_bytes=cfg.compress_min_kb * 1024,
        )
        LOG.info(
            "Сжатие: обработано %s, пропущено %s, сэкономлено ~%s MB",
            comp.compressed,
            comp.skipped,
            round(comp.saved_bytes / (1024 * 1024), 1),
        )
    LOG.info("Готово → %s", folder)
    for path, err in conv.errors:
        LOG.error("%s: %s", path, err)
    return 1 if conv.errors else 0


if __name__ == "__main__":
    sys.exit(main())
