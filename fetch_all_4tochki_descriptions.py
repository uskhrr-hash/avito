#!/usr/bin/env python3
"""Скачивает описания всех моделей из каталога 4tochki (без привязки к goods)."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from avito.fourtochki import fetch_all_catalog_descriptions, load_catalog_json
from avito.fourtochki_config import fourtochki_fetch_kwargs, fourtochki_path, load_raw_config

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("fetch_all_4tochki")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Массовая загрузка описаний 4tochki")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--catalog", type=Path, default=None)
    p.add_argument("--output", type=Path, default=None, help="data/4tochki_descriptions.json")
    p.add_argument("--refresh", action="store_true", help="Перекачать HTML, игнорировать кэш")
    p.add_argument("--no-resume", action="store_true", help="Не пропускать уже ok в bulk JSON")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("-o", "--report-dir", type=Path, default=ROOT / "output")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    raw = load_raw_config(args.config)
    fetch_kw = fourtochki_fetch_kwargs(ROOT, raw)
    catalog_path = args.catalog or fourtochki_path(
        ROOT, raw, "catalog_json", "data/4tochki_model_urls.json"
    )
    bulk_path = args.output or fourtochki_path(
        ROOT, raw, "descriptions_json", "data/4tochki_descriptions.json"
    )
    cache_dir = fourtochki_path(ROOT, raw, "cache_dir", "data/4tochki_html_cache")

    if not catalog_path.is_file():
        LOG.error("Каталог не найден: %s — сначала import_4tochki_catalog.py", catalog_path)
        return 2

    catalog = load_catalog_json(catalog_path)
    LOG.info("Моделей в каталоге: %s", len(catalog.models))

    bulk, report = fetch_all_catalog_descriptions(
        catalog,
        cache_dir=cache_dir,
        bulk_path=bulk_path,
        refresh=args.refresh,
        resume=not args.no_resume,
        limit=args.limit,
        pause_sec=fetch_kw["pause_sec"],
        timeout_sec=fetch_kw["timeout_sec"],
        user_agent=fetch_kw.get("user_agent") or None,
    )

    ok = sum(1 for r in report if r.get("статус") in ("ok", "кэш bulk"))
    LOG.info("Готово: %s / %s → %s", ok, len(report), bulk_path)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    import pandas as pd

    report_path = args.report_dir / "fourtochki_fetch_all_report.xlsx"
    pd.DataFrame(report).to_excel(report_path, index=False)
    LOG.info("Отчёт: %s", report_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOG.error("%s", exc)
        raise
