-- Таблицы описаний для автозагрузки Avito.
-- Не требует CREATE SCHEMA — таблицы в существующей схеме (по умолчанию public).
-- Плейсхолдер {schema} подставляется в init_descriptions_db.py

CREATE TABLE IF NOT EXISTS {schema}.avito_tire_models (
    id              SERIAL PRIMARY KEY,
    model_key       VARCHAR(512) NOT NULL UNIQUE,
    brand           VARCHAR(255) NOT NULL DEFAULT '',
    model           VARCHAR(255) NOT NULL DEFAULT '',
    catalog_4tochki VARCHAR(512),
    canonical_name  VARCHAR(512),
    dictionary_ok   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_avito_tire_models_brand_model
    ON {schema}.avito_tire_models (brand, model);

CREATE TABLE IF NOT EXISTS {schema}.avito_model_descriptions (
    id              SERIAL PRIMARY KEY,
    tire_model_id   INTEGER NOT NULL REFERENCES {schema}.avito_tire_models(id) ON DELETE CASCADE,
    html            TEXT NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'draft',
    source          VARCHAR(64) NOT NULL DEFAULT 'manual',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT avito_model_descriptions_status_chk
        CHECK (status IN ('draft', 'approved', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_avito_model_descriptions_model_status
    ON {schema}.avito_model_descriptions (tire_model_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS {schema}.avito_description_generations (
    id                    SERIAL PRIMARY KEY,
    tire_model_id         INTEGER NOT NULL REFERENCES {schema}.avito_tire_models(id) ON DELETE CASCADE,
    model_description_id  INTEGER REFERENCES {schema}.avito_model_descriptions(id) ON DELETE SET NULL,
    provider              VARCHAR(64) NOT NULL DEFAULT 'deepseek',
    model_name            VARCHAR(128) NOT NULL DEFAULT '',
    prompt_hash           VARCHAR(64),
    prompt_text           TEXT,
    input_facts           TEXT,
    raw_response          TEXT,
    tokens_in             INTEGER,
    tokens_out            INTEGER,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_avito_description_generations_model
    ON {schema}.avito_description_generations (tire_model_id, created_at DESC);
