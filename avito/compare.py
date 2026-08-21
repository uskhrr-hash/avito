"""Сопоставление остатков с Avito (номенклатура 1:1) и расчёт цен."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from avito.config import CompareSettings
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
    ushk_in_stock: bool = False
    sam_mb_cash_price: bool = False
    source: str = ""
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


def load_stock_from_db(
    db_path: Path,
    *,
    schema_path: Path | None = None,
) -> list[StockRow]:
    """Остатки из локального SQLite (результат build_stock)."""
    from avito.stock_db import iter_items, row_count, stock_connection

    if not db_path.exists():
        raise FileNotFoundError(
            f"БД остатков не найдена: {db_path}. Запустите: python build_stock.py"
        )
    with stock_connection(db_path, schema_path=schema_path) as conn:
        if row_count(conn) <= 0:
            raise FileNotFoundError(
                f"БД остатков пуста: {db_path}. Запустите: python build_stock.py"
            )
        db_rows = iter_items(conn)
    return [
        StockRow(
            article=r.article,
            nomenclature=r.name,
            incoming=float(r.price),
            quantity=r.quantity,
            avito_price=r.avito_price,
            ushk_in_stock=r.ushk_in_stock,
            sam_mb_cash_price=r.sam_mb_cash_price,
            source=r.source,
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
        for r in db_rows
        if r.article and r.name and r.price > 0
    ]


def load_stock(
    path: Path,
    cfg: CompareSettings,
    *,
    stock_db_path: Path | None = None,
    stock_db_schema: Path | None = None,
) -> list[StockRow]:
    """Читает остатки только из SQLite (build_stock). Excel/path fallback удалён."""
    del path, cfg  # legacy signature: stock_file path больше не читается
    if stock_db_path is None:
        raise FileNotFoundError(
            "Нужен stock_db (data/avito_stock.db). Запустите: python build_stock.py"
        )
    return load_stock_from_db(stock_db_path, schema_path=stock_db_schema)


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
    manual_prices: dict[str, float] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    posting: list[dict] = []
    problems: list[dict] = []
    seen_nom: dict[str, int] = {}
    manuals = manual_prices or {}

    for row in stock:
        key = row.nomenclature  # 1:1, только strip при загрузке
        seen_nom[key] = seen_nom.get(key, 0) + 1

        # остатки в нашем формате; avito_min по name_canonical после normalize_avito.py
        avito_min = avito_mins.get(key)
        art = str(row.article or "").strip()
        manual = manuals.get(art)
        if manual is not None and manual > 0:
            rec = fixed_price_recommendation(manual, row.incoming)
        else:
            rec = recommend_price(
                row.incoming,
                no_avito_multiplier=cfg.no_avito_multiplier,
                floor_multiplier=cfg.floor_multiplier,
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
        "ушк_в_наличии": bool(row.ushk_in_stock),
        "цена_за_наличный_расчет": bool(row.sam_mb_cash_price),
        "avito_min": avito_min if on_avito else "",
        "цена_avito_фикс": row.avito_price if row.avito_price is not None else "",
        "recommended_price": rec.recommended_price,
        "price_rule": rec.price_rule,
        "discount_pct": rec.discount_pct if rec.discount_pct is not None else "",
        "floor_входящая_x1.1": round_price_to_tens(rec.floor_price),
        "дубликат_остаток": duplicate,
        "kind": row.kind or "tire",
        "brand": row.brand,
        "model": row.model,
        "wheel_type": row.wheel_type,
        "width": row.width,
        "diameter": row.diameter,
        "studs": row.studs,
        "circle": row.circle,
        "et": row.et,
        "hub": row.hub,
    }


def own_listings_report(df: pd.DataFrame) -> list[dict]:
    own = df[df["is_own"] == True]  # noqa: E712
    cols = ["avito_id", "title", "price_per_tire", "seller", "own_match", "url"]
    cols = [c for c in cols if c in own.columns]
    return own[cols].to_dict(orient="records")
