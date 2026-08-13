#!/usr/bin/env python3
"""Repair listings renamed md→pg that still carry md-bound AvitoIds (error 1013)."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from avito.avito_api import AvitoApiClient, load_avito_api_config
from avito.db import load_secrets

MD_IN_MSG = re.compile(r"\b(md_\d+)\b", re.I)


def _fetch_1013_renames(client: AvitoApiClient, upload_id: int) -> dict[str, str]:
    """pg_id → md_id from report items."""
    out: dict[str, str] = {}
    data = client.request(
        "GET", f"/autoload/v2/reports/{upload_id}/items?per_page=200&page=0"
    )
    pages = int((data.get("meta") or {}).get("pages") or 1)
    items = list(data.get("items") or [])
    per = int((data.get("meta") or {}).get("per_page") or 200)
    for page in range(1, pages):
        chunk = client.request(
            "GET",
            f"/autoload/v2/reports/{upload_id}/items?per_page={per}&page={page}",
        )
        items.extend(chunk.get("items") or [])
    for it in items:
        if (it.get("section") or {}).get("slug") != "error_params":
            continue
        ad_id = str(it.get("ad_id") or "").strip()
        if not ad_id.startswith("pg_"):
            continue
        for msg in it.get("messages") or []:
            if int(msg.get("code") or 0) != 1013:
                continue
            m = MD_IN_MSG.search(str(msg.get("title") or ""))
            if m:
                out[ad_id] = m.group(1).lower()
                break
    return out


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--upload-id", type=int, default=580453245)
    p.add_argument("--db", type=Path, default=ROOT / "data" / "avito_stock.db")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    secrets = load_secrets(ROOT / "secrets.local.yaml")
    client = AvitoApiClient(load_avito_api_config(secrets))
    renames = _fetch_1013_renames(client, args.upload_id)
    print(f"1013 renames from report: {len(renames)}")
    for i, (a, b) in enumerate(list(renames.items())[:8]):
        print(f"  {a} → {b}")

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    planned = []
    for pg_id, md_id in renames.items():
        row = con.execute(
            "SELECT listing_id, article_id, avito_id, store_key FROM listings WHERE listing_id = ?",
            (pg_id,),
        ).fetchone()
        if not row:
            continue
        exists_md = con.execute(
            "SELECT listing_id FROM listings WHERE listing_id = ?", (md_id,)
        ).fetchone()
        planned.append((dict(row), md_id, bool(exists_md)))

    print(f"listings to rename: {len(planned)}")
    if not args.apply:
        print("dry-run (pass --apply)")
        return 0

    n = 0
    for row, md_id, exists_md in planned:
        pg_id = row["listing_id"]
        store = md_id.split("_", 1)[0]
        if exists_md:
            # md already present — drop conflicting pg row (keep md)
            con.execute("DELETE FROM listings WHERE listing_id = ?", (pg_id,))
        else:
            con.execute(
                "UPDATE listings SET listing_id = ?, store_key = ? WHERE listing_id = ?",
                (md_id, store, pg_id),
            )
        n += 1
    con.commit()
    print(f"applied: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
