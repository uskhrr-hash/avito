#!/usr/bin/env python3
"""Собирает input/goods.xlsx из Google Sheets и БД."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from avito.config import load_config
from avito.stock_sources import load_secrets, refresh_goods_file

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("build_stock")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Сбор остатков из Google Sheets и БД")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = load_config(args.config)
    cfg = app.stock_sources
    if not cfg.enabled:
        LOG.info("stock_sources.enabled=false — пропускаю сбор")
        return 0

    sec_path = cfg.secrets_file if cfg.secrets_file.is_absolute() else ROOT / cfg.secrets_file
    secrets = load_secrets(sec_path)

    out, merged = refresh_goods_file(cfg, root=ROOT, secrets=secrets)
    g_count = sum(1 for r in merged if r.source == "google")
    d_count = sum(1 for r in merged if r.source == "db")
    LOG.info("Google: %s, DB: %s, итого: %s → %s", g_count, d_count, len(merged), out)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOG.error("%s", exc)
        raise
