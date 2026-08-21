#!/usr/bin/env python3
"""Smoke: diff-only helpers + sync_state schema (без live Avito API)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from avito.build_listings import (  # noqa: E402
    filter_photo_update_rows,
    listing_content_fingerprint,
)
from avito.stock_db import (  # noqa: E402
    ListingDbRow,
    load_sync_state_map,
    mark_sync_photos,
    mark_sync_prices,
    mark_sync_qtys,
    seed_sync_state_price_qty,
    stock_connection,
    sync_state_count,
)
from avito.sync_listings import (  # noqa: E402
    SyncItem,
    filter_oos_payload,
    filter_price_items,
    filter_stock_items,
)


def _item(aid: int, price: int, qty: int) -> SyncItem:
    return SyncItem(
        listing_id=f"md_{aid}",
        article=str(aid),
        avito_id=aid,
        price=price,
        quantity=qty,
    )


def main() -> int:
    items = [_item(1, 1000, 4), _item(2, 2000, 2), _item(3, 3000, 1)]
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        with stock_connection(db) as conn:
            assert sync_state_count(conn) == 0
            seeded = seed_sync_state_price_qty(
                conn,
                [
                    ("1", "md_1", "1", 1000, 4),
                    ("2", "md_2", "2", 2000, 2),
                    ("3", "md_3", "3", 3000, 1),
                ],
            )
            assert seeded == 3, seeded
            state = load_sync_state_map(conn)

            # price unchanged → skip all
            send, skipped = filter_price_items(items, state)
            assert send == [] and skipped == 3, (send, skipped)

            # change one price
            items2 = [_item(1, 1100, 4), _item(2, 2000, 2), _item(3, 3000, 1)]
            send, skipped = filter_price_items(items2, state)
            assert len(send) == 1 and send[0].avito_id == 1 and skipped == 2

            # stock: change qty on #2
            items3 = [_item(1, 1000, 4), _item(2, 2000, 8), _item(3, 3000, 1)]
            send_s, skip_s = filter_stock_items(items3, state)
            assert len(send_s) == 1 and send_s[0].avito_id == 2 and skip_s == 2

            oos = [
                {"item_id": 9, "quantity": 0, "external_id": "md_9"},
                {"item_id": 1, "quantity": 0, "external_id": "md_1"},
            ]
            # #1 has last_qty=4 → send; after we mark 9 as 0, skip
            send_o, skip_o = filter_oos_payload(oos, state)
            assert len(send_o) == 2 and skip_o == 0
            mark_sync_qtys(conn, [("9", "md_9", "", 0)])
            state = load_sync_state_map(conn)
            send_o, skip_o = filter_oos_payload(oos, state)
            assert any(r["item_id"] == 1 for r in send_o)
            assert skip_o == 1

            mark_sync_prices(conn, [("1", "md_1", "1", 1100)])
            state = load_sync_state_map(conn)
            send, skipped = filter_price_items(items2, state)
            assert send == [] and skipped == 3

            # photo fingerprint
            row_a = ListingDbRow(
                listing_id="md_1",
                article_id="1",
                avito_id="1",
                title="A",
                photo_urls="https://x/a.jpg",
                description_html="<p>1</p>",
            )
            row_b = ListingDbRow(
                listing_id="md_1",
                article_id="1",
                avito_id="1",
                title="A",
                photo_urls="https://x/b.jpg",
                description_html="<p>1</p>",
            )
            assert listing_content_fingerprint(row_a) != listing_content_fingerprint(row_b)

            # seed photos when no hashes
            send_p, skip_p, marks, seeded_p = filter_photo_update_rows(
                [row_a], state, {}, force_full=False, seed_on_empty=True
            )
            assert seeded_p and send_p == [] and marks
            mark_sync_photos(conn, marks)
            state = load_sync_state_map(conn)
            send_p, skip_p, marks, seeded_p = filter_photo_update_rows(
                [row_a], state, {}, force_full=False, seed_on_empty=True
            )
            assert not seeded_p and send_p == [] and skip_p == 1
            send_p, skip_p, _, _ = filter_photo_update_rows(
                [row_b], state, {}, force_full=False, seed_on_empty=True
            )
            assert len(send_p) == 1 and skip_p == 0

    # config knobs
    from avito.config import _load_avito_sync

    sync = _load_avito_sync({})
    assert sync.diff_only is True
    assert sync.seed_on_empty is True
    assert sync.photo_updates_diff_only is True
    assert sync.full_ids_min_interval_hours == 24
    print("smoke_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
