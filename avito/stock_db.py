"""Локальный SQLite-кэш остатков (ERP + Google → build_stock)."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

LOG = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stock_items (
    article           TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    quantity          TEXT NOT NULL DEFAULT '',
    price             REAL NOT NULL,
    source            TEXT NOT NULL DEFAULT '',
    avito_price       REAL,
    ushk_in_stock     INTEGER NOT NULL DEFAULT 0,
    sam_mb_cash_price INTEGER NOT NULL DEFAULT 0,
    kind              TEXT NOT NULL DEFAULT 'tire',
    brand             TEXT NOT NULL DEFAULT '',
    model             TEXT NOT NULL DEFAULT '',
    wheel_type        TEXT NOT NULL DEFAULT '',
    width             TEXT NOT NULL DEFAULT '',
    diameter          TEXT NOT NULL DEFAULT '',
    studs             TEXT NOT NULL DEFAULT '',
    circle            TEXT NOT NULL DEFAULT '',
    et                TEXT NOT NULL DEFAULT '',
    hub               TEXT NOT NULL DEFAULT '',
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stock_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS no_photos_queue (
    article       TEXT PRIMARY KEY,
    nomenclature  TEXT NOT NULL DEFAULT '',
    stores        TEXT NOT NULL DEFAULT '',
    problem       TEXT NOT NULL DEFAULT '',
    kind          TEXT NOT NULL DEFAULT 'tire',
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_no_photos_stores ON no_photos_queue (stores);

CREATE TABLE IF NOT EXISTS posting_items (
    article              TEXT PRIMARY KEY,
    nomenclature         TEXT NOT NULL,
    quantity             TEXT NOT NULL DEFAULT '',
    incoming             REAL NOT NULL,
    on_avito             INTEGER NOT NULL DEFAULT 0,
    ushk_in_stock        INTEGER NOT NULL DEFAULT 0,
    sam_mb_cash_price    INTEGER NOT NULL DEFAULT 0,
    avito_min            REAL,
    avito_price_fixed    REAL,
    recommended_price    REAL NOT NULL,
    price_rule           TEXT NOT NULL DEFAULT '',
    discount_pct         REAL,
    floor_price          REAL,
    duplicate            INTEGER NOT NULL DEFAULT 0,
    kind                 TEXT NOT NULL DEFAULT 'tire',
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS posting_aux (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS missing_models (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS avito_ids (
    article    TEXT PRIMARY KEY,
    avito_id   TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS listings (
    listing_id        TEXT PRIMARY KEY,
    article_id        TEXT NOT NULL,
    avito_id          TEXT NOT NULL DEFAULT '',
    title             TEXT NOT NULL DEFAULT '',
    price             REAL,
    photo_urls        TEXT NOT NULL DEFAULT '',
    description_html  TEXT NOT NULL DEFAULT '',
    store_key         TEXT NOT NULL DEFAULT '',
    brand             TEXT NOT NULL DEFAULT '',
    model             TEXT NOT NULL DEFAULT '',
    width             TEXT NOT NULL DEFAULT '',
    profile           TEXT NOT NULL DEFAULT '',
    diameter          TEXT NOT NULL DEFAULT '',
    season            TEXT NOT NULL DEFAULT '',
    load_index        TEXT NOT NULL DEFAULT '',
    speed_index       TEXT NOT NULL DEFAULT '',
    run_flat          TEXT NOT NULL DEFAULT '',
    condition_val     TEXT NOT NULL DEFAULT '',
    multi_name        TEXT NOT NULL DEFAULT '',
    multi_item        TEXT NOT NULL DEFAULT 'Да',
    quantity          TEXT NOT NULL DEFAULT 'за 1 шт.',
    photos_kind       TEXT NOT NULL DEFAULT '',
    contact_person    TEXT NOT NULL DEFAULT '',
    phone             TEXT NOT NULL DEFAULT '',
    address           TEXT NOT NULL DEFAULT '',
    contact_method    TEXT NOT NULL DEFAULT '',
    company           TEXT NOT NULL DEFAULT '',
    email             TEXT NOT NULL DEFAULT '',
    listing_fee       TEXT NOT NULL DEFAULT '',
    category          TEXT NOT NULL DEFAULT '',
    goods_type        TEXT NOT NULL DEFAULT '',
    ad_type           TEXT NOT NULL DEFAULT '',
    product_type      TEXT NOT NULL DEFAULT '',
    free_tire_fitting TEXT NOT NULL DEFAULT '',
    audience          TEXT NOT NULL DEFAULT '',
    in_feed           INTEGER NOT NULL DEFAULT 1,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_listings_article ON listings (article_id);
CREATE INDEX IF NOT EXISTS idx_listings_avito ON listings (avito_id);
CREATE INDEX IF NOT EXISTS idx_listings_in_feed ON listings (in_feed);

-- Ручная цена (админка / загрузка фото) — высший приоритет в compare
CREATE TABLE IF NOT EXISTS manual_prices (
    article    TEXT PRIMARY KEY,
    price      REAL NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by TEXT NOT NULL DEFAULT ''
);

-- Последнее успешно отправленное в Avito API / XML (diff-only sync)
CREATE TABLE IF NOT EXISTS avito_sync_state (
    avito_id              TEXT PRIMARY KEY,
    listing_id            TEXT NOT NULL DEFAULT '',
    article               TEXT NOT NULL DEFAULT '',
    last_price            INTEGER,
    last_qty              INTEGER,
    last_photo_hash       TEXT NOT NULL DEFAULT '',
    last_price_synced_at  TEXT,
    last_qty_synced_at    TEXT,
    last_photo_synced_at  TEXT,
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sync_state_listing ON avito_sync_state (listing_id);
CREATE INDEX IF NOT EXISTS idx_sync_state_article ON avito_sync_state (article);
"""


@dataclass(frozen=True)
class StockDbRow:
    article: str
    name: str
    quantity: str
    price: float
    source: str
    avito_price: float | None = None
    ushk_in_stock: bool = False
    sam_mb_cash_price: bool = False
    kind: str = "tire"
    brand: str = ""
    model: str = ""
    wheel_type: str = ""
    width: str = ""
    diameter: str = ""
    studs: str = ""
    circle: str = ""
    et: str = ""
    hub: str = ""


@dataclass(frozen=True)
class NoPhotoDbRow:
    article: str
    nomenclature: str
    stores: str
    problem: str
    kind: str = "tire"


@dataclass(frozen=True)
class ListingDbRow:
    listing_id: str
    article_id: str
    avito_id: str = ""
    title: str = ""
    price: float | None = None
    photo_urls: str = ""
    description_html: str = ""
    store_key: str = ""
    brand: str = ""
    model: str = ""
    width: str = ""
    profile: str = ""
    diameter: str = ""
    season: str = ""
    load_index: str = ""
    speed_index: str = ""
    run_flat: str = ""
    condition_val: str = ""
    multi_name: str = ""
    multi_item: str = "Да"
    quantity: str = "за 1 шт."
    photos_kind: str = ""
    contact_person: str = ""
    phone: str = ""
    address: str = ""
    contact_method: str = ""
    company: str = ""
    email: str = ""
    listing_fee: str = ""
    category: str = ""
    goods_type: str = ""
    ad_type: str = ""
    product_type: str = ""
    free_tire_fitting: str = ""
    audience: str = ""
    in_feed: bool = True
    updated_at: str = ""


def resolve_stock_db_path(path: Path, *, project_root: Path | None = None) -> Path:
    if path.is_absolute():
        return path
    if project_root is not None:
        return project_root / path
    return path


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}


_STOCK_EXTRA_COLS: tuple[tuple[str, str], ...] = (
    ("kind", "TEXT NOT NULL DEFAULT 'tire'"),
    ("brand", "TEXT NOT NULL DEFAULT ''"),
    ("model", "TEXT NOT NULL DEFAULT ''"),
    ("wheel_type", "TEXT NOT NULL DEFAULT ''"),
    ("width", "TEXT NOT NULL DEFAULT ''"),
    ("diameter", "TEXT NOT NULL DEFAULT ''"),
    ("studs", "TEXT NOT NULL DEFAULT ''"),
    ("circle", "TEXT NOT NULL DEFAULT ''"),
    ("et", "TEXT NOT NULL DEFAULT ''"),
    ("hub", "TEXT NOT NULL DEFAULT ''"),
)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """ALTER для колонок, которых нет в старых БД (CREATE IF NOT EXISTS их не добавит)."""
    stock_cols = _table_columns(conn, "stock_items")
    if stock_cols:
        for col, decl in _STOCK_EXTRA_COLS:
            if col not in stock_cols:
                conn.execute(f"ALTER TABLE stock_items ADD COLUMN {col} {decl}")
    np_cols = _table_columns(conn, "no_photos_queue")
    if np_cols and "kind" not in np_cols:
        conn.execute(
            "ALTER TABLE no_photos_queue ADD COLUMN kind TEXT NOT NULL DEFAULT 'tire'"
        )
    if np_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_no_photos_kind ON no_photos_queue (kind)"
        )
    posting_cols = _table_columns(conn, "posting_items")
    if posting_cols and "kind" not in posting_cols:
        conn.execute(
            "ALTER TABLE posting_items ADD COLUMN kind TEXT NOT NULL DEFAULT 'tire'"
        )
    if posting_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_posting_kind ON posting_items (kind)"
        )


def init_db(conn: sqlite3.Connection, *, schema_path: Path | None = None) -> None:
    # Сначала миграции колонок (старые БД), потом CREATE IF NOT EXISTS / индексы.
    _migrate_schema(conn)
    if schema_path is not None and schema_path.is_file():
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    # Всегда догоняем актуальный SCHEMA_SQL (новые таблицы после деплоя)
    conn.executescript(SCHEMA_SQL)
    _migrate_schema(conn)
    conn.commit()


@contextmanager
def stock_connection(
    db_path: Path,
    *,
    schema_path: Path | None = None,
) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        init_db(conn, schema_path=schema_path)
        yield conn
    finally:
        conn.close()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO stock_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM stock_meta WHERE key = ?", (key,)
    ).fetchone()
    return str(row["value"]) if row else default


def replace_all(
    conn: sqlite3.Connection,
    rows: list[StockDbRow],
    *,
    built_at: str | None = None,
) -> int:
    """Полная перезапись остатков (один снимок после build_stock)."""
    stamp = built_at or _utcnow_iso()
    conn.execute("DELETE FROM stock_items")
    payload = [
        (
            r.article,
            r.name,
            r.quantity or "",
            float(r.price),
            r.source or "",
            r.avito_price,
            1 if r.ushk_in_stock else 0,
            1 if r.sam_mb_cash_price else 0,
            _normalize_kind(r.kind),
            (r.brand or "").strip(),
            (r.model or "").strip(),
            (r.wheel_type or "").strip(),
            (r.width or "").strip(),
            (r.diameter or "").strip(),
            (r.studs or "").strip(),
            (r.circle or "").strip(),
            (r.et or "").strip(),
            (r.hub or "").strip(),
            stamp,
        )
        for r in rows
        if r.article and r.name
    ]
    conn.executemany(
        """
        INSERT INTO stock_items(
            article, name, quantity, price, source, avito_price,
            ushk_in_stock, sam_mb_cash_price,
            kind, brand, model, wheel_type, width, diameter, studs, circle, et, hub,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    set_meta(conn, "built_at", stamp)
    set_meta(conn, "row_count", str(len(payload)))
    conn.commit()
    LOG.info("stock_db: записано %s позиций (built_at=%s)", len(payload), stamp)
    return len(payload)


def row_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM stock_items").fetchone()
    return int(row["n"] if row else 0)


def _row_from_sql(row: sqlite3.Row) -> StockDbRow:
    avito_raw = row["avito_price"]
    avito_price = float(avito_raw) if avito_raw is not None else None
    keys = set(row.keys())
    return StockDbRow(
        article=str(row["article"] or "").strip(),
        name=str(row["name"] or "").strip(),
        quantity=str(row["quantity"] or "").strip(),
        price=float(row["price"] or 0),
        source=str(row["source"] or "").strip(),
        avito_price=avito_price,
        ushk_in_stock=bool(row["ushk_in_stock"]),
        sam_mb_cash_price=bool(row["sam_mb_cash_price"]),
        kind=_normalize_kind(row["kind"]) if "kind" in keys else "tire",
        brand=str(row["brand"] or "").strip() if "brand" in keys else "",
        model=str(row["model"] or "").strip() if "model" in keys else "",
        wheel_type=str(row["wheel_type"] or "").strip() if "wheel_type" in keys else "",
        width=str(row["width"] or "").strip() if "width" in keys else "",
        diameter=str(row["diameter"] or "").strip() if "diameter" in keys else "",
        studs=str(row["studs"] or "").strip() if "studs" in keys else "",
        circle=str(row["circle"] or "").strip() if "circle" in keys else "",
        et=str(row["et"] or "").strip() if "et" in keys else "",
        hub=str(row["hub"] or "").strip() if "hub" in keys else "",
    )


def _stock_select_sql(conn: sqlite3.Connection) -> str:
    cols = _table_columns(conn, "stock_items")
    extra = [
        c
        for c in (
            "kind",
            "brand",
            "model",
            "wheel_type",
            "width",
            "diameter",
            "studs",
            "circle",
            "et",
            "hub",
        )
        if c in cols
    ]
    extra_sql = (", " + ", ".join(extra)) if extra else ""
    return (
        "SELECT article, name, quantity, price, source, avito_price, "
        f"ushk_in_stock, sam_mb_cash_price{extra_sql} FROM stock_items"
    )


def iter_items(conn: sqlite3.Connection) -> list[StockDbRow]:
    rows = conn.execute(_stock_select_sql(conn) + " ORDER BY article").fetchall()
    return [_row_from_sql(r) for r in rows]


def lookup(conn: sqlite3.Connection, article: str) -> StockDbRow | None:
    art = str(article or "").strip()
    if not art:
        return None
    row = conn.execute(
        _stock_select_sql(conn) + " WHERE article = ?",
        (art,),
    ).fetchone()
    return _row_from_sql(row) if row else None


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 30,
    kind: str = "",
) -> list[StockDbRow]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    like = f"%{q}%"
    where = ["(lower(article) LIKE ? OR lower(name) LIKE ?)"]
    params: list[Any] = [like, like]
    want = str(kind or "").strip()
    if want and "kind" in _table_columns(conn, "stock_items"):
        where.append("kind = ?")
        params.append(_normalize_kind(want))
    params.extend([q, f"{q}%", max(1, int(limit))])
    rows = conn.execute(
        _stock_select_sql(conn)
        + " WHERE "
        + " AND ".join(where)
        + """
        ORDER BY
          CASE WHEN lower(article) = ? THEN 0
               WHEN lower(article) LIKE ? THEN 1
               ELSE 2 END,
          article
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_row_from_sql(r) for r in rows]


def starred_articles(conn: sqlite3.Connection) -> frozenset[str]:
    """Артикулы с seller-star source (google/p1/db:p2–p4) без полной выгрузки каталога."""
    sources = ("google", "p1", "db:p2", "db:p3", "db:p4")
    placeholders = ",".join("?" for _ in sources)
    rows = conn.execute(
        f"SELECT article FROM stock_items WHERE lower(source) IN ({placeholders})",
        sources,
    ).fetchall()
    return frozenset(str(r["article"] or "").strip() for r in rows if r["article"])


def db_file_mtime(db_path: Path) -> float | None:
    try:
        if db_path.is_file():
            return db_path.stat().st_mtime
    except OSError:
        pass
    return None


def _normalize_kind(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("wheel", "wheels", "диск", "диски"):
        return "wheel"
    return "tire"


def replace_no_photos(
    conn: sqlite3.Connection,
    rows: list[NoPhotoDbRow] | list[dict],
    *,
    built_at: str | None = None,
) -> int:
    """Полная перезапись очереди «нет фото»."""
    stamp = built_at or _utcnow_iso()
    conn.execute("DELETE FROM no_photos_queue")
    payload: list[tuple[str, str, str, str, str, str]] = []
    for raw in rows:
        if isinstance(raw, NoPhotoDbRow):
            article = raw.article
            name = raw.nomenclature
            stores = raw.stores
            problem = raw.problem
            kind = _normalize_kind(raw.kind)
        else:
            article = str(raw.get("артикул") or raw.get("article") or "").strip()
            if article.endswith(".0"):
                try:
                    article = str(int(float(article)))
                except ValueError:
                    pass
            name = str(raw.get("номенклатура") or raw.get("nomenclature") or "").strip()
            stores = str(raw.get("магазины") or raw.get("stores") or "").strip()
            problem = str(raw.get("проблема") or raw.get("problem") or "").strip()
            kind = _normalize_kind(raw.get("kind") or raw.get("product_kind"))
        if not article:
            continue
        payload.append((article, name, stores, problem, kind, stamp))
    conn.executemany(
        """
        INSERT INTO no_photos_queue(article, nomenclature, stores, problem, kind, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    set_meta(conn, "no_photos_built_at", stamp)
    set_meta(conn, "no_photos_row_count", str(len(payload)))
    tires_n = sum(1 for p in payload if p[4] == "tire")
    wheels_n = sum(1 for p in payload if p[4] == "wheel")
    set_meta(conn, "no_photos_tire_count", str(tires_n))
    set_meta(conn, "no_photos_wheel_count", str(wheels_n))
    conn.commit()
    LOG.info(
        "no_photos_queue: записано %s позиций (tire=%s wheel=%s built_at=%s)",
        len(payload),
        tires_n,
        wheels_n,
        stamp,
    )
    return len(payload)


def no_photos_count(conn: sqlite3.Connection, *, kind: str = "") -> int:
    want = str(kind or "").strip().lower()
    if want in ("tire", "wheel"):
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM no_photos_queue WHERE kind = ?", (want,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS n FROM no_photos_queue").fetchone()
    return int(row["n"] if row else 0)


def query_no_photos(
    conn: sqlite3.Connection,
    *,
    store_prefix: str = "",
    limit: int = 0,
    allowed_articles: frozenset[str] | None = None,
    kind: str = "",
) -> list[NoPhotoDbRow]:
    """Очередь без фото. store_prefix — фильтр по подстроке в stores (md/pg).
    kind — tire|wheel|"" (все). limit=0 — без ограничения.
    Фильтры и LIMIT по возможности в SQL (без полной выгрузки в Python).
    """
    prefix = store_prefix.strip().lower()
    limit_n = int(limit) if limit and int(limit) > 0 else 0
    want = _normalize_kind(kind) if str(kind or "").strip() else ""
    has_kind = "kind" in _table_columns(conn, "no_photos_queue")

    if allowed_articles is not None and not allowed_articles:
        return []

    select = "SELECT article, nomenclature, stores, problem"
    if has_kind:
        select += ", kind"
    select += " FROM no_photos_queue"

    where: list[str] = []
    params: list[Any] = []
    if has_kind and want:
        where.append("kind = ?")
        params.append(want)
    if prefix:
        where.append("instr(lower(stores), ?) > 0")
        params.append(prefix)

    # article IN (...) — только если реестр не огромный; иначе фильтр в Python
    use_in = (
        allowed_articles is not None
        and 0 < len(allowed_articles) <= 4000
    )
    if use_in:
        arts = sorted(allowed_articles)
        placeholders = ",".join("?" for _ in arts)
        where.append(f"article IN ({placeholders})")
        params.extend(arts)

    sql = select
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY article"
    if limit_n and (allowed_articles is None or use_in):
        sql += " LIMIT ?"
        params.append(limit_n)

    rows = conn.execute(sql, params).fetchall()
    out: list[NoPhotoDbRow] = []
    for row in rows:
        article = str(row["article"] or "").strip()
        if not article:
            continue
        if allowed_articles is not None and not use_in and article not in allowed_articles:
            continue
        stores = str(row["stores"] or "").strip()
        row_kind = _normalize_kind(row["kind"]) if has_kind else "tire"
        out.append(
            NoPhotoDbRow(
                article=article,
                nomenclature=str(row["nomenclature"] or "").strip(),
                stores=stores,
                problem=str(row["problem"] or "").strip(),
                kind=row_kind,
            )
        )
        if limit_n and len(out) >= limit_n:
            break
    return out


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _opt_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in ("1", "true", "yes", "да", "y")


def _clean_article(value: Any) -> str:
    article = str(value or "").strip()
    if article.endswith(".0"):
        try:
            article = str(int(float(article)))
        except ValueError:
            pass
    if article.lower() in ("nan", "none"):
        return ""
    return article


def replace_posting(
    conn: sqlite3.Connection,
    posting: list[dict],
    problems: list[dict] | None = None,
    own_rows: list[dict] | None = None,
    match_rows: list[dict] | None = None,
    *,
    built_at: str | None = None,
) -> int:
    """Полная перезапись результата compare_prices."""
    stamp = built_at or _utcnow_iso()
    conn.execute("DELETE FROM posting_items")
    conn.execute("DELETE FROM posting_aux")
    payload: list[tuple] = []
    for raw in posting:
        article = _clean_article(raw.get("артикул") or raw.get("article"))
        name = str(raw.get("номенклатура") or raw.get("nomenclature") or "").strip()
        if not article or not name:
            continue
        price = _opt_float(raw.get("recommended_price"))
        incoming = _opt_float(raw.get("входящая") or raw.get("incoming"))
        if price is None or incoming is None:
            continue
        floor_key = "floor_входящая_x1.1"
        payload.append(
            (
                article,
                name,
                str(raw.get("количество") or raw.get("quantity") or "").strip(),
                float(incoming),
                0,  # on_avito — парсер выключен
                1 if _opt_bool(raw.get("ушк_в_наличии") or raw.get("ushk_in_stock")) else 0,
                1
                if _opt_bool(
                    raw.get("цена_за_наличный_расчет") or raw.get("sam_mb_cash_price")
                )
                else 0,
                None,  # avito_min
                None,  # avito_price_fixed (устарело)
                float(price),
                str(raw.get("price_rule") or "").strip(),
                _opt_float(raw.get("discount_pct")),
                _opt_float(raw.get(floor_key) or raw.get("floor_price")),
                1 if _opt_bool(raw.get("дубликат_остаток") or raw.get("duplicate")) else 0,
                _normalize_kind(raw.get("kind") or raw.get("product_kind")),
                stamp,
            )
        )
    has_kind = "kind" in _table_columns(conn, "posting_items")
    if has_kind:
        conn.executemany(
            """
            INSERT INTO posting_items(
                article, nomenclature, quantity, incoming, on_avito, ushk_in_stock,
                sam_mb_cash_price, avito_min, avito_price_fixed, recommended_price,
                price_rule, discount_pct, floor_price, duplicate, kind, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    else:
        conn.executemany(
            """
            INSERT INTO posting_items(
                article, nomenclature, quantity, incoming, on_avito, ushk_in_stock,
                sam_mb_cash_price, avito_min, avito_price_fixed, recommended_price,
                price_rule, discount_pct, floor_price, duplicate, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [p[:14] + (p[15],) for p in payload],
        )
    aux: list[tuple[str, str]] = []
    for kind, rows in (
        ("problems", problems or []),
        ("matches", match_rows or []),
        ("own", own_rows or []),
    ):
        for row in rows:
            aux.append((kind, json.dumps(row, ensure_ascii=False, default=str)))
    if aux:
        conn.executemany(
            "INSERT INTO posting_aux(kind, payload_json) VALUES (?, ?)",
            aux,
        )
    set_meta(conn, "posting_built_at", stamp)
    set_meta(conn, "posting_row_count", str(len(payload)))
    conn.commit()
    LOG.info("posting_items: записано %s позиций (built_at=%s)", len(payload), stamp)
    return len(payload)


def load_posting_dataframe(conn: sqlite3.Connection):
    """DataFrame в формате листа «к выкладке» для build_autoload."""
    import pandas as pd

    has_kind = "kind" in _table_columns(conn, "posting_items")
    stock_cols = set(_table_columns(conn, "stock_items") or [])
    wheel_join = "brand" in stock_cols and "wheel_type" in stock_cols
    kind_sql = ", p.kind" if has_kind else ""
    if wheel_join:
        sql = f"""
        SELECT p.article, p.nomenclature, p.quantity, p.incoming, p.on_avito,
               p.ushk_in_stock, p.sam_mb_cash_price, p.avito_min, p.avito_price_fixed,
               p.recommended_price, p.price_rule, p.discount_pct, p.floor_price,
               p.duplicate{kind_sql},
               COALESCE(s.brand, '') AS brand,
               COALESCE(s.model, '') AS model,
               COALESCE(s.wheel_type, '') AS wheel_type,
               COALESCE(s.width, '') AS width,
               COALESCE(s.diameter, '') AS diameter,
               COALESCE(s.studs, '') AS studs,
               COALESCE(s.circle, '') AS circle,
               COALESCE(s.et, '') AS et,
               COALESCE(s.hub, '') AS hub
        FROM posting_items p
        LEFT JOIN stock_items s ON s.article = p.article
        ORDER BY p.article
        """
    else:
        kind_sql_plain = ", kind" if has_kind else ""
        sql = f"""
        SELECT article, nomenclature, quantity, incoming, on_avito, ushk_in_stock,
               sam_mb_cash_price, avito_min, avito_price_fixed, recommended_price,
               price_rule, discount_pct, floor_price, duplicate{kind_sql_plain}
        FROM posting_items
        ORDER BY article
        """
    rows = conn.execute(sql).fetchall()
    records = []
    for r in rows:
        keys = set(r.keys())
        rec = {
            "артикул": r["article"],
            "номенклатура": r["nomenclature"],
            "количество": r["quantity"],
            "входящая": r["incoming"],
            "ушк_в_наличии": bool(r["ushk_in_stock"]),
            "цена_за_наличный_расчет": bool(r["sam_mb_cash_price"]),
            "recommended_price": r["recommended_price"],
            "price_rule": r["price_rule"],
            "discount_pct": r["discount_pct"] if r["discount_pct"] is not None else "",
            "floor_входящая_x1.1": r["floor_price"] if r["floor_price"] is not None else "",
            "дубликат_остаток": bool(r["duplicate"]),
            "kind": _normalize_kind(r["kind"]) if has_kind and "kind" in keys else "tire",
        }
        if wheel_join:
            rec.update(
                {
                    "brand": str(r["brand"] or "").strip(),
                    "model": str(r["model"] or "").strip(),
                    "wheel_type": str(r["wheel_type"] or "").strip(),
                    "width": str(r["width"] or "").strip(),
                    "diameter": str(r["diameter"] or "").strip(),
                    "studs": str(r["studs"] or "").strip(),
                    "circle": str(r["circle"] or "").strip(),
                    "et": str(r["et"] or "").strip(),
                    "hub": str(r["hub"] or "").strip(),
                }
            )
        records.append(rec)
    return pd.DataFrame(records)


def replace_missing_models(
    conn: sqlite3.Connection,
    rows: list[dict],
    *,
    built_at: str | None = None,
) -> int:
    stamp = built_at or _utcnow_iso()
    conn.execute("DELETE FROM missing_models")
    payload = [
        (json.dumps(row, ensure_ascii=False, default=str),)
        for row in rows
        if row
    ]
    if payload:
        conn.executemany("INSERT INTO missing_models(payload_json) VALUES (?)", payload)
    set_meta(conn, "missing_models_built_at", stamp)
    set_meta(conn, "missing_models_count", str(len(payload)))
    conn.commit()
    return len(payload)


def replace_avito_ids(
    conn: sqlite3.Connection,
    mapping: dict[str, str],
    *,
    built_at: str | None = None,
) -> int:
    """Перезапись ключ → avito_id. Ключи listing-level (md_/pg_) сохраняем."""
    stamp = built_at or _utcnow_iso()
    conn.execute("DELETE FROM avito_ids")
    payload: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for key, val in mapping.items():
        if not key or not val:
            continue
        article = _clean_article(key)
        avito_id = str(val).strip().split(".")[0]
        if not article or not avito_id or avito_id.lower() == "nan":
            continue
        if article in seen:
            continue
        seen.add(article)
        payload.append((article, avito_id, stamp))
    conn.executemany(
        "INSERT INTO avito_ids(article, avito_id, updated_at) VALUES (?, ?, ?)",
        payload,
    )
    set_meta(conn, "avito_ids_built_at", stamp)
    set_meta(conn, "avito_ids_count", str(len(payload)))
    conn.commit()
    LOG.info("avito_ids: записано %s", len(payload))
    return len(payload)


def load_avito_ids_map(conn: sqlite3.Connection, stores: Any = None) -> dict[str, str]:
    """article/listing_id → avito_id. Без копирования одного Id на все магазины."""
    del stores
    rows = conn.execute("SELECT article, avito_id FROM avito_ids").fetchall()
    out: dict[str, str] = {}
    for row in rows:
        article = _clean_article(row["article"])
        avito_id = str(row["avito_id"] or "").strip()
        if not article or not avito_id:
            continue
        out[article] = avito_id
    return out


def import_avito_ids_csv(conn: sqlite3.Connection, path: Path) -> int:
    """Разовый импорт input/avito_ids.csv → sqlite (артикул или listing_id)."""
    import pandas as pd

    if not path.is_file():
        return 0
    df = pd.read_csv(path, encoding="utf-8-sig", sep=None, engine="python")
    cols = {str(c).strip().lower(): c for c in df.columns}
    art = (
        cols.get("артикул")
        or cols.get("article")
        or cols.get("listing_id")
        or cols.get("id")
        or cols.get("уникальный идентификатор объявления")
    )
    aid = cols.get("avito_id") or cols.get("номер объявления на авито") or cols.get("avito id")
    if not art or not aid:
        return 0
    mapping: dict[str, str] = {}
    for _, r in df.iterrows():
        a = _clean_article(r[art])
        i = str(r[aid]).strip().split(".")[0]
        if a and i and i.lower() != "nan":
            mapping[a] = i
    return replace_avito_ids(conn, mapping)



_LISTING_COLUMNS = (
    "listing_id",
    "article_id",
    "avito_id",
    "title",
    "price",
    "photo_urls",
    "description_html",
    "store_key",
    "brand",
    "model",
    "width",
    "profile",
    "diameter",
    "season",
    "load_index",
    "speed_index",
    "run_flat",
    "condition_val",
    "multi_name",
    "multi_item",
    "quantity",
    "photos_kind",
    "contact_person",
    "phone",
    "address",
    "contact_method",
    "company",
    "email",
    "listing_fee",
    "category",
    "goods_type",
    "ad_type",
    "product_type",
    "free_tire_fitting",
    "audience",
    "in_feed",
    "updated_at",
)


def _listing_from_sql(row: sqlite3.Row) -> ListingDbRow:
    price_raw = row["price"]
    try:
        price = float(price_raw) if price_raw is not None else None
    except (TypeError, ValueError):
        price = None
    return ListingDbRow(
        listing_id=str(row["listing_id"] or "").strip(),
        article_id=str(row["article_id"] or "").strip(),
        avito_id=str(row["avito_id"] or "").strip(),
        title=str(row["title"] or "").strip(),
        price=price,
        photo_urls=str(row["photo_urls"] or "").strip(),
        description_html=str(row["description_html"] or ""),
        store_key=str(row["store_key"] or "").strip(),
        brand=str(row["brand"] or "").strip(),
        model=str(row["model"] or "").strip(),
        width=str(row["width"] or "").strip(),
        profile=str(row["profile"] or "").strip(),
        diameter=str(row["diameter"] or "").strip(),
        season=str(row["season"] or "").strip(),
        load_index=str(row["load_index"] or "").strip(),
        speed_index=str(row["speed_index"] or "").strip(),
        run_flat=str(row["run_flat"] or "").strip(),
        condition_val=str(row["condition_val"] or "").strip(),
        multi_name=str(row["multi_name"] or "").strip(),
        multi_item=str(row["multi_item"] or "Да").strip() or "Да",
        quantity=str(row["quantity"] or "за 1 шт.").strip() or "за 1 шт.",
        photos_kind=str(row["photos_kind"] or "").strip(),
        contact_person=str(row["contact_person"] or "").strip(),
        phone=str(row["phone"] or "").strip(),
        address=str(row["address"] or "").strip(),
        contact_method=str(row["contact_method"] or "").strip(),
        company=str(row["company"] or "").strip(),
        email=str(row["email"] or "").strip(),
        listing_fee=str(row["listing_fee"] or "").strip(),
        category=str(row["category"] or "").strip(),
        goods_type=str(row["goods_type"] or "").strip(),
        ad_type=str(row["ad_type"] or "").strip(),
        product_type=str(row["product_type"] or "").strip(),
        free_tire_fitting=str(row["free_tire_fitting"] or "").strip(),
        audience=str(row["audience"] or "").strip(),
        in_feed=bool(row["in_feed"]),
        updated_at=str(row["updated_at"] or "").strip(),
    )


def _listing_to_tuple(row: ListingDbRow | dict, *, stamp: str) -> tuple:
    if isinstance(row, ListingDbRow):
        d = {
            "listing_id": row.listing_id,
            "article_id": row.article_id,
            "avito_id": row.avito_id,
            "title": row.title,
            "price": row.price,
            "photo_urls": row.photo_urls,
            "description_html": row.description_html,
            "store_key": row.store_key,
            "brand": row.brand,
            "model": row.model,
            "width": row.width,
            "profile": row.profile,
            "diameter": row.diameter,
            "season": row.season,
            "load_index": row.load_index,
            "speed_index": row.speed_index,
            "run_flat": row.run_flat,
            "condition_val": row.condition_val,
            "multi_name": row.multi_name,
            "multi_item": row.multi_item,
            "quantity": row.quantity,
            "photos_kind": row.photos_kind,
            "contact_person": row.contact_person,
            "phone": row.phone,
            "address": row.address,
            "contact_method": row.contact_method,
            "company": row.company,
            "email": row.email,
            "listing_fee": row.listing_fee,
            "category": row.category,
            "goods_type": row.goods_type,
            "ad_type": row.ad_type,
            "product_type": row.product_type,
            "free_tire_fitting": row.free_tire_fitting,
            "audience": row.audience,
            "in_feed": 1 if row.in_feed else 0,
            "updated_at": row.updated_at or stamp,
        }
    else:
        d = dict(row)
        d["in_feed"] = 1 if d.get("in_feed", True) else 0
        d["updated_at"] = d.get("updated_at") or stamp
    listing_id = _clean_article(d.get("listing_id"))
    article_id = _clean_article(d.get("article_id"))
    if not listing_id or not article_id:
        return ()
    price = d.get("price")
    try:
        price_f = float(price) if price is not None and str(price).strip() != "" else None
    except (TypeError, ValueError):
        price_f = None
    return (
        listing_id,
        article_id,
        str(d.get("avito_id") or "").strip().split(".")[0],
        str(d.get("title") or "").strip(),
        price_f,
        str(d.get("photo_urls") or "").strip(),
        str(d.get("description_html") or ""),
        str(d.get("store_key") or "").strip(),
        str(d.get("brand") or "").strip(),
        str(d.get("model") or "").strip(),
        str(d.get("width") or "").strip(),
        str(d.get("profile") or "").strip(),
        str(d.get("diameter") or "").strip(),
        str(d.get("season") or "").strip(),
        str(d.get("load_index") or "").strip(),
        str(d.get("speed_index") or "").strip(),
        str(d.get("run_flat") or "").strip(),
        str(d.get("condition_val") or "").strip(),
        str(d.get("multi_name") or "").strip(),
        str(d.get("multi_item") or "Да").strip() or "Да",
        str(d.get("quantity") or "за 1 шт.").strip() or "за 1 шт.",
        str(d.get("photos_kind") or "").strip(),
        str(d.get("contact_person") or "").strip(),
        str(d.get("phone") or "").strip(),
        str(d.get("address") or "").strip(),
        str(d.get("contact_method") or "").strip(),
        str(d.get("company") or "").strip(),
        str(d.get("email") or "").strip(),
        str(d.get("listing_fee") or "").strip(),
        str(d.get("category") or "").strip(),
        str(d.get("goods_type") or "").strip(),
        str(d.get("ad_type") or "").strip(),
        str(d.get("product_type") or "").strip(),
        str(d.get("free_tire_fitting") or "").strip(),
        str(d.get("audience") or "").strip(),
        int(d.get("in_feed") or 0),
        str(d.get("updated_at") or stamp),
    )


def upsert_listings(
    conn: sqlite3.Connection,
    rows: list[ListingDbRow] | list[dict],
    *,
    built_at: str | None = None,
    replace_all: bool = False,
) -> int:
    """Upsert объявлений. replace_all=True — полная замена таблицы."""
    stamp = built_at or _utcnow_iso()
    if replace_all:
        conn.execute("DELETE FROM listings")
    payload: list[tuple] = []
    for raw in rows:
        t = _listing_to_tuple(raw, stamp=stamp)
        if t:
            payload.append(t)
    if not payload:
        if replace_all:
            set_meta(conn, "listings_built_at", stamp)
            set_meta(conn, "listings_count", "0")
            conn.commit()
        return 0
    cols = ", ".join(_LISTING_COLUMNS)
    placeholders = ", ".join("?" for _ in _LISTING_COLUMNS)
    updates = ", ".join(
        f"{c}=excluded.{c}" for c in _LISTING_COLUMNS if c != "listing_id"
    )
    conn.executemany(
        f"""
        INSERT INTO listings({cols}) VALUES ({placeholders})
        ON CONFLICT(listing_id) DO UPDATE SET {updates}
        """,
        payload,
    )
    set_meta(conn, "listings_built_at", stamp)
    n = conn.execute("SELECT COUNT(*) AS n FROM listings").fetchone()
    set_meta(conn, "listings_count", str(int(n["n"] if n else 0)))
    conn.commit()
    LOG.info("listings: upsert %s (всего %s)", len(payload), n["n"] if n else 0)
    return len(payload)


def load_listings(
    conn: sqlite3.Connection,
    *,
    in_feed_only: bool = False,
) -> list[ListingDbRow]:
    sql = f"SELECT {', '.join(_LISTING_COLUMNS)} FROM listings"
    if in_feed_only:
        sql += " WHERE in_feed = 1"
    sql += " ORDER BY listing_id"
    return [_listing_from_sql(r) for r in conn.execute(sql).fetchall()]


def load_listings_map(conn: sqlite3.Connection) -> dict[str, ListingDbRow]:
    return {r.listing_id: r for r in load_listings(conn) if r.listing_id}


def delete_listings_not_in(
    conn: sqlite3.Connection,
    keep_listing_ids: set[str],
) -> int:
    rows = conn.execute("SELECT listing_id FROM listings").fetchall()
    to_delete = [
        str(r["listing_id"])
        for r in rows
        if str(r["listing_id"] or "").strip() not in keep_listing_ids
    ]
    if not to_delete:
        return 0
    conn.executemany("DELETE FROM listings WHERE listing_id = ?", [(x,) for x in to_delete])
    conn.commit()
    return len(to_delete)


def sync_avito_ids_from_listings(
    conn: sqlite3.Connection,
    *,
    built_at: str | None = None,
) -> int:
    """Собрать avito_ids из listings (listing_id и article_id → avito_id)."""
    rows = conn.execute(
        "SELECT listing_id, article_id, avito_id FROM listings "
        "WHERE avito_id IS NOT NULL AND trim(avito_id) != ''"
    ).fetchall()
    mapping: dict[str, str] = {}
    for row in rows:
        avito_id = str(row["avito_id"] or "").strip().split(".")[0]
        if not avito_id or avito_id.lower() == "nan":
            continue
        lid = _clean_article(row["listing_id"])
        art = _clean_article(row["article_id"])
        if lid:
            mapping[lid] = avito_id
        # Не фанатим article→id если уже есть другой listing-level Id.
        # Bare article пишем только если ещё нет ключа.
        if art and art not in mapping:
            mapping[art] = avito_id
    return replace_avito_ids(conn, mapping, built_at=built_at)

@dataclass(frozen=True)
class ManualPriceRow:
    article: str
    price: float
    updated_at: str
    updated_by: str


def get_manual_price(conn: sqlite3.Connection, article: str) -> float | None:
    art = _clean_article(article)
    if not art:
        return None
    row = conn.execute(
        "SELECT price FROM manual_prices WHERE article = ?", (art,)
    ).fetchone()
    if not row:
        return None
    try:
        return float(row["price"])
    except (TypeError, ValueError):
        return None


def load_manual_prices_map(conn: sqlite3.Connection) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in conn.execute("SELECT article, price FROM manual_prices").fetchall():
        art = _clean_article(row["article"])
        try:
            price = float(row["price"])
        except (TypeError, ValueError):
            continue
        if art and price > 0:
            out[art] = price
    return out


def set_manual_price(
    conn: sqlite3.Connection,
    article: str,
    price: float,
    *,
    updated_by: str = "",
) -> ManualPriceRow:
    art = _clean_article(article)
    if not art:
        raise ValueError("Пустой артикул")
    try:
        value = float(price)
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректная цена") from exc
    if value <= 0:
        raise ValueError("Цена должна быть > 0")
    stamp = _utcnow_iso()
    by = str(updated_by or "").strip()
    conn.execute(
        """
        INSERT INTO manual_prices(article, price, updated_at, updated_by)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(article) DO UPDATE SET
            price=excluded.price,
            updated_at=excluded.updated_at,
            updated_by=excluded.updated_by
        """,
        (art, value, stamp, by),
    )
    conn.commit()
    return ManualPriceRow(article=art, price=value, updated_at=stamp, updated_by=by)


def clear_manual_price(conn: sqlite3.Connection, article: str) -> bool:
    art = _clean_article(article)
    if not art:
        return False
    cur = conn.execute("DELETE FROM manual_prices WHERE article = ?", (art,))
    conn.commit()
    return cur.rowcount > 0


def get_manual_price_row(
    conn: sqlite3.Connection, article: str
) -> ManualPriceRow | None:
    art = _clean_article(article)
    if not art:
        return None
    row = conn.execute(
        "SELECT article, price, updated_at, updated_by FROM manual_prices WHERE article = ?",
        (art,),
    ).fetchone()
    if not row:
        return None
    return ManualPriceRow(
        article=str(row["article"]),
        price=float(row["price"]),
        updated_at=str(row["updated_at"] or ""),
        updated_by=str(row["updated_by"] or ""),
    )


@dataclass(frozen=True)
class AdminProductRow:
    article: str
    name: str
    price: float
    manual_price: float | None = None


def load_posting_prices_map(
    conn: sqlite3.Connection,
    articles: list[str] | tuple[str, ...] | frozenset[str] | None = None,
) -> dict[str, tuple[float | None, str]]:
    """article → (recommended_price, price_rule). Optionally only for given articles."""
    out: dict[str, tuple[float | None, str]] = {}
    if articles is not None:
        arts = [_clean_article(a) for a in articles]
        arts = [a for a in arts if a]
        if not arts:
            return out
        chunk = 400
        for i in range(0, len(arts), chunk):
            part = arts[i : i + chunk]
            placeholders = ",".join("?" for _ in part)
            rows = conn.execute(
                f"""
                SELECT article, recommended_price, price_rule
                FROM posting_items
                WHERE article IN ({placeholders})
                """,
                part,
            ).fetchall()
            for r in rows:
                art = _clean_article(r["article"])
                if not art:
                    continue
                try:
                    price = float(r["recommended_price"])
                except (TypeError, ValueError):
                    price = None
                out[art] = (price, str(r["price_rule"] or "").strip())
        return out

    rows = conn.execute(
        "SELECT article, recommended_price, price_rule FROM posting_items"
    ).fetchall()
    for r in rows:
        art = _clean_article(r["article"])
        if not art:
            continue
        try:
            price = float(r["recommended_price"])
        except (TypeError, ValueError):
            price = None
        out[art] = (price, str(r["price_rule"] or "").strip())
    return out


def _fill_admin_photo_temp(
    conn: sqlite3.Connection, articles: frozenset[str] | set[str]
) -> None:
    conn.execute("DROP TABLE IF EXISTS temp._admin_photo_arts")
    conn.execute(
        "CREATE TEMP TABLE _admin_photo_arts(article TEXT PRIMARY KEY) WITHOUT ROWID"
    )
    if not articles:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO temp._admin_photo_arts(article) VALUES (?)",
        [(a,) for a in articles if a],
    )


def query_admin_products(
    conn: sqlite3.Connection,
    *,
    query: str = "",
    only_manual: bool = False,
    has_photos: str = "",
    photo_articles: frozenset[str] | set[str] | None = None,
    limit: int = 300,
    offset: int = 0,
) -> tuple[list[AdminProductRow], int]:
    """
    Paginated stock (+ orphan manuals) for photo-admin listings.
    has_photos: "" | "1" | "0"; when "1"/"0", photo_articles is required (may be empty).
    """
    q = str(query or "").strip().lower()
    photos_filter = str(has_photos or "").strip()
    limit_n = max(0, int(limit)) if limit is not None else 0
    offset_n = max(0, int(offset or 0))

    if photos_filter in ("1", "0"):
        arts = frozenset(photo_articles or ())
        if photos_filter == "1" and not arts:
            return [], 0
        _fill_admin_photo_temp(conn, arts)

    if only_manual:
        base_sql = """
            SELECT m.article AS article,
                   COALESCE(s.name, '') AS name,
                   COALESCE(s.price, 0) AS price,
                   m.price AS manual_price
            FROM manual_prices m
            LEFT JOIN stock_items s ON s.article = m.article
        """
    else:
        base_sql = """
            SELECT s.article AS article,
                   s.name AS name,
                   s.price AS price,
                   m.price AS manual_price
            FROM stock_items s
            LEFT JOIN manual_prices m ON m.article = s.article
            UNION ALL
            SELECT m.article AS article,
                   '' AS name,
                   0 AS price,
                   m.price AS manual_price
            FROM manual_prices m
            WHERE NOT EXISTS (
                SELECT 1 FROM stock_items s WHERE s.article = m.article
            )
        """

    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append("(lower(article) LIKE ? OR lower(name) LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like])
    if photos_filter == "1":
        where.append(
            "article IN (SELECT article FROM temp._admin_photo_arts)"
        )
    elif photos_filter == "0":
        where.append(
            "article NOT IN (SELECT article FROM temp._admin_photo_arts)"
        )

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    wrapped = f"SELECT * FROM ({base_sql}) AS admin_base{where_sql}"

    total = int(
        conn.execute(f"SELECT COUNT(*) AS n FROM ({wrapped})", params).fetchone()["n"]
    )

    rows_sql = wrapped + " ORDER BY article"
    row_params = list(params)
    if limit_n > 0:
        rows_sql += " LIMIT ? OFFSET ?"
        row_params.extend([limit_n, offset_n])
    raw = conn.execute(rows_sql, row_params).fetchall()

    out: list[AdminProductRow] = []
    for r in raw:
        art = _clean_article(r["article"])
        if not art:
            continue
        try:
            price = float(r["price"] or 0)
        except (TypeError, ValueError):
            price = 0.0
        manual = None
        if r["manual_price"] is not None:
            try:
                manual = float(r["manual_price"])
            except (TypeError, ValueError):
                manual = None
            if manual is not None and manual <= 0:
                manual = None
        out.append(
            AdminProductRow(
                article=art,
                name=str(r["name"] or "").strip(),
                price=price,
                manual_price=manual,
            )
        )
    return out, total


@dataclass(frozen=True)
class AvitoSyncStateRow:
    avito_id: str
    listing_id: str = ""
    article: str = ""
    last_price: int | None = None
    last_qty: int | None = None
    last_photo_hash: str = ""
    last_price_synced_at: str = ""
    last_qty_synced_at: str = ""
    last_photo_synced_at: str = ""


def sync_state_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM avito_sync_state").fetchone()
    return int(row["n"] or 0) if row else 0


def load_sync_state_map(conn: sqlite3.Connection) -> dict[str, AvitoSyncStateRow]:
    """avito_id → last-sent state."""
    out: dict[str, AvitoSyncStateRow] = {}
    rows = conn.execute(
        """
        SELECT avito_id, listing_id, article, last_price, last_qty, last_photo_hash,
               last_price_synced_at, last_qty_synced_at, last_photo_synced_at
        FROM avito_sync_state
        """
    ).fetchall()
    for r in rows:
        aid = str(r["avito_id"] or "").strip()
        if not aid:
            continue
        price = r["last_price"]
        qty = r["last_qty"]
        try:
            price_i = int(price) if price is not None else None
        except (TypeError, ValueError):
            price_i = None
        try:
            qty_i = int(qty) if qty is not None else None
        except (TypeError, ValueError):
            qty_i = None
        out[aid] = AvitoSyncStateRow(
            avito_id=aid,
            listing_id=str(r["listing_id"] or "").strip(),
            article=str(r["article"] or "").strip(),
            last_price=price_i,
            last_qty=qty_i,
            last_photo_hash=str(r["last_photo_hash"] or "").strip(),
            last_price_synced_at=str(r["last_price_synced_at"] or "").strip(),
            last_qty_synced_at=str(r["last_qty_synced_at"] or "").strip(),
            last_photo_synced_at=str(r["last_photo_synced_at"] or "").strip(),
        )
    return out


def load_sync_state_by_listing(conn: sqlite3.Connection) -> dict[str, AvitoSyncStateRow]:
    """listing_id → state (для XML photo_updates без avito_id в ключе)."""
    out: dict[str, AvitoSyncStateRow] = {}
    for row in load_sync_state_map(conn).values():
        lid = str(row.listing_id or "").strip()
        if lid:
            out[lid] = row
    return out


def _sync_state_upsert_row(
    conn: sqlite3.Connection,
    *,
    avito_id: str,
    listing_id: str = "",
    article: str = "",
    last_price: int | None = None,
    last_qty: int | None = None,
    last_photo_hash: str | None = None,
    touch_price: bool = False,
    touch_qty: bool = False,
    touch_photo: bool = False,
) -> None:
    aid = str(avito_id or "").strip()
    if not aid:
        return
    stamp = _utcnow_iso()
    existing = conn.execute(
        "SELECT listing_id, article, last_price, last_qty, last_photo_hash FROM avito_sync_state WHERE avito_id = ?",
        (aid,),
    ).fetchone()
    if existing:
        lid = listing_id or str(existing["listing_id"] or "")
        art = article or str(existing["article"] or "")
        price = last_price if touch_price else existing["last_price"]
        qty = last_qty if touch_qty else existing["last_qty"]
        photo = (
            last_photo_hash
            if touch_photo and last_photo_hash is not None
            else str(existing["last_photo_hash"] or "")
        )
        price_at = stamp if touch_price else None
        qty_at = stamp if touch_qty else None
        photo_at = stamp if touch_photo else None
        conn.execute(
            """
            UPDATE avito_sync_state SET
                listing_id = ?,
                article = ?,
                last_price = COALESCE(?, last_price),
                last_qty = COALESCE(?, last_qty),
                last_photo_hash = CASE WHEN ? THEN ? ELSE last_photo_hash END,
                last_price_synced_at = COALESCE(?, last_price_synced_at),
                last_qty_synced_at = COALESCE(?, last_qty_synced_at),
                last_photo_synced_at = COALESCE(?, last_photo_synced_at),
                updated_at = ?
            WHERE avito_id = ?
            """,
            (
                lid,
                art,
                price if touch_price else None,
                qty if touch_qty else None,
                1 if touch_photo else 0,
                photo if touch_photo else "",
                price_at,
                qty_at,
                photo_at,
                stamp,
                aid,
            ),
        )
        return
    conn.execute(
        """
        INSERT INTO avito_sync_state(
            avito_id, listing_id, article, last_price, last_qty, last_photo_hash,
            last_price_synced_at, last_qty_synced_at, last_photo_synced_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            aid,
            listing_id,
            article,
            last_price if touch_price else None,
            last_qty if touch_qty else None,
            (last_photo_hash or "") if touch_photo else "",
            stamp if touch_price else None,
            stamp if touch_qty else None,
            stamp if touch_photo else None,
            stamp,
        ),
    )


def mark_sync_prices(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, int]],
) -> int:
    """rows: (avito_id, listing_id, article, price)."""
    for avito_id, listing_id, article, price in rows:
        _sync_state_upsert_row(
            conn,
            avito_id=avito_id,
            listing_id=listing_id,
            article=article,
            last_price=int(price),
            touch_price=True,
        )
    conn.commit()
    return len(rows)


def mark_sync_qtys(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, int]],
) -> int:
    """rows: (avito_id, listing_id, article, qty)."""
    for avito_id, listing_id, article, qty in rows:
        _sync_state_upsert_row(
            conn,
            avito_id=avito_id,
            listing_id=listing_id,
            article=article,
            last_qty=int(qty),
            touch_qty=True,
        )
    conn.commit()
    return len(rows)


def mark_sync_photos(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, str]],
) -> int:
    """rows: (avito_id, listing_id, article, photo_hash)."""
    for avito_id, listing_id, article, photo_hash in rows:
        key = str(avito_id or "").strip() or f"lid:{listing_id}"
        _sync_state_upsert_row(
            conn,
            avito_id=key,
            listing_id=listing_id,
            article=article,
            last_photo_hash=str(photo_hash or ""),
            touch_photo=True,
        )
    conn.commit()
    return len(rows)


def seed_sync_state_price_qty(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, int, int]],
) -> int:
    """
    Первый прогон после деплоя: записать текущие price/qty как уже отправленные,
    чтобы не устроить массовый blast в API.
    rows: (avito_id, listing_id, article, price, qty)
    """
    stamp = _utcnow_iso()
    payload = [
        (
            str(avito_id).strip(),
            str(listing_id or "").strip(),
            str(article or "").strip(),
            int(price),
            int(qty),
            stamp,
            stamp,
            stamp,
        )
        for avito_id, listing_id, article, price, qty in rows
        if str(avito_id or "").strip()
    ]
    if not payload:
        return 0
    conn.executemany(
        """
        INSERT INTO avito_sync_state(
            avito_id, listing_id, article, last_price, last_qty,
            last_price_synced_at, last_qty_synced_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(avito_id) DO UPDATE SET
            listing_id=excluded.listing_id,
            article=excluded.article,
            last_price=excluded.last_price,
            last_qty=excluded.last_qty,
            last_price_synced_at=excluded.last_price_synced_at,
            last_qty_synced_at=excluded.last_qty_synced_at,
            updated_at=excluded.updated_at
        """,
        payload,
    )
    set_meta(conn, "avito_sync_seeded_at", stamp)
    set_meta(conn, "avito_sync_seed_count", str(len(payload)))
    conn.commit()
    return len(payload)
