-- SQLite: локальная БД описаний (без Docker / PostgreSQL).
-- Файл: data/avito_descriptions.db

CREATE TABLE IF NOT EXISTS avito_tire_models (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_key       TEXT NOT NULL UNIQUE,
    brand           TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    catalog_4tochki TEXT,
    canonical_name  TEXT,
    dictionary_ok   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_avito_tire_models_brand_model
    ON avito_tire_models (brand, model);

CREATE TABLE IF NOT EXISTS avito_model_descriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tire_model_id   INTEGER NOT NULL REFERENCES avito_tire_models(id) ON DELETE CASCADE,
    html            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'approved', 'rejected')),
    source          TEXT NOT NULL DEFAULT 'manual',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_avito_model_descriptions_model_status
    ON avito_model_descriptions (tire_model_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS avito_description_generations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    tire_model_id         INTEGER NOT NULL REFERENCES avito_tire_models(id) ON DELETE CASCADE,
    model_description_id  INTEGER REFERENCES avito_model_descriptions(id) ON DELETE SET NULL,
    provider              TEXT NOT NULL DEFAULT 'deepseek',
    model_name            TEXT NOT NULL DEFAULT '',
    prompt_hash           TEXT,
    prompt_text           TEXT,
    input_facts           TEXT,
    raw_response          TEXT,
    tokens_in             INTEGER,
    tokens_out            INTEGER,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_avito_description_generations_model
    ON avito_description_generations (tire_model_id, created_at DESC);
