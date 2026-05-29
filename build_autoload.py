#!/usr/bin/env python3
"""posting_*.xlsx + шаблон Avito → autoload_*.xlsx для загрузки в ЛК."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from avito.autoload import fill_autoload_template, load_avito_ids, load_posting
from avito.config import load_config

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("build_autoload")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Заполнение шаблона автозагрузки Avito")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--posting", type=Path, default=None, help="posting_*.xlsx")
    p.add_argument("--template", type=Path, default=None)
    p.add_argument("-o", "--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--date", default=None)
    return p.parse_args()


def find_latest_posting(output_dir: Path) -> Path | None:
    files = sorted(output_dir.glob("posting_*.xlsx"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cfg = load_config(args.config).autoload
    stamp = args.date or date.today().isoformat()

    posting_path = args.posting or find_latest_posting(args.output_dir)
    if not posting_path or not posting_path.exists():
        LOG.error("Нет posting_*.xlsx — сначала: python compare_prices.py")
        return 1

    template_path = args.template or (ROOT / cfg.template_file)
    if not template_path.is_absolute():
        template_path = ROOT / template_path
    if not template_path.exists():
        LOG.error("Шаблон не найден: %s", template_path)
        return 1

    avito_ids_path = ROOT / cfg.avito_ids_file
    avito_ids = load_avito_ids(avito_ids_path)

    posting_df = load_posting(posting_path)
    out_path = args.output_dir / f"autoload_{stamp}.xlsx"

    stats = fill_autoload_template(
        template_path=template_path,
        posting_df=posting_df,
        cfg=cfg,
        avito_ids=avito_ids,
        output_path=out_path,
    )

    LOG.info("Posting: %s (%s строк)", posting_path.name, len(posting_df))
    LOG.info("Шаблон: %s", template_path.name)
    LOG.info(
        "Готово: обновлено %s, добавлено %s, пропущено %s → %s",
        stats["updated"],
        stats["appended"],
        stats["skipped"],
        out_path,
    )
    LOG.info(
        "Фото (пример): yandex_disk://%s/АРТИКУЛ/01.%s",
        cfg.yandex_disk_root,
        cfg.image_ext,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
