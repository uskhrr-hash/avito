#!/usr/bin/env python3
"""Остатки + дамп Avito → posting_YYYY-MM-DD.xlsx (номенклатура 1:1)."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from avito.compare import (
    avito_min_by_title,
    build_posting_rows,
    load_avito_dump,
    load_stock,
    own_listings_report,
)
from avito.config import load_config

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("compare_prices")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Сравнение остатков с Avito")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "--avito-csv",
        type=Path,
        default=None,
        help="Дамп Avito (по умолчанию — последний output/avito_tires_*.csv)",
    )
    p.add_argument(
        "--stock",
        type=Path,
        default=None,
        help="Остатки (по умолчанию из config compare.stock_file)",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=ROOT / "output",
    )
    p.add_argument(
        "--date",
        default=None,
        help="Дата в имени файла YYYY-MM-DD (по умолчанию сегодня)",
    )
    return p.parse_args()


def find_latest_avito_csv(output_dir: Path) -> Path | None:
    files = sorted(output_dir.glob("avito_tires_*.csv"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def write_posting_xlsx(
    path: Path,
    posting: list[dict],
    problems: list[dict],
    own_rows: list[dict],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(posting).to_excel(writer, sheet_name="к выкладке", index=False)
        pd.DataFrame(problems).to_excel(writer, sheet_name="проблемы", index=False)
        pd.DataFrame(own_rows).to_excel(writer, sheet_name="свои на avito", index=False)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cfg = load_config(args.config)
    cmp_cfg = cfg.compare
    stamp = args.date or date.today().isoformat()

    avito_path = args.avito_csv or find_latest_avito_csv(args.output_dir)
    if not avito_path or not avito_path.exists():
        LOG.error("Нет файла дампа Avito в %s", args.output_dir)
        return 1

    stock_path = args.stock or (ROOT / cmp_cfg.stock_file)
    if not stock_path.is_absolute():
        stock_path = ROOT / stock_path

    try:
        stock = load_stock(stock_path, cmp_cfg)
    except FileNotFoundError as exc:
        LOG.error("%s — положите файл в input/stock.xlsx", exc)
        return 1
    except KeyError as exc:
        LOG.error("%s — проверьте имена колонок в config.yaml", exc)
        return 1

    if not stock:
        LOG.error("В остатках нет строк с номенклатурой и ценой")
        return 1

    avito_df = load_avito_dump(avito_path, cmp_cfg.own_seller_names)
    avito_mins = avito_min_by_title(
        avito_df,
        exclude_needs_review=cmp_cfg.exclude_needs_review,
    )

    posting, problems, _ = build_posting_rows(stock, avito_mins, cmp_cfg, stamp)
    own_rows = own_listings_report(avito_df)

    # номенклатура в остатках, но нет ни одного title на avito (для статистики)
    stock_keys = {r.nomenclature for r in stock}
    avito_titles = set(avito_df["title"].astype(str).str.strip())
    for nom in sorted(stock_keys - avito_titles):
        if not any(p["номенклатура"] == nom and p["есть_на_avito"] for p in posting):
            pass  # already handled via no_avito in posting

    out_path = args.output_dir / f"posting_{stamp}.xlsx"
    write_posting_xlsx(out_path, posting, problems, own_rows)

    on_avito = sum(1 for p in posting if p["есть_на_avito"])
    LOG.info("Avito дамп: %s (%s строк)", avito_path.name, len(avito_df))
    LOG.info("Остатки: %s (%s позиций)", stock_path.name, len(stock))
    LOG.info("Совпадение 1:1 на Avito: %s / %s", on_avito, len(posting))
    LOG.info("Свои объявления в дампе: %s", len(own_rows))
    LOG.info("→ %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
