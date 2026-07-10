"""База описаний по моделям шин (бренд + модель, без типоразмера)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

TABLE_COLUMNS = (
    "бренд",
    "модель",
    "ключ_модели",
    "имя_каноническое",
    "словарь_распознан",
    "каталог_4tochki",
    "описание_html",
    "источник",
    "обновлено",
)


def model_key(brand: str, model: str) -> str:
    return " ".join(x for x in (brand.strip(), model.strip()) if x).strip()


def load_model_descriptions(path: Path) -> dict[str, str]:
    """Возвращает {ключ_модели: html}. Поддерживает .xlsx и legacy .yaml."""
    if not path.exists():
        return {}
    if path.suffix.lower() in (".xlsx", ".xls"):
        return _load_from_excel(path)
    return _load_from_yaml(path)


def _load_from_yaml(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = raw.get("descriptions") if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        key = str(k).strip()
        val = str(v).strip()
        if key and val:
            out[key] = val
    return out


def _load_from_excel(path: Path) -> dict[str, str]:
    df = pd.read_excel(path, sheet_name=0)
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        html = str(row.get("описание_html", "") or "").strip()
        if not html or html.lower() == "nan":
            continue
        key = str(row.get("ключ_модели", "") or "").strip()
        if not key or key.lower() == "nan":
            key = model_key(
                str(row.get("бренд", "") or ""),
                str(row.get("модель", "") or ""),
            )
        if key:
            out[key] = html
    return out


def load_model_descriptions_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=list(TABLE_COLUMNS))
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, sheet_name=0)
    else:
        descs = _load_from_yaml(path)
        rows = [
            {
                "бренд": "",
                "модель": "",
                "ключ_модели": k,
                "каталог_4tochki": "",
                "описание_html": v,
                "источник": "yaml",
                "обновлено": "",
            }
            for k, v in descs.items()
        ]
        df = pd.DataFrame(rows)
    for col in TABLE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[list(TABLE_COLUMNS)]


def _row_quality_score(row: dict) -> int:
    """Чем выше — тем предпочтительнее строка при дедупликации."""
    score = 0
    if str(row.get("словарь_распознан", "") or "").strip().lower() == "да":
        score += 10
    canon = str(row.get("имя_каноническое", "") or "").strip()
    if canon and canon.lower() != "nan":
        score += 5
    key = str(row.get("ключ_модели", "") or "").strip()
    cat = str(row.get("каталог_4tochki", "") or "").strip()
    if cat and key and key != cat:
        score += 3
    return score


def _dedupe_table_rows(rows: list[dict]) -> list[dict]:
    """
    Одна модель каталога → одна строка.
    Убирает legacy-строки, где ключ_модели = имя 4tochki, если есть канон словаря.
    """
    by_catalog: dict[str, dict] = {}
    by_key_only: dict[str, dict] = {}
    for row in rows:
        cat = str(row.get("каталог_4tochki", "") or "").strip()
        key = str(row.get("ключ_модели", "") or "").strip()
        if not key or key.lower() == "nan":
            continue
        if cat and cat.lower() != "nan":
            prev = by_catalog.get(cat)
            if prev is None or _row_quality_score(row) > _row_quality_score(prev):
                by_catalog[cat] = row
        else:
            prev = by_key_only.get(key)
            if prev is None or _row_quality_score(row) > _row_quality_score(prev):
                by_key_only[key] = row

    out: dict[str, dict] = dict(by_key_only)
    for row in by_catalog.values():
        key = str(row.get("ключ_модели", "") or "").strip()
        out[key] = row
    return list(out.values())


def save_model_descriptions_table(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for col in TABLE_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out = out[list(TABLE_COLUMNS)]
    out.to_excel(path, index=False)


def merge_model_descriptions_table(
    path: Path,
    rows: list[dict],
    *,
    overwrite: bool = False,
    replace_all: bool = False,
) -> dict[str, int]:
    """
    Добавляет/обновляет строки по ключ_модели.

    replace_all=True (export --overwrite): таблица = только переданные rows.
    Иначе дубли по каталог_4tochki снимаются в пользу канона словаря.
    """
    if replace_all:
        existing = pd.DataFrame(columns=list(TABLE_COLUMNS))
    else:
        existing = load_model_descriptions_table(path)
    by_key: dict[str, dict] = {}
    by_catalog: dict[str, str] = {}
    for row in _dedupe_table_rows(
        [{c: r.get(c, "") for c in TABLE_COLUMNS} for _, r in existing.iterrows()]
    ):
        key = str(row.get("ключ_модели", "") or "").strip()
        cat = str(row.get("каталог_4tochki", "") or "").strip()
        if key and key.lower() != "nan":
            by_key[key] = {c: row.get(c, "") for c in TABLE_COLUMNS}
            if cat and cat.lower() != "nan":
                by_catalog[cat] = key

    added = updated = skipped = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    for item in rows:
        brand = str(item.get("бренд", "") or "").strip()
        model = str(item.get("модель", "") or "").strip()
        key = str(item.get("ключ_модели", "") or "").strip() or model_key(brand, model)
        cat = str(item.get("каталог_4tochki", "") or "").strip()
        html = str(item.get("описание_html", "") or "").strip()
        if not key or not html:
            continue
        if cat and cat in by_catalog:
            old_key = by_catalog[cat]
            if old_key != key and old_key in by_key:
                del by_key[old_key]
                updated += 1
        if key in by_key and not overwrite:
            skipped += 1
            continue
        if key in by_key:
            updated += 1
        else:
            added += 1
        by_key[key] = {
            col: str(item.get(col, "") or "").strip()
            if col not in ("описание_html",)
            else html
            for col in TABLE_COLUMNS
        }
        by_key[key]["ключ_модели"] = key
        by_key[key]["описание_html"] = html
        if not by_key[key].get("обновлено"):
            by_key[key]["обновлено"] = now
        if not by_key[key].get("источник"):
            by_key[key]["источник"] = "4tochki"
        if cat:
            by_catalog[cat] = key

    merged = pd.DataFrame(_dedupe_table_rows(list(by_key.values())))
    save_model_descriptions_table(path, merged)
    return {"added": added, "updated": updated, "skipped": skipped}


def lookup_model_description(
    descriptions: dict[str, str],
    *,
    nomenclature: str,
    brand: str,
    model: str,
) -> str:
    """Поиск по brand+model, затем по префиксу ключа модели в номенклатуре."""
    key = model_key(brand, model)
    if key and key in descriptions:
        return descriptions[key]
    nom = nomenclature.strip()
    if not nom:
        return ""
    hits = [k for k in descriptions if nom == k or nom.startswith(k + " ")]
    if hits:
        return descriptions[max(hits, key=len)]
    return ""


def resolve_model_descriptions(
    *,
    xlsx_path: Path,
    descriptions_db_enabled: bool = False,
    secrets_path: Path | None = None,
    fallback_to_xlsx: bool = True,
    pg_schema: str = "public",
    project_root: Path | None = None,
) -> dict[str, str]:
    """
    Источник описаний: PostgreSQL (approved) с опциональным дополнением из xlsx.
    """
    from avito.db import descriptions_connection, load_secrets
    from avito.descriptions_db import configure_pg_schema, load_approved_descriptions

    xlsx_map = load_model_descriptions(xlsx_path) if xlsx_path.exists() else {}
    if not descriptions_db_enabled:
        return xlsx_map

    if not secrets_path or not secrets_path.exists():
        return xlsx_map if fallback_to_xlsx else {}

    try:
        configure_pg_schema(pg_schema)
        secrets = load_secrets(secrets_path)
        with descriptions_connection(secrets, project_root=project_root) as conn:
            db_map = load_approved_descriptions(conn)
    except Exception:
        return xlsx_map if fallback_to_xlsx else {}

    if not fallback_to_xlsx:
        return db_map
    merged = dict(xlsx_map)
    merged.update(db_map)
    return merged
