#!/usr/bin/env python3
"""Наполнить sqlite-индекс URL фото shinaufa (HEAD only, exact color для дисков).

Примеры:
  python warm_shinaufa_photos.py
  python warm_shinaufa_photos.py --kind wheels --force
  python warm_shinaufa_photos.py --only-missing
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
from avito.shinaufa_photo_index import (
    get_entry,
    import_json_cache,
    index_connection,
    stats,
    upsert_entry,
)
from avito.shinaufa_photos import (
    ShinaufaModelPhotoSettings,
    _cache_key,
    _is_wheels_base,
    _wheel_url_candidates,
    extract_wheel_color_from_title,
    head_url_ok,
    shinaufa_model_photo_url,
)
from avito.stock_db import load_posting_dataframe, stock_connection

LOG = logging.getLogger("warm_shinaufa_photos")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "--kind",
        choices=("all", "tire", "wheel"),
        default="all",
        help="Что прогревать",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Перепроверить уже известные ключи",
    )
    p.add_argument(
        "--only-missing",
        action="store_true",
        help="Только ключи, которых ещё нет в индексе",
    )
    p.add_argument("--limit", type=int, default=0, help="Макс. уникальных ключей")
    return p.parse_args()


def _settings_for(
    cfg,
    *,
    project_root: Path,
    kind: str,
) -> ShinaufaModelPhotoSettings:
    cache = getattr(cfg, "shinaufa_model_photo_cache", None)
    if cache is not None and not Path(cache).is_absolute():
        cache = project_root / cache
    if kind == "wheel":
        base = str(
            getattr(cfg, "shinaufa_model_photos_wheels_base", "")
            or "https://shinaufa.ru/images/large/wheels"
        )
    else:
        base = str(
            getattr(cfg, "shinaufa_model_photos_base", "")
            or "https://shinaufa.ru/images/large/tyres"
        )
    return ShinaufaModelPhotoSettings(
        enabled=True,
        base_url=base,
        cache_file=Path(cache) if cache else None,
        head_timeout_sec=float(
            getattr(cfg, "shinaufa_model_photo_timeout_sec", 5.0) or 5.0
        ),
        rate_limit_sec=float(
            getattr(cfg, "shinaufa_model_photo_rate_limit_sec", 0.05) or 0.05
        ),
        index_path=None,
        live_fetch=True,
    )


def _unique_jobs(df, kind_filter: str) -> list[dict]:
    seen: set[str] = set()
    jobs: list[dict] = []
    for _, row in df.iterrows():
        kind = str(row.get("kind") or "tire").strip().lower()
        if kind in ("wheel", "wheels", "диск", "диски", "disk", "disks"):
            kind = "wheel"
        else:
            kind = "tire"
        if kind_filter == "tire" and kind != "tire":
            continue
        if kind_filter == "wheel" and kind != "wheel":
            continue

        brand = str(row.get("brand") or "").strip()
        model = str(row.get("model") or "").strip()
        title = str(row.get("номенклатура") or "").strip()
        if (not brand or not model) and title:
            try:
                from avito.title_parse import parse_title_fields

                fields = parse_title_fields(title)
                brand = brand or str(fields.get("brand") or "").strip()
                model = model or str(fields.get("model") or "").strip()
            except Exception:  # noqa: BLE001
                pass
        if not brand or not model:
            continue

        color = ""
        if kind == "wheel":
            color = extract_wheel_color_from_title(title)
            if not color:
                continue

        base_kind = "wheels" if kind == "wheel" else "tyres"
        key = _cache_key(
            brand,
            model,
            base_url=f"https://shinaufa.ru/images/large/{base_kind}",
            color=color,
        )
        if key in seen:
            continue
        seen.add(key)
        jobs.append(
            {
                "key": key,
                "kind": kind,
                "brand": brand,
                "model": model,
                "color": color,
                "title": title,
            }
        )
    return jobs


def _resolve_url(job: dict, settings: ShinaufaModelPhotoSettings) -> tuple[bool, str]:
    brand = job["brand"]
    model = job["model"]
    color = job["color"]
    rl = float(settings.rate_limit_sec or 0.05)
    if _is_wheels_base(settings.base_url):
        for cand in _wheel_url_candidates(
            brand, model, base_url=settings.base_url, color=color
        ):
            if head_url_ok(
                cand,
                timeout_sec=settings.head_timeout_sec,
                rate_limit_sec=rl,
            ):
                return True, cand
        return False, ""
    cand = shinaufa_model_photo_url(brand, model, base_url=settings.base_url)
    if cand and head_url_ok(
        cand,
        timeout_sec=settings.head_timeout_sec,
        rate_limit_sec=rl,
    ):
        return True, cand
    return False, ""


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    app_cfg = load_config(Path(args.config))
    cfg = app_cfg.autoload

    index_path = getattr(cfg, "shinaufa_model_photo_index", None)
    if index_path is None:
        index_path = ROOT / "data" / "shinaufa_photo_index.sqlite"
    else:
        index_path = Path(index_path)
        if not index_path.is_absolute():
            index_path = ROOT / index_path

    with stock_connection(
        app_cfg.stock_db.path, schema_path=app_cfg.stock_db.schema_sql
    ) as stock_conn:
        df = load_posting_dataframe(stock_conn)

    kind_filter = args.kind
    jobs = _unique_jobs(df, kind_filter)
    if args.limit and args.limit > 0:
        jobs = jobs[: args.limit]

    LOG.info(
        "Jobs: %s (kind=%s, posting_rows=%s, index=%s)",
        len(jobs),
        kind_filter,
        len(df),
        index_path,
    )

    tire_settings = _settings_for(cfg, project_root=ROOT, kind="tire")
    wheel_settings = _settings_for(cfg, project_root=ROOT, kind="wheel")

    checked = 0
    skipped = 0
    ok_n = 0
    miss_n = 0

    with index_connection(index_path) as conn:
        json_cache = getattr(cfg, "shinaufa_model_photo_cache", None)
        if json_cache is not None:
            jp = Path(json_cache)
            if not jp.is_absolute():
                jp = ROOT / jp
            n_imp = import_json_cache(conn, jp)
            if n_imp:
                LOG.info("Imported %s entries from JSON cache %s", n_imp, jp)
            # Fix kinds for wheels_v3 keys mis-tagged as tyres on first import
            fixed = conn.execute(
                "UPDATE shinaufa_photo_index SET kind = 'wheels' "
                "WHERE cache_key LIKE '%wheels%' AND kind != 'wheels'"
            ).rowcount
            if fixed:
                LOG.info("Fixed kind=wheels for %s rows", fixed)

        for job in jobs:
            existing = get_entry(conn, job["key"])
            if existing is not None:
                if args.only_missing:
                    skipped += 1
                    continue
                if not args.force:
                    skipped += 1
                    continue

            settings = wheel_settings if job["kind"] == "wheel" else tire_settings
            ok, url = _resolve_url(job, settings)
            upsert_entry(
                conn,
                cache_key=job["key"],
                kind="wheels" if job["kind"] == "wheel" else "tyres",
                brand=job["brand"],
                model=job["model"],
                color=job["color"],
                url=url,
                ok=ok,
                source="head",
            )
            checked += 1
            if ok:
                ok_n += 1
                LOG.info("OK %s → %s", job["key"], url)
            else:
                miss_n += 1
                LOG.info(
                    "MISS brand=%r model=%r color=%r",
                    job["brand"],
                    job["model"],
                    job["color"],
                )
            if checked % 100 == 0:
                conn.commit()
                LOG.info("Progress: checked=%s ok=%s miss=%s", checked, ok_n, miss_n)

        conn.commit()
        st = stats(conn)

    LOG.info(
        "Done: checked=%s skipped=%s ok=%s miss=%s | index total=%s ok=%s miss=%s "
        "(tyres_ok=%s wheels_ok=%s)",
        checked,
        skipped,
        ok_n,
        miss_n,
        st["total"],
        st["ok"],
        st["miss"],
        st["tyres_ok"],
        st["wheels_ok"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
