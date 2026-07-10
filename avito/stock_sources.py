"""Сбор остатков из Google Sheets и БД в единый goods.xlsx."""

from __future__ import annotations

import logging

from dataclasses import dataclass

from pathlib import Path

import pandas as pd

import yaml

from avito.config import StockSourcesSettings

from avito.stock_priority import (

    REGISTER_QUERY,

    RegisterLine,

    StockPriorityConfig,

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

            )

        )

    return rows

def fetch_google_rows(cfg: StockSourcesSettings, secrets: dict) -> list[StockRow]:

    del secrets

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

    )

def fetch_db_rows(cfg: StockSourcesSettings, secrets: dict) -> list[StockRow]:

    d_cfg = secrets.get("db") or {}

    required = ("host", "port", "database", "user", "password")

    missing = [k for k in required if not str(d_cfg.get(k, "")).strip()]

    if missing:

        raise ValueError(f"В secrets.local.yaml не заполнены db-поля: {', '.join(missing)}")

    try:

        import psycopg2

    except ImportError as exc:

        raise RuntimeError("Установите зависимость: pip install psycopg2-binary") from exc

    conn = psycopg2.connect(

        host=str(d_cfg["host"]),

        port=int(d_cfg["port"]),

        dbname=str(d_cfg["database"]),

        user=str(d_cfg["user"]),

        password=str(d_cfg["password"]),

    )

    try:

        df = pd.read_sql_query(REGISTER_QUERY, conn)

    finally:

        conn.close()

    lines: list[RegisterLine] = []

    for _, row in df.iterrows():

        article = _clean_article(row.get("product_id"))

        name = str(row.get("product") or "").strip()

        supplier = str(row.get("supplier") or "").strip()

        price = _clean_price(row.get("price"))

        if not article or not supplier or price is None:

            continue

        lines.append(

            RegisterLine(

                article=article,

                name=name,

                supplier=supplier,

                price=price,

                quantity=_parse_quantity(row.get("quantity")),

            )

        )

    resolved = resolve_register_stock(lines, _priority_config(cfg))

    return [

        StockRow(

            article=item.article,

            name=item.name,

            quantity=item.quantity,

            price=item.base_price,

            source=f"db:{item.priority}",

            avito_price=None,

        )

        for item in resolved

    ]

def merge_rows(

    google_rows: list[StockRow],

    db_rows: list[StockRow],

) -> list[StockRow]:

    """Приоритет Google (П1): дубли артикулов из БД отбрасываются."""

    by_article: dict[str, StockRow] = {r.article: r for r in google_rows}

    for row in db_rows:

        if row.article not in by_article:

            by_article[row.article] = row

    return sorted(by_article.values(), key=lambda x: x.article)

GOODS_COLUMN_COUNT = 6

def write_goods_xlsx(path: Path, rows: list[StockRow]) -> None:

    path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(

        [

            [

                r.article,

                r.name,

                r.quantity,

                r.price,

                r.avito_price if r.avito_price is not None else "",

                r.source,

            ]

            for r in rows

        ],

        columns=["артикул", "номенклатура", "количество", "цена", "цена_avito", "source"],

    )

    df.to_excel(path, sheet_name="Sheet1", index=False, header=False)

def fetch_merged_stock(cfg: StockSourcesSettings, secrets: dict) -> list[StockRow]:

    """Остатки из Google (П1) и БД (П2–П6)."""

    g_rows: list[StockRow] = []

    d_rows: list[StockRow] = []

    if cfg.google_enabled:

        if not cfg.google_csv_url and not cfg.google_spreadsheet_id:

            raise ValueError(

                "config.yaml: задайте stock_sources.google.csv_url или spreadsheet_id"

            )

        g_rows = fetch_google_rows(cfg, secrets)

    if cfg.db_enabled:

        d_rows = fetch_db_rows(cfg, secrets)

    if not cfg.google_enabled and not cfg.db_enabled:

        raise ValueError("stock_sources: включите google и/или db")

    return merge_rows(g_rows, d_rows)

def refresh_goods_file(

    cfg: StockSourcesSettings,

    *,

    root: Path,

    secrets: dict,

) -> tuple[Path, list[StockRow]]:

    """Перезаписывает goods.xlsx свежими данными из источников."""

    merged = fetch_merged_stock(cfg, secrets)

    out = cfg.output_file if cfg.output_file.is_absolute() else root / cfg.output_file

    write_goods_xlsx(out, merged)

    return out, merged

def is_legacy_goods_format(df: pd.DataFrame) -> bool:

    """Старый goods: 5 колонок без цена_avito."""

    return len(df.columns) < GOODS_COLUMN_COUNT

def summarize_sources(rows: list[StockRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = "p1" if row.source == "google" else row.source.replace("db:", "", 1)
        counts[key] = counts.get(key, 0) + 1
    return counts

