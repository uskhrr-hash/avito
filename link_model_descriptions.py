#!/usr/bin/env python3
"""Связывает bulk 4tochki + словарь + goods → input/model_descriptions.xlsx."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from avito.config import load_config
from avito.fourtochki import (
    link_descriptions_to_goods,
    load_catalog_json,
    load_descriptions_bulk,
    normalize_for_descriptions,
)
from avito.fourtochki_config import fourtochki_fetch_kwargs, fourtochki_path, load_raw_config
from avito.model_descriptions import load_model_descriptions_table, merge_model_descriptions_table
from avito.nomenclature_api import NomenclatureApiError

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("link_model_descriptions")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Сопоставление описаний 4tochki с goods через словарь")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--bulk", type=Path, default=None)
    p.add_argument("--catalog", type=Path, default=None)
    p.add_argument("--goods", type=Path, default=None)
    p.add_argument("--all-models", action="store_true", help="Все модели каталога, не только из goods")
    p.add_argument("--only-missing", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
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
    raw = load_raw_config(args.config)
    fetch_kw = fourtochki_fetch_kwargs(ROOT, raw)
    dummy_size = fetch_kw["dummy_size"]

    bulk_path = args.bulk or fourtochki_path(
        ROOT, raw, "descriptions_json", "data/4tochki_descriptions.json"
    )
    catalog_path = args.catalog or fourtochki_path(
        ROOT, raw, "catalog_json", "data/4tochki_model_urls.json"
    )
    goods_path = args.goods or app.compare.stock_file
    if not goods_path.is_absolute():
        goods_path = ROOT / goods_path

    table_path = app.autoload.model_descriptions_file
    if not table_path.is_absolute():
        table_path = ROOT / table_path

    if not bulk_path.is_file():
        LOG.error("Bulk не найден: %s — сначала fetch_all_4tochki_descriptions.py", bulk_path)
        return 2
    if not catalog_path.is_file():
        LOG.error("Каталог не найден: %s", catalog_path)
        return 2

    bulk = load_descriptions_bulk(bulk_path)
    catalog = load_catalog_json(catalog_path)
    goods_noms = _read_nomenclatures(
        goods_path,
        has_header=app.compare.stock_has_header,
        col_index=app.compare.stock_indexes.get("nomenclature", 1),
    )
    LOG.info("Номенклатур в goods: %s", len(goods_noms))

    api = app.nomenclature_api
    try:
        dictionary = normalize_for_descriptions(
            catalog,
            goods_noms,
            base_url=api.base_url,
            batch_size=api.batch_size,
            pause_sec=api.pause_sec,
            timeout_sec=api.timeout_sec,
            dummy_size=dummy_size,
        )
    except NomenclatureApiError as exc:
        LOG.error("%s", exc)
        return 2
    goods_ok = sum(1 for n in goods_noms if n in dictionary.by_query)
    LOG.info(
        "Словарь: goods распознано %s / %s, связей goods→каталог %s",
        goods_ok,
        len(goods_noms),
        len(dictionary.by_catalog_key),
    )

    table_rows, report = link_descriptions_to_goods(
        bulk,
        catalog,
        goods_noms,
        dictionary,
        dummy_size=dummy_size,
        goods_only=not args.all_models,
    )

    with_desc = sum(1 for r in report if r.get("есть_описание"))
    canon_yes = sum(1 for r in table_rows if r.get("словарь_распознан") == "да")
    goods_no_dict = sum(1 for r in report if not r.get("словарь"))
    LOG.info("Goods с описанием 4tochki: %s / %s", with_desc, len(report))
    LOG.info(
        "Моделей в таблице: %s (канон словаря: %s), goods без словаря: %s",
        len(table_rows),
        canon_yes,
        goods_no_dict,
    )

    if args.only_missing:
        existing = load_model_descriptions_table(table_path)
        have = set(existing["ключ_модели"].astype(str).str.strip())
        table_rows = [r for r in table_rows if r.get("ключ_модели") not in have]
        LOG.info("Новых моделей (only-missing): %s", len(table_rows))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "model_descriptions_link_report.xlsx"
    pd.DataFrame(report).to_excel(report_path, index=False)
    LOG.info("Отчёт: %s", report_path)

    summary = pd.DataFrame(
        [
            {"метрика": "goods всего", "значение": len(goods_noms)},
            {"метрика": "goods распознано словарём", "значение": goods_ok},
            {"метрика": "goods с описанием 4tochki", "значение": with_desc},
            {"метрика": "моделей в таблице", "значение": len(table_rows)},
            {"метрика": "канон словаря в таблице", "значение": canon_yes},
        ]
    )
    summary.to_excel(args.output_dir / "model_descriptions_link_summary.xlsx", index=False)

    if args.dry_run:
        LOG.info("dry-run: таблица не изменена")
        return 0

    if not table_rows:
        LOG.info("Нечего записывать")
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
