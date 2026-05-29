"""Имена файлов фото для Яндекс.Диска и автозагрузки Avito."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# При проверке на диске ищем любое из этих расширений
SEARCH_EXTENSIONS = ("webp", "web", "jpg", "jpeg", "png", "heic", "heif")


@dataclass(frozen=True)
class PhotoNamingSettings:
    yandex_disk_root: str
    image_count: int
    image_ext: str
    # flat — все файлы в папке Авито/ (удобно с телефона)
    # folder — Авито/58971/1.jpg
    photo_layout: str = "flat"


def _stem_parts(article: str, index: int) -> str:
    """Имя без расширения: 165935 или 165935-2."""
    art = str(article).strip()
    if index <= 1:
        return art
    return f"{art}-{index}"


def photo_filename(article: str, index: int, ext: str) -> str:
    """index 1..n → 165935.jpeg, 165935-2.jpeg …"""
    e = ext.lstrip(".")
    return f"{_stem_parts(article, index)}.{e}"


def photo_filenames(article: str, cfg: PhotoNamingSettings) -> list[str]:
    """
    Правила для человека (layout=flat):
      1 фото  → 58971.jpg
      2+ фото → 58971.jpg, 58971-2.jpg, 58971-3.jpg
    layout=folder:
      58971/1.jpg, 58971/2.jpg
    """
    art = str(article).strip()
    if not art:
        return []
    ext = cfg.image_ext.lstrip(".")
    n = max(1, cfg.image_count)
    layout = (cfg.photo_layout or "flat").lower()

    if layout == "folder":
        return [f"{art}/{i}.{ext}" for i in range(1, n + 1)]

    return [photo_filename(art, i, ext) for i in range(1, n + 1)]


def find_photo_file(folder: Path, article: str, index: int) -> Path | None:
    """Ищет файл на диске с любым из SEARCH_EXTENSIONS."""
    stem = _stem_parts(article, index)
    for ext in SEARCH_EXTENSIONS:
        for variant in (ext, ext.upper()):
            p = folder / f"{stem}.{variant}"
            if p.is_file():
                return p
    return None


def yandex_disk_urls(article: str, cfg: PhotoNamingSettings) -> str:
    root = cfg.yandex_disk_root.strip("/").strip("\\")
    parts = [
        f"yandex_disk://{root}/{name}" for name in photo_filenames(article, cfg)
    ]
    return " | ".join(parts)


def human_photo_hint(article: str, cfg: PhotoNamingSettings) -> str:
    names = photo_filenames(article, cfg)
    if len(names) == 1:
        return names[0]
    return ", ".join(names)
