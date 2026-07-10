#!/usr/bin/env python3
"""Прогон title из дампа Avito через сервис словарей → name (наш формат)."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from avito.config import load_config
from avito.nomenclature_api import NomenclatureApiError, normalize_titles

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("normalize_avito")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Нормализация title Avito через API словарей")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--csv", type=Path, default=None, help="avito_tires_*.csv")
    p.add_argument("-o", "--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--date", default=None)
    p.add_argument("--batch-size", type=int, default=None)
    return p.parse_args()


def find_latest_csv(output_dir: Path) -> Path | None:
    files = [p for p in output_dir.glob("avito_tires_*.csv") if "normalized" not in p.name]
    return sorted(files, key=lambda p: p.stat().st_mtime)[-1] if files else None


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_config(args.config)
    api = cfg.nomenclature_api
    batch_size = args.batch_size if args.batch_size is not None else api.batch_size

    src = args.csv or find_latest_csv(args.output_dir)
    if not src or not src.exists():
        LOG.error("Нет avito_tires_*.csv в output/")
        return 1

    stamp = args.date or date.today().isoformat()
    out_path = args.output_dir / f"avito_tires_normalized_{stamp}.csv"

    df = pd.read_csv(src, encoding="utf-8-sig")
    if "title" not in df.columns:
        LOG.error("В CSV нет колонки title")
        return 1

    titles = df["title"].astype(str).str.strip().tolist()
    unique = sorted({t for t in titles if t and t.lower() != "nan"})
    LOG.info("Уникальных title: %s (строк в дампе: %s)", len(unique), len(df))

    try:
        parsed = normalize_titles(
            unique,
            base_url=api.base_url,
            batch_size=batch_size,
            pause_sec=api.pause_sec,
            timeout_sec=api.timeout_sec,
        )
    except NomenclatureApiError as e:
        LOG.error("%s", e)
        return 2

    LOG.info("Распознано словарём: %s / %s", len(parsed), len(unique))

    # развернуть в колонки
    rows_map: dict[str, dict] = {}
    for title, fields in parsed.items():
        rows_map[title] = {
            "name_canonical": fields.get("name", ""),
            "norm_brand": fields.get("brand", ""),
            "norm_model": fields.get("model", ""),
            "norm_season": fields.get("season", ""),
            "norm_mnemo": fields.get("mnemo", ""),
            "norm_width": fields.get("width", ""),
            "norm_profile": fields.get("profile", ""),
            "norm_diameter": fields.get("diameter", ""),
            "norm_load": fields.get("load", ""),
            "norm_speed": fields.get("speed", ""),
            "dict_recognized": True,
        }

    def row_extra(title: str) -> dict:
        base = {
            "name_canonical": "",
            "norm_brand": "",
            "norm_model": "",
            "norm_season": "",
            "norm_mnemo": "",
            "norm_width": "",
            "norm_profile": "",
            "norm_diameter": "",
            "norm_load": "",
            "norm_speed": "",
            "dict_recognized": False,
        }
        if title in rows_map:
            base.update(rows_map[title])
        return base

    extras = df["title"].astype(str).str.strip().map(row_extra)
    extra_df = pd.DataFrame(extras.tolist())
    out = pd.concat([df, extra_df], axis=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    LOG.info("→ %s", out_path)

    miss = len(unique) - len(parsed)
    if miss:
        LOG.info("Не распознано: %s (см. dict_recognized=false)", miss)
    return 0


if __name__ == "__main__":
    sys.exit(main())
