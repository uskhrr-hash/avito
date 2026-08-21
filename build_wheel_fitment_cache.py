#!/usr/bin/env python3
"""Собрать кэш размер→авто и артикул→авто для описаний дисков Avito.

Источник истины: Postgres shinaufa.public.cars (кэш Wheel-Size), те же
допуски ET±2 / DIA±0.1, что на сайте.

Примеры:
  # На VPS Avito (если есть SHINAUFA_PG_DSN) + локальный stock db:
  python3 build_wheel_fitment_cache.py \\
      --stock-db data/avito_stock.db \\
      --out data/wheel_fitment_cache.db

  # Из JSONL дампа cars (id\\tjson на строку), без прямого PG:
  python3 build_wheel_fitment_cache.py \\
      --cars-jsonl /tmp/cars_wheels.jsonl \\
      --names-json /tmp/cars_names_ru.json \\
      --stock-db data/avito_stock.db \\
      --out data/wheel_fitment_cache.db
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, unquote, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from avito.wheel_fitment_cache import (  # noqa: E402
    CarHit,
    WheelFitmentCache,
    aggregate_cars,
    format_cars_html,
    format_cars_text,
    parse_bolt_pattern,
    size_key,
    size_key_from_stock,
    _num,
)

LOG = logging.getLogger("build_wheel_fitment_cache")


def _connect_pg(dsn: str):
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"psycopg2 required: {exc}") from exc
    conn = psycopg2.connect(dsn)
    return conn, psycopg2.extras.RealDictCursor


def dsn_from_env() -> str:
    raw = (os.environ.get("SHINAUFA_PG_DSN") or "").strip()
    if raw:
        return raw
    host = (os.environ.get("SHINAUFA_PG_HOST") or "").strip()
    user = (os.environ.get("SHINAUFA_PG_USER") or "").strip()
    password = os.environ.get("SHINAUFA_PG_PASSWORD")
    if not host or not user or password is None:
        return ""
    port = (os.environ.get("SHINAUFA_PG_PORT") or "5432").strip() or "5432"
    db = (
        os.environ.get("SHINAUFA_PG_DB")
        or os.environ.get("SHINAUFA_PG_DATABASE")
        or "shinaufa"
    ).strip()
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(db)}"
    )


def load_names_ru(path: Path | None) -> dict[str, dict[str, str]]:
    """cars_names_ru.php exported as JSON: {makes:{}, models:{}, pairs:{}}."""
    if path is None or not path.is_file():
        return {"makes": {}, "models": {}, "pairs": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "makes": {str(k).lower(): str(v) for k, v in (data.get("makes") or {}).items()},
        "models": {
            str(k).lower(): str(v) for k, v in (data.get("models") or {}).items()
        },
        "pairs": {str(k).lower(): str(v) for k, v in (data.get("pairs") or {}).items()},
    }


def resolve_ru_names(
    make: str,
    model: str,
    names: dict[str, dict[str, str]],
) -> tuple[str, str]:
    make_l = make.lower()
    model_l = model.lower()
    pair = names.get("pairs", {}).get(f"{make_l}/{model_l}", "")
    make_ru = names.get("makes", {}).get(make_l, "")
    model_ru = pair or names.get("models", {}).get(model_l, "")
    return make_ru, model_ru


def _engine_from_value(raw: Any) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, (bytes, memoryview)):
        raw = bytes(raw).decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    data = raw.get("data", raw)
    if isinstance(data, list):
        if not data or not isinstance(data[0], dict):
            return None
        data = data[0]
    if not isinstance(data, dict) or not data.get("wheels"):
        return None
    return data


def iter_fitment_from_engine(
    car_id: str,
    engine: dict,
    names: dict[str, dict[str, str]],
) -> Iterable[tuple[str, float, int, float, float, float, CarHit]]:
    parts = str(car_id).split("|")
    if len(parts) != 4:
        return
    make, model, year_s, _mod = parts
    try:
        year = int(year_s)
    except ValueError:
        year = 0
    make_ru, model_ru = resolve_ru_names(make, model, names)
    hit = CarHit(
        make=make,
        model=model,
        year=year,
        make_ru=make_ru,
        model_ru=model_ru,
        hits=1,
    )
    tech = engine.get("technical") if isinstance(engine.get("technical"), dict) else {}
    bolts = tech.get("stud_holes")
    pcd = tech.get("pcd")
    dia = tech.get("centre_bore")
    if bolts is None or pcd is None:
        b2, p2 = parse_bolt_pattern(tech.get("bolt_pattern"))
        bolts = bolts if bolts is not None else b2
        pcd = pcd if pcd is not None else p2
    bolts_n = _num(bolts)
    pcd_n = _num(pcd)
    dia_n = _num(dia)
    if bolts_n is None or pcd_n is None or dia_n is None:
        return
    seen: set[str] = set()
    for wheel in engine.get("wheels") or []:
        if not isinstance(wheel, dict):
            continue
        for axle in ("front", "rear"):
            pos = wheel.get(axle)
            if not isinstance(pos, dict):
                continue
            diameter = _num(pos.get("rim_diameter"))
            et = _num(pos.get("rim_offset"))
            if diameter is None or et is None:
                continue
            sk = size_key(
                diameter=diameter,
                bolts=int(bolts_n),
                pcd=float(pcd_n),
                et=float(et),
                dia=float(dia_n),
            )
            if sk in seen:
                continue
            seen.add(sk)
            yield sk, float(diameter), int(bolts_n), float(pcd_n), float(et), float(dia_n), hit


def collect_size_map(
    rows: Iterable[tuple[str, Any]],
    names: dict[str, dict[str, str]],
) -> dict[str, dict[str, Any]]:
    """size_key -> {diameter,bolts,pcd,et,dia, hits: list[CarHit]} with year merge."""
    out: dict[str, dict[str, Any]] = {}
    hit_index: dict[str, dict[tuple[str, str, int], CarHit]] = defaultdict(dict)
    for car_id, value in rows:
        engine = _engine_from_value(value)
        if not engine:
            continue
        for sk, d, b, p, e, h, hit in iter_fitment_from_engine(car_id, engine, names):
            bucket = out.get(sk)
            if bucket is None:
                bucket = {
                    "diameter": d,
                    "bolts": b,
                    "pcd": p,
                    "et": e,
                    "dia": h,
                }
                out[sk] = bucket
            key = (hit.make.lower(), hit.model.lower(), hit.year)
            existing = hit_index[sk].get(key)
            if existing is None:
                hit_index[sk][key] = CarHit(
                    make=hit.make,
                    model=hit.model,
                    year=hit.year,
                    make_ru=hit.make_ru,
                    model_ru=hit.model_ru,
                    hits=1,
                )
            else:
                existing.hits += 1
    for sk, idx in hit_index.items():
        out[sk]["hits"] = list(idx.values())
    return out


def fetch_cars_from_pg(dsn: str) -> list[tuple[str, Any]]:
    conn, cur_factory = _connect_pg(dsn)
    try:
        with conn.cursor(cursor_factory=cur_factory) as cur:
            cur.execute(
                "SELECT id, value FROM cars WHERE id LIKE %s",
                ("%|%|%|%",),
            )
            rows = [(str(r["id"]), r["value"]) for r in cur.fetchall()]
    finally:
        conn.close()
    return rows


def fetch_cars_from_jsonl(path: Path) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if "\t" in line:
                cid, payload = line.split("\t", 1)
                rows.append((cid, payload))
                continue
            obj = json.loads(line)
            rows.append((str(obj["id"]), obj.get("value")))
    return rows


def map_articles(
    stock_db: Path,
    cache: WheelFitmentCache,
) -> list[dict[str, Any]]:
    con = sqlite3.connect(str(stock_db))
    con.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(stock_items)")}
        need = {"article", "diameter", "studs", "circle", "et", "hub"}
        if not need.issubset(cols):
            # try alternate names
            pass
        q = (
            "SELECT article, diameter, width, studs, circle, et, hub "
            "FROM stock_items WHERE lower(coalesce(kind,'')) IN ('wheel','wheels','диск','диски')"
        )
        rows = con.execute(q).fetchall()
    finally:
        con.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        article = str(r["article"] or "").strip()
        if not article:
            continue
        sk = size_key_from_stock(
            diameter=r["diameter"],
            studs=r["studs"],
            circle=r["circle"],
            et=r["et"],
            hub=r["hub"],
        )
        hits, matched = cache.lookup_size(
            diameter=r["diameter"],
            bolts=r["studs"],
            pcd=r["circle"],
            et=r["et"],
            dia=r["hub"],
        )
        groups = aggregate_cars(hits)
        out.append(
            {
                "article": article,
                "size_key": sk or "",
                "diameter": _num(r["diameter"]),
                "bolts": int(_num(r["studs"]) or 0) or None,
                "pcd": _num(r["circle"]),
                "et": _num(r["et"]),
                "dia": _num(r["hub"]),
                "cars_html": format_cars_html(groups),
                "cars_text": format_cars_text(groups),
                "car_count": len(groups),
                "matched_size_key": matched,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", default="", help="Postgres DSN (else SHINAUFA_PG_*)")
    ap.add_argument("--cars-jsonl", type=Path, default=None)
    ap.add_argument("--names-json", type=Path, default=None)
    ap.add_argument("--stock-db", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/wheel_fitment_cache.db"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    names = load_names_ru(args.names_json)
    if args.cars_jsonl:
        LOG.info("Loading cars from JSONL %s", args.cars_jsonl)
        car_rows = fetch_cars_from_jsonl(args.cars_jsonl)
    else:
        dsn = (args.dsn or dsn_from_env()).strip()
        if not dsn:
            LOG.error("Need --dsn / SHINAUFA_PG_DSN or --cars-jsonl")
            return 2
        # mask in logs
        parsed = urlparse(dsn)
        LOG.info(
            "Loading cars from Postgres %s/%s",
            parsed.hostname,
            (parsed.path or "/").lstrip("/"),
        )
        car_rows = fetch_cars_from_pg(dsn)
    LOG.info("cars rows: %s", len(car_rows))

    size_map = collect_size_map(car_rows, names)
    LOG.info("distinct wheel sizes: %s", len(size_map))

    if args.out.exists():
        args.out.unlink()
    cache = WheelFitmentCache(args.out)
    n_sizes = cache.replace_size_cars(
        (
            sk,
            meta["diameter"],
            meta["bolts"],
            meta["pcd"],
            meta["et"],
            meta["dia"],
            meta["hits"],
        )
        for sk, meta in size_map.items()
    )
    LOG.info("wrote size rows: %s", n_sizes)

    articles = map_articles(args.stock_db, cache)
    with_cars = sum(1 for a in articles if a["car_count"] > 0)
    n_arts = cache.replace_article_cars(articles)
    cache.set_meta("built_at", datetime.now(timezone.utc).isoformat())
    cache.set_meta("cars_rows", str(len(car_rows)))
    cache.set_meta("size_rows", str(n_sizes))
    cache.set_meta("article_rows", str(n_arts))
    cache.set_meta("articles_with_cars", str(with_cars))
    cache.close()

    LOG.info(
        "articles=%s with_cars=%s out=%s",
        n_arts,
        with_cars,
        args.out,
    )
    # sample
    samples = [a for a in articles if a["car_count"] > 0][:3]
    for s in samples:
        LOG.info("sample %s: %s", s["article"], s["cars_text"][:180])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
