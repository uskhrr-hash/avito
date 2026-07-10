"""Данные и сохранение фото для веб-загрузки."""
from __future__ import annotations

import csv
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from avito.compare import load_stock
from avito.manager_inbox import photo_filename, photo_relative_path, photo_target_path
from avito.photo_convert import compress_image_in_place, convert_image_to_jpeg
from avito.photo_upload.settings import PhotoUploadRuntime
from avito.store_registry import fetch_articles_at_supplier

LOG = logging.getLogger(__name__)

_ARTICLE_RE = re.compile(r"^\d{4,}$")


@dataclass(frozen=True)
class StockItem:
    article: str
    nomenclature: str
    quantity: str


@dataclass(frozen=True)
class NoPhotoItem:
    article: str
    nomenclature: str
    stores: str
    problem: str


@dataclass(frozen=True)
class PendingPhotoMeta:
    index: int
    relative_path: str
    filename: str


@dataclass(frozen=True)
class UploadResult:
    saved: list[str]
    article: str


def normalize_article(value: str) -> str:
    return str(value or "").strip()


def validate_article(value: str) -> str:
    art = normalize_article(value)
    if not _ARTICLE_RE.match(art):
        raise ValueError("Артикул: только цифры, минимум 4 символа")
    return art


def _stock_items(runtime: PhotoUploadRuntime) -> list[StockItem]:
    cfg = runtime.config.compare
    rows = load_stock(runtime.stock_file, cfg)
    return [
        StockItem(
            article=str(r.article).strip(),
            nomenclature=str(r.nomenclature).strip(),
            quantity=str(r.quantity).strip(),
        )
        for r in rows
        if str(r.article).strip()
    ]


def lookup_stock(runtime: PhotoUploadRuntime, article: str) -> StockItem | None:
    art = normalize_article(article)
    if not art:
        return None
    for row in _stock_items(runtime):
        if row.article == art:
            return row
    return None


def search_stock(runtime: PhotoUploadRuntime, query: str, *, limit: int = 30) -> list[StockItem]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    out: list[StockItem] = []
    for row in _stock_items(runtime):
        hay = f"{row.article} {row.nomenclature}".lower()
        if q in hay:
            out.append(row)
            if len(out) >= limit:
                break
    return out


def _latest_no_photos_csv(runtime: PhotoUploadRuntime) -> Path | None:
    if not runtime.output_dir.is_dir():
        return None
    files = sorted(
        runtime.output_dir.glob("autoload_no_photos_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


@dataclass(frozen=True)
class NoPhotosQueueResult:
    items: list[NoPhotoItem]
    source_file: str | None
    hint: str


def load_no_photos_queue_info(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    limit: int = 80,
    in_store_only: bool = False,
    in_store_articles: frozenset[str] | None = None,
) -> NoPhotosQueueResult:
    path = _latest_no_photos_csv(runtime)
    prefix = store_prefix.strip()
    store = runtime.stores_config.get(prefix)
    ushk_name = store.ushk_supplier if store else None

    if path is None:
        return NoPhotosQueueResult(
            [],
            None,
            "Список ещё не собран. На сервере запустите: build_stock → compare_prices → build_autoload",
        )

    if in_store_only and not ushk_name:
        return NoPhotosQueueResult(
            [],
            path.name,
            f"Для магазина {prefix} не задан ushk_supplier в stores.yaml",
        )

    items = load_no_photos_queue(
        runtime,
        store_prefix=store_prefix,
        limit=limit,
        in_store_only=in_store_only,
        in_store_articles=in_store_articles,
    )

    if not items:
        if in_store_only and ushk_name:
            return NoPhotosQueueResult(
                [],
                path.name,
                f"Нет позиций без фото, которые есть на {ushk_name} (реестр, от 4 шт)",
            )
        return NoPhotosQueueResult(
            [],
            path.name,
            f"Для магазина {prefix} в {path.name} нет позиций (или всё уже снято)",
        )
    return NoPhotosQueueResult(items, path.name, "")


def load_no_photos_queue(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    limit: int = 80,
    in_store_only: bool = False,
    in_store_articles: frozenset[str] | None = None,
) -> list[NoPhotoItem]:
    path = _latest_no_photos_csv(runtime)
    if path is None:
        return []
    prefix = store_prefix.strip().lower()
    store = runtime.stores_config.get(store_prefix.strip())
    ushk_name = store.ushk_supplier if store else None

    registry: frozenset[str] | None = None
    if in_store_only:
        if in_store_articles is not None:
            registry = in_store_articles
        elif ushk_name:
            secrets = yaml.safe_load(runtime.secrets_file.read_text(encoding="utf-8")) or {}
            registry = fetch_articles_at_supplier(secrets, ushk_name)
        else:
            return []

    out: list[NoPhotoItem] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            stores = str(row.get("магазины", "")).lower()
            if prefix and prefix not in stores:
                continue
            article = str(row.get("артикул", "")).strip()
            if not article:
                continue
            if registry is not None and article not in registry:
                continue
            out.append(
                NoPhotoItem(
                    article=article,
                    nomenclature=str(row.get("номенклатура", "")).strip(),
                    stores=str(row.get("магазины", "")).strip(),
                    problem=str(row.get("проблема", "")).strip(),
                )
            )
            if len(out) >= limit:
                break
    return out


def next_photo_index(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
) -> int:
    art = validate_article(article)
    existing: set[int] = set()
    for idx in range(1, 20):
        rel = photo_relative_path(
            art,
            idx,
            store_prefix=store_prefix,
            photo_layout=runtime.photo_layout,
            prefix_in_filename=runtime.prefix_in_filename,
        )
        if (runtime.photos_dir / Path(rel)).is_file():
            existing.add(idx)
    for idx in range(1, 20):
        if idx not in existing:
            return idx
    return max(existing, default=0) + 1


def pending_photo_meta(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    index: int,
) -> PendingPhotoMeta:
    art = validate_article(article)
    if index < 1 or index > 19:
        raise ValueError("Номер фото: от 1 до 19")
    rel = photo_relative_path(
        art,
        index,
        store_prefix=store_prefix,
        photo_layout=runtime.photo_layout,
        prefix_in_filename=runtime.prefix_in_filename,
    )
    name = photo_filename(
        art,
        index,
        store_prefix=store_prefix,
        photo_layout=runtime.photo_layout,
        prefix_in_filename=runtime.prefix_in_filename,
    )
    return PendingPhotoMeta(index=index, relative_path=rel, filename=name)


def save_uploaded_photo(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    index: int,
    data: bytes,
) -> str:
    if len(data) > runtime.max_upload_bytes:
        raise ValueError(f"Файл больше {runtime.max_upload_bytes // (1024 * 1024)} МБ")
    art = validate_article(article)
    target = photo_target_path(
        runtime.photos_dir,
        art,
        index,
        store_prefix=store_prefix,
        photo_layout=runtime.photo_layout,
        prefix_in_filename=runtime.prefix_in_filename,
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".upload") as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        convert_image_to_jpeg(
            tmp_path,
            target,
            quality=runtime.jpeg_quality,
            max_dimension=runtime.jpeg_max_dimension,
        )
        compress_image_in_place(
            target,
            quality=runtime.jpeg_quality,
            max_dimension=runtime.jpeg_max_dimension,
            min_bytes=400_000,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    rel = photo_relative_path(
        art,
        index,
        store_prefix=store_prefix,
        photo_layout=runtime.photo_layout,
        prefix_in_filename=runtime.prefix_in_filename,
    )
    LOG.info("Фото загружено: %s (%s байт)", rel, target.stat().st_size)
    return rel


def save_upload_batch(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    items: list[tuple[int, bytes]],
) -> UploadResult:
    if not items:
        raise ValueError("Нет фото для отправки")
    saved: list[str] = []
    art = validate_article(article)
    for index, data in items:
        rel = save_uploaded_photo(
            runtime,
            store_prefix=store_prefix,
            article=art,
            index=index,
            data=data,
        )
        saved.append(rel)
    return UploadResult(saved=saved, article=art)
