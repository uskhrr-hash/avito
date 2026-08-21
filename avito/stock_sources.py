"""Сбор остатков из Google Sheets и ERP → SQLite."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from avito.config import StockSourcesSettings, WheelsSettings
from avito.stock_priority import (
    RegisterLine,
    StockPriorityConfig,
    articles_with_ushk_stock,
    articles_with_sam_mb_cash_stock,
    register_tires_query,
    register_wheels_query,
    resolve_register_stock,
)

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class StockRow:
    article: str
    name: str
    quantity: str
    price: float
    source: str
    avito_price: float | None = None
    ushk_in_stock: bool = False
    sam_mb_cash_price: bool = False
    kind: str = "tire"
    brand: str = ""
    model: str = ""
    wheel_type: str = ""
    width: str = ""
    diameter: str = ""
    studs: str = ""
    circle: str = ""
    et: str = ""
    hub: str = ""


def load_secrets(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Не найден файл секретов: {path}. Создайте из secrets.local.yaml.example"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _clean_article(value) -> str:
    s = str(value or "").strip()
    if not s or s.lower() == "nan":
        return ""
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except ValueError:
            pass
    return s


def _clean_price(value) -> float | None:
    s = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not s or s.lower() == "nan":
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _clean_qty(value) -> str:
    s = str(value or "").strip()
    return "" if s.lower() == "nan" else s


def _parse_quantity(value) -> float:
    s = str(value or "").strip().replace(",", ".")
    if not s or s.lower() == "nan":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _cell_str(value) -> str:
    s = str(value or "").strip()
    return "" if s.lower() in ("nan", "none") else s


def _required_google_columns(cols: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in cols.items() if k != "avito_price" and v}


def _rows_from_df(df: pd.DataFrame, cols: dict[str, str], *, source: str) -> list[StockRow]:
    rows: list[StockRow] = []
    for _, r in df.iterrows():
        article = _clean_article(r.get(cols["article"]))
        name = str(r.get(cols["name"], "") or "").strip()
        price = _clean_price(r.get(cols["price"]))
        qty = _clean_qty(r.get(cols.get("quantity", ""), ""))
        if not article or not name or price is None:
            continue
        rows.append(
            StockRow(
                article=article,
                name=name,
                quantity=qty,
                price=price,
                source=source,
                avito_price=None,
                sam_mb_cash_price=(source == "google"),
                kind="tire",
            )
        )
    return rows


def _rows_from_df_by_index(
    df: pd.DataFrame,
    *,
    article_idx: int,
    name_idx: int,
    quantity_idx: int,
    price_idx: int,
    source: str,
) -> list[StockRow]:
    rows: list[StockRow] = []
    for _, r in df.iterrows():
        article = _clean_article(r.iloc[article_idx] if article_idx < len(r) else "")
        name = str(r.iloc[name_idx] if name_idx < len(r) else "").strip()
        price = _clean_price(r.iloc[price_idx] if price_idx < len(r) else None)
        qty = _clean_qty(r.iloc[quantity_idx] if quantity_idx < len(r) else "")
        if not article or not name or price is None:
            continue
        rows.append(
            StockRow(
                article=article,
                name=name,
                quantity=qty,
                price=price,
                source=source,
                avito_price=None,
                sam_mb_cash_price=(source == "google"),
                kind="tire",
            )
        )
    return rows


def fetch_google_rows(cfg: StockSourcesSettings, secrets: dict) -> list[StockRow]:
    if cfg.google_csv_url:
        csv_url = cfg.google_csv_url.strip()
        if csv_url.endswith("/pubhtml"):
            csv_url = csv_url[:-8] + "/pub?output=csv"
        elif "/pubhtml?" in csv_url:
            csv_url = csv_url.replace("/pubhtml?", "/pub?output=csv&")
        elif "output=csv" not in csv_url and "/pub?" in csv_url:
            if csv_url.endswith("?"):
                csv_url += "output=csv"
            else:
                csv_url += "&output=csv"
        df = pd.read_csv(csv_url)
        required = _required_google_columns(cfg.google_columns)
        if all(c in df.columns for c in required.values()):
            return _rows_from_df(df, cfg.google_columns, source="google")
        df = pd.read_csv(csv_url, header=None)
        return _rows_from_df_by_index(
            df,
            article_idx=0,
            name_idx=1,
            quantity_idx=2,
            price_idx=3,
            source="google",
        )
    g_cfg = secrets.get("google") or {}
    cred = str(g_cfg.get("credentials_file", "")).strip()
    if not cred:
        raise ValueError("В secrets.local.yaml не задан google.credentials_file")
    try:
        import gspread
    except ImportError as exc:
        raise RuntimeError("Установите зависимости: pip install gspread google-auth") from exc
    gc = gspread.service_account(filename=cred)
    sh = gc.open_by_key(cfg.google_spreadsheet_id)
    ws = sh.worksheet(cfg.google_worksheet)
    values = ws.get_all_records()
    df = pd.DataFrame(values)
    return _rows_from_df(df, cfg.google_columns, source="google")


def _priority_config(cfg: StockSourcesSettings) -> StockPriorityConfig:
    return StockPriorityConfig(
        min_quantity=cfg.db_min_quantity,
        moscow_min_quantity=cfg.db_moscow_min_quantity,
        supplier_ufa=cfg.db_supplier_ufa,
        supplier_moscow=cfg.db_supplier_moscow,
        ushk_prefix=cfg.db_ushk_prefix,
        ufa_multiplier=cfg.db_ufa_multiplier,
        moscow_multiplier=cfg.db_moscow_multiplier,
        excluded_suppliers=frozenset(cfg.db_excluded_suppliers),
        allowed_suppliers=frozenset(cfg.db_allowed_suppliers),
    )


def _register_line_from_df_row(row) -> RegisterLine | None:
    article = _clean_article(row.get("product_id"))
    name = str(row.get("product") or "").strip()
    supplier = str(row.get("supplier") or "").strip()
    price = _clean_price(row.get("price"))
    if not article or not supplier or price is None:
        return None
    kind = _cell_str(row.get("kind")) or "tire"
    if kind not in ("tire", "wheel"):
        kind = "tire"
    return RegisterLine(
        article=article,
        name=name,
        supplier=supplier,
        price=price,
        quantity=_parse_quantity(row.get("quantity")),
        kind=kind,
        brand=_cell_str(row.get("brand")),
        model=_cell_str(row.get("model")),
        wheel_type=_cell_str(row.get("wheel_type")),
        width=_cell_str(row.get("width")),
        diameter=_cell_str(row.get("diameter")),
        studs=_cell_str(row.get("studs")),
        circle=_cell_str(row.get("circle")),
        et=_cell_str(row.get("et")),
        hub=_cell_str(row.get("hub")),
    )


def _load_register_lines(
    cfg: StockSourcesSettings,
    secrets: dict,
    *,
    wheels: WheelsSettings | None = None,
) -> list[RegisterLine]:
    d_cfg = secrets.get("db") or {}
    required = ("host", "port", "database", "user", "password")
    missing = [k for k in required if not str(d_cfg.get(k, "")).strip()]
    if missing:
        raise ValueError(f"В secrets.local.yaml не заполнены db-поля: {', '.join(missing)}")
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("Установите зависимость: pip install psycopg2-binary") from exc

    wheels_cfg = wheels or WheelsSettings()
    # Два отдельных SELECT быстрее и стабильнее, чем UNION ALL через pandas.
    queries = [register_tires_query()]
    if wheels_cfg.enabled:
        queries.append(register_wheels_query(wheel_types=tuple(wheels_cfg.types)))

    connect_timeout = int(d_cfg.get("connect_timeout", 15) or 15)
    conn = psycopg2.connect(
        host=str(d_cfg["host"]),
        port=int(d_cfg["port"]),
        dbname=str(d_cfg["database"]),
        user=str(d_cfg["user"]),
        password=str(d_cfg["password"]),
        connect_timeout=connect_timeout,
    )
    lines: list[RegisterLine] = []
    try:
        with conn.cursor() as cur:
            for query in queries:
                t0 = __import__("time").time()
                cur.execute(query)
                cols = [d[0] for d in cur.description]
                n = 0
                while True:
                    batch = cur.fetchmany(5000)
                    if not batch:
                        break
                    for tup in batch:
                        row = dict(zip(cols, tup))
                        line = _register_line_from_df_row(row)
                        if line is not None:
                            lines.append(line)
                        n += 1
                LOG.info(
                    "ERP register query: rows=%s in %.1fs",
                    n,
                    __import__("time").time() - t0,
                )
    finally:
        conn.close()
    return lines


def _rows_from_register_lines(
    lines: list[RegisterLine],
    cfg: StockSourcesSettings,
) -> list[StockRow]:
    resolved = resolve_register_stock(lines, _priority_config(cfg))
    return [
        StockRow(
            article=item.article,
            name=item.name,
            quantity=item.quantity,
            price=item.base_price,
            source=f"db:{item.priority}",
            avito_price=None,
            ushk_in_stock=item.ushk_in_stock,
            sam_mb_cash_price=item.sam_mb_cash_price,
            kind=item.kind,
            brand=item.brand,
            model=item.model,
            wheel_type=item.wheel_type,
            width=item.width,
            diameter=item.diameter,
            studs=item.studs,
            circle=item.circle,
            et=item.et,
            hub=item.hub,
        )
        for item in resolved
    ]


def fetch_db_rows(
    cfg: StockSourcesSettings,
    secrets: dict,
    *,
    wheels: WheelsSettings | None = None,
) -> list[StockRow]:
    lines = _load_register_lines(cfg, secrets, wheels=wheels)
    return _rows_from_register_lines(lines, cfg)


def merge_rows(
    google_rows: list[StockRow],
    db_rows: list[StockRow],
    *,
    ushk_articles: frozenset[str] | None = None,
    sam_mb_cash_articles: frozenset[str] | None = None,
) -> list[StockRow]:
    """Google (П1), если не дороже ERP. Если Google выше — берём ERP."""
    ushk_set = ushk_articles or frozenset()
    cash_set = sam_mb_cash_articles or frozenset()
    by_article: dict[str, StockRow] = {}
    for r in google_rows:
        ushk = r.ushk_in_stock or r.article in ushk_set
        cash = r.sam_mb_cash_price or r.article in cash_set or r.source == "google"
        by_article[r.article] = StockRow(
            article=r.article,
            name=r.name,
            quantity=r.quantity,
            price=r.price,
            source=r.source,
            avito_price=r.avito_price,
            ushk_in_stock=ushk,
            sam_mb_cash_price=cash,
            kind=r.kind or "tire",
            brand=r.brand,
            model=r.model,
            wheel_type=r.wheel_type,
            width=r.width,
            diameter=r.diameter,
            studs=r.studs,
            circle=r.circle,
            et=r.et,
            hub=r.hub,
        )
    for row in db_rows:
        existing = by_article.get(row.article)
        if existing is None:
            by_article[row.article] = row
            continue
        if row.price < existing.price:
            ushk = row.ushk_in_stock or existing.ushk_in_stock or row.article in ushk_set
            by_article[row.article] = StockRow(
                article=row.article,
                name=row.name or existing.name,
                quantity=row.quantity,
                price=row.price,
                source=row.source,
                avito_price=row.avito_price if row.avito_price is not None else existing.avito_price,
                ushk_in_stock=ushk,
                sam_mb_cash_price=row.sam_mb_cash_price,
                kind=row.kind or existing.kind or "tire",
                brand=row.brand or existing.brand,
                model=row.model or existing.model,
                wheel_type=row.wheel_type or existing.wheel_type,
                width=row.width or existing.width,
                diameter=row.diameter or existing.diameter,
                studs=row.studs or existing.studs,
                circle=row.circle or existing.circle,
                et=row.et or existing.et,
                hub=row.hub or existing.hub,
            )
    return sorted(by_article.values(), key=lambda x: x.article)


GOODS_COLUMN_COUNT = 6  # legacy constant; Excel goods writer removed


def _parse_ushk_cell(value) -> bool:
    s = str(value or "").strip().lower()
    return s in ("1", "true", "да", "yes")


def fetch_merged_stock(
    cfg: StockSourcesSettings,
    secrets: dict,
    *,
    wheels: WheelsSettings | None = None,
) -> list[StockRow]:
    """Остатки из Google (П1) и БД (П2–П6), опционально с дисками."""
    g_rows: list[StockRow] = []
    d_rows: list[StockRow] = []
    ushk_articles: frozenset[str] = frozenset()
    sam_mb_cash_articles: frozenset[str] = frozenset()
    if cfg.google_enabled:
        if not cfg.google_csv_url and not cfg.google_spreadsheet_id:
            raise ValueError(
                "config.yaml: задайте stock_sources.google.csv_url или spreadsheet_id"
            )
        g_rows = fetch_google_rows(cfg, secrets)
    if cfg.db_enabled:
        register_lines = _load_register_lines(cfg, secrets, wheels=wheels)
        prio_cfg = _priority_config(cfg)
        ushk_articles = articles_with_ushk_stock(register_lines, prio_cfg)
        sam_mb_cash_articles = articles_with_sam_mb_cash_stock(register_lines, prio_cfg)
        d_rows = _rows_from_register_lines(register_lines, cfg)
    if not cfg.google_enabled and not cfg.db_enabled:
        raise ValueError("stock_sources: включите google и/или db")
    return merge_rows(
        g_rows,
        d_rows,
        ushk_articles=ushk_articles,
        sam_mb_cash_articles=sam_mb_cash_articles,
    )


def refresh_goods_file(
    cfg: StockSourcesSettings,
    *,
    root: Path,
    secrets: dict,
    wheels: WheelsSettings | None = None,
    stock_db_path: Path | None = None,
    stock_db_schema: Path | None = None,
) -> tuple[Path, list[StockRow]]:
    """Собирает остатки из источников → SQLite."""
    from avito.stock_db import StockDbRow, replace_all, stock_connection

    merged = fetch_merged_stock(cfg, secrets, wheels=wheels)
    db_path = stock_db_path or (root / "data" / "avito_stock.db")
    if not db_path.is_absolute():
        db_path = root / db_path
    schema = stock_db_schema
    if schema is not None and not schema.is_absolute():
        schema = root / schema
    with stock_connection(db_path, schema_path=schema) as conn:
        replace_all(
            conn,
            [
                StockDbRow(
                    article=r.article,
                    name=r.name,
                    quantity=r.quantity,
                    price=float(r.price),
                    source=r.source,
                    avito_price=r.avito_price,
                    ushk_in_stock=bool(r.ushk_in_stock),
                    sam_mb_cash_price=bool(r.sam_mb_cash_price),
                    kind=r.kind or "tire",
                    brand=r.brand or "",
                    model=r.model or "",
                    wheel_type=r.wheel_type or "",
                    width=r.width or "",
                    diameter=r.diameter or "",
                    studs=r.studs or "",
                    circle=r.circle or "",
                    et=r.et or "",
                    hub=r.hub or "",
                )
                for r in merged
            ],
        )
    return db_path, merged


def summarize_sources(rows: list[StockRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = "p1" if row.source == "google" else row.source.replace("db:", "", 1)
        counts[key] = counts.get(key, 0) + 1
    return counts


def summarize_kinds(rows: list[StockRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = row.kind or "tire"
        counts[key] = counts.get(key, 0) + 1
    return counts
