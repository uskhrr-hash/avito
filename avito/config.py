from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from avito.stores import StoresConfig, load_stores


@dataclass
class ScrapeSettings:
    search_url: str
    max_pages: int
    page_delay_sec: float
    page_delay_jitter_sec: float
    page_delay_step_sec: float
    page_delay_step_from: int
    page_rest_every: int
    page_rest_sec: float
    page_rest_jitter_sec: float
    browser_profile_dir: Path
    headless: bool


@dataclass
class CompareSettings:
    stock_file: Path
    stock_has_header: bool
    stock_indexes: dict[str, int]
    article_column: str
    nomenclature_column: str
    incoming_price_column: str
    quantity_column: str
    own_seller_names: list[str]
    exclude_needs_review: bool
    no_avito_multiplier: float
    floor_multiplier: float
    avito_discounts: tuple[float, ...]
    stock_only: bool


@dataclass
class NomenclatureApiSettings:
    base_url: str
    batch_size: int
    pause_sec: float
    timeout_sec: float


@dataclass
class AutoloadSettings:
    template_file: Path
    working_file: Path
    prefer_latest_avito_export: bool
    close_not_in_goods: bool
    sheet_name: str | None
    image_mode: str
    yandex_disk_root: str
    photos_public_base_url: str
    photo_layout: str
    photo_store_prefix_in_filename: bool
    image_count: int
    image_ext: str
    convert_photos_to_jpeg: bool
    jpeg_quality: int
    compress_photos: bool
    jpeg_max_dimension: int
    compress_min_kb: int
    model_photo_fallback: bool
    photo_article_first: bool
    manager_inbox_subdir: str
    photos_local_dir: Path | None
    verify_photos_on_disk: bool
    model_descriptions_file: Path
    missing_models_file: str
    description_html: str
    store_pitch_html: str
    llm_store_brief: str
    defaults: dict[str, str]
    skip_without_photos: bool
    include_all_goods_in_autoload: bool
    no_photos_file: str
    avito_ids_file: Path
    max_listing_quantity: int = 12
    new_listings_feed: Path | None = None
    photo_updates_feed: Path | None = None


@dataclass
class DescriptionsDbSettings:
    enabled: bool
    schema_sql: Path
    sqlite_schema_sql: Path
    pg_schema: str
    auto_approve_llm: bool
    llm_max_chars: int
    fallback_to_xlsx: bool


@dataclass
class PhotoUploadSettings:
    enabled: bool
    host: str
    port: int
    session_max_age_hours: int
    max_upload_mb: int
    public_mount_path: str


@dataclass
class AvitoSyncSettings:
    enabled: bool
    dry_run: bool
    stock_batch_size: int
    price_pause_sec: float
    refresh_ids_after_publish: bool


@dataclass
class AppConfig:
    scrape: ScrapeSettings
    compare: CompareSettings
    autoload: AutoloadSettings
    nomenclature_api: NomenclatureApiSettings
    stores: StoresConfig
    stock_sources: "StockSourcesSettings"
    descriptions_db: DescriptionsDbSettings
    photo_upload: PhotoUploadSettings
    avito_sync: AvitoSyncSettings


@dataclass
class StockSourcesSettings:
    enabled: bool
    secrets_file: Path
    output_file: Path
    google_enabled: bool
    google_csv_url: str
    google_spreadsheet_id: str
    google_worksheet: str
    google_columns: dict[str, str]
    google_avito_price_column_index: int
    db_enabled: bool
    db_min_quantity: int
    db_moscow_min_quantity: int
    db_supplier_ufa: str
    db_supplier_moscow: str
    db_ushk_prefix: str
    db_ufa_multiplier: float
    db_moscow_multiplier: float
    db_excluded_suppliers: tuple[str, ...]
    db_allowed_suppliers: tuple[str, ...]


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_merged_yaml(path: Path) -> dict:
    """config.yaml + config.local.yaml (если есть)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    local_path = path.parent / "config.local.yaml"
    if local_path.is_file():
        local_raw = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        if local_raw:
            raw = _deep_merge(raw, local_raw)
    return raw


def load_settings(path: Path) -> ScrapeSettings:
    return load_config(path).scrape


def load_config(path: Path) -> AppConfig:
    raw = load_merged_yaml(path)
    root = path.parent
    stores_path = root / str(raw.get("stores_file", "stores.yaml"))
    compare_raw = raw.get("compare") or {}

    discounts = compare_raw.get("avito_discounts", [0.01, 0.02, 0.03])
    scrape_raw = dict(raw)
    scrape_raw.update(raw.get("scrape") or {})
    return AppConfig(
        scrape=ScrapeSettings(
            search_url=str(scrape_raw.get("search_url", "")).strip().replace("\n", "").replace(" ", ""),
            max_pages=int(scrape_raw.get("max_pages", 0)),
            page_delay_sec=float(scrape_raw.get("page_delay_sec", 7)),
            page_delay_jitter_sec=float(scrape_raw.get("page_delay_jitter_sec", 3)),
            page_delay_step_sec=float(scrape_raw.get("page_delay_step_sec", 0.25)),
            page_delay_step_from=int(scrape_raw.get("page_delay_step_from", 5)),
            page_rest_every=int(scrape_raw.get("page_rest_every", 8)),
            page_rest_sec=float(scrape_raw.get("page_rest_sec", 30)),
            page_rest_jitter_sec=float(scrape_raw.get("page_rest_jitter_sec", 15)),
            browser_profile_dir=Path(scrape_raw.get("browser_profile_dir", ".browser_profile")),
            headless=bool(scrape_raw.get("headless", True)),
        ),
        compare=CompareSettings(
            stock_file=Path(compare_raw.get("stock_file", "input/goods.xlsx")),
            stock_has_header=bool(compare_raw.get("stock_has_header", True)),
            stock_indexes={
                str(k): int(v)
                for k, v in (compare_raw.get("stock_indexes") or {
                    "article": 0,
                    "nomenclature": 1,
                    "quantity": 2,
                    "price": 3,
                    "avito_price": 4,
                }).items()
            },
            article_column=str(compare_raw.get("article_column", "Артикул")),
            nomenclature_column=str(
                compare_raw.get("nomenclature_column", "Номенклатура")
            ),
            incoming_price_column=str(
                compare_raw.get("incoming_price_column", "Цена")
            ),
            quantity_column=str(compare_raw.get("quantity_column", "Количество")),
            own_seller_names=list(
                raw.get("own_seller_names", ["Шинный Центр №1"])
            ),
            exclude_needs_review=bool(compare_raw.get("exclude_needs_review", True)),
            no_avito_multiplier=float(compare_raw.get("no_avito_multiplier", 1.15)),
            floor_multiplier=float(compare_raw.get("floor_multiplier", 1.10)),
            avito_discounts=tuple(float(x) for x in discounts),
            stock_only=bool(compare_raw.get("stock_only", True)),
        ),
        autoload=_load_autoload(raw.get("autoload") or {}),
        nomenclature_api=_load_nomenclature_api(raw.get("nomenclature_api") or {}),
        stores=load_stores(stores_path),
        stock_sources=_load_stock_sources(raw.get("stock_sources") or {}),
        descriptions_db=_load_descriptions_db(raw.get("descriptions_db") or {}, root),
        photo_upload=_load_photo_upload(raw.get("photo_upload") or {}),
        avito_sync=_load_avito_sync(raw.get("avito_sync") or {}),
    )


def _optional_path(value) -> Path | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return Path(s)


def _load_nomenclature_api(raw: dict) -> NomenclatureApiSettings:
    return NomenclatureApiSettings(
        base_url=str(raw.get("base_url", "http://192.168.1.75/")),
        batch_size=int(raw.get("batch_size", 40)),
        pause_sec=float(raw.get("pause_sec", 0.2)),
        timeout_sec=float(raw.get("timeout_sec", 90)),
    )


def _load_descriptions_db(raw: dict, root: Path) -> DescriptionsDbSettings:
    schema = raw.get("schema_sql", "sql/avito_descriptions.sql")
    sqlite_schema = raw.get("sqlite_schema_sql", "sql/avito_descriptions_sqlite.sql")
    return DescriptionsDbSettings(
        enabled=bool(raw.get("enabled", False)),
        schema_sql=root / str(schema),
        sqlite_schema_sql=root / str(sqlite_schema),
        pg_schema=str(raw.get("pg_schema", "public")).strip() or "public",
        auto_approve_llm=bool(raw.get("auto_approve_llm", True)),
        llm_max_chars=int(raw.get("llm_max_chars", 2500)),
        fallback_to_xlsx=bool(raw.get("fallback_to_xlsx", True)),
    )


def _load_stock_sources(raw: dict) -> StockSourcesSettings:
    g_raw = raw.get("google") or {}
    d_raw = raw.get("db") or {}
    excluded = d_raw.get("excluded_suppliers") or [
        "Сам МБ прочие",
        "Вектра Екб",
        "Вектра Уфа",
        "Колобокс Нижний",
        "Колобокс Уфа",
        "Шинсервис",
        "Римэкс",
    ]
    allowed = d_raw.get("allowed_suppliers") or [
        "Сам МБ Уфа",
        "Сам МБ Москва",
        "Бринэкс",
        "Пауэр Уфа",
        "Шининвест",
    ]
    return StockSourcesSettings(
        enabled=bool(raw.get("enabled", False)),
        secrets_file=Path(raw.get("secrets_file", "secrets.local.yaml")),
        output_file=Path(raw.get("output_file", "input/goods.xlsx")),
        google_enabled=bool(g_raw.get("enabled", True)),
        google_csv_url=str(g_raw.get("csv_url", "")).strip(),
        google_spreadsheet_id=str(g_raw.get("spreadsheet_id", "")).strip(),
        google_worksheet=str(g_raw.get("worksheet", "Лист1")).strip(),
        google_columns={
            "article": str((g_raw.get("columns") or {}).get("article", "product_id")),
            "name": str((g_raw.get("columns") or {}).get("name", "name")),
            "price": str((g_raw.get("columns") or {}).get("price", "price")),
            "quantity": str((g_raw.get("columns") or {}).get("quantity", "quantity")),
            "avito_price": str((g_raw.get("columns") or {}).get("avito_price", "avito_price")),
        },
        google_avito_price_column_index=int(g_raw.get("avito_price_column_index", 6)),
        db_enabled=bool(d_raw.get("enabled", True)),
        db_min_quantity=int(d_raw.get("min_quantity", 4)),
        db_moscow_min_quantity=int(d_raw.get("moscow_min_quantity", 40)),
        db_supplier_ufa=str(d_raw.get("supplier_ufa", "Сам МБ Уфа")).strip(),
        db_supplier_moscow=str(d_raw.get("supplier_moscow", "Сам МБ Москва")).strip(),
        db_ushk_prefix=str(d_raw.get("ushk_prefix", "УШК")).strip(),
        db_ufa_multiplier=float(d_raw.get("ufa_multiplier", 0.9)),
        db_moscow_multiplier=float(d_raw.get("moscow_multiplier", 0.9)),
        db_excluded_suppliers=tuple(str(x).strip() for x in excluded if str(x).strip()),
        db_allowed_suppliers=tuple(str(x).strip() for x in allowed if str(x).strip()),
    )


def _load_autoload(raw: dict) -> AutoloadSettings:
    defaults = dict(raw.get("defaults") or {})
    if not defaults:
        defaults = {
            "listing_type": "Package",
            "contact_person": "Владислав",
            "phone": "79273181543",
            "address": "Республика Башкортостан, Уфа, улица Менделеева, 21",
            "contact_method": "По телефону и в сообщениях",
            "category": "Запчасти и аксессуары",
            "goods_type": "Шины, диски и колёса",
            "ad_type": "Товар приобретен на продажу",
            "product_type": "Шины",
            "merge_ads": "Да",
            "free_mounting": "Нет",
            "condition": "Новое",
            "run_flat": "Нет",
            "audience": "Частные лица и бизнес",
            "company": "Шинный Центр №1",
            "email": "md@shinaufa.ru",
        }
    return AutoloadSettings(
        template_file=Path(
            raw.get(
                "template_file",
                "input/432801655_2026-05-29T09_58_00Z.xlsx",
            )
        ),
        working_file=Path(raw.get("working_file", "input/autoload_working.xlsx")),
        prefer_latest_avito_export=bool(
            raw.get("prefer_latest_avito_export", True)
        ),
        close_not_in_goods=bool(raw.get("close_not_in_goods", True)),
        sheet_name=raw.get("sheet_name"),
        image_mode=str(raw.get("image_mode", "yandex_disk")),
        yandex_disk_root=str(raw.get("yandex_disk_root", "Авито")),
        photos_public_base_url=str(raw.get("photos_public_base_url", "")).strip(),
        photo_layout=str(raw.get("photo_layout", "flat")),
        photo_store_prefix_in_filename=bool(
            raw.get("photo_store_prefix_in_filename", True)
        ),
        image_count=int(raw.get("image_count", 0)),
        image_ext=str(raw.get("image_ext", "jpg")),
        convert_photos_to_jpeg=bool(raw.get("convert_photos_to_jpeg", True)),
        jpeg_quality=int(raw.get("jpeg_quality", 85)),
        compress_photos=bool(raw.get("compress_photos", True)),
        jpeg_max_dimension=int(raw.get("jpeg_max_dimension", 1920)),
        compress_min_kb=int(raw.get("compress_min_kb", 400)),
        model_photo_fallback=bool(raw.get("model_photo_fallback", True)),
        photo_article_first=bool(raw.get("photo_article_first", True)),
        manager_inbox_subdir=str(raw.get("manager_inbox_subdir", "входящие")),
        photos_local_dir=_optional_path(raw.get("photos_local_dir")),
        verify_photos_on_disk=bool(raw.get("verify_photos_on_disk", True)),
        model_descriptions_file=Path(
            raw.get("model_descriptions_file", "input/model_descriptions.xlsx")
        ),
        missing_models_file=str(
            raw.get("missing_models_file", "missing_model_descriptions.xlsx")
        ),
        description_html=str(
            raw.get(
                "description_html",
                (
                    "<p><strong>{availability_headline}</strong></p>"
                    '<p>Новые шины &quot;{nomenclature}&quot;🛞🛞🛞</p>'
                    "<p><strong>Цена за наличные!</strong></p>"
                ),
            )
        ),
        store_pitch_html=str(raw.get("store_pitch_html", "")),
        llm_store_brief=str(raw.get("llm_store_brief", "")),
        defaults={str(k): str(v) for k, v in defaults.items()},
        skip_without_photos=bool(raw.get("skip_without_photos", True)),
        include_all_goods_in_autoload=bool(
            raw.get("include_all_goods_in_autoload", False)
        ),
        no_photos_file=str(raw.get("no_photos_file", "no_photos.xlsx")),
        avito_ids_file=Path(raw.get("avito_ids_file", "input/avito_ids.csv")),
        max_listing_quantity=max(1, int(raw.get("max_listing_quantity", 12))),
        new_listings_feed=_optional_path(raw.get("new_listings_feed", "input/autoload_new.xlsx")),
        photo_updates_feed=_optional_path(
            raw.get("photo_updates_feed", "input/autoload_photo_updates.xlsx")
        ),
    )


def _load_avito_sync(raw: dict) -> AvitoSyncSettings:
    return AvitoSyncSettings(
        enabled=bool(raw.get("enabled", True)),
        dry_run=bool(raw.get("dry_run", False)),
        stock_batch_size=max(1, min(int(raw.get("stock_batch_size", 200)), 200)),
        price_pause_sec=float(raw.get("price_pause_sec", 0.4)),
        refresh_ids_after_publish=bool(raw.get("refresh_ids_after_publish", True)),
    )


def _load_photo_upload(raw: dict) -> PhotoUploadSettings:
    mount = str(raw.get("public_mount_path", "/photo")).strip() or "/photo"
    if not mount.startswith("/"):
        mount = f"/{mount}"
    return PhotoUploadSettings(
        enabled=bool(raw.get("enabled", False)),
        host=str(raw.get("host", "127.0.0.1")),
        port=int(raw.get("port", 8765)),
        session_max_age_hours=int(raw.get("session_max_age_hours", 72)),
        max_upload_mb=int(raw.get("max_upload_mb", 12)),
        public_mount_path=mount.rstrip("/") or "/photo",
    )
