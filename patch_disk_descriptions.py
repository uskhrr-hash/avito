#!/usr/bin/env python3
"""Patch disk listing descriptions in Avito stock DB (headline + fitment).

Does NOT republish XML. Nightly build_autoload will regenerate the same way.
Optionally mark listings dirty for next photo_updates diff by touching description.
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from avito.autoload import _availability_headline  # noqa: E402
from avito.wheel_fitment_cache import load_fitment_cache  # noqa: E402

LOG = logging.getLogger("patch_disk_descriptions")

_HEAD_RE = re.compile(
    r"(<p><strong>)(?:Шины|Диски)( в наличии!| под заказ 1-2 дня)(</strong></p>)",
    re.I,
)
_FITMENT_RE = re.compile(
    r"<p><strong>Подходит на:.*?</strong></p>",
    re.I | re.S,
)


def _ushk_from_desc_or_stock(desc: str, article: str, stock_ushk: dict[str, bool]) -> bool:
    if article in stock_ushk:
        return stock_ushk[article]
    # heuristic from current headline
    return "в наличии" in desc[:120].lower()


def patch_description(
    desc: str,
    *,
    ushk: bool,
    fitment_html: str,
) -> str:
    headline = _availability_headline(ushk, product_kind="wheel")
    out = desc or ""
    if _HEAD_RE.search(out):
        out = _HEAD_RE.sub(rf"\g<1>{headline}\g<3>", out, count=1)
    else:
        # prepend if somehow missing
        out = f"<p><strong>{headline}</strong></p>" + out

    out = _FITMENT_RE.sub("", out)
    if fitment_html:
        # insert after payment terms block if present, else after second <p>
        m = re.search(
            r"(<p><strong>(?:Любая форма оплаты, НДС|Цена за наличный расчет)</strong></p>)",
            out,
            re.I,
        )
        if m:
            pos = m.end()
            out = out[:pos] + fitment_html + out[pos:]
        else:
            # after availability + title
            parts = out.split("</p>", 2)
            if len(parts) >= 3:
                out = "</p>".join(parts[:2]) + "</p>" + fitment_html + parts[2]
            else:
                out = fitment_html + out
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock-db", type=Path, default=Path("data/avito_stock.db"))
    ap.add_argument(
        "--fitment-cache",
        type=Path,
        default=Path("data/wheel_fitment_cache.db"),
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    cache = load_fitment_cache(args.fitment_cache)
    con = sqlite3.connect(str(args.stock_db))
    con.row_factory = sqlite3.Row

    stock_ushk: dict[str, bool] = {}
    try:
        for r in con.execute(
            "SELECT article, ushk_in_stock FROM stock_items WHERE kind='wheel'"
        ):
            val = r["ushk_in_stock"]
            stock_ushk[str(r["article"])] = bool(val) or str(val).lower() in (
                "1",
                "true",
                "да",
                "yes",
            )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("ushk map: %s", exc)

    q = "SELECT listing_id, article_id, description_html FROM listings WHERE product_type='Диски'"
    if args.limit > 0:
        q += f" LIMIT {int(args.limit)}"
    rows = con.execute(q).fetchall()
    updated = 0
    samples: list[tuple[str, str, str]] = []
    for r in rows:
        article = str(r["article_id"] or "").strip()
        old = str(r["description_html"] or "")
        ushk = _ushk_from_desc_or_stock(old, article, stock_ushk)
        fit_html = cache.html_for_article(article) if cache else ""
        new = patch_description(old, ushk=ushk, fitment_html=fit_html)
        if new == old:
            continue
        updated += 1
        if len(samples) < 3:
            samples.append((article, old[:280], new[:400]))
        if not args.dry_run:
            con.execute(
                "UPDATE listings SET description_html=?, updated_at=datetime('now') "
                "WHERE listing_id=?",
                (new, r["listing_id"]),
            )
    if not args.dry_run:
        con.commit()
    con.close()
    LOG.info("disk listings scanned=%s updated=%s dry_run=%s", len(rows), updated, args.dry_run)
    for art, before, after in samples:
        LOG.info("--- sample %s BEFORE ---\n%s", art, before)
        LOG.info("--- sample %s AFTER ---\n%s", art, after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
