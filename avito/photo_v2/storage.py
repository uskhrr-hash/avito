"""Thin storage helpers for Photo v2 — reuse photo_upload disk/stock logic, no admin UI."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avito.photo_upload.service import (
    MAX_UPLOAD_BATCH,
    delete_photo_file,
    list_photo_files,
    load_no_photos_queue,
    lookup_stock,
    next_photo_index,
    normalize_product_kind,
    pending_photo_meta,
    save_upload_batch,
    search_stock,
    validate_article,
)
from avito.photo_upload.settings import PhotoUploadRuntime, load_photo_upload_runtime

STORE_MAX_INDEX = 19
PHOTOS_PUBLIC_PREFIX = "/photos/"
ARTICLES_DEFAULT_LIMIT = 40
ARTICLES_MAX_LIMIT = 80
LISTINGS_DEFAULT_LIMIT = 40
LISTINGS_MAX_LIMIT = 80
PHOTOS_DEFAULT_LIMIT = 40
PHOTOS_MAX_LIMIT = 80
NOMENCLATURE_SHORT = 80


@dataclass(frozen=True)
class LookupResult:
    article: str
    kind: str
    found: bool
    nomenclature: str
    quantity: str
    star: bool
    next_index: int
    filename: str
    relative_path: str
    folder: str


@dataclass(frozen=True)
class ArticleLight:
    """Slim row for picker / typeahead — no full catalog payload."""

    article: str
    kind: str
    nomenclature: str = ""
    quantity: str = ""
    photo_count: int | None = None


@dataclass(frozen=True)
class ArticlesPage:
    items: list[ArticleLight]
    limit: int
    offset: int
    has_more: bool
    mode: str  # search | need_photos


@dataclass(frozen=True)
class ListingLight:
    """Slim row for Товары tab — no mtime / full catalog payload."""

    article: str
    kind: str
    nomenclature: str = ""
    photo_count: int = 0
    folders: tuple[str, ...] = ()
    incoming: float | None = None
    manual_price: float | None = None
    calculated_price: float | None = None
    price_rule: str = ""


@dataclass(frozen=True)
class ListingsPage:
    items: list[ListingLight]
    limit: int
    offset: int
    has_more: bool
    total: int


@dataclass(frozen=True)
class PhotoFileLight:
    relative_path: str
    folder: str
    filename: str
    size: int = 0


@dataclass(frozen=True)
class PhotosPage:
    items: list[PhotoFileLight]
    limit: int
    offset: int
    has_more: bool


def load_storage_runtime(
    *,
    config_path: Path,
    project_root: Path | None = None,
) -> PhotoUploadRuntime:
    """Same photos_dir / stock DB / layout as v1 — feeds keep working."""
    return load_photo_upload_runtime(
        config_path=config_path,
        project_root=project_root,
    )


def aggregate_lookup(
    storage: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    kind: str = "tire",
) -> LookupResult:
    """ONE call: stock existence + next free index + folder/path.

    Articles do not overlap tire/wheel — stock row kind wins when found.
    """
    art = validate_article(article)
    prefer = str(kind or "").strip().lower()
    product_kind = (
        normalize_product_kind(prefer) if prefer in ("tire", "wheel") else "tire"
    )
    stock = lookup_stock(storage, art, kind=product_kind)
    resolved_kind = (
        normalize_product_kind(getattr(stock, "kind", None) or product_kind)
        if stock
        else product_kind
    )
    idx = next_photo_index(
        storage,
        store_prefix=store_prefix,
        article=art,
        max_index=STORE_MAX_INDEX,
        product_kind=resolved_kind,
    )
    meta = pending_photo_meta(
        storage,
        store_prefix=store_prefix,
        article=art,
        index=idx,
        max_index=STORE_MAX_INDEX,
        product_kind=resolved_kind,
    )
    rel = str(meta.relative_path).replace("\\", "/")
    folder = "/".join(rel.split("/")[:-1]) if "/" in rel else store_prefix
    return LookupResult(
        article=art,
        kind=resolved_kind,
        found=stock is not None,
        nomenclature=(stock.nomenclature if stock else ""),
        quantity=(stock.quantity if stock else ""),
        star=bool(stock.star) if stock else False,
        next_index=meta.index,
        filename=meta.filename,
        relative_path=rel,
        folder=folder,
    )


def save_store_uploads(
    storage: PhotoUploadRuntime,
    *,
    store_prefix: str,
    article: str,
    items: list[tuple[int, bytes]],
    kind: str = "tire",
):
    """Write JPEG(s) to the same disk layout as v1. No points / contributors."""
    product_kind = normalize_product_kind(kind)
    return save_upload_batch(
        storage,
        store_prefix=store_prefix,
        article=article,
        items=items,
        max_index=STORE_MAX_INDEX,
        contributor_user_id=None,
        product_kind=product_kind,
    )


def _short_name(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= NOMENCLATURE_SHORT:
        return text
    return text[: NOMENCLATURE_SHORT - 1].rstrip() + "…"


def list_articles_light(
    storage: PhotoUploadRuntime,
    *,
    store_prefix: str,
    q: str = "",
    kind: str = "tire",
    limit: int = ARTICLES_DEFAULT_LIMIT,
    offset: int = 0,
    need_photos: bool = False,
) -> ArticlesPage:
    """Light article list for picker. Does not load full catalog.

    need_photos=True → no-photos queue (photo_upload).
    else q → stock search. Empty q without need_photos → empty page.
    """
    product_kind = normalize_product_kind(kind)
    limit_n = max(1, min(int(limit or ARTICLES_DEFAULT_LIMIT), ARTICLES_MAX_LIMIT))
    offset_n = max(0, int(offset or 0))
    query = str(q or "").strip()
    fetch_n = offset_n + limit_n + 1

    if need_photos:
        # Pagination via over-fetch + slice (queue API has no offset).
        rows = load_no_photos_queue(
            storage,
            store_prefix=store_prefix,
            limit=fetch_n,
            in_store_only=False,
            kind=product_kind,
        )
        page = rows[offset_n : offset_n + limit_n]
        items = [
            ArticleLight(
                article=r.article,
                kind=normalize_product_kind(r.kind) if r.kind else product_kind,
                nomenclature=_short_name(r.nomenclature),
                quantity="",
                photo_count=0,
            )
            for r in page
        ]
        return ArticlesPage(
            items=items,
            limit=limit_n,
            offset=offset_n,
            has_more=len(rows) > offset_n + limit_n,
            mode="need_photos",
        )

    if not query:
        return ArticlesPage(
            items=[],
            limit=limit_n,
            offset=offset_n,
            has_more=False,
            mode="search",
        )

    rows = search_stock(
        storage,
        query,
        limit=fetch_n,
        kind=product_kind,
    )
    page = rows[offset_n : offset_n + limit_n]
    items = [
        ArticleLight(
            article=r.article,
            kind=normalize_product_kind(r.kind) if r.kind else product_kind,
            nomenclature=_short_name(r.nomenclature),
            quantity=str(r.quantity or "").strip(),
            photo_count=None,
        )
        for r in page
    ]
    return ArticlesPage(
        items=items,
        limit=limit_n,
        offset=offset_n,
        has_more=len(rows) > offset_n + limit_n,
        mode="search",
    )


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def list_listings_page(
    storage: PhotoUploadRuntime,
    *,
    kind: str = "",
    limit: int = LISTINGS_DEFAULT_LIMIT,
    offset: int = 0,
    q: str = "",
) -> ListingsPage:
    """Slim listings for Товары.

    Same disk/stock as v1: photo index + prices via photo_upload helpers.
    kind empty/omitted → no tire|wheel filter (articles do not overlap).
    """
    from avito.photo_upload.service import _cached_photo_index
    from avito.pricing import recommend_price
    from avito.stock_db import load_posting_prices_map, stock_connection

    raw_kind = str(kind or "").strip().lower()
    product_kind = (
        normalize_product_kind(raw_kind) if raw_kind in ("tire", "wheel") else ""
    )
    limit_n = max(1, min(int(limit or LISTINGS_DEFAULT_LIMIT), LISTINGS_MAX_LIMIT))
    offset_n = max(0, int(offset or 0))
    query = str(q or "").strip().lower()

    photos = _cached_photo_index(storage, folder="")

    with stock_connection(
        storage.stock_db_path, schema_path=storage.stock_db_schema
    ) as conn:
        cols = {
            str(r[1]) for r in conn.execute("PRAGMA table_info(stock_items)").fetchall()
        }
        has_kind = "kind" in cols
        where: list[str] = []
        params: list[Any] = []
        if has_kind and product_kind:
            where.append("s.kind = ?")
            params.append(product_kind)
        if query:
            where.append("(lower(s.article) LIKE ? OR lower(s.name) LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        kind_select = ", s.kind AS kind" if has_kind else ""
        base = f"""
            SELECT s.article AS article,
                   s.name AS name,
                   s.price AS price,
                   m.price AS manual_price{kind_select}
            FROM stock_items s
            LEFT JOIN manual_prices m ON m.article = s.article
            {where_sql}
        """
        total_n = int(
            conn.execute(f"SELECT COUNT(*) AS n FROM ({base})", params).fetchone()["n"]
        )
        rows_sql = base + " ORDER BY s.article LIMIT ? OFFSET ?"
        raw = conn.execute(rows_sql, [*params, limit_n, offset_n]).fetchall()
        arts = [str(r["article"] or "").strip() for r in raw if r["article"]]
        try:
            posting_price = load_posting_prices_map(conn, arts) if arts else {}
        except Exception:  # noqa: BLE001 — same fallback as list_products
            posting_price = {}

    page_raw: list[dict[str, Any]] = []
    for row in raw:
        art = str(row["article"] or "").strip()
        if not art:
            continue
        name = str(row["name"] or "").strip()
        incoming = float(row["price"] or 0)
        manual = row["manual_price"]
        if manual is not None:
            try:
                manual = float(manual)
            except (TypeError, ValueError):
                manual = None
        photo = photos.get(art) or {}
        photo_count = int(photo.get("photo_count") or 0)
        calc, rule = posting_price.get(art, (None, ""))
        if calc is None and incoming > 0 and manual is None:
            calc = float(recommend_price(incoming).recommended_price)
            rule = "markup_x1.15"
        row_kind = product_kind or "tire"
        if has_kind:
            try:
                row_kind = normalize_product_kind(row["kind"] or product_kind or "tire")
            except (KeyError, IndexError, TypeError):
                row_kind = product_kind or "tire"
        page_raw.append(
            {
                "article": art,
                "kind": row_kind,
                "nomenclature": name,
                "incoming": incoming or None,
                "photo_count": photo_count,
                "folders": sorted(photo.get("folders") or []),
                "manual_price": manual,
                "calculated_price": calc,
                "price_rule": "manual" if manual is not None else (rule or ""),
            }
        )

    items = [
        ListingLight(
            article=str(r.get("article") or "").strip(),
            kind=normalize_product_kind(str(r.get("kind") or "tire")),
            nomenclature=_short_name(str(r.get("nomenclature") or "")),
            photo_count=int(r.get("photo_count") or 0),
            folders=tuple(str(x) for x in (r.get("folders") or [])),
            incoming=_opt_float(r.get("incoming")),
            manual_price=_opt_float(r.get("manual_price")),
            calculated_price=_opt_float(r.get("calculated_price")),
            price_rule=str(r.get("price_rule") or ""),
        )
        for r in page_raw
    ]
    return ListingsPage(
        items=items,
        limit=limit_n,
        offset=offset_n,
        has_more=offset_n + len(items) < total_n,
        total=total_n,
    )


def list_photos_page(
    storage: PhotoUploadRuntime,
    *,
    store_prefix: str,
    folder: str = "",
    article: str = "",
    limit: int = PHOTOS_DEFAULT_LIMIT,
    offset: int = 0,
) -> PhotosPage:
    """Photo files for one shop folder only (no cross-shop). Same disk as v1."""
    store = str(store_prefix or "").strip().lower()
    if not store:
        raise ValueError("Нет магазина")
    want = str(folder or "").strip().lower()
    # Manager may filter within own folder only; empty → own store.
    if want and want != store:
        raise ValueError("Чужие папки недоступны")
    limit_n = max(1, min(int(limit or PHOTOS_DEFAULT_LIMIT), PHOTOS_MAX_LIMIT))
    offset_n = max(0, int(offset or 0))
    rows, has_more = list_photo_files(
        storage,
        folder=store,
        article=str(article or "").strip(),
        limit=limit_n,
        offset=offset_n,
    )
    items = [
        PhotoFileLight(
            relative_path=str(r.get("relative_path") or "").replace("\\", "/"),
            folder=str(r.get("folder") or ""),
            filename=str(r.get("filename") or ""),
            size=int(r.get("size") or 0),
        )
        for r in rows
        if r.get("relative_path")
    ]
    return PhotosPage(
        items=items,
        limit=limit_n,
        offset=offset_n,
        has_more=bool(has_more),
    )


@dataclass(frozen=True)
class DeletePhotoResult:
    deleted: str
    missing: bool = False


def delete_store_photo(
    storage: PhotoUploadRuntime,
    *,
    store_prefix: str,
    relative_path: str,
) -> DeletePhotoResult:
    """Delete one photo under the shop folder; soft-ok if already gone.

    Mirrors v1 ``delete_photo_file`` (unlink + photo index cache invalidate).
    Rejects paths outside ``{store_prefix}/``.
    """
    store = str(store_prefix or "").strip().lower()
    if not store:
        raise ValueError("Нет магазина")
    rel = str(relative_path or "").replace("\\", "/").strip().lstrip("/")
    if not rel or ".." in Path(rel).parts or Path(rel).is_absolute():
        raise ValueError("Некорректный путь")
    parts = Path(rel).parts
    if not parts or parts[0].lower() != store:
        raise ValueError("Чужие фото недоступны")
    try:
        deleted = delete_photo_file(storage, rel)
        return DeletePhotoResult(deleted=deleted, missing=False)
    except ValueError as exc:
        msg = str(exc)
        if "не найден" in msg.lower() or "not found" in msg.lower():
            return DeletePhotoResult(deleted=rel, missing=True)
        raise


__all__ = [
    "ARTICLES_DEFAULT_LIMIT",
    "ARTICLES_MAX_LIMIT",
    "LISTINGS_DEFAULT_LIMIT",
    "LISTINGS_MAX_LIMIT",
    "PHOTOS_DEFAULT_LIMIT",
    "PHOTOS_MAX_LIMIT",
    "ArticleLight",
    "ArticlesPage",
    "ListingLight",
    "ListingsPage",
    "DeletePhotoResult",
    "PhotoFileLight",
    "PhotosPage",
    "PHOTOS_PUBLIC_PREFIX",
    "STORE_MAX_INDEX",
    "LookupResult",
    "MAX_UPLOAD_BATCH",
    "aggregate_lookup",
    "delete_store_photo",
    "list_articles_light",
    "list_listings_page",
    "list_photos_page",
    "load_storage_runtime",
    "normalize_product_kind",
    "save_store_uploads",
    "validate_article",
]
