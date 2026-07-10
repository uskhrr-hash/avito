"""Сопоставление остатков с Avito (номенклатура 1:1) и расчёт цен."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from avito.config import CompareSettings
from avito.stock_sources import GOODS_COLUMN_COUNT, is_legacy_goods_format
from avito.own import is_own_listing
from avito.pricing import (
    PriceRecommendation,
    fixed_price_recommendation,
    recommend_price,
    round_price_to_tens,
)

_USABLE_CONFIDENCE = frozenset({"exact", "inferred"})


@dataclass
class StockRow:
    article: str
    nomenclature: str
    incoming: float
    quantity: str
    avito_price: float | None = None


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


def _parse_optional_avito_price(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip().lower()
    if not s or s in ("nan", "google", "db"):
        return None
    return _parse_incoming(value)


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
        raise FileNotFoundError(
            f"Файл остатков не найден: {path}. Запустите: python build_stock.py"
        )

    df = _read_stock_dataframe(path, cfg)
    if not cfg.stock_has_header and is_legacy_goods_format(df):
        raise ValueError(
            f"Устаревший {path.name} ({len(df.columns)} колонок, нужно {GOODS_COLUMN_COUNT}). "
            "Остатки только из Google и БД: python build_stock.py"
        )
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
    i_avito = idx.get("avito_price")

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
        avito_price = None
        if i_avito is not None:
            avito_price = _parse_optional_avito_price(
                r.iloc[i_avito] if i_avito < len(r) else None
            )
        rows.append(
            StockRow(
                article=_clean_article(article),
                nomenclature=nom,
                incoming=incoming,
                quantity=qty,
                avito_price=avito_price,
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
    df = _apply_match_keys(df)
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


def _apply_match_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Ключ сопоставления с goods: name_canonical, если словарь распознал title."""
    if "name_canonical" not in df.columns:
        df["match_key"] = df["title"].astype(str).str.strip()
        return df

    df["match_key"] = ""
    if "dict_recognized" in df.columns:
        ok = df["dict_recognized"] == True  # noqa: E712
        df.loc[ok, "match_key"] = (
            df.loc[ok, "name_canonical"].astype(str).str.strip()
        )
    else:
        canon = df["name_canonical"].astype(str).str.strip()
        df["match_key"] = canon.where(~canon.isin(("", "nan", "None")), "")
    return df


def diagnose_unmatched_stock(nom: str, df: pd.DataFrame, *, exclude_needs_review: bool) -> str:
    """Почему номенклатура из goods не получила avito_min."""
    nom = nom.strip()
    if "name_canonical" not in df.columns:
        return "нет нормализованного дампа — запустите normalize_avito.py"

    sub = df[df["name_canonical"].astype(str).str.strip() == nom]
    if not sub.empty:
        competitors = sub[sub["is_own"] == False]  # noqa: E712
        if competitors.empty:
            return "в дампе только свои объявления"
        priced = competitors[competitors["price_per_tire"].notna()]
        if priced.empty:
            return "есть объявления, нет цены за штуку"
        if exclude_needs_review and "price_confidence" in priced.columns:
            usable = priced[priced["price_confidence"].isin(_USABLE_CONFIDENCE)]
            if usable.empty:
                return "есть объявления, цена только needs_review"
        return "есть в дампе, min не рассчитан (проверьте фильтры)"

    if "dict_recognized" in df.columns:
        unk = df[df["dict_recognized"] == False]  # noqa: E712
        if not unk.empty and nom:
            token = nom.split()[0]
            hits = unk[
                unk["title"].astype(str).str.contains(token, case=False, na=False)
            ]
            if not hits.empty:
                return (
                    f"нет name={nom!r} в дампе; "
                    f"похожие title без словаря: {len(hits)}"
                )

    return "нет в дампе Avito (по name_canonical)"


def stock_avito_match_rows(
    stock: list[StockRow],
    avito_df: pd.DataFrame,
    avito_mins: dict[str, float],
    *,
    exclude_needs_review: bool,
) -> tuple[list[dict], list[dict]]:
    """Отчёт сопоставления goods.номенклатура ↔ name_canonical и проблемы."""
    details: list[dict] = []
    problems: list[dict] = []

    for row in stock:
        nom = row.nomenclature
        avito_min = avito_mins.get(nom)
        matched = avito_min is not None

        sub = pd.DataFrame()
        if "name_canonical" in avito_df.columns:
            sub = avito_df[
                avito_df["name_canonical"].astype(str).str.strip() == nom
            ]

        reason = ""
        if not matched:
            reason = diagnose_unmatched_stock(
                nom, avito_df, exclude_needs_review=exclude_needs_review
            )
            problems.append({"номенклатура": nom, "проблема": reason})

        n_total = len(sub)
        n_own = int(sub["is_own"].sum()) if n_total and "is_own" in sub.columns else 0
        n_competitor = n_total - n_own if n_total else 0

        details.append(
            {
                "номенклатура": nom,
                "артикул": row.article,
                "совпадение": "да" if matched else "нет",
                "avito_min": avito_min if matched else "",
                "объявлений_с_таким_name": n_total,
                "конкурентов": n_competitor,
                "своих": n_own,
                "причина_если_нет": reason,
            }
        )

    return details, problems


def avito_min_by_title(df: pd.DataFrame, *, exclude_needs_review: bool) -> dict[str, float]:
    """Минимальная цена конкурентов: ключ = match_key (name_canonical из словаря)."""
    work = df.copy()
    if "match_key" not in work.columns:
        work["match_key"] = work["title"].astype(str).str.strip()
    work["title_key"] = work["match_key"].astype(str).str.strip()
    work = work[~work["title_key"].isin(("", "nan", "None"))]
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

        # остатки в нашем формате; avito_min по name_canonical после normalize_avito.py
        avito_min = avito_mins.get(key)
        if row.avito_price is not None:
            rec = fixed_price_recommendation(
                row.avito_price,
                row.incoming,
                avito_min,
                floor_multiplier=cfg.floor_multiplier,
            )
        else:
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


def stock_only_overview_rows(stock: list[StockRow]) -> list[dict]:
    """Лист «остатки» для режима без парсера Avito."""
    return [
        {
            "артикул": row.article,
            "номенклатура": row.nomenclature,
            "количество": row.quantity,
            "входящая": row.incoming,
            "цена_avito_фикс": row.avito_price if row.avito_price is not None else "",
        }
        for row in stock
    ]


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
        "цена_avito_фикс": row.avito_price if row.avito_price is not None else "",
        "recommended_price": rec.recommended_price,
        "price_rule": rec.price_rule,
        "discount_pct": rec.discount_pct if rec.discount_pct is not None else "",
        "floor_входящая_x1.1": round_price_to_tens(rec.floor_price),
        "дубликат_остаток": duplicate,
    }


def own_listings_report(df: pd.DataFrame) -> list[dict]:
    own = df[df["is_own"] == True]  # noqa: E712
    cols = ["avito_id", "title", "price_per_tire", "seller", "own_match", "url"]
    cols = [c for c in cols if c in own.columns]
    return own[cols].to_dict(orient="records")
