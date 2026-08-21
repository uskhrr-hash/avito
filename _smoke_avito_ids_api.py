#!/usr/bin/env python3
"""Smoke: AvitoId harvest via JSON API → sqlite (без xlsx)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("smoke_avito_ids_api")


def main() -> int:
    from avito.autoload import load_avito_ids
    from avito.avito_api import AvitoApiClient, fetch_avito_ids_by_ad_ids, load_avito_api_config
    from avito.config import load_config
    from avito.db import load_secrets
    from avito.stock_db import (
        load_avito_ids_map,
        load_listings,
        load_posting_dataframe,
        replace_avito_ids,
        stock_connection,
    )
    from avito.sync_listings import collect_ad_ids_for_api, refresh_avito_ids_from_api

    app = load_config(ROOT / "config.yaml")
    assert app.autoload.prefer_latest_avito_export is False, "prefer_latest must be false"

    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = ROOT / secrets_path

    with stock_connection(app.stock_db.path, schema_path=app.stock_db.schema_sql) as conn:
        before_map = load_avito_ids_map(conn)
        before_listings = sum(1 for r in load_listings(conn) if r.avito_id)
        posting_df = load_posting_dataframe(conn)
        listing_ids = [r.listing_id for r in load_listings(conn) if r.listing_id]

    LOG.info(
        "BEFORE avito_ids=%s listings_with_id=%s posting_rows=%s",
        len(before_map),
        before_listings,
        len(posting_df),
    )

    client = AvitoApiClient(load_avito_api_config(load_secrets(secrets_path)))
    # быстрый smoke: 3 listing_id
    sample = [x for x in listing_ids if "_" in x][:3]
    probe = fetch_avito_ids_by_ad_ids(client, sample)
    LOG.info("API probe sample=%s found=%s %s", sample, len(probe), probe)

    ad_ids = collect_ad_ids_for_api(
        posting_df,
        app.stores,
        extra_keys=list(before_map.keys()),
        listing_ids=listing_ids,
    )
    LOG.info("candidate ad_ids=%s", len(ad_ids))
    csv_path = ROOT / app.autoload.avito_ids_file
    existing = dict(before_map)
    if csv_path.is_file():
        existing = {**load_avito_ids(csv_path, app.stores), **existing}

    merged = refresh_avito_ids_from_api(
        client,
        ad_ids,
        existing=existing,
        stores=app.stores,
        include_report=True,
    )
    with stock_connection(app.stock_db.path, schema_path=app.stock_db.schema_sql) as conn:
        n = replace_avito_ids(conn, merged)
        after_map = load_avito_ids_map(conn)

    LOG.info("AFTER replace_avito_ids=%s map_keys=%s", n, len(after_map))
    underscore = sum(1 for k in after_map if "_" in k)
    bare = sum(1 for k in after_map if "_" not in k)
    LOG.info("key_types underscore=%s bare=%s", underscore, bare)
    LOG.info(
        "code_path: prefer_latest_avito_export=%s (xlsx export skipped on daily)",
        app.autoload.prefer_latest_avito_export,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
