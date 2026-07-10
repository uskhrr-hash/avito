#!/usr/bin/env python3
"""Импорт номеров объявлений из выгрузки Авито → input/avito_ids.csv."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from avito.autoload import (
    _extract_avito_export_maps,
    avito_ids_for_posting,
    find_latest_avito_export,
    load_avito_ids,
    load_posting,
    save_avito_ids_csv,
)
from avito.config import load_config

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("import_avito_ids")


def find_latest_posting(output_dir: Path) -> Path | None:
    files = sorted(output_dir.glob("posting_*.xlsx"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Номера активных объявлений Avito → avito_ids.csv"
    )
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "export",
        nargs="?",
        type=Path,
        default=None,
        help="xlsx с Авито (по умолчанию — последний 432801655_*.xlsx в input/)",
    )
    p.add_argument(
        "--posting",
        type=Path,
        default=None,
        help="posting_*.xlsx для сопоставления названия → артикул",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Куда писать csv (по умолчанию из config)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    app_cfg = load_config(args.config)
    export = args.export
    if export is None:
        export = find_latest_avito_export(ROOT / "input")
    if export is None or not export.exists():
        LOG.error(
            "Не найден файл выгрузки — положите xlsx в input/ или укажите путь"
        )
        return 1

    posting_path = args.posting or find_latest_posting(ROOT / "output")
    posting_df = (
        load_posting(posting_path)
        if posting_path and posting_path.exists()
        else pd.DataFrame()
    )

    out = args.output or (ROOT / app_cfg.autoload.avito_ids_file)
    stores = app_cfg.stores
    ids_from_xlsx, titles_from_xlsx = _extract_avito_export_maps(export)
    existing = load_avito_ids(out, stores) if out.exists() else {}
    merged = avito_ids_for_posting(
        posting_df,
        stores,
        ids_from_xlsx=ids_from_xlsx,
        titles_from_xlsx=titles_from_xlsx,
        ids_from_csv=existing,
    )
    if not merged:
        LOG.error(
            "Не удалось сопоставить объявления — нужен posting с номенклатурой "
            "или md_артикул в выгрузке"
        )
        return 1

    n = save_avito_ids_csv(out, merged)
    LOG.info("Источник: %s (%s названий)", export.name, len(titles_from_xlsx))
    if posting_path:
        LOG.info("Posting: %s", posting_path.name)
    LOG.info("Записано %s артикулов → %s", n, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
