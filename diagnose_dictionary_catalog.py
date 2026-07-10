#!/usr/bin/env python3
"""Диагностика: каталог 4tochki → словарь → канонические ключи."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from avito.config import load_config
from avito.fourtochki import (
    catalog_query_variants,
    load_catalog_json,
    load_descriptions_bulk,
    normalize_catalog_dictionary,
    resolve_canonical_model,
)
from avito.fourtochki_config import fourtochki_fetch_kwargs, fourtochki_path, load_raw_config
from avito.nomenclature_api import NomenclatureApiError

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("diagnose_dictionary")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Диагностика канона словаря для каталога 4tochki")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("-o", "--output-dir", type=Path, default=ROOT / "output")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = load_config(args.config)
    raw = load_raw_config(args.config)
    fetch_kw = fourtochki_fetch_kwargs(ROOT, raw)
    catalog = load_catalog_json(
        fourtochki_path(ROOT, raw, "catalog_json", "data/4tochki_model_urls.json")
    )
    bulk_path = fourtochki_path(ROOT, raw, "descriptions_json", "data/4tochki_descriptions.json")
    bulk = load_descriptions_bulk(bulk_path) if bulk_path.is_file() else {"models": {}}

    api = app.nomenclature_api
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

    rows = []
    for catalog_key, entry in sorted(catalog.models.items()):
        html = str((bulk.get("models", {}).get(catalog_key) or {}).get("description_html", "") or "")
        canon = resolve_canonical_model(
            catalog_key=catalog_key,
            catalog_brand=entry.brand,
            catalog_model=entry.model,
            dictionary=dictionary,
            dummy_size=fetch_kw["dummy_size"],
        )
        variants = catalog_query_variants(catalog_key, fetch_kw["dummy_size"])
        hit_query = next((q for q in variants if q in dictionary.by_query), "")
        rows.append(
            {
                "каталог_4tochki": catalog_key,
                "есть_описание": "да" if html.strip() else "нет",
                "словарь": canon["словарь_распознан"],
                "источник": canon.get("словарь_источник", ""),
                "бренд": canon["бренд"],
                "модель": canon["модель"],
                "ключ_модели": canon["ключ_модели"],
                "имя_каноническое": canon["имя_каноническое"],
                "запрос_сработал": hit_query,
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / "diagnose_dictionary_catalog.xlsx"
    pd.DataFrame(rows).to_excel(out, index=False)

    ok = sum(1 for r in rows if r["словарь"] == "да")
    with_desc = sum(1 for r in rows if r["есть_описание"] == "да")
    ok_desc = sum(1 for r in rows if r["словарь"] == "да" and r["есть_описание"] == "да")
    LOG.info("Каталог: %s моделей, словарь: %s, с описанием: %s", len(rows), ok, with_desc)
    LOG.info("Попадут в таблицу (канон + описание): %s → %s", ok_desc, out)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOG.error("%s", exc)
        raise
