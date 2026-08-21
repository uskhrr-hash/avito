"""Автозагрузка Avito: helpers для listings/XML (Excel battle path удалён)."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from avito.config import AutoloadSettings
from avito.photos import (
    PhotoNamingSettings,
    is_avito_hosted_photo_urls,
    photo_urls_look_like_article,
    photo_urls_ok_for_avito_update,
)
from avito.shinaufa_photos import ShinaufaModelPhotoSettings
from avito.stores import Store, StoresConfig, merge_defaults
from avito.model_descriptions import lookup_model_description
from avito.pricing import round_price_to_tens
from avito.title_parse import parse_title_fields, build_multi_name_from_title
from avito.tire_catalog import load_tire_catalog, normalize_title_fields

LOG = logging.getLogger(__name__)

DATA_START_ROW = 5
HEADER_ROW = 2
MAX_AVITO_DESCRIPTION_LEN = 7500
# В шаблоне Авито «Количество» — из справочника («за N шт.»), не остаток на складе.
AUTOLOAD_PRICE_QUANTITY = "за 1 шт."

_XLSX_GONE = (
    "Excel/openpyxl удалён из battle path. Используйте listings SQLite + XML "
    "(build_autoload / publish_avito_feed)."
)


def _xlsx_removed(*_a, **_k):
    raise RuntimeError(_XLSX_GONE)

def normalize_article_id(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return ""
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except ValueError:
            pass
    return s

def posting_keep_sets(
    posting_df: pd.DataFrame,
    stores: StoresConfig,
) -> tuple[set[str], set[str], set[str]]:
    """Артикулы, номенклатура и Id объявления (md_артикул) из posting."""
    articles: set[str] = set()
    titles: set[str] = set()
    listing_ids: set[str] = set()
    for _, post in posting_df.iterrows():
        nom = str(post.get("номенклатура", "")).strip()
        if nom and nom.lower() != "nan":
            titles.add(nom)
        article = normalize_article_id(post.get("артикул", ""))
        if article:
            articles.add(article)
            listing_ids.add(article)
            for store in stores.stores:
                listing_ids.add(store.listing_id(article))
    return articles, titles, listing_ids

def row_in_goods(
    *,
    row_id: str,
    article: str,
    title: str,
    keep_articles: set[str],
    keep_titles: set[str],
    keep_listing_ids: set[str],
) -> bool:
    if row_id and row_id in keep_listing_ids:
        return True
    if article and article in keep_articles:
        return True
    if title and title in keep_titles:
        return True
    return False

def resolve_photos_folder(cfg: AutoloadSettings, project_root: Path) -> Path | None:
    if not cfg.verify_photos_on_disk or not cfg.photos_local_dir:
        return None
    folder = cfg.photos_local_dir
    if not folder.is_absolute():
        folder = project_root / folder
    return folder if folder.is_dir() else None

def _shinaufa_photo_settings(
    cfg: AutoloadSettings,
    *,
    project_root: Path | None = None,
    product_kind: str = "tire",
) -> ShinaufaModelPhotoSettings:
    cache = getattr(cfg, "shinaufa_model_photo_cache", None)
    if cache is not None and project_root is not None and not Path(cache).is_absolute():
        cache = Path(project_root) / cache
    kind = str(product_kind or "tire").strip().lower()
    if kind in ("wheel", "wheels", "диск", "диски", "disk", "disks"):
        base = str(
            getattr(
                cfg,
                "shinaufa_model_photos_wheels_base",
                "https://shinaufa.ru/images/large/wheels",
            )
            or "https://shinaufa.ru/images/large/wheels"
        )
    else:
        base = str(
            getattr(
                cfg,
                "shinaufa_model_photos_base",
                "https://shinaufa.ru/images/large/tyres",
            )
            or "https://shinaufa.ru/images/large/tyres"
        )
    index = getattr(cfg, "shinaufa_model_photo_index", None)
    if index is not None and project_root is not None and not Path(index).is_absolute():
        index = Path(project_root) / index
    return ShinaufaModelPhotoSettings(
        enabled=bool(getattr(cfg, "shinaufa_model_photos_enabled", False)),
        base_url=base,
        cache_file=Path(cache) if cache else None,
        head_timeout_sec=float(
            getattr(cfg, "shinaufa_model_photo_timeout_sec", 5.0) or 5.0
        ),
        rate_limit_sec=float(
            getattr(cfg, "shinaufa_model_photo_rate_limit_sec", 0.05) or 0.05
        ),
        index_path=Path(index) if index else None,
        live_fetch=bool(getattr(cfg, "shinaufa_model_photo_live_fetch", False)),
    )

def _photo_cfg(cfg: AutoloadSettings) -> PhotoNamingSettings:
    return PhotoNamingSettings(
        image_count=cfg.image_count,
        image_ext=cfg.image_ext,
        photo_layout=getattr(cfg, "photo_layout", "flat"),
        photos_public_base_url=getattr(cfg, "photos_public_base_url", ""),
    )

class _SafeDict(dict):
    def __missing__(self, key):
        return ""

def _availability_headline(ushk_in_stock: bool, *, product_kind: str = "tire") -> str:
    """Заголовок наличия: шины / диски — по kind, не по шаблону шин."""
    kind = str(product_kind or "tire").strip().lower()
    is_wheel = kind in ("wheel", "wheels", "диск", "диски", "rim", "rims")
    noun = "Диски" if is_wheel else "Шины"
    if ushk_in_stock:
        return f"{noun} в наличии!"
    return f"{noun} под заказ 1-2 дня"

def _posting_ushk_in_stock(post_row) -> bool:
    if post_row is None:
        return False
    val = post_row.get("ушк_в_наличии")
    if val is True:
        return True
    return str(val or "").strip().lower() in ("true", "1", "да", "yes")

def _posting_sam_mb_cash_price(post_row) -> bool:
    if post_row is None:
        return False
    val = post_row.get("цена_за_наличный_расчет")
    if val is True:
        return True
    return str(val or "").strip().lower() in ("true", "1", "да", "yes")

def _payment_terms(sam_mb_cash_price: bool) -> str:
    if sam_mb_cash_price:
        return "Цена за наличный расчет"
    return "Любая форма оплаты, НДС"

def _autoload_price(value) -> int:
    """Цена в Excel автозагрузки — до десятков рублей."""
    return round_price_to_tens(float(value))

def _avito_id_for_row(
    listing_id: str,
    article: str,
    avito_ids: dict[str, str],
) -> str:
    """
    Номер Avito только для конкретного Id строки.

    Не подставляем общий article→id на md_/pg_ — иначе один номер
    на два магазина → error AvitoId.
    """
    lid = normalize_article_id(listing_id)
    if lid and lid in avito_ids:
        return avito_ids[lid]
    if lid and "_" in lid:
        return ""
    art = normalize_article_id(article) or _article_from_listing_id(lid)
    if art and art in avito_ids:
        return avito_ids[art]
    return ""

def _should_replace_photo_urls(current: str, *, source: str) -> bool:
    """
    Фото артикула всегда пишем в файл (замена модели или ссылок Avito).
    Модель — не трогаем уже принятые Avito-ссылки.
    """
    if source == "article":
        return True
    return not is_avito_hosted_photo_urls(current)

def _format_price(value) -> str:
    try:
        return format(_autoload_price(value), "_").replace("_", " ")
    except Exception:
        return ""

def _article_from_listing_id(listing_id: str) -> str:
    sid = normalize_article_id(listing_id)
    if "_" in sid:
        return sid.split("_", 1)[1]
    return sid

def _store_defaults_for_listing_id(
    listing_id: str,
    stores: StoresConfig,
    cfg_defaults: dict[str, str],
) -> dict[str, str]:
    sid = normalize_article_id(listing_id)
    prefix = ""
    if "_" in sid:
        prefix = sid.split("_", 1)[0]
    elif stores.legacy_unprefixed_store:
        prefix = stores.legacy_unprefixed_store
    store = stores.get(prefix)
    if store:
        return merge_defaults(cfg_defaults, store)
    return dict(cfg_defaults)

def _posting_row_lookup(
    posting_df: pd.DataFrame,
    *,
    max_quantity: int = 12,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for _, row in posting_df.iterrows():
        nom = str(row.get("номенклатура", "") or "").strip()
        if not nom:
            continue
        rec = row.get("recommended_price")
        if pd.isna(rec):
            continue
        out[nom] = {
            "article": normalize_article_id(row.get("артикул", "")),
            "price": _autoload_price(rec),
            "quantity": _quantity_label(
                str(row.get("количество", "")),
                max_quantity=max_quantity,
            ),
            "ushk_in_stock": _posting_ushk_in_stock(row),
            "sam_mb_cash_price": _posting_sam_mb_cash_price(row),
        }
    return out

def _format_description(
    template: str,
    *,
    nomenclature: str,
    article: str,
    price: int,
    quantity: str,
    model_description: str,
    store_pitch: str = "",
    store_defaults: dict[str, str],
    ushk_in_stock: bool = False,
    sam_mb_cash_price: bool = False,
    product_kind: str = "tire",
    fitment_cars: str = "",
) -> str:
    payload = _SafeDict(
        nomenclature=nomenclature,
        article=article,
        price=str(price),
        price_human=_format_price(price),
        quantity=quantity,
        availability_headline=_availability_headline(
            ushk_in_stock, product_kind=product_kind
        ),
        payment_terms=_payment_terms(sam_mb_cash_price),
        model_description=model_description,
        fitment_cars=fitment_cars or "",
        store_pitch=store_pitch or "",
        contact_person=store_defaults.get("contact_person", ""),
        phone=store_defaults.get("phone", ""),
        address=store_defaults.get("address", ""),
        company=store_defaults.get("company", ""),
        email=store_defaults.get("email", ""),
        contact_method=store_defaults.get("contact_method", ""),
    )
    desc = template.format_map(payload)
    return desc[:MAX_AVITO_DESCRIPTION_LEN]

def _quantity_label(qty: str, *, max_quantity: int = 12) -> str:
    """Остаток на складе для текста описания (не для колонки «Количество» в Excel)."""
    q = str(qty).strip()
    if not q or q.lower() == "nan":
        return "1"
    try:
        n = int(float(q))
        if n <= 0:
            return "1"
        cap = max(1, int(max_quantity))
        return str(min(n, cap))
    except ValueError:
        return "1"

def _to_float_or_none(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(" ", "").replace(",", ".")
    if not s or s.lower() in ("nan", "none"):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def _is_priority_for_photo_queue(post_row) -> bool:
    """Все позиции без фото попадают в очередь (парсера конкурентов нет)."""
    del post_row
    return True

def avito_ids_for_posting(
    posting_df: pd.DataFrame,
    stores: StoresConfig,
    *,
    ids_from_xlsx: dict[str, str] | None = None,
    titles_from_xlsx: dict[str, str] | None = None,
    ids_from_csv: dict[str, str] | None = None,
) -> dict[str, str]:
    """Собрать avito_id по listing_id (md_/pg_) / артикулу / названию — без fan-out на все магазины."""
    del stores  # fan-out отключён намеренно
    by_listing = dict(ids_from_xlsx or {})
    by_title = dict(titles_from_xlsx or {})
    for key, val in list(by_listing.items()):
        if key.startswith("title:"):
            by_title[key[6:]] = val
    out = merge_avito_ids(by_listing, ids_from_csv or {}, stores=None)

    for _, row in posting_df.iterrows():
        nom = str(row.get("номенклатура", "") or "").strip()
        art = normalize_article_id(row.get("артикул", ""))
        avito_num = ""
        if nom and nom in by_title:
            avito_num = by_title[nom]
        elif nom and f"title:{nom}" in by_listing:
            avito_num = by_listing[f"title:{nom}"]
        if not avito_num or not art:
            continue
        # Только артикул — не копируем на md_/pg_ (у магазинов разные объявления).
        out.setdefault(art, avito_num)
    return out

def merge_avito_ids(
    *maps: dict[str, str],
    stores: StoresConfig | None = None,
) -> dict[str, str]:
    """Поздние словари перекрывают ранние. Без размножения article ↔ все магазины."""
    del stores
    out: dict[str, str] = {}
    for m in maps:
        for key, val in m.items():
            if not key or not val:
                continue
            if str(key).startswith("title:"):
                continue
            out[str(key).strip()] = str(val).strip().split(".")[0]
    return out

def save_avito_ids_csv(path: Path, mapping: dict[str, str]) -> int:
    """Записать avito_ids.csv (listing_id или артикул; avito_id)."""
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, val in sorted(mapping.items()):
        k = str(key).strip()
        v = str(val).strip().split(".")[0]
        if not k or not v or k.startswith("title:") or k in seen:
            continue
        seen.add(k)
        rows.append((k, v))
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["артикул;avito_id", *(f"{a};{i}" for a, i in rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return len(rows)

def load_avito_ids(path: Path, stores: StoresConfig | None = None) -> dict[str, str]:
    """Читает CSV: ключ = listing_id (md_…) или артикул. Без fan-out на все магазины."""
    del stores
    if not path.exists():
        return {}
    df = pd.read_csv(path, encoding="utf-8-sig", sep=None, engine="python")
    cols = {str(c).strip().lower(): c for c in df.columns}
    art = (
        cols.get("артикул")
        or cols.get("article")
        or cols.get("listing_id")
        or cols.get("id")
    )
    aid = cols.get("avito_id") or cols.get("номер объявления на авито") or cols.get("avito id")
    prefix_col = cols.get("префикс") or cols.get("prefix") or cols.get("магазин")
    if not art or not aid:
        return {}
    out: dict[str, str] = {}
    for _, r in df.iterrows():
        a = normalize_article_id(r[art])
        i = str(r[aid]).strip()
        if not a or not i or i.lower() == "nan":
            continue
        avito_id = i.split(".")[0]
        if prefix_col:
            p = str(r[prefix_col]).strip().lower()
            if p and "_" not in a:
                a = f"{p}_{a}"
        out[a] = avito_id
    return out

def _listing_id_for_article(
    article: str,
    stores: StoresConfig,
    *,
    current_id: str = "",
) -> str:
    """md_12044 — наш Id для автозагрузки (не числовой Id Авито)."""
    prefix = ""
    if current_id and "_" in current_id:
        p = current_id.split("_", 1)[0]
        if p in stores.by_prefix():
            prefix = p
    if not prefix and stores.stores:
        prefix = stores.stores[0].prefix
    store = stores.get(prefix) if prefix else None
    if store:
        return store.listing_id(article)
    return f"{prefix}_{article}" if prefix else article

def save_workbook(path: Path):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def load_posting(path: Path):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def find_latest_avito_export(search_dir: Path):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def resolve_autoload_base(cfg, *, root: Path, override=None, use_working: bool = False):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def extract_avito_ids_from_xlsx(path: Path, stores=None):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def _extract_avito_export_maps(path: Path):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def fill_autoload_template(*args, **kwargs):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def filter_new_listings_workbook(*args, **kwargs):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def filter_photo_updates_workbook(*args, **kwargs):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def merge_autoload_feed_workbooks(*args, **kwargs):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def _find_data_sheet(wb):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def _header_map(ws):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

def _col(headers, name: str):
    """Удалено: Excel battle path."""
    raise RuntimeError(_XLSX_GONE)

