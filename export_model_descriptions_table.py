#!/usr/bin/env python3
"""Bulk 4tochki → Excel: описания + ключи моделей в каноне словаря."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from avito.config import load_config
from avito.fourtochki import (
    bulk_json_to_table_rows,
    load_catalog_json,
    load_descriptions_bulk,
    normalize_catalog_dictionary,
)
from avito.fourtochki_config import fourtochki_fetch_kwargs, fourtochki_path, load_raw_config
from avito.model_descriptions import merge_model_descriptions_table
from avito.nomenclature_api import NomenclatureApiError

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("export_model_descriptions_table")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Экспорт описаний 4tochki в Excel (ключи = канон словаря)"
    )
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--bulk", type=Path, default=None)
    p.add_argument("--catalog", type=Path, default=None)
    p.add_argument("-o", "--output", type=Path, default=None)
    p.add_argument(
        "--include-unrecognized",
        action="store_true",
        help="Включить строки без канона словаря (ключи 4tochki — не рекомендуется)",
    )
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app_raw = load_raw_config(args.config)
    app = load_config(args.config)
    fetch_kw = fourtochki_fetch_kwargs(ROOT, app_raw)
    api = app.nomenclature_api

    bulk_path = args.bulk or fourtochki_path(
        ROOT, app_raw, "descriptions_json", "data/4tochki_descriptions.json"
    )
    catalog_path = args.catalog or fourtochki_path(
        ROOT, app_raw, "catalog_json", "data/4tochki_model_urls.json"
    )
    out_path = args.output or app.autoload.model_descriptions_file
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    if not bulk_path.is_file():
        LOG.error("Bulk не найден: %s", bulk_path)
        return 2

    bulk = load_descriptions_bulk(bulk_path)
    catalog = load_catalog_json(catalog_path)
    with_html = sum(
        1
        for k in catalog.models
        if (bulk.get("models", {}).get(k) or {}).get("description_html")
    )
    LOG.info("Каталог: %s моделей, с описанием в bulk: %s", len(catalog.models), with_html)

    try:
        dictionary = normalize_catalog_dictionary(
            catalog,
            base_url=api.base_url,
            batch_size=api.batch_size,
            pause_sec=api.pause_sec,
            timeout_sec=api.timeout_sec,
            dummy_size=fetch_kw["dummy_size"],
        )
    except NomenclatureApiError as exc:
        LOG.error("%s", exc)
        return 2
    LOG.info(
        "Словарь распознал моделей каталога: %s / %s",
        len(dictionary.by_catalog_key),
        len(catalog.models),
    )

    rows, skipped = bulk_json_to_table_rows(
        bulk,
        catalog,
        dictionary,
        dummy_size=fetch_kw["dummy_size"],
        canonical_only=not args.include_unrecognized,
    )
    LOG.info(
        "В таблицу: %s строк (канон словаря), пропущено без канона: %s",
        len(rows),
        len(skipped),
    )

    out_dir = ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    if skipped:
        skip_path = out_dir / "model_descriptions_unrecognized.xlsx"
        pd.DataFrame(skipped).to_excel(skip_path, index=False)
        LOG.info("Без канона словаря → %s", skip_path)

    stats = merge_model_descriptions_table(
        out_path,
        rows,
        overwrite=True,
        replace_all=args.overwrite,
    )
    LOG.info(
        "Таблица: +%s, обновлено %s, пропущено %s → %s",
        stats["added"],
        stats["updated"],
        stats["skipped"],
        out_path,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOG.error("%s", exc)
        raise
