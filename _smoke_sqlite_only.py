#!/usr/bin/env python3
"""Prod smoke: photo stock path must not touch Excel."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from avito.compare import load_stock, load_stock_from_db
from avito.config import load_config
from avito.photo_upload import service as svc
from avito.photo_upload.settings import load_photo_upload_runtime


def main() -> int:
    cfg = load_config(Path("config.yaml"))
    rows = load_stock_from_db(cfg.stock_db.path, schema_path=cfg.stock_db.schema_sql)
    print("db_rows", len(rows))
    if rows:
        print("sample", rows[0].article, getattr(rows[0], "kind", None), rows[0].source)

    rows2 = load_stock(
        Path("input/goods.xlsx"),
        cfg.compare,
        stock_db_path=cfg.stock_db.path,
        stock_db_schema=cfg.stock_db.schema_sql,
    )
    assert len(rows2) == len(rows)
    print("load_stock_db_ok", len(rows2))

    rt = load_photo_upload_runtime(config_path=Path("config.yaml"))
    svc._STOCK_CACHE.clear()
    called = {"excel": 0}
    orig = pd.read_excel

    def guard(*a, **k):
        called["excel"] += 1
        raise AssertionError(f"read_excel called: args={a[:1]} kwargs={list(k)}")

    pd.read_excel = guard
    try:
        items = svc._stock_items(rt)
        q = items[0].article[:4] if items else "1004"
        found = svc.search_stock(rt, q, limit=5)
        lookup = svc.lookup_stock(rt, items[0].article) if items else None
        print(
            "photo_items",
            len(items),
            "search",
            len(found),
            "lookup",
            None if lookup is None else lookup.article,
            "read_excel_calls",
            called["excel"],
        )
        assert called["excel"] == 0, called
        assert len(items) > 1000
    finally:
        pd.read_excel = orig

    # cold start after DB mtime change
    svc._STOCK_CACHE.clear()
    db = Path(rt.stock_db_path)
    before = db.stat().st_mtime
    db.touch()
    after = db.stat().st_mtime
    items2 = svc._stock_items(rt)
    print("cold_after_touch", len(items2), "mtime", before, "->", after)
    assert len(items2) == len(items)
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
