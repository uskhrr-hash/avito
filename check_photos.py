#!/usr/bin/env python3
"""Проверка имён фото в папке Авито (локальная копия или синхронизация Диска)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from avito.config import load_config
from avito.photos import (
    PhotoNamingSettings,
    find_photo_file,
    photo_filenames,
    yandex_disk_urls,
)

ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Проверить, что файлы фото названы как ждёт автозагрузка",
    )
    p.add_argument("article", help="Артикул, например 165935")
    p.add_argument(
        "-d",
        "--dir",
        type=Path,
        help="Папка Авито на диске (синхронизация Яндекс.Диска или копия)",
    )
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config).autoload
    photo_cfg = PhotoNamingSettings(
        yandex_disk_root=cfg.yandex_disk_root,
        image_count=cfg.image_count,
        image_ext=cfg.image_ext,
        photo_layout=cfg.photo_layout,
    )

    article = str(args.article).strip()
    expected = photo_filenames(article, photo_cfg)
    cfg_ext = cfg.image_ext.lstrip(".").lower()

    print(f"Артикул: {article}")
    print(f"Режим: {cfg.photo_layout}, расширение в config: .{cfg_ext}")
    print(f"Ожидаемые имена в папке «{cfg.yandex_disk_root}»:")
    for name in expected:
        print(f"  • {name}")
    print()
    print("В автозагрузке:")
    print(f"  {yandex_disk_urls(article, photo_cfg)}")
    print()

    if not args.dir:
        print("Папку на Яндекс.Диске отсюда не видно.")
        print("Сверьте вручную: имена как выше, расширение ." + cfg_ext)
        print("Расширение задаётся в config.yaml → image_ext (сейчас ." + cfg_ext + ")")
        print()
        print('Локально: python check_photos.py 165935 -d "…\\YandexDisk\\Авито"')
        print()
        print("Avito обычно принимает jpg/jpeg/png/webp. HEIC — конвертировать.")
        return 0

    folder = args.dir
    if not folder.is_dir():
        print(f"Ошибка: папка не найдена: {folder}")
        return 1

    found: list[str] = []
    missing: list[str] = []
    wrong_ext: list[str] = []

    for i, name in enumerate(expected, start=1):
        p = folder / name
        if cfg.photo_layout == "folder":
            p = folder / name
        if p.is_file():
            found.append(name)
            continue
        actual = find_photo_file(folder, article, i)
        if actual:
            actual_ext = actual.suffix.lstrip(".").lower()
            if actual_ext != cfg_ext:
                wrong_ext.append(
                    f"{actual.name} (в config .{cfg_ext}, на диске .{actual_ext} — "
                    f"поменяйте image_ext в config.yaml на {actual_ext!r})"
                )
            else:
                found.append(actual.name)
        else:
            missing.append(name)

    extras: list[str] = []
    for f in folder.iterdir():
        if not f.is_file() or article not in f.stem:
            continue
        if f.name not in found and not any(
            Path(x).name == f.name for x in found
        ):
            extras.append(f.name)

    print(f"Папка: {folder}")
    if found:
        print("OK:")
        for x in found:
            print(f"  + {x}")
    if wrong_ext:
        print("Расширение не совпадает с config:")
        for x in wrong_ext:
            print(f"  ! {x}")
    if missing:
        print("Не найдено:")
        for x in missing:
            print(f"  - {x}")
    if extras:
        print("Другие файлы с этим артикулом:")
        for x in extras:
            print(f"  ? {x}")

    if wrong_ext:
        return 1
    if missing and not found:
        print("\nЧастые ошибки: подпапка вместо «Авито»; другое имя (01.jpeg); пробелы.")
        return 1
    if not missing:
        print("\nВсё ок — python build_autoload.py")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
