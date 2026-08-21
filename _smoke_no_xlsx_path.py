#!/usr/bin/env python3
"""Проверка: daily path не открывает 432801655_*.xlsx."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from avito.config import load_config
    import build_autoload as ba

    app = load_config(ROOT / "config.yaml")
    cfg = app.autoload
    assert cfg.prefer_latest_avito_export is False

    opened: list[str] = []

    real_extract = ba._extract_avito_export_maps

    def guard(path):
        opened.append(str(path))
        raise AssertionError(f"xlsx export opened: {path}")

    # Только _load_avito_ids без полной сборки
    from avito.stock_db import load_posting_dataframe, stock_connection

    with stock_connection(app.stock_db.path, schema_path=app.stock_db.schema_sql) as conn:
        posting_df = load_posting_dataframe(conn).head(5)

    with mock.patch.object(ba, "_extract_avito_export_maps", side_effect=guard):
        with mock.patch.object(
            ba, "_refresh_avito_ids_api", side_effect=lambda *a, **k: dict(existing_stub)
        ):
            # не трогаем sqlite replace
            with mock.patch("avito.stock_db.replace_avito_ids", return_value=0):
                existing_stub = {"md_probe": "999"}
                ids, _path = ba._load_avito_ids(
                    app,
                    cfg,
                    app.stores,
                    posting_df,
                    template_path=None,
                    refresh_from_api=True,
                )
    print("prefer_latest", cfg.prefer_latest_avito_export)
    print("xlsx_opened", opened)
    print("ids_sample_keys", list(ids)[:5], "n=", len(ids))
    print("OK: daily path does not read 432801655_*.xlsx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
