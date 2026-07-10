#!/usr/bin/env python3
"""Проверка одной модели через словарь: каталог → +размер → словарь → канон без размера."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from avito.config import load_config
from avito.fourtochki import (
    catalog_query_title,
    dictionary_fields_to_canonical,
    resolve_canonical_model,
)
from avito.fourtochki_config import fourtochki_fetch_kwargs, load_raw_config
from avito.nomenclature_api import NomenclatureApiError, normalize_titles


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Тест словаря на одной модели каталога")
    p.add_argument(
        "catalog_model",
        nargs="?",
        default="Hankook Winter i*Pike RS2 W429",
        help="Имя модели как в каталоге 4tochki (без размера)",
    )
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    api = cfg.nomenclature_api
    fetch_kw = fourtochki_fetch_kwargs(ROOT, load_raw_config(args.config))
    dummy_size = fetch_kw["dummy_size"]
    catalog_key = args.catalog_model.strip()

    query = catalog_query_title(catalog_key, dummy_size)
    print("Каталог 4tochki:", catalog_key)
    print("Запрос в словарь:", query)
    print()

    try:
        parsed = normalize_titles(
            [query],
            base_url=api.base_url,
            batch_size=1,
            pause_sec=0,
            timeout_sec=api.timeout_sec,
        )
    except NomenclatureApiError as exc:
        print("Ошибка API:", exc)
        return 2

    fields = parsed.get(query)
    if not fields:
        print("Словарь не распознал (пустой ответ).")
        return 1

    print("Ответ словаря (сырой):")
    print(json.dumps(fields, ensure_ascii=False, indent=2))
    print()

    canon = dictionary_fields_to_canonical(fields)
    row = resolve_canonical_model(
        catalog_key=catalog_key,
        catalog_brand=str(fields.get("brand", "")),
        catalog_model=catalog_key.split(None, 1)[-1] if " " in catalog_key else catalog_key,
        normalized_catalog=parsed,
        dummy_size=dummy_size,
    )
    print("Канон без размера:")
    print("  ключ_модели:", canon["ключ_модели"])
    print("  бренд:", canon["бренд"])
    print("  модель:", canon["модель"])
    print("  имя_каноническое:", canon["имя_каноническое"])
    print("  словарь_распознан:", row["словарь_распознан"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
