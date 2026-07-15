"""Имена и поиск фото на Яндекс.Диске (с префиксом магазина)."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger(__name__)

from avito.photo_convert import (
    AVITO_FRIENDLY_EXTENSIONS,
    SOURCE_TO_JPEG_EXTENSIONS,
    autoload_disk_basename,
    ensure_jpeg_file,
    normalize_yandex_photo_urls,
)
from urllib.parse import quote

from avito.yandex_disk_api import YandexDiskDownloadUrls, disk_resource_path

__all__ = [
    "normalize_yandex_photo_urls",
    "is_avito_hosted_photo_urls",
    "photo_urls_look_like_article",
]


@dataclass(frozen=True)
class PhotoNamingSettings:
    yandex_disk_root: str
    image_count: int
    image_ext: str
    photo_layout: str = "flat"
    photos_public_base_url: str = ""


@dataclass(frozen=True)
class StorePhotos:
    prefix: str
    files: tuple[Path, ...]


@dataclass(frozen=True)
class ResolvedListingPhotos:
    """Набор фото для объявления и источник: article | model."""

    store_sets: tuple[StorePhotos, ...]
    source: str = ""


def model_photo_label(brand: str, model: str) -> str:
    """Имя без расширения: Formula + Energy → «Formula Energy»."""
    return " ".join(x.strip() for x in (str(brand), str(model)) if x and str(x).strip())


def model_photo_stem_variants(brand: str, model: str, index: int) -> list[str]:
    stem = model_photo_label(brand, model)
    if not stem:
        return []
    if index <= 1:
        return [stem, f"{stem}-1"]
    return [f"{stem}-{index}"]


def prefixed_stem_variants(prefix: str, article: str, index: int) -> list[str]:
    """md + 103926 → md103926, md103926-1, md103926-2 …"""
    p = str(prefix).strip()
    art = str(article).strip()
    if not p or not art:
        return []
    if index <= 1:
        return [f"{p}{art}", f"{p}{art}-1"]
    return [f"{p}{art}-{index}"]


def unprefixed_stem_variants(article: str, index: int) -> list[str]:
    art = str(article).strip()
    if index <= 1:
        return [art, f"{art}-1"]
    return [f"{art}-{index}"]


def _find_by_stems(
    folder: Path,
    stems: list[str],
    *,
    jpeg_quality: int = 92,
) -> Path | None:
    """Только jpg/jpeg/png для Avito; HEIC/WebP → конвертация в .jpg на диске."""
    for stem in stems:
        for ext in AVITO_FRIENDLY_EXTENSIONS:
            for variant in (ext, ext.upper()):
                p = folder / f"{stem}.{variant}"
                if p.is_file():
                    return p
        for ext in SOURCE_TO_JPEG_EXTENSIONS:
            for variant in (ext, ext.upper()):
                src = folder / f"{stem}.{variant}"
                if src.is_file():
                    jpg = ensure_jpeg_file(src, quality=jpeg_quality)
                    if jpg:
                        return jpg
    return None


def _search_dirs_for_store(folder: Path, prefix: str, layout: str) -> list[Path]:
    """flat — только корень; store_subdir — сначала Авито/md/, затем корень."""
    layout = (layout or "flat").lower()
    if layout != "store_subdir":
        return [folder]
    sub = folder / prefix
    if sub.is_dir():
        return [sub, folder]
    return [folder]


def _store_prefix_in_filename(layout: str, prefix_in_filename: bool) -> bool:
    """store_subdir + false → 124889.jpg в папке md; flat → всегда md124889.jpg в корне."""
    if (layout or "flat").lower() != "store_subdir":
        return True
    return prefix_in_filename


def _article_stem_variants(
    prefix: str,
    article: str,
    index: int,
    *,
    layout: str,
    prefix_in_filename: bool,
) -> list[str]:
    if _store_prefix_in_filename(layout, prefix_in_filename):
        return prefixed_stem_variants(prefix, article, index)
    return unprefixed_stem_variants(article, index)


def discover_prefixed_photos(
    folder: Path,
    prefix: str,
    article: str,
    *,
    layout: str = "flat",
    prefix_in_filename: bool = True,
    max_count: int = 0,
    jpeg_quality: int = 92,
) -> list[Path]:
    if not folder.is_dir():
        return []
    stem_modes: list[bool] = [_store_prefix_in_filename(layout, prefix_in_filename)]
    if (
        (layout or "flat").lower() == "store_subdir"
        and not prefix_in_filename
    ):
        stem_modes.append(True)
    for search in _search_dirs_for_store(folder, prefix, layout):
        for use_prefix in stem_modes:
            found: list[Path] = []
            i = 1
            while True:
                p = _find_by_stems(
                    search,
                    _article_stem_variants(
                        prefix,
                        article,
                        i,
                        layout=layout,
                        prefix_in_filename=use_prefix,
                    ),
                    jpeg_quality=jpeg_quality,
                )
                if p is None:
                    break
                found.append(p)
                if max_count and len(found) >= max_count:
                    break
                i += 1
            if found:
                return found
    return []


def discover_model_photos(
    folder: Path,
    brand: str,
    model: str,
    *,
    max_count: int = 0,
    jpeg_quality: int = 92,
) -> list[Path]:
    """Фото по бренду+модели: Formula Energy.jpg, Formula Energy-1.jpg …"""
    if not folder.is_dir() or not model_photo_label(brand, model):
        return []
    found: list[Path] = []
    i = 1
    while True:
        p = _find_by_stems(
            folder,
            model_photo_stem_variants(brand, model, i),
            jpeg_quality=jpeg_quality,
        )
        if p is None:
            break
        found.append(p)
        if max_count and len(found) >= max_count:
            break
        i += 1
    return found


def discover_unprefixed_photos(
    folder: Path,
    article: str,
    *,
    max_count: int = 0,
    jpeg_quality: int = 92,
) -> list[Path]:
    if not folder.is_dir():
        return []
    found: list[Path] = []
    i = 1
    while True:
        p = _find_by_stems(
            folder,
            unprefixed_stem_variants(article, i),
            jpeg_quality=jpeg_quality,
        )
        if p is None:
            break
        found.append(p)
        if max_count and len(found) >= max_count:
            break
        i += 1
    return found


def discover_photos_for_stores(
    folder: Path,
    article: str,
    prefixes: tuple[str, ...],
    *,
    layout: str = "flat",
    prefix_in_filename: bool = True,
    legacy_unprefixed_prefix: str | None = None,
    article_first: bool = False,
    max_count: int = 0,
    jpeg_quality: int = 92,
    contributors_prefix: str | None = None,
) -> list[StorePhotos]:
    """По каждому магазину — отдельный набор файлов, если есть хотя бы одно фото.

    Если ни у одного магазина нет фото, но есть в contributors_prefix —
    возвращаем один StorePhotos с assign_store_for_contributor_article.
    """
    art = str(article).strip()
    if not art:
        return []

    out: list[StorePhotos] = []
    seen_prefixes: set[str] = set()

    if article_first and legacy_unprefixed_prefix:
        files = discover_unprefixed_photos(
            folder, art, max_count=max_count, jpeg_quality=jpeg_quality
        )
        if files:
            return [StorePhotos(prefix=legacy_unprefixed_prefix, files=tuple(files))]

    for prefix in prefixes:
        files = discover_prefixed_photos(
            folder,
            prefix,
            art,
            layout=layout,
            prefix_in_filename=prefix_in_filename,
            max_count=max_count,
            jpeg_quality=jpeg_quality,
        )
        if files:
            out.append(StorePhotos(prefix=prefix, files=tuple(files)))
            seen_prefixes.add(prefix)

    if legacy_unprefixed_prefix and legacy_unprefixed_prefix not in seen_prefixes:
        files = discover_unprefixed_photos(
            folder, art, max_count=max_count, jpeg_quality=jpeg_quality
        )
        if files:
            out.append(
                StorePhotos(prefix=legacy_unprefixed_prefix, files=tuple(files))
            )

    if out:
        return out

    pool = (contributors_prefix or "").strip()
    if pool and prefixes:
        files = discover_prefixed_photos(
            folder,
            pool,
            art,
            layout=layout,
            prefix_in_filename=False,
            max_count=max_count,
            jpeg_quality=jpeg_quality,
        )
        if files:
            assigned = assign_store_for_contributor_article(art, prefixes)
            return [StorePhotos(prefix=assigned, files=tuple(files))]

    return out


def assign_store_for_contributor_article(
    article: str, prefixes: tuple[str, ...]
) -> str:
    """Детерминированно ~50/50 между md/pg по артикулу."""
    if not prefixes:
        raise ValueError("Нет магазинов для назначения")
    digest = hashlib.md5(str(article).strip().encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(prefixes)
    return prefixes[idx]


def newest_file_mtime(files: tuple[Path, ...] | list[Path]) -> float | None:
    if not files:
        return None
    return max(p.stat().st_mtime for p in files)


def select_store_when_conflict(candidates: list[StorePhotos]) -> StorePhotos | None:
    """
    Один артикул, фото у нескольких магазинов — оставляем один магазин.

    По каждому магазину берём самый новый файл (max mtime), затем:
    - одна дата → магазин с более ранним из этих max;
    - разные даты → магазин с более поздним (свежим) max.
    """
    ranked: list[tuple[StorePhotos, float]] = []
    for sp in candidates:
        mt = newest_file_mtime(sp.files)
        if mt is not None:
            ranked.append((sp, mt))

    if not ranked:
        return None
    if len(ranked) == 1:
        return ranked[0][0]

    dates = {datetime.fromtimestamp(mt).date() for _, mt in ranked}
    if len(dates) == 1:
        return min(ranked, key=lambda item: item[1])[0]
    return max(ranked, key=lambda item: item[1])[0]


def resolve_listing_stores(
    folder: Path,
    article: str,
    prefixes: tuple[str, ...],
    *,
    layout: str = "flat",
    prefix_in_filename: bool = True,
    legacy_unprefixed_prefix: str | None = None,
    max_count: int = 0,
    jpeg_quality: int = 92,
    contributors_prefix: str | None = None,
) -> list[StorePhotos]:
    """Найти фото и при конфликте магазинов оставить одного победителя."""
    return list(
        resolve_listing_photo_sets(
            folder,
            article,
            prefixes,
            layout=layout,
            prefix_in_filename=prefix_in_filename,
            legacy_unprefixed_prefix=legacy_unprefixed_prefix,
            max_count=max_count,
            jpeg_quality=jpeg_quality,
            contributors_prefix=contributors_prefix,
        ).store_sets
    )


def resolve_listing_photo_sets(
    folder: Path | None,
    article: str,
    prefixes: tuple[str, ...],
    *,
    layout: str = "flat",
    prefix_in_filename: bool = True,
    brand: str = "",
    model: str = "",
    model_fallback: bool = False,
    article_first: bool = False,
    legacy_unprefixed_prefix: str | None = None,
    max_count: int = 0,
    jpeg_quality: int = 92,
    contributors_prefix: str | None = None,
) -> ResolvedListingPhotos:
    """
    Сначала фото по артикулу (md12345-1.jpg), иначе — по бренду+модели.

    Временный запасной вариант, пока нет снимков с артикулом в имени.
    """
    if not folder or not str(article).strip():
        return ResolvedListingPhotos(())

    all_found = discover_photos_for_stores(
        folder,
        article,
        prefixes,
        layout=layout,
        prefix_in_filename=prefix_in_filename,
        legacy_unprefixed_prefix=legacy_unprefixed_prefix,
        article_first=article_first,
        max_count=max_count,
        jpeg_quality=jpeg_quality,
        contributors_prefix=contributors_prefix,
    )
    if len(all_found) <= 1:
        store_sets = all_found
    else:
        winner = select_store_when_conflict(all_found)
        store_sets = [winner] if winner else []
    if store_sets:
        return ResolvedListingPhotos(tuple(store_sets), "article")

    if not model_fallback:
        return ResolvedListingPhotos(())

    model_files = discover_model_photos(
        folder,
        brand,
        model,
        max_count=max_count,
        jpeg_quality=jpeg_quality,
    )
    if not model_files:
        return ResolvedListingPhotos(())

    prefix = legacy_unprefixed_prefix or (prefixes[0] if prefixes else "md")
    label = model_photo_label(brand, model)
    LOG.info(
        "Артикул %s: фото модели «%s» (временно, нет снимков артикула)",
        article,
        label,
    )
    return ResolvedListingPhotos(
        (StorePhotos(prefix=prefix, files=tuple(model_files)),),
        "model",
    )


def photo_relative_path(
    path: Path,
    photos_root: Path | None,
    *,
    article: str,
    layout: str,
    store_prefix: str | None = None,
    use_disk_basename: bool = False,
) -> str:
    """
    Относительный путь файла для URL/nginx или yandex_disk://.

  Если задан photos_root — фактический путь от корня папки фото
  (модель в корне → без md/; артикул в md/ → md/124889.jpg).
    """
    if photos_root is not None:
        try:
            rel = path.resolve().relative_to(photos_root.resolve())
            if use_disk_basename:
                parent = rel.parent
                name = autoload_disk_basename(path)
                return (
                    f"{parent.as_posix()}/{name}"
                    if parent.parts
                    else name
                )
            return rel.as_posix()
        except ValueError:
            pass

    layout = (layout or "flat").lower()
    name = autoload_disk_basename(path) if use_disk_basename else path.name
    if layout == "folder":
        return f"{article.strip()}/{name}"
    if layout == "store_subdir" and store_prefix:
        return f"{store_prefix.strip()}/{name}"
    return name


def disk_path_to_yandex_name(
    path: Path,
    article: str,
    layout: str,
    *,
    store_prefix: str | None = None,
    photos_root: Path | None = None,
) -> str:
    return photo_relative_path(
        path,
        photos_root,
        article=article,
        layout=layout,
        store_prefix=store_prefix,
        use_disk_basename=True,
    )


def is_avito_hosted_photo_url(url: str) -> bool:
    u = url.strip().lower()
    return "avito.ru/autoload" in u and "image" in u


def is_avito_hosted_photo_urls(text: str) -> bool:
    if not text or not str(text).strip():
        return False
    return any(
        is_avito_hosted_photo_url(part)
        for part in str(text).split("|")
        if part.strip()
    )


def photo_urls_look_like_article(photos: str, article: str) -> bool:
    """Ссылки ведут на фото артикула (не модель, не CDN Авито)."""
    text = str(photos or "").strip()
    art = str(article or "").strip()
    if not text or not art or is_avito_hosted_photo_urls(text):
        return False
    low = text.lower()
    a = art.lower()
    markers = (
        f"/{a}.",
        f"/{a}-",
        f"md{a}",
        f"pg{a}",
        f"sc{a}",
        f"/{a}/",
    )
    return any(m in low for m in markers)


def yandex_disk_urls_from_files(
    files: list[Path] | tuple[Path, ...],
    *,
    yandex_disk_root: str,
    article: str,
    layout: str,
    store_prefix: str | None = None,
    photos_root: Path | None = None,
) -> str:
    root = yandex_disk_root.strip("/").strip("\\")
    parts = [
        f"yandex_disk://{root}/{disk_path_to_yandex_name(f, article, layout, store_prefix=store_prefix, photos_root=photos_root)}"
        for f in files
    ]
    return " | ".join(parts)


def yandex_https_urls_from_files(
    files: list[Path] | tuple[Path, ...],
    *,
    yandex_disk_root: str,
    article: str,
    layout: str,
    store_prefix: str | None = None,
    photos_root: Path | None = None,
    downloader: YandexDiskDownloadUrls,
) -> str:
    parts: list[str] = []
    for f in files:
        rel = photo_relative_path(
            f,
            photos_root,
            article=article,
            layout=layout,
            store_prefix=store_prefix,
        )
        disk_path = disk_resource_path(yandex_disk_root, rel)
        href = downloader.href_for_disk_file(disk_path, local_path=f)
        if href:
            parts.append(href)
    return " | ".join(parts)


def server_https_urls_from_files(
    files: list[Path] | tuple[Path, ...],
    *,
    photos_public_base_url: str,
    article: str,
    layout: str,
    store_prefix: str | None = None,
    photos_root: Path | None = None,
) -> str:
    base = photos_public_base_url.rstrip("/") + "/"
    parts: list[str] = []
    for f in files:
        rel = photo_relative_path(
            f,
            photos_root,
            article=article,
            layout=layout,
            store_prefix=store_prefix,
        )
        parts.append(base + quote(rel, safe="/"))
    return " | ".join(parts)


def build_store_photo_urls(
    store_photos: StorePhotos,
    cfg: PhotoNamingSettings,
    *,
    article: str,
    layout: str,
    image_mode: str = "yandex_disk",
    photos_root: Path | None = None,
    downloader: YandexDiskDownloadUrls | None = None,
) -> str:
    if not store_photos.files:
        return ""
    if image_mode == "yandex_https":
        if downloader is None:
            raise ValueError("yandex_https требует YandexDiskDownloadUrls")
        return yandex_https_urls_from_files(
            store_photos.files,
            yandex_disk_root=cfg.yandex_disk_root,
            article=article,
            layout=layout,
            store_prefix=store_photos.prefix,
            photos_root=photos_root,
            downloader=downloader,
        )
    if image_mode == "server_https":
        if not cfg.photos_public_base_url.strip():
            raise ValueError("server_https требует photos_public_base_url в config")
        return server_https_urls_from_files(
            store_photos.files,
            photos_public_base_url=cfg.photos_public_base_url,
            article=article,
            layout=layout,
            store_prefix=store_photos.prefix,
            photos_root=photos_root,
        )
    return yandex_disk_urls_from_files(
        store_photos.files,
        yandex_disk_root=cfg.yandex_disk_root,
        article=article,
        layout=layout,
        store_prefix=store_photos.prefix,
        photos_root=photos_root,
    )


def article_photo_filenames(article: str, *, max_count: int = 3) -> list[str]:
    """Имена для менеджеров: только артикул, без префикса магазина."""
    art = str(article).strip()
    if not art:
        return []
    names = [f"{art}.jpg", f"{art}-1.jpg", f"{art}-2.jpg"]
    return names[:max_count] if max_count else names


def human_photo_hint(article: str, count: int = 2) -> str:
    return ", ".join(article_photo_filenames(article, max_count=count))


def human_model_photo_hint(brand: str, model: str, count: int = 2) -> str:
    stem = model_photo_label(brand, model)
    if not stem:
        return ""
    names = [f"{stem}.jpg"]
    if count > 1:
        names.append(f"{stem}-1.jpg")
    return ", ".join(names)


def human_photo_hint_for_store(
    prefix: str,
    article: str,
    count: int = 3,
    *,
    layout: str = "flat",
    prefix_in_filename: bool = True,
) -> str:
    if (layout or "flat").lower() == "store_subdir" and not prefix_in_filename:
        names = human_photo_hint(article, count=count)
        return f"{names} (папка {prefix}/)"
    examples = prefixed_stem_variants(prefix, article, 1)[:1]
    if count > 1:
        examples = prefixed_stem_variants(prefix, article, 1) + prefixed_stem_variants(
            prefix, article, 2
        )[:1]
    return ", ".join(f"{s}.jpg" for s in examples)
