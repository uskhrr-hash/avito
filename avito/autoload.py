"""Заполнение шаблона автозагрузки Avito (Excel)."""
from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from avito.config import AutoloadSettings
from avito.photos import PhotoNamingSettings, yandex_disk_urls
from avito.title_parse import parse_title_fields

# Строки шаблона (1-based): 1 категория, 2 заголовки, 3 обязательность, 4 подсказки, 5+ данные
DATA_START_ROW = 5
HEADER_ROW = 2


def _find_data_sheet(wb) -> str:
    for name in wb.sheetnames:
        if name.startswith("Спр"):
            continue
        if name == "Инструкция":
            continue
        if "Легковые" in name or "Шины" in name:
            return name
    for name in wb.sheetnames:
        if not name.startswith("Спр") and name != "Инструкция":
            return name
    raise ValueError("Не найден лист шаблона в файле автозагрузки")


def _header_map(ws) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for col in range(1, ws.max_column + 1):
        val = ws.cell(HEADER_ROW, col).value
        if val is None:
            continue
        key = str(val).strip()
        if key:
            mapping[key] = col
    return mapping


def _col(headers: dict[str, int], name: str) -> int | None:
    if name in headers:
        return headers[name]
    low = name.lower()
    for k, v in headers.items():
        if k.lower() == low:
            return v
    return None


def build_image_urls(article: str, cfg: AutoloadSettings) -> str:
    if not article or cfg.image_mode != "yandex_disk":
        return ""
    photo_cfg = PhotoNamingSettings(
        yandex_disk_root=cfg.yandex_disk_root,
        image_count=cfg.image_count,
        image_ext=cfg.image_ext,
        photo_layout=getattr(cfg, "photo_layout", "flat"),
    )
    return yandex_disk_urls(article, photo_cfg)


def _format_description(template: str, nomenclature: str) -> str:
    return template.replace("{nomenclature}", nomenclature)


def _quantity_label(qty: str) -> str:
    q = str(qty).strip()
    if not q or q.lower() == "nan":
        return "1"
    try:
        n = int(float(q))
        return str(n) if n > 0 else "1"
    except ValueError:
        return "1"


def load_posting(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="к выкладке")
    return df


def load_avito_ids(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, encoding="utf-8-sig", sep=None, engine="python")
    cols = {str(c).strip().lower(): c for c in df.columns}
    art = cols.get("артикул") or cols.get("article")
    aid = cols.get("avito_id") or cols.get("номер объявления на авито") or cols.get("avito id")
    if not art or not aid:
        return {}
    out = {}
    for _, r in df.iterrows():
        a = str(r[art]).strip()
        i = str(r[aid]).strip()
        if a and i and i.lower() != "nan":
            if a.endswith(".0"):
                a = str(int(float(a)))
            out[a] = i.split(".")[0]
    return out


def fill_autoload_template(
    *,
    template_path: Path,
    posting_df: pd.DataFrame,
    cfg: AutoloadSettings,
    avito_ids: dict[str, str],
    output_path: Path,
) -> dict[str, int]:
    wb = load_workbook(template_path)
    sheet_name = cfg.sheet_name or _find_data_sheet(wb)
    ws = wb[sheet_name]
    headers = _header_map(ws)

    c_id = _col(headers, "Уникальный идентификатор объявления")
    c_avito = _col(headers, "Номер объявления на Авито")
    c_title = _col(headers, "Название объявления")
    c_price = _col(headers, "Цена")
    c_photos = _col(headers, "Ссылки на фото")
    c_desc = _col(headers, "Описание объявления")
    c_qty = _col(headers, "Количество")
    c_brand = _col(headers, "Производитель")
    c_model = _col(headers, "Модель")
    c_w = _col(headers, "Ширина профиля")
    c_p = _col(headers, "Высота профиля")
    c_d = _col(headers, "Диаметр")
    c_li = _col(headers, "Индекс нагрузки")
    c_si = _col(headers, "Индекс скорости")
    c_season = _col(headers, "Сезонность")
    c_run = _col(headers, "Run Flat")
    c_state = _col(headers, "Состояние")

    required = [c_id, c_title, c_price]
    if any(x is None for x in required):
        raise ValueError(f"В шаблоне не найдены обязательные колонки. Есть: {list(headers)[:8]}...")

    # индекс существующих строк
    by_title: dict[str, int] = {}
    by_id: dict[str, int] = {}
    prototype_row: list | None = None
    for row in range(DATA_START_ROW, ws.max_row + 1):
        title_val = ws.cell(row, c_title).value if c_title else None
        id_val = ws.cell(row, c_id).value if c_id else None
        if prototype_row is None and title_val:
            prototype_row = [ws.cell(row, c).value for c in range(1, ws.max_column + 1)]
        if title_val:
            by_title[str(title_val).strip()] = row
        if id_val:
            sid = str(id_val).strip()
            if sid.endswith(".0"):
                sid = str(int(float(sid)))
            by_id[sid] = row

    stats = {"updated": 0, "appended": 0, "skipped": 0}
    next_row = ws.max_row + 1
    if next_row < DATA_START_ROW:
        next_row = DATA_START_ROW

    for _, post in posting_df.iterrows():
        if post.get("дубликат_остаток") is True or str(post.get("дубликат_остаток")).lower() == "true":
            stats["skipped"] += 1
            continue

        nom = str(post.get("номенклатура", "")).strip()
        if not nom:
            stats["skipped"] += 1
            continue

        article = str(post.get("артикул", "")).strip()
        if article.endswith(".0"):
            article = str(int(float(article)))
        price = post.get("recommended_price")
        if pd.isna(price):
            stats["skipped"] += 1
            continue
        price_int = int(round(float(price)))

        photos = build_image_urls(article, cfg)
        if cfg.skip_without_photos and not photos and cfg.image_mode == "yandex_disk":
            stats["skipped"] += 1
            continue

        fields = parse_title_fields(nom)
        qty = _quantity_label(str(post.get("количество", "")))

        row_idx = by_title.get(nom) or (by_id.get(article) if article else None)

        if row_idx is None:
            if prototype_row is None:
                stats["skipped"] += 1
                continue
            row_idx = next_row
            for c in range(1, len(prototype_row) + 1):
                ws.cell(row_idx, c, copy.copy(prototype_row[c - 1]))
            next_row += 1
            stats["appended"] += 1
            if article:
                by_id[article] = row_idx
            by_title[nom] = row_idx
        else:
            stats["updated"] += 1

        ws.cell(row_idx, c_id, article or ws.cell(row_idx, c_id).value)
        if c_avito and article and article in avito_ids:
            ws.cell(row_idx, c_avito, avito_ids[article])
        ws.cell(row_idx, c_title, nom)
        ws.cell(row_idx, c_price, price_int)
        if c_photos and photos:
            ws.cell(row_idx, c_photos, photos)
        if c_desc:
            ws.cell(row_idx, c_desc, _format_description(cfg.description_html, nom))
        if c_qty:
            ws.cell(row_idx, c_qty, qty)
        if c_brand and fields["brand"]:
            ws.cell(row_idx, c_brand, fields["brand"])
        if c_model and fields["model"]:
            ws.cell(row_idx, c_model, fields["model"])
        if c_w and fields["width"]:
            ws.cell(row_idx, c_w, fields["width"])
        if c_p and fields["profile"]:
            ws.cell(row_idx, c_p, fields["profile"])
        if c_d and fields["diameter"]:
            ws.cell(row_idx, c_d, fields["diameter"])
        if c_li and fields["load_index"]:
            ws.cell(row_idx, c_li, fields["load_index"])
        if c_si and fields["speed_index"]:
            ws.cell(row_idx, c_si, fields["speed_index"])
        if c_season and fields["season"]:
            ws.cell(row_idx, c_season, fields["season"])
        if c_run:
            ws.cell(row_idx, c_run, cfg.defaults.get("run_flat", "Нет"))
        if c_state:
            ws.cell(row_idx, c_state, cfg.defaults.get("condition", "Новое"))

        for key, val in cfg.defaults.items():
            col = _col(headers, _DEFAULT_HEADER_ALIASES.get(key, key))
            if col and val and key not in ("run_flat", "condition"):
                current = ws.cell(row_idx, col).value
                if current in (None, ""):
                    ws.cell(row_idx, col, val)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return stats


_DEFAULT_HEADER_ALIASES = {
    "listing_type": "Способ размещения",
    "contact_person": "Контактное лицо",
    "phone": "Номер телефона",
    "address": "Адрес",
    "contact_method": "Способ связи",
    "category": "Категория",
    "goods_type": "Вид товара",
    "ad_type": "Вид объявления",
    "product_type": "Тип товара",
    "merge_ads": "Соединять это объявление с другими объявлениями",
    "free_mounting": "Бесплатный шиномонтаж",
    "company": "Название компании",
    "email": "Почта",
    "audience": "Целевая аудитория",
}
