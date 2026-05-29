"""Сопоставление остатков с Avito (номенклатура 1:1) и расчёт цен."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from avito.config import CompareSettings
from avito.own import is_own_listing
from avito.pricing import PriceRecommendation, recommend_price

_USABLE_CONFIDENCE = frozenset({"exact", "inferred"})


@dataclass
class StockRow:
    article: str
    nomenclature: str
    incoming: float
    quantity: str


def _parse_incoming(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip().replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _read_stock_dataframe(path: Path, cfg: CompareSettings) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if cfg.stock_has_header:
        if suffix == ".csv":
            return pd.read_csv(path, header=0, encoding="utf-8-sig")
        return pd.read_excel(path, sheet_name=0, header=0)
    if suffix == ".csv":
        return pd.read_csv(path, header=None, encoding="utf-8-sig")
    return pd.read_excel(path, sheet_name=0, header=None)


def load_stock(path: Path, cfg: CompareSettings) -> list[StockRow]:
    if not path.exists():
        raise FileNotFoundError(f"Файл остатков не найден: {path}")

    df = _read_stock_dataframe(path, cfg)
    rows: list[StockRow] = []

    if cfg.stock_has_header:
        art_col = _resolve_column(
            df.columns, cfg.article_column, ("артикул", "арт", "sku"), required=False
        )
        nom_col = _resolve_column(
            df.columns, cfg.nomenclature_column, ("номенклатура", "товар", "наименование")
        )
        price_col = _resolve_column(
            df.columns,
            cfg.incoming_price_column,
            ("цена", "входящая", "закуп", "входящая цена", "цена закуп"),
        )
        qty_col = _resolve_column(
            df.columns,
            cfg.quantity_column,
            ("количество", "кол-во", "остаток", "qty"),
            required=False,
        )
        for _, r in df.iterrows():
            nom = str(r.get(nom_col, "") or "").strip()
            if not nom or nom.lower() in ("nan", "номенклатура"):
                continue
            incoming = _parse_incoming(r.get(price_col))
            if incoming is None:
                continue
            article = str(r.get(art_col, "") or "").strip() if art_col else ""
            qty = str(r.get(qty_col, "") or "").strip() if qty_col else ""
            rows.append(
                StockRow(
                    article=_clean_article(article),
                    nomenclature=nom,
                    incoming=incoming,
                    quantity=qty,
                )
            )
        return rows

    idx = cfg.stock_indexes
    i_art = idx.get("article", 0)
    i_nom = idx.get("nomenclature", 1)
    i_qty = idx.get("quantity", 2)
    i_price = idx.get("price", 3)

    for _, r in df.iterrows():
        nom = str(r.iloc[i_nom] if i_nom < len(r) else "").strip()
        if not nom or nom.lower() in ("nan", "номенклатура"):
            continue
        incoming = _parse_incoming(r.iloc[i_price] if i_price < len(r) else None)
        if incoming is None:
            continue
        article = str(r.iloc[i_art] if i_art < len(r) else "").strip()
        qty = str(r.iloc[i_qty] if i_qty < len(r) else "").strip()
        if qty.lower() == "nan":
            qty = ""
        rows.append(
            StockRow(
                article=_clean_article(article),
                nomenclature=nom,
                incoming=incoming,
                quantity=qty,
            )
        )
    return rows


def _clean_article(value: str) -> str:
    s = value.strip()
    if s.lower() in ("nan", ""):
        return ""
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except ValueError:
            pass
    return s


def _resolve_column(
    columns,
    preferred: str,
    hints: tuple[str, ...],
    *,
    required: bool = True,
) -> str | None:
    cols = list(columns)
    if preferred in cols:
        return preferred
    lower_map = {str(c).strip().lower(): c for c in cols}
    if preferred.strip().lower() in lower_map:
        return lower_map[preferred.strip().lower()]
    for h in hints:
        if h in lower_map:
            return lower_map[h]
    if required:
        raise KeyError(
            f"Колонка «{preferred}» не найдена. Доступны: {', '.join(str(c) for c in cols)}"
        )
    return None


def load_avito_dump(path: Path, own_names: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "is_own" not in df.columns:
        owns = []
        matches = []
        for _, row in df.iterrows():
            ok, by = is_own_listing(
                seller=str(row.get("seller", "") or ""),
                title=str(row.get("title", "") or ""),
                description=str(row.get("description_snippet", "") or ""),
                own_names=own_names,
            )
            owns.append(ok)
            matches.append(by)
        df["is_own"] = owns
        df["own_match"] = matches
    return df


def avito_min_by_title(df: pd.DataFrame, *, exclude_needs_review: bool) -> dict[str, float]:
    """Минимальная цена конкурентов: ключ = title.strip() (1:1)."""
    work = df.copy()
    work["title_key"] = work["title"].astype(str).str.strip()
    work = work[work["title_key"] != ""]
    work = work[work["is_own"] == False]  # noqa: E712
    if exclude_needs_review:
        work = work[work["price_confidence"].isin(_USABLE_CONFIDENCE)]
    work = work[work["price_per_tire"].notna()]

    if work.empty:
        return {}

    grouped = work.groupby("title_key", as_index=False)["price_per_tire"].min()
    return dict(zip(grouped["title_key"], grouped["price_per_tire"].astype(float)))


def build_posting_rows(
    stock: list[StockRow],
    avito_mins: dict[str, float],
    cfg: CompareSettings,
    date_key: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    posting: list[dict] = []
    problems: list[dict] = []
    seen_nom: dict[str, int] = {}

    for row in stock:
        key = row.nomenclature  # 1:1, только strip при загрузке
        seen_nom[key] = seen_nom.get(key, 0) + 1

        avito_min = avito_mins.get(key)
        rec = recommend_price(
            row.incoming,
            avito_min,
            seed=key,
            date_key=date_key,
            no_avito_multiplier=cfg.no_avito_multiplier,
            floor_multiplier=cfg.floor_multiplier,
            discounts=cfg.avito_discounts,
        )

        posting.append(_posting_record(row, rec, avito_min, duplicate=(seen_nom[key] > 1)))

    for nom, cnt in seen_nom.items():
        if cnt > 1:
            problems.append(
                {
                    "номенклатура": nom,
                    "проблема": f"дубликат в остатках ({cnt} строк)",
                }
            )

    return posting, problems, []


def _posting_record(
    row: StockRow,
    rec: PriceRecommendation,
    avito_min: float | None,
    *,
    duplicate: bool,
) -> dict:
    on_avito = avito_min is not None
    return {
        "артикул": row.article,
        "номенклатура": row.nomenclature,
        "количество": row.quantity,
        "входящая": row.incoming,
        "есть_на_avito": on_avito,
        "avito_min": avito_min if on_avito else "",
        "recommended_price": rec.recommended_price,
        "price_rule": rec.price_rule,
        "discount_pct": rec.discount_pct if rec.discount_pct is not None else "",
        "floor_входящая_x1.1": int(round(rec.floor_price)),
        "дубликат_остаток": duplicate,
    }


def own_listings_report(df: pd.DataFrame) -> list[dict]:
    own = df[df["is_own"] == True]  # noqa: E712
    cols = ["avito_id", "title", "price_per_tire", "seller", "own_match", "url"]
    cols = [c for c in cols if c in own.columns]
    return own[cols].to_dict(orient="records")
