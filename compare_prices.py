#!/usr/bin/env python3
"""Остатки → posting_YYYY-MM-DD.xlsx (цены из Google/БД, без парсера Avito)."""
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
    stock_avito_match_rows,
    stock_only_overview_rows,
)
from avito.config import load_config
from avito.stock_sources import load_secrets, refresh_goods_file

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("compare_prices")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Цены для выкладки из остатков")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "--avito-csv",
        type=Path,
        default=None,
        help="(устар.) Дамп Avito — только если compare.stock_only: false",
    )
    p.add_argument(
        "--skip-stock-refresh",
        action="store_true",
        help="Не обновлять остатки из Google/БД (только для отладки)",
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
    norm = sorted(
        output_dir.glob("avito_tires_normalized_*.csv"),
        key=lambda p: p.stat().st_mtime,
    )
    if norm:
        return norm[-1]
    files = sorted(
        [p for p in output_dir.glob("avito_tires_*.csv") if "normalized" not in p.name],
        key=lambda p: p.stat().st_mtime,
    )
    return files[-1] if files else None


def write_posting_xlsx(
    path: Path,
    posting: list[dict],
    problems: list[dict],
    own_rows: list[dict],
    match_rows: list[dict],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(posting).to_excel(writer, sheet_name="к выкладке", index=False)
        pd.DataFrame(match_rows).to_excel(writer, sheet_name="сопоставление", index=False)
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

    stock_path = ROOT / cmp_cfg.stock_file
    if not stock_path.is_absolute():
        stock_path = ROOT / stock_path

    stock_cfg = cfg.stock_sources
    if stock_cfg.enabled and not args.skip_stock_refresh:
        sec_path = (
            stock_cfg.secrets_file
            if stock_cfg.secrets_file.is_absolute()
            else ROOT / stock_cfg.secrets_file
        )
        try:
            secrets = load_secrets(sec_path)
            stock_path, merged = refresh_goods_file(stock_cfg, root=ROOT, secrets=secrets)
            LOG.info(
                "Остатки обновлены из Google/БД: %s позиций → %s",
                len(merged),
                stock_path,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.error("Не удалось обновить остатки: %s", exc)
            return 2
    elif not stock_path.is_file():
        LOG.error("Нет %s — запустите: python build_stock.py", stock_path)
        return 1

    try:
        stock = load_stock(stock_path, cmp_cfg)
    except (FileNotFoundError, ValueError) as exc:
        LOG.error("%s", exc)
        return 1
    except KeyError as exc:
        LOG.error("%s — проверьте имена колонок в config.yaml", exc)
        return 1

    if not stock:
        LOG.error("В остатках нет строк с номенклатурой и ценой")
        return 1

    if cmp_cfg.stock_only:
        avito_mins: dict[str, float] = {}
        match_rows = stock_only_overview_rows(stock)
        own_rows: list[dict] = []
        posting, problems, _ = build_posting_rows(stock, avito_mins, cmp_cfg, stamp)
        LOG.info(
            "Режим stock_only: цены из колонки avito_price или входящая×%.2f",
            cmp_cfg.no_avito_multiplier,
        )
    else:
        avito_path = args.avito_csv or find_latest_avito_csv(args.output_dir)
        if not avito_path or not avito_path.exists():
            LOG.error("Нет файла дампа Avito в %s", args.output_dir)
            return 1
        if "normalized" not in avito_path.name and "name_canonical" not in pd.read_csv(
            avito_path, encoding="utf-8-sig", nrows=0
        ).columns:
            LOG.warning(
                "Дамп без name_canonical — сначала: python normalize_avito.py"
            )
        avito_df = load_avito_dump(avito_path, cmp_cfg.own_seller_names)
        avito_mins = avito_min_by_title(
            avito_df,
            exclude_needs_review=cmp_cfg.exclude_needs_review,
        )
        match_rows, match_problems = stock_avito_match_rows(
            stock,
            avito_df,
            avito_mins,
            exclude_needs_review=cmp_cfg.exclude_needs_review,
        )
        posting, problems, _ = build_posting_rows(stock, avito_mins, cmp_cfg, stamp)
        seen = {(p["номенклатура"], p["проблема"]) for p in problems}
        for p in match_problems:
            key = (p["номенклатура"], p["проблема"])
            if key not in seen:
                problems.append(p)
                seen.add(key)
        own_rows = own_listings_report(avito_df)
        LOG.info("Avito дамп: %s (%s строк)", avito_path.name, len(avito_df))

    out_path = args.output_dir / f"posting_{stamp}.xlsx"
    write_posting_xlsx(out_path, posting, problems, own_rows, match_rows)

    fixed = sum(1 for p in posting if p.get("price_rule") == "fixed_google")
    calc = len(posting) - fixed
    LOG.info("Остатки: %s (%s позиций)", stock_path.name, len(stock))
    LOG.info("К выкладке: %s (фикс %s, расчёт %s)", len(posting), fixed, calc)
    LOG.info("→ %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
