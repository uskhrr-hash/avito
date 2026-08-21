#!/usr/bin/env python3
"""Import size→cars JSON (from site PHP) into wheel_fitment_cache.db + map articles."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from avito.wheel_fitment_cache import (  # noqa: E402
    CarHit,
    WheelFitmentCache,
    aggregate_cars,
    format_cars_html,
    format_cars_text,
    size_key,
    size_key_from_stock,
    _num,
)
from build_wheel_fitment_cache import map_articles  # noqa: E402

LOG = logging.getLogger("import_wheel_size_index")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes-json", type=Path, required=True)
    ap.add_argument("--stock-db", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/wheel_fitment_cache.db"))
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.v else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    payload = json.loads(args.sizes_json.read_text(encoding="utf-8"))
    sizes = payload.get("sizes") or {}
    LOG.info(
        "import sizes=%s cars_rows=%s engine_rows=%s",
        len(sizes),
        payload.get("cars_rows"),
        payload.get("engine_rows"),
    )

    rows = []
    for sk, meta in sizes.items():
        hits = [
            CarHit(
                make=str(c.get("make") or ""),
                model=str(c.get("model") or ""),
                year=int(c.get("year") or 0),
                make_ru=str(c.get("make_ru") or ""),
                model_ru=str(c.get("model_ru") or ""),
                hits=int(c.get("hits") or 1),
            )
            for c in (meta.get("cars") or [])
            if c.get("make") and c.get("model")
        ]
        # normalize key
        sk2 = size_key(
            diameter=meta["diameter"],
            bolts=meta["bolts"],
            pcd=meta["pcd"],
            et=meta["et"],
            dia=meta["dia"],
        )
        rows.append(
            (
                sk2,
                float(meta["diameter"]),
                int(meta["bolts"]),
                float(meta["pcd"]),
                float(meta["et"]),
                float(meta["dia"]),
                hits,
            )
        )

    if args.out.exists():
        args.out.unlink()
    cache = WheelFitmentCache(args.out)
    n = cache.replace_size_cars(rows)
    articles = map_articles(args.stock_db, cache)
    with_cars = sum(1 for a in articles if a["car_count"] > 0)
    cache.replace_article_cars(articles)
    cache.set_meta("built_at", datetime.now(timezone.utc).isoformat())
    cache.set_meta("source", str(args.sizes_json))
    cache.set_meta("cars_rows", str(payload.get("cars_rows") or ""))
    cache.set_meta("engine_rows", str(payload.get("engine_rows") or ""))
    cache.set_meta("size_rows", str(n))
    cache.set_meta("article_rows", str(len(articles)))
    cache.set_meta("articles_with_cars", str(with_cars))
    cache.close()
    LOG.info("wrote %s sizes=%s articles=%s with_cars=%s", args.out, n, len(articles), with_cars)
    for a in [x for x in articles if x["car_count"] > 0][:3]:
        LOG.info("sample %s: %s", a["article"], a["cars_text"][:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
