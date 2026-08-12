#!/usr/bin/env python3
"""Пересобрать no_photos_queue (шины + диски) без полного autoload.

Очередь фотографа = posting без ЛОКАЛЬНЫХ фото артикула.
shinaufa/model в listings не убирает из очереди (ими только постим, пока нет своих).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from avito.config import load_config
from avito.photos import discover_photos_for_stores, product_photos_folder
from avito.stock_db import replace_no_photos, set_meta, stock_connection, _utcnow_iso
from avito.stores import load_stores
from avito.wheel_parse import is_wheel_kind

LOG = logging.getLogger("rebuild_no_photos")


def _norm_kind(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return "wheel" if is_wheel_kind(raw) else "tire"


def _has_article_photos(
    photos_root: Path,
    article: str,
    prefixes: tuple[str, ...],
    *,
    product_kind: str,
    layout: str,
    prefix_in_filename: bool,
    contributors_prefix: str,
) -> bool:
    folder = product_photos_folder(photos_root, product_kind)
    if not folder.is_dir():
        return False
    sets = discover_photos_for_stores(
        folder,
        article,
        prefixes,
        layout=layout,
        prefix_in_filename=prefix_in_filename,
        contributors_prefix=contributors_prefix or None,
        max_count=1,
    )
    return bool(sets)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Rebuild no_photos_queue with kind")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    stores_path = ROOT / "stores.yaml"
    if getattr(cfg, "stores_file", None):
        sp = Path(cfg.stores_file)
        stores_path = sp if sp.is_absolute() else ROOT / sp
    stores = load_stores(stores_path)

    # kind/name берём из SQLite stock_items (goods.xlsx больше не источник).
    kind_by_art: dict[str, str] = {}
    name_by_art: dict[str, str] = {}

    photos_root = Path(
        getattr(cfg.autoload, "photos_local_dir", "") or "/opt/avito_tires_photos"
    )
    layout = str(getattr(cfg.autoload, "photo_layout", "store_subdir") or "store_subdir")
    prefix_in_filename = bool(
        getattr(cfg.autoload, "photo_store_prefix_in_filename", False)
    )
    contributors = str(
        getattr(cfg.autoload, "contributors_prefix", "contributors") or "contributors"
    )
    prefixes = tuple(stores.prefixes)
    stores_label = ", ".join(prefixes)

    db_path = (
        Path(cfg.stock_db.path)
        if hasattr(cfg, "stock_db")
        else ROOT / "data/avito_stock.db"
    )
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    schema = None
    if hasattr(cfg, "stock_db") and getattr(cfg.stock_db, "schema_sql", None):
        schema = Path(cfg.stock_db.schema_sql)
        if not schema.is_absolute():
            schema = ROOT / schema

    stamp = _utcnow_iso()
    with stock_connection(db_path, schema_path=schema) as conn:
        for r in conn.execute(
            "SELECT article, name, kind FROM stock_items WHERE IFNULL(article,'') != ''"
        ):
            art = str(r["article"] or "").strip()
            if not art:
                continue
            kind_by_art[art] = _norm_kind(r["kind"] if "kind" in r.keys() else "tire")
            name_by_art[art] = str(r["name"] or "").strip()

        posting_cols = {r[1] for r in conn.execute("PRAGMA table_info(posting_items)")}
        if "kind" in posting_cols:
            updated = 0
            for art, kind in kind_by_art.items():
                cur = conn.execute(
                    "UPDATE posting_items SET kind = ? WHERE article = ? AND IFNULL(kind,'') != ?",
                    (kind, art, kind),
                )
                updated += int(cur.rowcount or 0)
            conn.commit()
            LOG.info("posting_items.kind backfill rows≈%s", updated)

        posting_rows = list(
            conn.execute("SELECT article, nomenclature, kind FROM posting_items")
        )

        queue: list[dict] = []
        tire_n = 0
        wheel_n = 0
        for row in posting_rows:
            art = str(row["article"] or "").strip()
            if not art:
                continue
            # Только артикулы с известным kind из goods (не болты/прочее).
            if art not in kind_by_art:
                continue
            kind = kind_by_art[art]
            name = name_by_art.get(art) or str(row["nomenclature"] or "").strip() or art

            if _has_article_photos(
                photos_root,
                art,
                prefixes,
                product_kind=kind,
                layout=layout,
                prefix_in_filename=prefix_in_filename,
                contributors_prefix=contributors,
            ):
                continue

            # shinaufa/model в listings не отменяет съёмку своих фото.
            problem = "нет локальных фото артикула"

            queue.append(
                {
                    "артикул": art,
                    "номенклатура": name,
                    "магазины": stores_label,
                    "проблема": problem,
                    "kind": kind,
                }
            )
            if kind == "wheel":
                wheel_n += 1
            else:
                tire_n += 1

        n = replace_no_photos(conn, queue, built_at=stamp)
        set_meta(conn, "no_photos_rebuild", "posting+local_article_only")
        conn.commit()
        LOG.info(
            "no_photos_queue rebuilt: total=%s tire=%s wheel=%s",
            n,
            tire_n,
            wheel_n,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
