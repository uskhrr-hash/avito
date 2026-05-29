from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ScrapeSettings:
    search_url: str
    max_pages: int
    page_delay_sec: float
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


@dataclass
class AutoloadSettings:
    template_file: Path
    sheet_name: str | None
    image_mode: str
    yandex_disk_root: str
    photo_layout: str
    image_count: int
    image_ext: str
    description_html: str
    defaults: dict[str, str]
    skip_without_photos: bool
    avito_ids_file: Path


@dataclass
class AppConfig:
    scrape: ScrapeSettings
    compare: CompareSettings
    autoload: AutoloadSettings


def load_settings(path: Path) -> ScrapeSettings:
    return load_config(path).scrape


def load_config(path: Path) -> AppConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    compare_raw = raw.get("compare") or {}

    discounts = compare_raw.get("avito_discounts", [0.01, 0.02, 0.03])
    return AppConfig(
        scrape=ScrapeSettings(
            search_url=str(raw["search_url"]).strip().replace("\n", "").replace(" ", ""),
            max_pages=int(raw.get("max_pages", 0)),
            page_delay_sec=float(raw.get("page_delay_sec", 2.5)),
            browser_profile_dir=Path(raw.get("browser_profile_dir", ".browser_profile")),
            headless=bool(raw.get("headless", True)),
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
        ),
        autoload=_load_autoload(raw.get("autoload") or {}),
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
            "company": "Шинный Центр",
            "email": "md@shinaufa.ru",
        }
    return AutoloadSettings(
        template_file=Path(
            raw.get(
                "template_file",
                "input/432801655_2026-05-29T09_58_00Z.xlsx",
            )
        ),
        sheet_name=raw.get("sheet_name"),
        image_mode=str(raw.get("image_mode", "yandex_disk")),
        yandex_disk_root=str(raw.get("yandex_disk_root", "Авито")),
        photo_layout=str(raw.get("photo_layout", "flat")),
        image_count=int(raw.get("image_count", 3)),
        image_ext=str(raw.get("image_ext", "jpg")),
        description_html=str(
            raw.get(
                "description_html",
                "<p><strong>Шины в наличии!</strong></p><p>Новые шины {nomenclature}</p>",
            )
        ),
        defaults={str(k): str(v) for k, v in defaults.items()},
        skip_without_photos=bool(raw.get("skip_without_photos", False)),
        avito_ids_file=Path(raw.get("avito_ids_file", "input/avito_ids.csv")),
    )
