"""Кэш совместимости дисков: размер → авто (из shinaufa ``cars`` / Wheel-Size).

Источник истины — Postgres shinaufa.cars (JSON Wheel-Size API), те же поля,
что сайт/чат используют для подбора:
  diameter, studs (bolts), pcd (circle), et (±2), dia/hub (±0.1).

Ширина обода в матч не входит (как в Cars::_fetchWheelSectionProducts).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

LOG = logging.getLogger(__name__)

# Как на сайте (cars.php): ET ±2 мм, DIA ±0.1 мм
ET_TOLERANCE = 2.0
DIA_TOLERANCE = 0.1001

DEFAULT_CACHE_PATH = Path("data/wheel_fitment_cache.db")
MAX_CARS_IN_AD = 18

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wheel_size_cars (
  size_key TEXT PRIMARY KEY,
  diameter REAL NOT NULL,
  bolts INTEGER NOT NULL,
  pcd REAL NOT NULL,
  et REAL NOT NULL,
  dia REAL NOT NULL,
  cars_json TEXT NOT NULL,
  car_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS wheel_size_cars_pcd_idx
  ON wheel_size_cars (diameter, bolts, pcd);

CREATE TABLE IF NOT EXISTS wheel_article_cars (
  article TEXT PRIMARY KEY,
  size_key TEXT NOT NULL,
  diameter REAL,
  bolts INTEGER,
  pcd REAL,
  et REAL,
  dia REAL,
  cars_html TEXT NOT NULL DEFAULT '',
  cars_text TEXT NOT NULL DEFAULT '',
  car_count INTEGER NOT NULL DEFAULT 0,
  matched_size_key TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS wheel_article_cars_size_idx
  ON wheel_article_cars (size_key);
"""


def _num(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", ".").replace(" ", "")
    if not s or s.lower() in ("nan", "none", "n/a", "…", "..."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt_num(value: float | int | None) -> str:
    if value is None:
        return ""
    f = float(value)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:g}"


def parse_bolt_pattern(raw: Any) -> tuple[int | None, float | None]:
    s = str(raw or "").strip().lower().replace(" ", "")
    if not s:
        return None, None
    m = re.match(r"^(\d+)\s*[xх×]\s*([\d.,]+)", s, re.I)
    if not m:
        return None, None
    return int(m.group(1)), float(m.group(2).replace(",", "."))


def size_key(
    *,
    diameter: float | int,
    bolts: int,
    pcd: float,
    et: float,
    dia: float,
) -> str:
    return "|".join(
        [
            _fmt_num(float(diameter)),
            str(int(bolts)),
            _fmt_num(float(pcd)),
            _fmt_num(float(et)),
            _fmt_num(float(dia)),
        ]
    )


def size_key_from_stock(
    *,
    diameter: Any,
    studs: Any = None,
    bolts: Any = None,
    circle: Any = None,
    pcd: Any = None,
    et: Any = None,
    hub: Any = None,
    dia: Any = None,
) -> str | None:
    d = _num(diameter)
    b = _num(bolts if bolts is not None else studs)
    p = _num(pcd if pcd is not None else circle)
    e = _num(et)
    h = _num(dia if dia is not None else hub)
    if d is None or b is None or p is None or e is None or h is None:
        return None
    return size_key(diameter=d, bolts=int(b), pcd=p, et=e, dia=h)


@dataclass
class CarHit:
    make: str
    model: str
    year: int
    make_ru: str = ""
    model_ru: str = ""
    hits: int = 1

    @property
    def label(self) -> str:
        make = self.make_ru or self.make.title()
        model = self.model_ru or self.model.replace("-", " ").title()
        return f"{make} {model}".strip()


@dataclass
class CarGroup:
    make: str
    model: str
    make_ru: str = ""
    model_ru: str = ""
    years: list[int] = field(default_factory=list)
    hits: int = 0

    def label(self) -> str:
        make = self.make_ru or self.make.title()
        model = self.model_ru or self.model.replace("-", " ").title()
        name = f"{make} {model}".strip()
        years = sorted({y for y in self.years if y > 0})
        if not years:
            return name
        if years[0] == years[-1]:
            return f"{name} ({years[0]})"
        return f"{name} ({years[0]}–{years[-1]})"


def aggregate_cars(hits: Sequence[CarHit]) -> list[CarGroup]:
    groups: dict[tuple[str, str], CarGroup] = {}
    for h in hits:
        key = (h.make.lower(), h.model.lower())
        g = groups.get(key)
        if g is None:
            g = CarGroup(
                make=h.make,
                model=h.model,
                make_ru=h.make_ru,
                model_ru=h.model_ru,
            )
            groups[key] = g
        if h.year > 0 and h.year not in g.years:
            g.years.append(h.year)
        g.hits += max(1, h.hits)
        if not g.make_ru and h.make_ru:
            g.make_ru = h.make_ru
        if not g.model_ru and h.model_ru:
            g.model_ru = h.model_ru
    out = list(groups.values())
    out.sort(key=lambda g: (-g.hits, g.label().lower()))
    return out


def format_cars_text(groups: Sequence[CarGroup], *, limit: int = MAX_CARS_IN_AD) -> str:
    if not groups:
        return ""
    shown = list(groups[: max(1, limit)])
    labels = [g.label() for g in shown]
    more = len(groups) - len(shown)
    body = ", ".join(labels)
    if more > 0:
        body += f" и ещё {more}"
    return f"Подходит на: {body}."


def format_cars_html(groups: Sequence[CarGroup], *, limit: int = MAX_CARS_IN_AD) -> str:
    text = format_cars_text(groups, limit=limit)
    if not text:
        return ""
    return f"<p><strong>{text}</strong></p>"


def cars_from_json(raw: str | list | dict | None) -> list[CarHit]:
    if raw is None or raw == "":
        return []
    data = json.loads(raw) if isinstance(raw, str) else raw
    if isinstance(data, dict) and "cars" in data:
        data = data["cars"]
    if not isinstance(data, list):
        return []
    out: list[CarHit] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        make = str(item.get("make") or "").strip()
        model = str(item.get("model") or "").strip()
        if not make or not model:
            continue
        year = int(item.get("year") or 0)
        out.append(
            CarHit(
                make=make,
                model=model,
                year=year,
                make_ru=str(item.get("make_ru") or "").strip(),
                model_ru=str(item.get("model_ru") or "").strip(),
                hits=int(item.get("hits") or 1),
            )
        )
    return out


def cars_to_json(hits: Sequence[CarHit]) -> str:
    payload = [
        {
            "make": h.make,
            "model": h.model,
            "year": h.year,
            "make_ru": h.make_ru,
            "model_ru": h.model_ru,
            "hits": h.hits,
        }
        for h in hits
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class WheelFitmentCache:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._by_pcd: dict[tuple[str, int, str], list[tuple[float, float, str]]] | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA_SQL)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._by_pcd = None

    def set_meta(self, key: str, value: str) -> None:
        con = self.connect()
        con.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        con.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        con = self.connect()
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def replace_size_cars(
        self,
        rows: Iterable[tuple[str, float, int, float, float, float, list[CarHit]]],
    ) -> int:
        con = self.connect()
        con.execute("DELETE FROM wheel_size_cars")
        n = 0
        for size_k, diameter, bolts, pcd, et, dia, hits in rows:
            groups_hits = list(hits)
            con.execute(
                "INSERT INTO wheel_size_cars"
                "(size_key, diameter, bolts, pcd, et, dia, cars_json, car_count) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    size_k,
                    float(diameter),
                    int(bolts),
                    float(pcd),
                    float(et),
                    float(dia),
                    cars_to_json(groups_hits),
                    len(aggregate_cars(groups_hits)),
                ),
            )
            n += 1
        con.commit()
        self._by_pcd = None
        return n

    def replace_article_cars(
        self,
        rows: Iterable[dict[str, Any]],
    ) -> int:
        con = self.connect()
        con.execute("DELETE FROM wheel_article_cars")
        n = 0
        for row in rows:
            con.execute(
                "INSERT INTO wheel_article_cars"
                "(article, size_key, diameter, bolts, pcd, et, dia, "
                "cars_html, cars_text, car_count, matched_size_key) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(row["article"]),
                    str(row.get("size_key") or ""),
                    row.get("diameter"),
                    row.get("bolts"),
                    row.get("pcd"),
                    row.get("et"),
                    row.get("dia"),
                    str(row.get("cars_html") or ""),
                    str(row.get("cars_text") or ""),
                    int(row.get("car_count") or 0),
                    str(row.get("matched_size_key") or ""),
                ),
            )
            n += 1
        con.commit()
        return n

    def _load_pcd_index(self) -> dict[tuple[str, int, str], list[tuple[float, float, str]]]:
        if self._by_pcd is not None:
            return self._by_pcd
        con = self.connect()
        idx: dict[tuple[str, int, str], list[tuple[float, float, str]]] = {}
        for row in con.execute(
            "SELECT size_key, diameter, bolts, pcd, et, dia FROM wheel_size_cars"
        ):
            key = (
                _fmt_num(float(row["diameter"])),
                int(row["bolts"]),
                _fmt_num(float(row["pcd"])),
            )
            idx.setdefault(key, []).append(
                (float(row["et"]), float(row["dia"]), str(row["size_key"]))
            )
        self._by_pcd = idx
        return idx

    def lookup_size(
        self,
        *,
        diameter: Any,
        bolts: Any,
        pcd: Any,
        et: Any,
        dia: Any,
        et_tol: float = ET_TOLERANCE,
        dia_tol: float = DIA_TOLERANCE,
    ) -> tuple[list[CarHit], str]:
        """Найти авто под размер. Возвращает (hits, matched_size_key)."""
        d = _num(diameter)
        b = _num(bolts)
        p = _num(pcd)
        e = _num(et)
        h = _num(dia)
        if d is None or b is None or p is None or e is None or h is None:
            return [], ""
        exact = size_key(diameter=d, bolts=int(b), pcd=p, et=e, dia=h)
        con = self.connect()
        row = con.execute(
            "SELECT cars_json, size_key FROM wheel_size_cars WHERE size_key=?",
            (exact,),
        ).fetchone()
        if row:
            return cars_from_json(row["cars_json"]), str(row["size_key"])

        # Tolerant: same diameter/bolts/pcd, ET±2, DIA±0.1
        candidates = self._load_pcd_index().get(
            (_fmt_num(d), int(b), _fmt_num(p)),
            [],
        )
        best_key = ""
        best_dist = 1e9
        for cet, cdia, sk in candidates:
            if abs(cet - e) > et_tol:
                continue
            if abs(cdia - h) > dia_tol:
                continue
            dist = abs(cet - e) + abs(cdia - h) * 10
            if dist < best_dist:
                best_dist = dist
                best_key = sk
        if not best_key:
            return [], ""
        row = con.execute(
            "SELECT cars_json, size_key FROM wheel_size_cars WHERE size_key=?",
            (best_key,),
        ).fetchone()
        if not row:
            return [], ""
        return cars_from_json(row["cars_json"]), str(row["size_key"])

    def html_for_article(self, article: str) -> str:
        art = str(article or "").strip()
        if not art:
            return ""
        con = self.connect()
        row = con.execute(
            "SELECT cars_html FROM wheel_article_cars WHERE article=?",
            (art,),
        ).fetchone()
        return str(row["cars_html"] or "") if row else ""

    def html_for_size_attrs(self, **attrs: Any) -> str:
        hits, _ = self.lookup_size(
            diameter=attrs.get("diameter"),
            bolts=attrs.get("bolts", attrs.get("studs")),
            pcd=attrs.get("pcd", attrs.get("circle")),
            et=attrs.get("et"),
            dia=attrs.get("dia", attrs.get("hub")),
        )
        return format_cars_html(aggregate_cars(hits))


def load_fitment_cache(path: Path | str | None) -> WheelFitmentCache | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        LOG.warning("wheel fitment cache missing: %s", p)
        return None
    try:
        cache = WheelFitmentCache(p)
        cache.connect()
        return cache
    except Exception as exc:  # noqa: BLE001
        LOG.warning("wheel fitment cache open failed: %s", exc)
        return None
