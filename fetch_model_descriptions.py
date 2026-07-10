#!/usr/bin/env python3
"""Быстрый путь: описания 4tochki только для моделей из goods → Excel-таблица.

Полный пайплайн: fetch_all_4tochki_descriptions.py → export/link
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

from avito.config import load_config
from avito.fourtochki import (
    collect_model_keys_from_nomenclatures,
    fetch_descriptions_for_keys,
    load_catalog_json,
    make_description_table_row,
    normalize_catalog_dictionary,
)
from avito.nomenclature_api import NomenclatureApiError
from avito.fourtochki_config import fourtochki_fetch_kwargs, fourtochki_path, load_raw_config
from avito.model_descriptions import load_model_descriptions_table, merge_model_descriptions_table

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("fetch_model_descriptions")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Загрузка описаний 4tochki для моделей из goods")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--catalog", type=Path, default=None)
    p.add_argument("--goods", type=Path, default=None)
    p.add_argument("--only-missing", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("-o", "--output-dir", type=Path, default=ROOT / "output")
    return p.parse_args()


def _read_nomenclatures(goods_path: Path, *, has_header: bool, col_index: int) -> list[str]:
    if not goods_path.is_file():
        raise FileNotFoundError(f"goods не найден: {goods_path}")
    df = (
        pd.read_excel(goods_path, sheet_name=0, header=0)
        if has_header
        else pd.read_excel(goods_path, sheet_name=0, header=None)
    )
    col = df.columns[col_index] if has_header else col_index
    return [str(x).strip() for x in df[col].dropna().tolist() if str(x).strip()]


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = load_config(args.config)
    raw = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    fetch_kw = fourtochki_fetch_kwargs(ROOT, raw)

    catalog_path = args.catalog or fourtochki_path(
        ROOT, raw, "catalog_json", "data/4tochki_model_urls.json"
    )
    cache_dir = fourtochki_path(ROOT, raw, "cache_dir", "data/4tochki_html_cache")

    goods_path = args.goods or app.compare.stock_file
    if not goods_path.is_absolute():
        goods_path = ROOT / goods_path

    table_path = app.autoload.model_descriptions_file
    if not table_path.is_absolute():
        table_path = ROOT / table_path

    if not catalog_path.is_file():
        LOG.error("Каталог не найден: %s — сначала import_4tochki_catalog.py", catalog_path)
        return 2

    catalog = load_catalog_json(catalog_path)
    noms = _read_nomenclatures(
        goods_path,
        has_header=app.compare.stock_has_header,
        col_index=app.compare.stock_indexes.get("nomenclature", 1),
    )
    LOG.info("Номенклатур в goods: %s", len(noms))

    key_map = collect_model_keys_from_nomenclatures(noms, catalog)
    LOG.info("Совпало с каталогом 4tochki: %s уникальных моделей", len(key_map))

    if args.only_missing:
        existing = load_model_descriptions_table(table_path)
        have = set(existing["ключ_модели"].astype(str).str.strip())
        key_map = {k: v for k, v in key_map.items() if k not in have and v not in have}
        LOG.info("Без уже известных моделей: %s", len(key_map))

    if not key_map:
        LOG.info("Нечего загружать")
        return 0

    fetch_kw_args: dict = {
        "cache_dir": cache_dir,
        "pause_sec": fetch_kw["pause_sec"],
        "timeout_sec": fetch_kw["timeout_sec"],
        "refresh": args.refresh,
        "limit": args.limit,
    }
    if fetch_kw.get("user_agent"):
        fetch_kw_args["user_agent"] = fetch_kw["user_agent"]

    raw_rows, report = fetch_descriptions_for_keys(catalog, key_map, **fetch_kw_args)

    ok = sum(1 for r in report if r.get("статус") == "ok")
    LOG.info("Загружено описаний: %s / %s", ok, len(report))

    try:
        dictionary = normalize_catalog_dictionary(
            catalog,
            base_url=app.nomenclature_api.base_url,
            batch_size=app.nomenclature_api.batch_size,
            pause_sec=app.nomenclature_api.pause_sec,
            timeout_sec=app.nomenclature_api.timeout_sec,
            dummy_size=fetch_kw["dummy_size"],
        )
    except NomenclatureApiError as exc:
        LOG.error("%s", exc)
        return 2

    table_rows: list[dict] = []
    seen: set[str] = set()
    for row in raw_rows:
        cat_key = str(row.get("каталог_4tochki", "") or "")
        entry = catalog.models.get(cat_key)
        if not entry:
            continue
        canon_row = make_description_table_row(
            catalog_key=cat_key,
            catalog_brand=entry.brand,
            catalog_model=entry.model,
            description_html=str(row.get("описание_html", "") or ""),
            dictionary=dictionary,
            dummy_size=fetch_kw["dummy_size"],
        )
        key = canon_row.get("ключ_модели", "")
        if key and key not in seen:
            seen.add(key)
            table_rows.append(canon_row)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "fourtochki_fetch_report.xlsx"
    pd.DataFrame(report).to_excel(report_path, index=False)
    LOG.info("Отчёт: %s", report_path)

    if args.dry_run:
        LOG.info("dry-run: таблица не изменена")
        return 0

    stats = merge_model_descriptions_table(table_path, table_rows, overwrite=args.overwrite)
    LOG.info(
        "Таблица: +%s, обновлено %s, пропущено %s → %s",
        stats["added"],
        stats["updated"],
        stats["skipped"],
        table_path,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOG.error("%s", exc)
        raise
