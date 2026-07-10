"""Конвертация и сжатие фото для автозагрузки Avito (HEIC/HEIF/WebP → .jpg)."""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger(__name__)

COMPRESSIBLE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})

# Расширения, которые Avito не принимает — конвертируем в .jpg
CONVERT_TO_JPEG_SUFFIXES = frozenset({".heic", ".heif", ".webp"})

# Форматы, которые Avito принимает в автозагрузке
AVITO_FRIENDLY_EXTENSIONS = ("jpg", "jpeg", "png")

SOURCE_TO_JPEG_EXTENSIONS = ("heic", "heif", "webp")


def _register_heif_opener() -> None:
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        pass


def jpeg_output_path(path: Path) -> Path:
    return path.with_suffix(".jpg")


def needs_jpeg_conversion(path: Path) -> bool:
    return path.suffix.lower() in CONVERT_TO_JPEG_SUFFIXES


def autoload_disk_basename(path: Path) -> str:
    """Имя файла в yandex_disk:// — для Avito всегда .jpg, не .heic/.webp."""
    if needs_jpeg_conversion(path):
        return jpeg_output_path(path).name
    return path.name


def normalize_yandex_photo_urls(text: str) -> str:
    """Заменить .heic/.heif/.webp на .jpg в уже записанных ссылках."""
    if not text or "yandex_disk://" not in text:
        return text
    out = text
    for ext in SOURCE_TO_JPEG_EXTENSIONS:
        for variant in (ext, ext.upper()):
            out = out.replace(f".{variant}", ".jpg")
    return out


def ensure_jpeg_file(
    src: Path,
    *,
    quality: int = 92,
) -> Path | None:
    """Вернуть .jpg для исходника; при необходимости сконвертировать на месте."""
    if not src.is_file():
        return None
    if not needs_jpeg_conversion(src):
        return src
    dst = jpeg_output_path(src)
    try:
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            return dst
        convert_image_to_jpeg(src, dst, quality=quality)
        return dst
    except Exception as exc:
        LOG.warning("JPEG: не удалось %s → %s: %s", src.name, dst.name, exc)
        return None


def _resize_if_needed(img, max_dimension: int):
    if max_dimension <= 0:
        return img
    width, height = img.size
    longest = max(width, height)
    if longest <= max_dimension:
        return img
    from PIL import Image

    scale = max_dimension / longest
    new_size = (max(int(width * scale), 1), max(int(height * scale), 1))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def convert_image_to_jpeg(
    src: Path,
    dst: Path,
    *,
    quality: int = 92,
    max_dimension: int = 0,
) -> None:
    _register_heif_opener()
    from PIL import Image

    with Image.open(src) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img = _resize_if_needed(img, max_dimension)
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, format="JPEG", quality=quality, optimize=True)


def needs_jpeg_compression(
    path: Path,
    *,
    min_bytes: int,
    max_dimension: int,
) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() not in COMPRESSIBLE_SUFFIXES:
        return False
    if min_bytes > 0 and path.stat().st_size >= min_bytes:
        return True
    if max_dimension <= 0:
        return False
    _register_heif_opener()
    from PIL import Image

    with Image.open(path) as img:
        width, height = img.size
    return max(width, height) > max_dimension


def compress_image_in_place(
    path: Path,
    *,
    quality: int = 85,
    max_dimension: int = 1920,
    min_bytes: int = 400_000,
) -> bool:
    """
    Уменьшить JPG/PNG на месте: ресайз по длинной стороне + JPEG quality.

    Возвращает True, если файл перезаписан.
    """
    if not needs_jpeg_compression(
        path, min_bytes=min_bytes, max_dimension=max_dimension
    ):
        return False

    _register_heif_opener()
    from PIL import Image

    original_size = path.stat().st_size
    with Image.open(path) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img = _resize_if_needed(img, max_dimension)
        fd, tmp_name = tempfile.mkstemp(
            suffix=".jpg",
            dir=path.parent,
            prefix=f".{path.stem}_",
        )
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            img.save(tmp, format="JPEG", quality=quality, optimize=True)
            new_size = tmp.stat().st_size
            if new_size >= original_size and path.suffix.lower() in {".jpg", ".jpeg"}:
                tmp.unlink(missing_ok=True)
                return False
            jpg_path = path if path.suffix.lower() != ".png" else path.with_suffix(".jpg")
            tmp.replace(jpg_path)
            if path.suffix.lower() == ".png" and path != jpg_path:
                path.unlink(missing_ok=True)
            return True
        except Exception:
            tmp.unlink(missing_ok=True)
            raise


@dataclass
class ConvertStats:
    converted: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class CompressStats:
    compressed: int = 0
    skipped: int = 0
    saved_bytes: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def convert_folder_to_jpeg(
    folder: Path,
    *,
    quality: int = 92,
    max_dimension: int = 0,
    remove_source: bool = False,
) -> ConvertStats:
    """
    HEIC/HEIF/WebP → .jpg в той же папке.

    Если .jpg уже есть и не старее исходника — пропуск.
    """
    stats = ConvertStats()
    if not folder.is_dir():
        return stats

    for src in sorted(folder.iterdir()):
        if not src.is_file() or not needs_jpeg_conversion(src):
            continue
        dst = jpeg_output_path(src)
        try:
            if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
                stats.skipped += 1
                continue
            convert_image_to_jpeg(
                src, dst, quality=quality, max_dimension=max_dimension
            )
            stats.converted += 1
            LOG.info("JPEG: %s → %s", src.name, dst.name)
            if remove_source:
                src.unlink()
        except Exception as exc:
            stats.errors.append((str(src), str(exc)))
            LOG.warning("JPEG: не удалось %s: %s", src.name, exc)

    return stats


def compress_folder_photos(
    folder: Path,
    *,
    quality: int = 85,
    max_dimension: int = 1920,
    min_bytes: int = 400_000,
) -> CompressStats:
    """Сжать крупные JPG/JPEG/PNG в папке (для Авито и загрузки на Диск)."""
    stats = CompressStats()
    if not folder.is_dir():
        return stats

    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in COMPRESSIBLE_SUFFIXES:
            continue
        try:
            before = path.stat().st_size
            if not compress_image_in_place(
                path,
                quality=quality,
                max_dimension=max_dimension,
                min_bytes=min_bytes,
            ):
                stats.skipped += 1
                continue
            after = path.stat().st_size
            stats.compressed += 1
            stats.saved_bytes += max(0, before - after)
            LOG.info(
                "Сжато: %s (%s KB → %s KB)",
                path.name,
                before // 1024,
                after // 1024,
            )
        except Exception as exc:
            stats.errors.append((str(path), str(exc)))
            LOG.warning("Сжатие: не удалось %s: %s", path.name, exc)

    return stats
