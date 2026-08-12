"""SQLite-индекс URL фото shinaufa.ru (hotlink).

Ключ тот же, что в shinaufa_photos._cache_key.
build_autoload читает индекс; warm_shinaufa_photos.py наполняет HEAD-ами.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS shinaufa_photo_index (
    cache_key   TEXT PRIMARY KEY,
    kind        TEXT NOT NULL DEFAULT 'tyres',
    brand       TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    ok          INTEGER NOT NULL DEFAULT 0,
    checked_at  TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'head'
);

CREATE INDEX IF NOT EXISTS idx_shinaufa_photo_ok
    ON shinaufa_photo_index (kind, ok);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def index_connection(path: Path) -> Iterator[sqlite3.Connection]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA_SQL)
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_entry(conn: sqlite3.Connection, cache_key: str) -> dict | None:
    row = conn.execute(
        "SELECT cache_key, kind, brand, model, color, url, ok, checked_at, source "
        "FROM shinaufa_photo_index WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def upsert_entry(
    conn: sqlite3.Connection,
    *,
    cache_key: str,
    kind: str,
    brand: str,
    model: str,
    color: str,
    url: str,
    ok: bool,
    source: str = "head",
    checked_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO shinaufa_photo_index
            (cache_key, kind, brand, model, color, url, ok, checked_at, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            kind=excluded.kind,
            brand=excluded.brand,
            model=excluded.model,
            color=excluded.color,
            url=excluded.url,
            ok=excluded.ok,
            checked_at=excluded.checked_at,
            source=excluded.source
        """,
        (
            cache_key,
            kind,
            brand,
            model,
            color or "",
            url or "",
            1 if ok else 0,
            checked_at or _utcnow(),
            source,
        ),
    )


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT kind, ok, COUNT(*) AS n FROM shinaufa_photo_index GROUP BY kind, ok"
    ).fetchall()
    out = {
        "total": 0,
        "ok": 0,
        "miss": 0,
        "tyres_ok": 0,
        "tyres_miss": 0,
        "wheels_ok": 0,
        "wheels_miss": 0,
    }
    for r in rows:
        n = int(r["n"])
        out["total"] += n
        kind = str(r["kind"] or "")
        if int(r["ok"]):
            out["ok"] += n
            if kind == "wheels":
                out["wheels_ok"] += n
            else:
                out["tyres_ok"] += n
        else:
            out["miss"] += n
            if kind == "wheels":
                out["wheels_miss"] += n
            else:
                out["tyres_miss"] += n
    return out


def import_json_cache(conn: sqlite3.Connection, json_path: Path) -> int:
    """Перенос старого JSON-кэша в sqlite (один раз)."""
    import json

    if not json_path.is_file():
        return 0
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    n = 0
    for key, hit in data.items():
        if key == "__head__" or not isinstance(hit, dict) or "ok" not in hit:
            continue
        parts = str(key).split("|")
        # keys: brand|model|tyres  OR  brand|model|color|wheels_v3
        tail = parts[-1] if parts else ""
        kind = "wheels" if "wheels" in tail else "tyres"
        brand = parts[0] if parts else ""
        model = parts[1] if len(parts) > 1 else ""
        color = parts[2] if kind == "wheels" and len(parts) > 3 else ""
        if kind == "wheels" and len(parts) == 3:
            # legacy brand|model|wheels
            color = ""
            model = parts[1] if len(parts) > 1 else ""
        upsert_entry(
            conn,
            cache_key=str(key),
            kind=kind,
            brand=brand,
            model=model,
            color=color,
            url=str(hit.get("url") or ""),
            ok=bool(hit.get("ok")),
            source="json_cache",
        )
        n += 1
    return n
