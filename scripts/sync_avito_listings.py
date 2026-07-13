#!/usr/bin/env python3
"""Обновление цены и остатков уже размещённых объявлений через Avito API."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from avito.autoload import (
    avito_ids_for_posting,
    load_avito_ids,
    load_posting,
    _extract_avito_export_maps,
    find_latest_avito_export,
)
from avito.avito_api import AvitoApiClient, load_avito_api_config
from avito.config import load_config
from avito.db import load_secrets
from avito.sync_listings import build_sync_items, sync_listings

LOG = logging.getLogger("sync_avito_listings")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Цена и остаток для объявлений, уже на Avito (без автозагрузки)"
    )
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--posting", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def find_latest_posting(output_dir: Path) -> Path | None:
    files = sorted(output_dir.glob("posting_*.xlsx"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    app = load_config(args.config)
    sync_cfg = app.avito_sync
    if not sync_cfg.enabled and not args.dry_run:
        LOG.info("avito_sync.enabled=false — пропуск")
        return 0

    posting_path = args.posting or find_latest_posting(ROOT / "output")
    if not posting_path or not posting_path.exists():
        LOG.error("Нет posting_*.xlsx — сначала compare_prices.py")
        return 1

    posting_df = load_posting(posting_path)
    avito_ids_path = ROOT / app.autoload.avito_ids_file
    ids_from_csv = load_avito_ids(avito_ids_path, app.stores) if avito_ids_path.exists() else {}

    export = find_latest_avito_export(ROOT / "input")
    ids_from_xlsx: dict[str, str] = {}
    titles_from_xlsx: dict[str, str] = {}
    if export:
        ids_from_xlsx, titles_from_xlsx = _extract_avito_export_maps(export)

    avito_ids = avito_ids_for_posting(
        posting_df,
        app.stores,
        ids_from_xlsx=ids_from_xlsx,
        titles_from_xlsx=titles_from_xlsx,
        ids_from_csv=ids_from_csv,
    )

    items = build_sync_items(
        posting_df,
        app.stores,
        avito_ids,
        max_listing_quantity=app.autoload.max_listing_quantity,
    )
    LOG.info("Posting: %s | к обновлению через API: %s", posting_path.name, len(items))
    if not items:
        return 0

    dry_run = args.dry_run or sync_cfg.dry_run
    if dry_run:
        LOG.info("Режим dry-run (запросы к API не отправляются)")

    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = ROOT / secrets_path
    client = AvitoApiClient(load_avito_api_config(load_secrets(secrets_path)))

    stats = sync_listings(
        client,
        items,
        dry_run=dry_run,
        stock_batch_size=sync_cfg.stock_batch_size,
        price_pause_sec=sync_cfg.price_pause_sec,
    )
    LOG.info(
        "Готово: цены ok=%s fail=%s | остатки ok=%s fail=%s",
        stats.prices_updated,
        stats.prices_failed,
        stats.stocks_updated,
        stats.stocks_failed,
    )
    for err in stats.errors[:20]:
        LOG.warning("%s", err)
    if len(stats.errors) > 20:
        LOG.warning("…ещё %s ошибок", len(stats.errors) - 20)
    return 1 if stats.prices_failed or stats.stocks_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
