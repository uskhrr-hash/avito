#!/usr/bin/env python3
"""Шпаргалка имён файлов для загрузки через web photo upload."""
from __future__ import annotations

import argparse
import html
import logging
import sys
from datetime import date
from pathlib import Path

from avito.compare import load_stock
from avito.config import load_config
from avito.photos import article_photo_filenames, human_photo_hint

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("prepare_photos")

PHOTO_APP_URL = "https://avito.shinaufa.ru/"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Список имён фото для web-загрузки")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--stock", type=Path, default=None)
    p.add_argument("-o", "--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--date", default=None)
    return p.parse_args()


def build_html(rows: list[dict], *, store_prefixes: list[str], stamp: str) -> str:
    store_dirs = ", ".join(f"<b>{html.escape(p)}</b>" for p in store_prefixes) or "—"
    layout_hint = (
        f"Загрузка: <a href=\"{PHOTO_APP_URL}\">{html.escape(PHOTO_APP_URL)}</a><br>"
        f"Магазины: {store_dirs}. Имена файлов: <code>124889.jpg</code>, "
        "<code>124889-1.jpg</code> …"
    )
    cards = []
    for r in rows:
        art = html.escape(str(r.get("артикул", "")))
        nom = html.escape(str(r.get("номенклатура", "")))
        hint = html.escape(human_photo_hint(str(r.get("артикул", "")), count=3))
        cards.append(
            f"<div class='card'><div class='art'>{art}</div>"
            f"<div class='nom'>{nom}</div><div class='files'>{hint}</div></div>"
        )
    body = "\n".join(cards) or "<p>Нет позиций</p>"
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Фото {html.escape(stamp)}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#f6f7f9}}
.card{{background:#fff;padding:12px 14px;margin:8px 0;border-radius:8px}}
.art{{font-weight:700}}.files{{color:#333;font-family:ui-monospace,monospace}}
.muted{{color:#666}}
</style></head><body>
<h1>Имена фото · {html.escape(stamp)}</h1>
<p class="muted">{layout_hint}</p>
{body}
</body></html>
"""


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = load_config(args.config)
    stamp = args.date or date.today().isoformat()
    stock_path = args.stock or (ROOT / app.compare.stock_file)
    stock = load_stock(
        stock_path,
        app.compare,
        stock_db_path=app.stock_db.path if app.stock_db.path.is_file() else None,
        stock_db_schema=app.stock_db.schema_sql,
    )
    rows = [
        {"артикул": r.article, "номенклатура": r.nomenclature}
        for r in stock
        if r.article
    ][:200]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"photo_names_{stamp}.html"
    out.write_text(
        build_html(rows, store_prefixes=list(app.stores.prefixes), stamp=stamp),
        encoding="utf-8",
    )
    LOG.info("Готово: %s (%s позиций, приложение %s)", out, len(rows), PHOTO_APP_URL)
    sample = article_photo_filenames(rows[0]["артикул"]) if rows else []
    if sample:
        LOG.info("Пример: %s", ", ".join(sample))
    return 0


if __name__ == "__main__":
    sys.exit(main())
