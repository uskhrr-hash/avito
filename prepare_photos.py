#!/usr/bin/env python3
"""Шпаргалка для загрузки фото на Яндекс.Диск с телефона."""
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

DISK_URL = "https://disk.yandex.ru/client/disk/%D0%90%D0%B2%D0%B8%D1%82%D0%BE"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Список имён фото для загрузки на Диск")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--stock", type=Path, default=None)
    p.add_argument("-o", "--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--date", default=None)
    return p.parse_args()


def _photo_cfg(app) -> PhotoNamingSettings:
    a = app.autoload
    return PhotoNamingSettings(
        yandex_disk_root=a.yandex_disk_root,
        image_count=a.image_count,
        image_ext=a.image_ext,
        photo_layout=getattr(a, "photo_layout", "flat"),
    )


def build_html(rows: list[dict], *, inbox_subdir: str, store_prefixes: list[str], stamp: str) -> str:
    store_dirs = ", ".join(f"<b>{html.escape(p)}</b>" for p in store_prefixes) or "—"
    layout_hint = (
        "Менеджеры: <b>Яндекс.Диск</b> → "
        f"<b>Авито/{html.escape(inbox_subdir)}/</b> + папка магазина ({store_dirs}).<br>"
        "Пример: положить <code>124889.jpg</code> в папку <code>md</code> → "
        "объявление с контактами магазина <b>md</b>."
    )
    cards = []
    for r in rows:
        art = html.escape(r["article"])
        nom = html.escape(r["nomenclature"])
        names = html.escape(human_photo_hint(r["article"]))
        cards.append(
            f"""
            <article class="card" data-search="{art} {nom}">
              <div class="art">{art}</div>
              <p class="nom">{nom}</p>
              <p class="files">📷 <code>{names}</code></p>
              <button type="button" class="copy" data-copy="{html.escape(r["copy_text"])}">
                Скопировать имя файла
              </button>
            </article>"""
        )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Фото на Диск — {stamp}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 12px;
            background: #f4f4f5; color: #111; }}
    h1 {{ font-size: 1.25rem; margin: 0 0 8px; }}
    .steps {{ background: #fff; border-radius: 12px; padding: 14px; margin-bottom: 12px;
              font-size: 0.95rem; line-height: 1.5; }}
    .steps a {{ color: #0066cc; }}
    #q {{ width: 100%; padding: 12px; font-size: 16px; border: 1px solid #ccc;
          border-radius: 10px; margin-bottom: 12px; }}
    .card {{ background: #fff; border-radius: 12px; padding: 14px; margin-bottom: 10px;
             box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
    .art {{ font-size: 1.75rem; font-weight: 700; letter-spacing: 0.02em; }}
    .nom {{ margin: 6px 0; font-size: 0.9rem; color: #444; }}
    .files code {{ font-size: 1rem; background: #eef; padding: 2px 6px; border-radius: 4px; }}
    .copy {{ margin-top: 10px; width: 100%; padding: 12px; font-size: 1rem;
             border: none; border-radius: 10px; background: #2563eb; color: #fff; }}
    .copy:active {{ background: #1d4ed8; }}
    .hidden {{ display: none; }}
    .toast {{ position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
              background: #111; color: #fff; padding: 10px 16px; border-radius: 8px;
              opacity: 0; transition: opacity .2s; pointer-events: none; }}
    .toast.show {{ opacity: 1; }}
  </style>
</head>
<body>
  <h1>Загрузка фото · {len(rows)} позиций</h1>
  <div class="steps">
    <p><b>С телефона:</b></p>
    <ol>
      <li>Откройте приложение <b>Яндекс Диск</b></li>
      <li>Папка <a href="{DISK_URL}">Авито</a></li>
      <li>{layout_hint}</li>
      <li>Имя файла = как ниже (можно нажать «Скопировать»)</li>
    </ol>
    <p>Одно фото: <code>АРТИКУЛ.{cfg.image_ext}</code> · ещё: <code>АРТИКУЛ-2.{cfg.image_ext}</code> …</p>
  </div>
  <input type="search" id="q" placeholder="Поиск по артикулу или названию…" autocomplete="off">
  <div id="list">{"".join(cards)}</div>
  <div class="toast" id="toast">Скопировано</div>
  <script>
    const q = document.getElementById('q');
    const cards = document.querySelectorAll('.card');
    q.addEventListener('input', () => {{
      const s = q.value.trim().toLowerCase();
      cards.forEach(c => {{
        c.classList.toggle('hidden', s && !c.dataset.search.toLowerCase().includes(s));
      }});
    }});
    document.querySelectorAll('.copy').forEach(btn => {{
      btn.addEventListener('click', () => {{
        navigator.clipboard.writeText(btn.dataset.copy).then(() => {{
          const t = document.getElementById('toast');
          t.classList.add('show');
          setTimeout(() => t.classList.remove('show'), 1500);
        }});
      }});
    }});
  </script>
</body>
</html>"""


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = load_config(args.config)
    stamp = args.date or date.today().isoformat()

    stock_path = args.stock or (ROOT / app.compare.stock_file)
    if not stock_path.is_absolute():
        stock_path = ROOT / stock_path

    try:
        stock = load_stock(stock_path, app.compare)
    except FileNotFoundError as exc:
        LOG.error("%s", exc)
        return 1

    rows: list[dict] = []
    for item in stock:
        if not item.article:
            continue
        files = article_photo_filenames(item.article)
        rows.append(
            {
                "article": item.article,
                "nomenclature": item.nomenclature,
                "copy_text": files[0],
            }
        )

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"photo_upload_{stamp}.html"
    txt_path = out_dir / f"photo_names_{stamp}.txt"

    html_path.write_text(
        build_html(
            rows,
            inbox_subdir=app.autoload.manager_inbox_subdir,
            store_prefixes=list(app.stores.prefixes),
            stamp=stamp,
        ),
        encoding="utf-8",
    )

    lines = [
        "# Загрузите в папку Авито/входящие на Яндекс.Диске",
        f"# {DISK_URL}",
        "# Имя файла: АРТИКУЛ.jpg или АРТИКУЛ-2.jpg",
        "",
    ]
    for r in rows:
        names = article_photo_filenames(r["article"])
        lines.append(f"{r['article']}\t{names[0]}\t{r['nomenclature'][:60]}")
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    LOG.info("Позиций: %s", len(rows))
    LOG.info("Откройте на телефоне: %s", html_path)
    LOG.info("Список имён: %s", txt_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
