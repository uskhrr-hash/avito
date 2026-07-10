"""Хранилище описаний моделей: SQLite (локально) или PostgreSQL."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from avito.model_descriptions import TABLE_COLUMNS, model_key

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

_ENGINE = "postgresql"
_PG_SCHEMA = "public"


def configure_descriptions_store(engine: str, *, pg_schema: str = "public") -> None:
    global _ENGINE, _PG_SCHEMA
    _ENGINE = engine if engine != "postgres" else "postgresql"
    _PG_SCHEMA = (pg_schema or "public").strip()


def configure_pg_schema(schema: str) -> None:
    configure_descriptions_store(_ENGINE, pg_schema=schema)


def _tbl(name: str) -> str:
    if _ENGINE == "sqlite":
        return name
    return f"{_PG_SCHEMA}.{name}"


def _ph() -> str:
    return "?" if _ENGINE == "sqlite" else "%s"


def _now() -> str | datetime:
    dt = datetime.now(timezone.utc)
    if _ENGINE == "sqlite":
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt


@contextmanager
def _cursor(conn: Any) -> Iterator[Any]:
    if _ENGINE == "sqlite":
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
    else:
        with conn.cursor() as cur:
            yield cur


def _fetch_id(cur: Any, row: Any) -> int:
    if row is None:
        raise RuntimeError("INSERT без id")
    return int(row[0])


def init_schema(
    conn: Any,
    schema_sql: Path,
    *,
    pg_schema: str = "public",
    engine: str | None = None,
) -> None:
    eng = engine or _ENGINE
    if eng == "sqlite":
        sql = schema_sql.read_text(encoding="utf-8")
        conn.executescript(sql)
        configure_descriptions_store("sqlite", pg_schema="")
        return
    schema = (pg_schema or "public").strip()
    sql = schema_sql.read_text(encoding="utf-8").replace("{schema}", schema)
    with _cursor(conn) as cur:
        cur.execute(sql)
    configure_descriptions_store("postgresql", pg_schema=schema)


@dataclass(frozen=True)
class TireModelRow:
    id: int
    model_key: str
    brand: str
    model: str
    catalog_4tochki: str
    canonical_name: str
    dictionary_ok: bool


def upsert_tire_model(
    conn: Any,
    *,
    model_key: str,
    brand: str = "",
    model: str = "",
    catalog_4tochki: str = "",
    canonical_name: str = "",
    dictionary_ok: bool = False,
) -> int:
    key = model_key.strip()
    if not key:
        raise ValueError("model_key пустой")
    now = _now()
    tm = _tbl("avito_tire_models")
    p = _ph()
    dict_val: bool | int = int(dictionary_ok) if _ENGINE == "sqlite" else dictionary_ok
    with _cursor(conn) as cur:
        if _ENGINE == "sqlite":
            cur.execute(
                f"""
                INSERT INTO {tm}
                    (model_key, brand, model, catalog_4tochki, canonical_name, dictionary_ok, updated_at)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT (model_key) DO UPDATE SET
                    brand = excluded.brand,
                    model = excluded.model,
                    catalog_4tochki = COALESCE(NULLIF(excluded.catalog_4tochki, ''), {tm}.catalog_4tochki),
                    canonical_name = COALESCE(NULLIF(excluded.canonical_name, ''), {tm}.canonical_name),
                    dictionary_ok = MAX(excluded.dictionary_ok, {tm}.dictionary_ok),
                    updated_at = excluded.updated_at
                RETURNING id
                """,
                (
                    key,
                    brand.strip(),
                    model.strip(),
                    catalog_4tochki.strip(),
                    canonical_name.strip(),
                    dict_val,
                    now,
                ),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO {tm}
                    (model_key, brand, model, catalog_4tochki, canonical_name, dictionary_ok, updated_at)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT (model_key) DO UPDATE SET
                    brand = EXCLUDED.brand,
                    model = EXCLUDED.model,
                    catalog_4tochki = COALESCE(NULLIF(EXCLUDED.catalog_4tochki, ''), {tm}.catalog_4tochki),
                    canonical_name = COALESCE(NULLIF(EXCLUDED.canonical_name, ''), {tm}.canonical_name),
                    dictionary_ok = EXCLUDED.dictionary_ok OR {tm}.dictionary_ok,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
                """,
                (
                    key,
                    brand.strip(),
                    model.strip(),
                    catalog_4tochki.strip(),
                    canonical_name.strip(),
                    dict_val,
                    now,
                ),
            )
        return _fetch_id(cur, cur.fetchone())


def insert_description(
    conn: Any,
    *,
    tire_model_id: int,
    html: str,
    status: str,
    source: str,
) -> int:
    html = html.strip()
    if not html:
        raise ValueError("html пустой")
    now = _now()
    md = _tbl("avito_model_descriptions")
    p = _ph()
    with _cursor(conn) as cur:
        cur.execute(
            f"""
            INSERT INTO {md}
                (tire_model_id, html, status, source, created_at, updated_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p})
            RETURNING id
            """,
            (tire_model_id, html, status, source, now, now),
        )
        return _fetch_id(cur, cur.fetchone())


def insert_generation_log(
    conn: Any,
    *,
    tire_model_id: int,
    model_description_id: int | None,
    provider: str,
    model_name: str,
    prompt_hash: str,
    prompt_text: str,
    input_facts: str,
    raw_response: str,
    tokens_in: int | None,
    tokens_out: int | None,
) -> None:
    dg = _tbl("avito_description_generations")
    p = _ph()
    with _cursor(conn) as cur:
        cur.execute(
            f"""
            INSERT INTO {dg} (
                tire_model_id, model_description_id, provider, model_name,
                prompt_hash, prompt_text, input_facts, raw_response,
                tokens_in, tokens_out
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """,
            (
                tire_model_id,
                model_description_id,
                provider,
                model_name,
                prompt_hash,
                prompt_text,
                input_facts,
                raw_response,
                tokens_in,
                tokens_out,
            ),
        )


def _latest_approved_sql() -> str:
    tm = _tbl("avito_tire_models")
    md = _tbl("avito_model_descriptions")
    p = _ph()
    if _ENGINE == "sqlite":
        return f"""
            SELECT tm.model_key, md.html
            FROM {md} md
            JOIN {tm} tm ON tm.id = md.tire_model_id
            WHERE md.status = {p}
              AND md.id = (
                  SELECT md2.id FROM {md} md2
                  WHERE md2.tire_model_id = tm.id AND md2.status = {p}
                  ORDER BY md2.updated_at DESC
                  LIMIT 1
              )
            ORDER BY tm.model_key
            """
    return f"""
            SELECT DISTINCT ON (tm.model_key)
                tm.model_key, md.html
            FROM {md} md
            JOIN {tm} tm ON tm.id = md.tire_model_id
            WHERE md.status = {p}
            ORDER BY tm.model_key, md.updated_at DESC
            """


def load_approved_descriptions(conn: Any) -> dict[str, str]:
    with _cursor(conn) as cur:
        if _ENGINE == "sqlite":
            cur.execute(_latest_approved_sql(), (STATUS_APPROVED, STATUS_APPROVED))
        else:
            cur.execute(_latest_approved_sql(), (STATUS_APPROVED,))
        return {str(k): str(v) for k, v in cur.fetchall() if k and v}


def list_deepseek_models_map(
    conn: Any,
    *,
    skip_if_updated_after: str = "",
) -> dict[str, dict[str, str]]:
    """Модели с описаниями source=deepseek (для перегенерации)."""
    tm = _tbl("avito_tire_models")
    md = _tbl("avito_model_descriptions")
    p = _ph()
    with _cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT DISTINCT tm.model_key, tm.brand, tm.model
            FROM {md} md
            JOIN {tm} tm ON tm.id = md.tire_model_id
            WHERE md.source = {p}
            ORDER BY tm.model_key
            """,
            ("deepseek",),
        )
        rows = cur.fetchall()
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        key = str(row[0]).strip()
        if not key:
            continue
        brand = str(row[1] or "").strip()
        model = str(row[2] or "").strip()
        if not brand and " " in key:
            brand, model = key.split(" ", 1)
        out[key] = {
            "brand": brand,
            "model": model,
            "season": "",
            "example_nom": "",
        }

    cutoff = (skip_if_updated_after or "").strip()
    if not cutoff:
        return out

    with _cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT tm.model_key, MAX(md.updated_at) AS ts
            FROM {md} md
            JOIN {tm} tm ON tm.id = md.tire_model_id
            WHERE md.source = {p}
            GROUP BY tm.model_key
            """,
            ("deepseek",),
        )
        fresh = {str(k) for k, ts in cur.fetchall() if str(ts) >= cutoff}
    return {k: v for k, v in out.items() if k not in fresh}


def get_latest_generation_facts(conn: Any, tire_model_id: int) -> str:
    dg = _tbl("avito_description_generations")
    p = _ph()
    with _cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT input_facts FROM {dg}
            WHERE tire_model_id = {p} AND COALESCE(input_facts, '') != ''
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (tire_model_id,),
        )
        row = cur.fetchone()
    if not row:
        return ""
    return str(row[0] or "").strip()


def list_models_without_approved(conn: Any, keys: list[str]) -> list[str]:
    if not keys:
        return []
    approved = load_approved_descriptions(conn)
    ordered: list[str] = []
    seen: set[str] = set()
    for k in keys:
        kk = k.strip()
        if not kk or kk in seen:
            continue
        seen.add(kk)
        if kk not in approved:
            ordered.append(kk)
    return ordered


def get_tire_model_by_key(conn: Any, key: str) -> TireModelRow | None:
    tm = _tbl("avito_tire_models")
    p = _ph()
    with _cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT id, model_key, brand, model, catalog_4tochki, canonical_name, dictionary_ok
            FROM {tm} WHERE model_key = {p}
            """,
            (key.strip(),),
        )
        row = cur.fetchone()
    if not row:
        return None
    return TireModelRow(
        id=int(row[0]),
        model_key=str(row[1]),
        brand=str(row[2] or ""),
        model=str(row[3] or ""),
        catalog_4tochki=str(row[4] or ""),
        canonical_name=str(row[5] or ""),
        dictionary_ok=bool(row[6]),
    )


def approve_description(conn: Any, description_id: int) -> None:
    now = _now()
    md = _tbl("avito_model_descriptions")
    p = _ph()
    with _cursor(conn) as cur:
        cur.execute(
            f"""
            UPDATE {md}
            SET status = {p}, updated_at = {p}
            WHERE id = {p}
            """,
            (STATUS_APPROVED, now, description_id),
        )


def import_xlsx_row(conn: Any, row: dict[str, Any], *, status: str = STATUS_APPROVED) -> bool:
    brand = str(row.get("бренд", "") or "").strip()
    model = str(row.get("модель", "") or "").strip()
    key = str(row.get("ключ_модели", "") or "").strip() or model_key(brand, model)
    html = str(row.get("описание_html", "") or "").strip()
    if not key or not html or html.lower() == "nan":
        return False

    dict_ok = str(row.get("словарь_распознан", "") or "").strip().lower() == "да"
    tire_id = upsert_tire_model(
        conn,
        model_key=key,
        brand=brand,
        model=model,
        catalog_4tochki=str(row.get("каталог_4tochki", "") or "").strip(),
        canonical_name=str(row.get("имя_каноническое", "") or "").strip(),
        dictionary_ok=dict_ok,
    )

    md = _tbl("avito_model_descriptions")
    p = _ph()
    with _cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT 1 FROM {md} md
            WHERE md.tire_model_id = {p} AND md.status = {p} AND md.html = {p}
            LIMIT 1
            """,
            (tire_id, status, html),
        )
        if cur.fetchone():
            return False

    source = str(row.get("источник", "") or "").strip() or "xlsx_import"
    insert_description(conn, tire_model_id=tire_id, html=html, status=status, source=source)
    return True


def export_to_dataframe(conn: Any):
    import pandas as pd

    tm = _tbl("avito_tire_models")
    md = _tbl("avito_model_descriptions")
    p = _ph()
    if _ENGINE == "sqlite":
        sql = f"""
            SELECT tm.brand, tm.model, tm.model_key, tm.canonical_name,
                   CASE WHEN tm.dictionary_ok THEN 'да' ELSE '' END,
                   tm.catalog_4tochki, md.html, md.source, md.status,
                   strftime('%Y-%m-%d %H:%M', md.updated_at)
            FROM {tm} tm
            JOIN {md} md ON md.tire_model_id = tm.id
            WHERE md.id = (
                SELECT md2.id FROM {md} md2
                WHERE md2.tire_model_id = tm.id
                ORDER BY md2.updated_at DESC
                LIMIT 1
            )
            ORDER BY tm.model_key
            """
        params: tuple = ()
    else:
        sql = f"""
            SELECT DISTINCT ON (tm.model_key)
                tm.brand, tm.model, tm.model_key, tm.canonical_name,
                CASE WHEN tm.dictionary_ok THEN 'да' ELSE '' END,
                tm.catalog_4tochki, md.html, md.source, md.status,
                to_char(md.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI')
            FROM {tm} tm
            JOIN {md} md ON md.tire_model_id = tm.id
            ORDER BY tm.model_key, md.updated_at DESC
            """
        params = ()

    with _cursor(conn) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    data = []
    for r in rows:
        data.append(
            {
                "бренд": r[0] or "",
                "модель": r[1] or "",
                "ключ_модели": r[2] or "",
                "имя_каноническое": r[3] or "",
                "словарь_распознан": r[4] or "",
                "каталог_4tochki": r[5] or "",
                "описание_html": r[6] or "",
                "источник": r[7] or "",
                "статус": r[8] or "",
                "обновлено": r[9] or "",
            }
        )
    if not data:
        return pd.DataFrame(columns=list(TABLE_COLUMNS) + ("статус",))
    return pd.DataFrame(data)


def write_descriptions_xlsx(conn: Any, path: Path) -> int:
    """Экспорт БД → Excel (для просмотра; автозагрузка читает из БД)."""
    df = export_to_dataframe(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
    return len(df)


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def html_to_plain(text: str) -> str:
    t = _HTML_TAG_RE.sub(" ", text)
    t = re.sub(r"\s+", " ", t)
    return t.strip()
