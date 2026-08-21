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
    template_file: Path  # deprecated unused
    working_file: Path  # deprecated unused
    prefer_latest_avito_export: bool  # deprecated unused
    close_not_in_goods: bool
    sheet_name: str | None
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
    model_descriptions_file: Path  # deprecated unused
    missing_models_file: str  # deprecated unused
    description_html: str
    store_pitch_html: str
    llm_store_brief: str
    defaults: dict[str, str]
    skip_without_photos: bool
    include_all_goods_in_autoload: bool
    avito_ids_file: Path
    max_listing_quantity: int = 12
    new_listings_feed: Path | None = None
    photo_updates_feed: Path | None = None
    contributors_prefix: str = "contributors"
    shinaufa_model_photos_enabled: bool = True
    shinaufa_model_photos_base: str = "https://shinaufa.ru/images/large/tyres"
    shinaufa_model_photos_wheels_base: str = "https://shinaufa.ru/images/large/wheels"
    shinaufa_model_photo_cache: Path | None = None
    shinaufa_model_photo_index: Path | None = None
    shinaufa_model_photo_timeout_sec: float = 5.0
    shinaufa_model_photo_rate_limit_sec: float = 0.05
    shinaufa_model_photo_live_fetch: bool = False
    # Desktop / legacy
    image_mode: str = "server_https"
    yandex_disk_root: str = "Авито"
    no_photos_file: str = "no_photos"  # deprecated unused


@dataclass
class DescriptionsDbSettings:
    enabled: bool
    schema_sql: Path
    sqlite_schema_sql: Path
    pg_schema: str
    auto_approve_llm: bool
    llm_max_chars: int


@dataclass
class PhotoUploadSettings:
    enabled: bool
    host: str
    port: int
    session_max_age_hours: int
    max_upload_mb: int
    public_mount_path: str
    db_path: Path
    contributors_prefix: str
    points_per_photo: int
    contributor_max_photos: int
    contributor_shops: tuple[str, ...] = ()


@dataclass
class AvitoSyncSettings:
    enabled: bool
    dry_run: bool
    stock_batch_size: int
    price_pause_sec: float
    refresh_ids_after_publish: bool
    close_oos: bool = True
    # Diff-only: не слать цену/qty если совпадает с last-sent в SQLite
    diff_only: bool = True
    force_full_sync: bool = False
    # Первый прогон при пустом avito_sync_state: seed текущих price/qty (без blast)
    seed_on_empty: bool = True
    price_max_retries: int = 4
    # AvitoId full refresh: missing/new каждый прогон; полный ≤1×/сутки
    full_ids_refresh: bool = True
    force_full_ids_refresh: bool = False
    full_ids_min_interval_hours: int = 24
    # Час локальной TZ (Asia/Yekaterinburg), с которого разрешён daily full refresh
    full_ids_daily_hour: int = 3
    # XML photo_updates: только изменившиеся (fingerprint)
    photo_updates_diff_only: bool = False
    force_full_photo_updates: bool = False


@dataclass
class StockDbSettings:
    """Локальный SQLite-кэш остатков (не ERP)."""
    path: Path
    schema_sql: Path


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


@dataclass
class WheelsSettings:
    """Диски в том же фиде, что и шины (product_type=Диски).

    Disable: wheels.enabled: false
    Publish gate: wheels.include_in_publish: false (default) — generate but don't
    push wheels into live Avito publish feeds / close tires accidentally.

    Pilot gate (safe with include_in_publish=false):
      publish_ids: [md_…, …] — only these wheel listing/article ids enter publish XML
      publish_limit: N — cap wheels when include_in_publish=true (ignored if publish_ids set)
    Tires are never filtered by these gates.
    """

    enabled: bool = True
    types: tuple[str, ...] = ("1", "2", "3")
    product_type: str = "Диски"
    include_in_autoload: bool = True
    include_in_publish: bool = False
    skip_without_photos: bool = False
    description_html: str = ""
    publish_ids: tuple[str, ...] = ()
    publish_limit: int | None = None


@dataclass
class AppConfig:
    scrape: ScrapeSettings
    compare: CompareSettings
    autoload: AutoloadSettings
    nomenclature_api: NomenclatureApiSettings
    stores: StoresConfig
    stock_sources: StockSourcesSettings
    stock_db: StockDbSettings
    descriptions_db: DescriptionsDbSettings
    photo_upload: PhotoUploadSettings
    avito_sync: AvitoSyncSettings
    wheels: WheelsSettings


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
            # stock_file deprecated — runtime uses stock_db only
            stock_file=Path(compare_raw.get("stock_file", "data/avito_stock.db")),
            stock_has_header=bool(compare_raw.get("stock_has_header", True)),
            stock_indexes={
                str(k): int(v)
                for k, v in (compare_raw.get("stock_indexes") or {
                    "article": 0,
                    "nomenclature": 1,
                    "quantity": 2,
                    "price": 3,
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
        stock_db=_load_stock_db(raw.get("stock_db") or {}, root),
        descriptions_db=_load_descriptions_db(raw.get("descriptions_db") or {}, root),
        photo_upload=_load_photo_upload(raw.get("photo_upload") or {}),
        avito_sync=_load_avito_sync(raw.get("avito_sync") or {}),
        wheels=_load_wheels(raw.get("wheels") or {}),
    )


def _optional_path(value) -> Path | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return Path(s)


def _load_wheels(raw: dict) -> WheelsSettings:
    types_raw = raw.get("types") or ["1", "2", "3"]
    types = tuple(str(x).strip() for x in types_raw if str(x).strip())
    if not types:
        types = ("1", "2", "3")
    ids_raw = raw.get("publish_ids") or []
    if isinstance(ids_raw, str):
        ids_raw = [ids_raw]
    publish_ids = tuple(
        str(x).strip() for x in ids_raw if str(x).strip()
    )
    limit_raw = raw.get("publish_limit", None)
    publish_limit: int | None
    if limit_raw is None or str(limit_raw).strip() == "":
        publish_limit = None
    else:
        publish_limit = max(0, int(limit_raw))
    return WheelsSettings(
        enabled=bool(raw.get("enabled", True)),
        types=types,
        product_type=str(raw.get("product_type", "Диски") or "Диски").strip()
        or "Диски",
        include_in_autoload=bool(raw.get("include_in_autoload", True)),
        include_in_publish=bool(raw.get("include_in_publish", False)),
        skip_without_photos=bool(raw.get("skip_without_photos", False)),
        description_html=str(raw.get("description_html", "") or ""),
        publish_ids=publish_ids,
        publish_limit=publish_limit,
    )


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
    )


def _load_stock_db(raw: dict, root: Path) -> StockDbSettings:
    path = Path(str(raw.get("path", "data/avito_stock.db")).strip() or "data/avito_stock.db")
    schema = Path(
        str(raw.get("schema_sql", "sql/avito_stock_sqlite.sql")).strip()
        or "sql/avito_stock_sqlite.sql"
    )
    if not path.is_absolute():
        path = root / path
    if not schema.is_absolute():
        schema = root / schema
    return StockDbSettings(path=path, schema_sql=schema)


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
        # deprecated: was goods.xlsx cache; runtime writes SQLite only
        output_file=Path(raw.get("output_file", "data/avito_stock.db")),
        google_enabled=bool(g_raw.get("enabled", True)),
        google_csv_url=str(g_raw.get("csv_url", "")).strip(),
        google_spreadsheet_id=str(g_raw.get("spreadsheet_id", "")).strip(),
        google_worksheet=str(g_raw.get("worksheet", "Лист1")).strip(),
        google_columns={
            "article": str((g_raw.get("columns") or {}).get("article", "product_id")),
            "name": str((g_raw.get("columns") or {}).get("name", "name")),
            "price": str((g_raw.get("columns") or {}).get("price", "price")),
            "quantity": str((g_raw.get("columns") or {}).get("quantity", "quantity")),
        },
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
        # deprecated Excel paths kept for YAML compat; unused by daily
        template_file=Path(raw.get("template_file", "input/_deprecated_template")),
        working_file=Path(raw.get("working_file", "input/_deprecated_working")),
        prefer_latest_avito_export=bool(
            raw.get("prefer_latest_avito_export", False)
        ),
        close_not_in_goods=bool(raw.get("close_not_in_goods", True)),
        sheet_name=raw.get("sheet_name"),
        photos_public_base_url=str(
            raw.get("photos_public_base_url", "https://avito.shinaufa.ru/photos")
        ).strip(),
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
            raw.get("model_descriptions_file", "data/avito_descriptions.db")
        ),
        missing_models_file=str(
            raw.get("missing_models_file", "missing_model_descriptions")
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
        avito_ids_file=Path(raw.get("avito_ids_file", "input/avito_ids.csv")),
        max_listing_quantity=max(1, int(raw.get("max_listing_quantity", 12))),
        new_listings_feed=_optional_path(raw.get("new_listings_feed", "input/autoload_new.xml")),
        photo_updates_feed=_optional_path(
            raw.get("photo_updates_feed", "input/autoload_photo_updates.xml")
        ),
        contributors_prefix=str(
            raw.get("contributors_prefix", "contributors")
        ).strip()
        or "contributors",
        shinaufa_model_photos_enabled=bool(
            raw.get("shinaufa_model_photos_enabled", True)
        ),
        shinaufa_model_photos_base=str(
            raw.get(
                "shinaufa_model_photos_base",
                "https://shinaufa.ru/images/large/tyres",
            )
        ).strip()
        or "https://shinaufa.ru/images/large/tyres",
        shinaufa_model_photos_wheels_base=str(
            raw.get(
                "shinaufa_model_photos_wheels_base",
                "https://shinaufa.ru/images/large/wheels",
            )
        ).strip()
        or "https://shinaufa.ru/images/large/wheels",
        shinaufa_model_photo_cache=_optional_path(
            raw.get(
                "shinaufa_model_photo_cache",
                "data/shinaufa_model_photo_cache.json",
            )
        ),
        shinaufa_model_photo_index=_optional_path(
            raw.get(
                "shinaufa_model_photo_index",
                "data/shinaufa_photo_index.sqlite",
            )
        ),
        shinaufa_model_photo_timeout_sec=float(
            raw.get("shinaufa_model_photo_timeout_sec", 5)
        ),
        shinaufa_model_photo_rate_limit_sec=float(
            raw.get("shinaufa_model_photo_rate_limit_sec", 0.05)
        ),
        shinaufa_model_photo_live_fetch=bool(
            raw.get("shinaufa_model_photo_live_fetch", False)
        ),
        image_mode=str(raw.get("image_mode", "server_https") or "server_https"),
        yandex_disk_root=str(raw.get("yandex_disk_root", "Авито") or "Авито"),
        no_photos_file=str(raw.get("no_photos_file", "no_photos") or "no_photos"),
    )


def _load_avito_sync(raw: dict) -> AvitoSyncSettings:
    return AvitoSyncSettings(
        enabled=bool(raw.get("enabled", True)),
        dry_run=bool(raw.get("dry_run", False)),
        stock_batch_size=max(1, min(int(raw.get("stock_batch_size", 200)), 200)),
        price_pause_sec=float(raw.get("price_pause_sec", 0.4)),
        refresh_ids_after_publish=bool(raw.get("refresh_ids_after_publish", True)),
        close_oos=bool(raw.get("close_oos", True)),
        diff_only=bool(raw.get("diff_only", True)),
        force_full_sync=bool(raw.get("force_full_sync", False)),
        seed_on_empty=bool(raw.get("seed_on_empty", True)),
        price_max_retries=max(1, int(raw.get("price_max_retries", 4))),
        full_ids_refresh=bool(raw.get("full_ids_refresh", True)),
        force_full_ids_refresh=bool(raw.get("force_full_ids_refresh", False)),
        full_ids_min_interval_hours=max(
            1, int(raw.get("full_ids_min_interval_hours", 24))
        ),
        full_ids_daily_hour=max(0, min(int(raw.get("full_ids_daily_hour", 3)), 23)),
        photo_updates_diff_only=bool(raw.get("photo_updates_diff_only", False)),
        force_full_photo_updates=bool(raw.get("force_full_photo_updates", False)),
    )


def _load_photo_upload(raw: dict) -> PhotoUploadSettings:
    mount = str(raw.get("public_mount_path", "/")).strip() or "/"
    if not mount.startswith("/"):
        mount = f"/{mount}"
    # Root "/" is valid (Photo v2 at domain root); do not coerce to /photo.
    mount_norm = mount.rstrip("/") or "/"
    db_raw = str(raw.get("db_path", "data/photo_upload.db")).strip() or "data/photo_upload.db"
    contrib = str(raw.get("contributors_prefix", "contributors")).strip() or "contributors"
    shops_raw = raw.get("contributor_shops") or []
    shops = tuple(
        str(x).strip() for x in shops_raw if str(x).strip()
    )
    return PhotoUploadSettings(
        enabled=bool(raw.get("enabled", False)),
        host=str(raw.get("host", "127.0.0.1")),
        port=int(raw.get("port", 8766)),
        session_max_age_hours=int(raw.get("session_max_age_hours", 72)),
        max_upload_mb=int(raw.get("max_upload_mb", 12)),
        public_mount_path=mount_norm,
        db_path=Path(db_raw),
        contributors_prefix=contrib,
        points_per_photo=max(0, int(raw.get("points_per_photo", 10))),
        contributor_max_photos=max(1, int(raw.get("contributor_max_photos", 10))),
        contributor_shops=shops,
    )
