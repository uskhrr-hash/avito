-- SQLite: локальный кэш остатков и пайплайна Avito.
-- Файл: data/avito_stock.db

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

-- Очередь «нет фото» (build_autoload → photo upload)
CREATE TABLE IF NOT EXISTS no_photos_queue (
    article       TEXT PRIMARY KEY,
    nomenclature  TEXT NOT NULL DEFAULT '',
    stores        TEXT NOT NULL DEFAULT '',
    problem       TEXT NOT NULL DEFAULT '',
    kind          TEXT NOT NULL DEFAULT 'tire',
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_no_photos_stores ON no_photos_queue (stores);

-- Результат compare_prices → build_autoload
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

-- Объявления автозагрузки (SoT вместо autoload_working.xlsx)
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

-- Ручная цена (админка) — высший приоритет при расчёте выкладки
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
