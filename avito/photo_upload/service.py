"""Данные и сохранение фото для веб-загрузки."""
from __future__ import annotations

import csv
import logging
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from avito.manager_inbox import photo_filename, photo_relative_path, photo_target_path
from avito.photo_convert import compress_image_in_place, convert_image_to_jpeg
from avito.photo_upload.settings import PhotoUploadRuntime
from avito.stock_priority import is_seller_star_source
from avito.store_registry import fetch_articles_at_supplier
from avito.wheel_parse import is_tire_kind, is_wheel_kind

LOG = logging.getLogger(__name__)

_ARTICLE_RE = re.compile(r"^\d{4,}$")

# Fallback-кэш полного каталога (CSV / HTTP registry). Hot paths use SQL lookup/search.
_STOCK_CACHE: dict[str, tuple[float, float, list["StockItem"]]] = {}
_STOCK_CACHE_TTL_SEC = 120.0
MAX_UPLOAD_BATCH = 10
DEFAULT_SEARCH_LIMIT = 30
MAX_SEARCH_LIMIT = 50


def normalize_product_kind(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if is_wheel_kind(raw):
        return "wheel"
    return "tire"


def _kind_matches(row_kind: str, want: str) -> bool:
    want_n = normalize_product_kind(want)
    row_n = normalize_product_kind(row_kind)
    if want_n == "wheel":
        return is_wheel_kind(row_n)
    return is_tire_kind(row_n)


@dataclass(frozen=True)
class StockItem:
    article: str
    nomenclature: str
    quantity: str
    star: bool = False
    kind: str = "tire"


@dataclass(frozen=True)
class NoPhotoItem:
    article: str
    nomenclature: str
    stores: str
    problem: str
    star: bool = False
    kind: str = "tire"


@dataclass(frozen=True)
class PendingPhotoMeta:
    index: int
    relative_path: str
    filename: str


@dataclass(frozen=True)
class UploadResult:
    saved: list[str]
    article: str
    points_awarded: int = 0
    balance: int | None = None


def normalize_article(value: str) -> str:
    return str(value or "").strip()


def validate_article(value: str) -> str:
    art = normalize_article(value)
    if not _ARTICLE_RE.match(art):
        raise ValueError("Артикул: только цифры, минимум 4 символа")
    return art


def _stock_items(runtime: PhotoUploadRuntime) -> list[StockItem]:
    db_path = runtime.stock_db_path
    key = str(db_path.resolve()) if db_path else ""
    try:
        mtime = db_path.stat().st_mtime if db_path and db_path.is_file() else 0.0
    except OSError:
        mtime = 0.0
    now = time.time()
    cached = _STOCK_CACHE.get(key)
    if cached and cached[0] == mtime and now < cached[1]:
        return cached[2]

    if not db_path or not db_path.is_file():
        LOG.warning("Нет SQLite остатков: %s (нужен build_stock)", db_path)
        if cached:
            return cached[2]
        return []

    try:
        from avito.compare import load_stock_from_db

        rows = load_stock_from_db(db_path, schema_path=runtime.stock_db_schema)
        items = [
            StockItem(
                article=str(r.article).strip(),
                nomenclature=str(r.nomenclature).strip(),
                quantity=str(r.quantity).strip(),
                star=is_seller_star_source(r.source),
                kind=normalize_product_kind(getattr(r, "kind", "tire")),
            )
            for r in rows
            if str(r.article).strip()
        ]
    except Exception as exc:  # noqa: BLE001
        LOG.warning("Не удалось прочитать остатки из SQLite %s: %s", key, exc)
        if cached:
            return cached[2]
        return []

    _STOCK_CACHE[key] = (mtime, now + _STOCK_CACHE_TTL_SEC, items)
    return items


def _stock_item_from_db(row) -> StockItem:
    return StockItem(
        article=str(row.article).strip(),
        nomenclature=str(row.name).strip(),
        quantity=str(row.quantity).strip(),
        star=is_seller_star_source(row.source),
        kind=normalize_product_kind(getattr(row, "kind", "tire")),
    )


def _starred_articles(runtime: PhotoUploadRuntime) -> frozenset[str]:
    try:
        from avito.stock_db import starred_articles, stock_connection

        with stock_connection(
            runtime.stock_db_path, schema_path=runtime.stock_db_schema
        ) as conn:
            return starred_articles(conn)
    except Exception:
        return frozenset(row.article for row in _stock_items(runtime) if row.star)


def lookup_stock(
    runtime: PhotoUploadRuntime,
    article: str,
    *,
    kind: str = "tire",
) -> StockItem | None:
    art = normalize_article(article)
    if not art:
        return None
    want = normalize_product_kind(kind)
    try:
        from avito.stock_db import lookup, stock_connection

        with stock_connection(
            runtime.stock_db_path, schema_path=runtime.stock_db_schema
        ) as conn:
            row = lookup(conn, art)
        if row is not None:
            return _stock_item_from_db(row)
        return None
    except Exception as exc:  # noqa: BLE001
        LOG.warning("SQL lookup_stock failed, fallback: %s", exc)
    for row in _stock_items(runtime):
        if row.article == art and _kind_matches(row.kind, want):
            return row
    for row in _stock_items(runtime):
        if row.article == art:
            return row
    return None


def search_stock(
    runtime: PhotoUploadRuntime,
    query: str,
    *,
    limit: int = DEFAULT_SEARCH_LIMIT,
    kind: str = "tire",
) -> list[StockItem]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    want = normalize_product_kind(kind)
    limit_n = max(1, min(int(limit or DEFAULT_SEARCH_LIMIT), MAX_SEARCH_LIMIT))
    try:
        from avito.stock_db import search, stock_connection

        with stock_connection(
            runtime.stock_db_path, schema_path=runtime.stock_db_schema
        ) as conn:
            rows = search(conn, q, limit=limit_n, kind=want)
        return [_stock_item_from_db(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        LOG.warning("SQL search_stock failed, fallback: %s", exc)
    out: list[StockItem] = []
    for row in _stock_items(runtime):
        if not _kind_matches(row.kind, want):
            continue
        hay = f"{row.article} {row.nomenclature}".lower()
        if q in hay:
            out.append(row)
            if len(out) >= limit_n:
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
    ushk_supplier: str | None = None,
    kind: str = "tire",
) -> NoPhotosQueueResult:
    from avito.stock_db import get_meta, no_photos_count, stock_connection

    prefix = store_prefix.strip()
    store = runtime.stores_config.get(prefix) if prefix else None
    ushk_name = (ushk_supplier or "").strip() or (
        store.ushk_supplier if store else None
    )
    want = normalize_product_kind(kind)
    kind_label = "дисков" if want == "wheel" else "шин"

    source_name: str | None = None
    with stock_connection(
        runtime.stock_db_path, schema_path=runtime.stock_db_schema
    ) as conn:
        built_at = (get_meta(conn, "no_photos_built_at") or "").strip()
        n_queue = no_photos_count(conn, kind=want)
    if not built_at and n_queue <= 0:
        csv_path = _latest_no_photos_csv(runtime)
        if csv_path is None:
            return NoPhotosQueueResult(
                [],
                None,
                "Список ещё не собран. На сервере запустите: build_stock → compare_prices → build_autoload",
            )
        source_name = csv_path.name
    else:
        source_name = f"no_photos_queue@{built_at or 'sqlite'}"

    if in_store_only and not ushk_name:
        return NoPhotosQueueResult(
            [],
            source_name,
            (
                f"Для магазина {prefix} не задан ushk_supplier в stores.yaml"
                if prefix
                else "У сотрудника не указан магазин (склад УШК)"
            ),
        )

    items = load_no_photos_queue(
        runtime,
        store_prefix=store_prefix,
        limit=limit,
        in_store_only=in_store_only,
        in_store_articles=in_store_articles,
        ushk_supplier=ushk_name,
        kind=want,
    )

    if not items:
        if in_store_only and ushk_name:
            return NoPhotosQueueResult(
                [],
                source_name,
                f"Нет {kind_label} без фото на {ushk_name} (реестр, от 4 шт)",
            )
        if prefix:
            return NoPhotosQueueResult(
                [],
                source_name,
                f"Для магазина {prefix} в {source_name} нет {kind_label} без фото",
            )
        return NoPhotosQueueResult(
            [],
            source_name,
            f"В {source_name} нет {kind_label} без фото",
        )
    return NoPhotosQueueResult(items, source_name, "")


def load_no_photos_queue(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    limit: int = 80,
    in_store_only: bool = False,
    in_store_articles: frozenset[str] | None = None,
    ushk_supplier: str | None = None,
    kind: str = "tire",
) -> list[NoPhotoItem]:
    from avito.stock_db import query_no_photos, stock_connection

    prefix = store_prefix.strip().lower()
    store = runtime.stores_config.get(store_prefix.strip()) if store_prefix.strip() else None
    ushk_name = (ushk_supplier or "").strip() or (
        store.ushk_supplier if store else None
    )
    want = normalize_product_kind(kind)

    limit_n = int(limit) if limit else 80
    if limit_n <= 0:
        limit_n = 80
    limit_n = min(limit_n, 200)

    kind_articles: frozenset[str] | None = None
    registry: frozenset[str] | None = None
    if in_store_only:
        if in_store_articles is not None:
            registry = in_store_articles
        elif ushk_name:
            secrets = yaml.safe_load(runtime.secrets_file.read_text(encoding="utf-8")) or {}
            # Postgres фильтрует tire/wheel сам; Excel нужен только для HTTP.
            via = str((secrets.get("db") or {}).get("register_via") or "").strip().lower()
            if via in ("http", "https", "api"):
                # Avoid full catalog: SQL articles by kind
                try:
                    from avito.stock_db import stock_connection

                    with stock_connection(
                        runtime.stock_db_path, schema_path=runtime.stock_db_schema
                    ) as conn:
                        rows = conn.execute(
                            "SELECT article FROM stock_items WHERE kind = ?",
                            (want,),
                        ).fetchall()
                    kind_articles = frozenset(
                        str(r["article"] or "").strip() for r in rows if r["article"]
                    )
                except Exception:
                    kind_articles = frozenset(
                        row.article
                        for row in _stock_items(runtime)
                        if _kind_matches(row.kind, want)
                    )
            registry = fetch_articles_at_supplier(
                secrets,
                ushk_name,
                product_kind=want,
                kind_articles=kind_articles,
            )
        else:
            return []

    starred = _starred_articles(runtime)

    with stock_connection(
        runtime.stock_db_path, schema_path=runtime.stock_db_schema
    ) as conn:
        db_rows = query_no_photos(
            conn,
            store_prefix=store_prefix.strip(),
            limit=limit_n,
            allowed_articles=registry,
            kind=want,
        )

    out: list[NoPhotoItem] = []
    if db_rows:
        for row in db_rows:
            article = row.article
            if not article:
                continue
            row_kind = normalize_product_kind(row.kind) if row.kind else want
            out.append(
                NoPhotoItem(
                    article=article,
                    nomenclature=row.nomenclature,
                    stores=row.stores,
                    problem=row.problem,
                    star=article in starred,
                    kind=row_kind,
                )
            )
            if len(out) >= limit_n:
                break
        return out

    if kind_articles is None:
        try:
            from avito.stock_db import stock_connection as _sc

            with _sc(
                runtime.stock_db_path, schema_path=runtime.stock_db_schema
            ) as conn:
                rows = conn.execute(
                    "SELECT article FROM stock_items WHERE kind = ?",
                    (want,),
                ).fetchall()
            kind_articles = frozenset(
                str(r["article"] or "").strip() for r in rows if r["article"]
            )
        except Exception:
            kind_articles = frozenset(
                row.article for row in _stock_items(runtime) if _kind_matches(row.kind, want)
            )
    path = _latest_no_photos_csv(runtime)
    if path is None:
        return []
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
            row_kind = str(row.get("kind", "") or "").strip()
            if row_kind:
                if not _kind_matches(row_kind, want):
                    continue
            elif kind_articles and article not in kind_articles:
                continue
            elif not row_kind and want == "wheel":
                continue
            out.append(
                NoPhotoItem(
                    article=article,
                    nomenclature=str(row.get("номенклатура", "")).strip(),
                    stores=str(row.get("магазины", "")).strip(),
                    problem=str(row.get("проблема", "")).strip(),
                    star=article in starred,
                    kind=normalize_product_kind(row_kind) if row_kind else want,
                )
            )
            if len(out) >= limit_n:
                break
    return out


def next_photo_index(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    max_index: int | None = None,
    product_kind: str = "tire",
) -> int:
    art = validate_article(article)
    kind = normalize_product_kind(product_kind)
    limit = max_index if max_index is not None else 19
    limit = max(1, min(int(limit), 19))
    existing: set[int] = set()
    for idx in range(1, limit + 1):
        rel = photo_relative_path(
            art,
            idx,
            store_prefix=store_prefix,
            photo_layout=runtime.photo_layout,
            prefix_in_filename=runtime.prefix_in_filename,
            product_kind=kind,
        )
        if (runtime.photos_dir / Path(rel)).is_file():
            existing.add(idx)
    for idx in range(1, limit + 1):
        if idx not in existing:
            return idx
    raise ValueError(f"Уже есть {limit} фото для артикула {art}")


def pending_photo_meta(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    index: int,
    max_index: int | None = None,
    product_kind: str = "tire",
) -> PendingPhotoMeta:
    art = validate_article(article)
    kind = normalize_product_kind(product_kind)
    limit = max_index if max_index is not None else 19
    limit = max(1, min(int(limit), 19))
    if index < 1 or index > limit:
        raise ValueError(f"Номер фото: от 1 до {limit}")
    rel = photo_relative_path(
        art,
        index,
        store_prefix=store_prefix,
        photo_layout=runtime.photo_layout,
        prefix_in_filename=runtime.prefix_in_filename,
        product_kind=kind,
    )
    name = photo_filename(
        art,
        index,
        store_prefix=store_prefix,
        photo_layout=runtime.photo_layout,
        prefix_in_filename=runtime.prefix_in_filename,
    )
    return PendingPhotoMeta(index=index, relative_path=rel, filename=name)


def photo_slot_exists(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    index: int,
    product_kind: str = "tire",
) -> bool:
    kind = normalize_product_kind(product_kind)
    rel = photo_relative_path(
        article,
        index,
        store_prefix=store_prefix,
        photo_layout=runtime.photo_layout,
        prefix_in_filename=runtime.prefix_in_filename,
        product_kind=kind,
    )
    return (runtime.photos_dir / Path(rel)).is_file()


def save_uploaded_photo(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    index: int,
    data: bytes,
    max_index: int | None = None,
    product_kind: str = "tire",
) -> tuple[str, bool]:
    """Сохранить фото. Возвращает (relative_path, was_new_slot)."""
    if len(data) > runtime.max_upload_bytes:
        raise ValueError(f"Файл больше {runtime.max_upload_bytes // (1024 * 1024)} МБ")
    art = validate_article(article)
    kind = normalize_product_kind(product_kind)
    limit = max_index if max_index is not None else 19
    if index < 1 or index > limit:
        raise ValueError(f"Номер фото: от 1 до {limit}")
    was_new = not photo_slot_exists(
        runtime,
        store_prefix=store_prefix,
        article=art,
        index=index,
        product_kind=kind,
    )
    target = photo_target_path(
        runtime.photos_dir,
        art,
        index,
        store_prefix=store_prefix,
        photo_layout=runtime.photo_layout,
        prefix_in_filename=runtime.prefix_in_filename,
        product_kind=kind,
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".upload") as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        # Single Pillow pass: convert already applies quality + max_dimension.
        convert_image_to_jpeg(
            tmp_path,
            target,
            quality=runtime.jpeg_quality,
            max_dimension=runtime.jpeg_max_dimension,
        )
        # Second pass only if convert could not resize (max_dimension unset)
        # and the file is still huge.
        if runtime.jpeg_max_dimension <= 0 and target.stat().st_size >= 400_000:
            compress_image_in_place(
                target,
                quality=runtime.jpeg_quality,
                max_dimension=1920,
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
        product_kind=kind,
    )
    LOG.info("Фото загружено: %s (%s байт)", rel, target.stat().st_size)
    return rel, was_new


def save_upload_batch(
    runtime: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    items: list[tuple[int, bytes]],
    max_index: int | None = None,
    contributor_user_id: int | None = None,
    product_kind: str = "tire",
) -> UploadResult:
    if not items:
        raise ValueError("Нет фото для отправки")
    if len(items) > MAX_UPLOAD_BATCH:
        raise ValueError(f"За один раз не больше {MAX_UPLOAD_BATCH} фото")
    saved: list[str] = []
    points = 0
    art = validate_article(article)
    kind = normalize_product_kind(product_kind)
    from avito.photo_upload import db as photo_db

    for index, data in items:
        rel, was_new = save_uploaded_photo(
            runtime,
            store_prefix=store_prefix,
            article=art,
            index=index,
            data=data,
            max_index=max_index,
            product_kind=kind,
        )
        saved.append(rel)
        if (
            contributor_user_id is not None
            and was_new
            and runtime.points_per_photo > 0
        ):
            with runtime.db() as conn:
                photo_db.add_points(
                    conn,
                    user_id=contributor_user_id,
                    delta=runtime.points_per_photo,
                    reason="Загрузка фото",
                    article=art,
                    photo_index=index,
                )
            points += runtime.points_per_photo

    balance = None
    if contributor_user_id is not None:
        with runtime.db() as conn:
            balance = photo_db.user_balance(conn, contributor_user_id)

    return UploadResult(
        saved=saved, article=art, points_awarded=points, balance=balance
    )


def article_from_photo_filename(name: str, store_prefixes: list[str]) -> str | None:
    """Извлечь артикул из имени файла: md122062-1.jpg → 122062."""
    stem = Path(name).stem.strip()
    if not stem:
        return None
    low = stem.lower()
    for prefix in store_prefixes:
        p = prefix.strip().lower()
        if (
            p
            and low.startswith(p)
            and len(low) > len(p)
            and low[len(p)].isdigit()
        ):
            stem = stem[len(prefix) :]
            break
    m = re.match(r"^(\d{4,})(?:-\d+)?$", stem)
    return m.group(1) if m else None


def _scan_photo_index(
    runtime: PhotoUploadRuntime, *, folder: str = ""
) -> dict[str, dict]:
    """article → {photo_count, folders, mtime} по файлам на диске."""
    root = runtime.photos_dir
    if not root.is_dir():
        return {}
    store_prefixes = [s.prefix for s in runtime.stores]
    folder_f = folder.strip().lower()
    if folder_f == runtime.contributors_prefix:
        search_dirs = [root / runtime.contributors_prefix]
    elif folder_f and folder_f in store_prefixes:
        search_dirs = [root / folder_f]
    else:
        search_dirs = [root / f for f in store_prefixes]
        search_dirs.append(root / runtime.contributors_prefix)

    by_article: dict[str, dict] = {}
    for d in search_dirs:
        if not d.is_dir():
            continue
        for path in d.glob("*.jpg"):
            art = article_from_photo_filename(path.name, store_prefixes)
            if not art:
                continue
            entry = by_article.get(art)
            if entry is None:
                entry = {"photo_count": 0, "folders": set(), "mtime": 0}
                by_article[art] = entry
            entry["photo_count"] += 1
            entry["folders"].add(path.parent.name)
            mtime = int(path.stat().st_mtime)
            if mtime > entry["mtime"]:
                entry["mtime"] = mtime
    return by_article


def list_products(
    runtime: PhotoUploadRuntime,
    *,
    folder: str = "",
    query: str = "",
    only_manual: bool = False,
    has_photos: str = "",
    limit: int = 300,
) -> tuple[list[dict], int]:
    """
    Товары из остатков (SQLite) + фото/ручные/расчётные цены.
    has_photos: "" | "1" | "0"
    Возвращает (items, total_before_limit).
    """
    from avito.stock_db import (
        iter_items,
        load_manual_prices_map,
        load_posting_dataframe,
        stock_connection,
    )

    photos = _scan_photo_index(runtime, folder=folder)
    manuals: dict[str, float] = {}
    posting_price: dict[str, tuple[float | None, str]] = {}
    stock_rows: list[tuple[str, str, float]] = []

    with stock_connection(
        runtime.stock_db_path, schema_path=runtime.stock_db_schema
    ) as conn:
        manuals = load_manual_prices_map(conn)
        for item in iter_items(conn):
            stock_rows.append((item.article, item.name, float(item.price)))
        try:
            pdf = load_posting_dataframe(conn)
        except Exception:
            pdf = None
        if pdf is not None and not pdf.empty:
            for _, row in pdf.iterrows():
                a = str(row.get("артикул") or "").strip()
                if a.endswith(".0"):
                    try:
                        a = str(int(float(a)))
                    except (ValueError, TypeError):
                        pass
                if not a:
                    continue
                try:
                    price = float(row.get("recommended_price"))
                except (TypeError, ValueError):
                    price = None
                rule = str(row.get("price_rule") or "").strip()
                posting_price[a] = (price, rule)

    stock_arts = {a for a, _, _ in stock_rows}
    for art, price in manuals.items():
        if art not in stock_arts:
            stock_rows.append((art, "", 0.0))

    q = query.strip().lower()
    photos_filter = str(has_photos or "").strip()
    matched: list[dict] = []
    for art, name, incoming in sorted(stock_rows, key=lambda x: x[0]):
        photo = photos.get(art) or {}
        photo_count = int(photo.get("photo_count") or 0)
        manual = manuals.get(art)
        calc, rule = posting_price.get(art, (None, ""))
        if calc is None and incoming > 0 and manual is None:
            from datetime import date

            from avito.pricing import recommend_price

            calc = float(
                recommend_price(
                    incoming,
                    None,
                    seed=art,
                    date_key=date.today().isoformat(),
                ).recommended_price
            )
            rule = "markup_x1.15"
        if only_manual and manual is None:
            continue
        if photos_filter == "1" and photo_count <= 0:
            continue
        if photos_filter == "0" and photo_count > 0:
            continue
        if q and q not in art.lower() and q not in (name or "").lower():
            continue
        matched.append(
            {
                "article": art,
                "nomenclature": name,
                "incoming": incoming or None,
                "photo_count": photo_count,
                "folders": sorted(photo.get("folders") or []),
                "mtime": int(photo.get("mtime") or 0),
                "manual_price": manual,
                "calculated_price": calc,
                "price_rule": "manual" if manual is not None else rule,
                "effective_price": manual if manual is not None else calc,
                "has_photos": photo_count > 0,
            }
        )

    total = len(matched)
    limit_n = max(0, int(limit)) if limit is not None else 0
    if limit_n > 0:
        matched = matched[:limit_n]
    return matched, total


def list_photo_files(
    runtime: PhotoUploadRuntime,
    *,
    folder: str = "",
    article: str = "",
    limit: int = 80,
) -> list[dict]:
    """Список файлов в photos_dir для админки."""
    root = runtime.photos_dir
    if not root.is_dir():
        return []
    folders = [runtime.contributors_prefix] + [s.prefix for s in runtime.stores]
    folder = folder.strip().lower()
    art = article.strip()
    out: list[dict] = []
    search_dirs: list[Path]
    if folder and folder in folders:
        search_dirs = [root / folder]
    else:
        search_dirs = [root / f for f in folders]
    for d in search_dirs:
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True):
            name = path.name
            if art and not (name.startswith(art + ".") or name.startswith(art + "-")):
                continue
            rel = path.relative_to(root).as_posix()
            st = path.stat()
            out.append(
                {
                    "relative_path": rel,
                    "folder": path.parent.name,
                    "filename": name,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                }
            )
            if len(out) >= limit:
                return out
    return out


def delete_photo_file(runtime: PhotoUploadRuntime, relative_path: str) -> str:
    rel = Path(relative_path.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Некорректный путь")
    target = (runtime.photos_dir / rel).resolve()
    root = runtime.photos_dir.resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("Путь вне папки фото")
    if not target.is_file():
        raise ValueError("Файл не найден")
    target.unlink()
    return rel.as_posix()
