"""Генерация XML-фида автозагрузки Avito (formatVersion=3).

Русские заголовки шаблона → английские теги XML по документации Avito.
Публичный фид — XML (listings SQLite → write_ads_xml).
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from avito.title_parse import build_multi_name_from_title

# Поля отчёта Avito / служебные — в фид не пишем
_SKIP_HEADERS = {
    "AvitoStatus",
    "AvitoDateEnd",
    "Статус объявления",
}

# Русский заголовок → XML-тег (английские имена Avito Autoload)
_HEADER_TO_TAG: dict[str, str] = {
    "Уникальный идентификатор объявления": "Id",
    "Номер объявления на Авито": "AvitoId",
    "AvitoId": "AvitoId",
    "Способ размещения": "ListingFee",
    "Контактное лицо": "ManagerName",
    "Номер телефона": "ContactPhone",
    "Адрес": "Address",
    "Способ связи": "ContactMethod",
    "Категория": "Category",
    "Описание объявления": "Description",
    "Ссылки на фото": "Images",
    "Название объявления": "Title",
    "Цена": "Price",
    "Бесплатный шиномонтаж": "FreeTireFitting",
    "Вид товара": "GoodsType",
    "Вид объявления": "AdType",
    "Тип товара": "ProductType",
    "Соединять это объявление с другими объявлениями": "MultiItem",
    "Мультиобъявление": "MultiItem",
    "MultiItem": "MultiItem",
    "Название мультиобъявления": "MultiName",
    "MultiName": "MultiName",
    "Производитель": "Brand",
    "Модель": "Model",
    "Ширина профиля": "TireSectionWidth",
    "Диаметр": "RimDiameter",
    # Avito format: TireAspectRatio (не AspectRatio — иначе 1073 на всех объявлениях)
    "Высота профиля": "TireAspectRatio",
    "Сезонность": "TireType",
    "Индекс нагрузки": "LoadIndex",
    "Количество": "Quantity",
    "Индекс скорости": "SpeedIndex",
    "Run Flat": "RunFlat",
    "Разноширокие": "DifferentWidth",
    "Год выпуска": "ManufactureYear",
    "Состояние": "Condition",
    "Целевая аудитория": "Audience",
    "Почта": "Email",
    "Название компании": "CompanyName",
    # Диски (ProductType=Диски) — официальные теги leaf=diski (user-docs).
    "Тип диска": "RimType",
    "Производитель диска": "RimBrand",
    "Модель диска": "RimModel",
    "Ширина обода": "RimWidth",
    "Количество отверстий": "RimBolts",
    "Диаметр расположения отверстий": "RimBoltsDiameter",
    "Разболтовка": "RimBoltsDiameter",
    "Вылет": "RimOffset",
    "Вылет (ET)": "RimOffset",
    "DIA": "RimDIA",
    "Центральное отверстие (DIA)": "RimDIA",
    "Диаметр ступицы": "RimDIA",
    "TypeID": "TypeId",
    "TypeId": "TypeId",
}

_TAG_ORDER = [
    "Id",
    "AvitoId",
    "ListingFee",
    "ManagerName",
    "ContactPhone",
    "Address",
    "ContactMethod",
    "Category",
    "GoodsType",
    "ProductType",
    "AdType",
    "Title",
    "Description",
    "Price",
    "Images",
    "Brand",
    "Model",
    "TireSectionWidth",
    "TireAspectRatio",
    "RimDiameter",
    "TireType",
    "LoadIndex",
    "SpeedIndex",
    "Quantity",
    "RunFlat",
    "DifferentWidth",
    "ManufactureYear",
    "Condition",
    "RimBrand",
    "RimModel",
    "RimType",
    "RimWidth",
    "RimBolts",
    "RimBoltsDiameter",
    "RimOffset",
    "RimDIA",
    "MultiItem",
    "MultiName",
    "FreeTireFitting",
    "Audience",
    "CompanyName",
    "Email",
    "TypeId",
]


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value).strip()


def _photo_urls(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"\s*\|\s*", raw)
    return [p.strip() for p in parts if p.strip()]


def _xml_text(value: str) -> str:
    return html.escape(value, quote=False)


def _cdata(value: str) -> str:
    # ]]> нельзя внутри одной CDATA-секции
    safe = value.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def _row_to_tags(row: dict[str, Any]) -> dict[str, Any]:
    tag_values: dict[str, Any] = {}
    for header, value in row.items():
        if header in _SKIP_HEADERS:
            continue
        tag = _HEADER_TO_TAG.get(header)
        if not tag and header in _TAG_ORDER:
            tag = header
        if not tag:
            continue
        if tag == "Images":
            urls = _photo_urls(_cell_str(value))
            if urls:
                tag_values[tag] = urls
        else:
            text = _cell_str(value)
            if text:
                tag_values[tag] = text

    # Мультиобъявление: MultiItem без MultiName на Avito не группирует.
    # Если MultiName нет — считаем из Title.
    if not tag_values.get("MultiName"):
        title = tag_values.get("Title") or _cell_str(
            row.get("Название объявления")
        )
        multi = build_multi_name_from_title(title)
        if multi:
            tag_values["MultiName"] = multi
    if tag_values.get("MultiName") and not tag_values.get("MultiItem"):
        tag_values["MultiItem"] = "Да"

    return tag_values


def _format_ad(tag_values: dict[str, Any]) -> list[str]:
    lines = ["  <Ad>"]
    ordered = [t for t in _TAG_ORDER if t in tag_values]
    ordered += [t for t in tag_values if t not in ordered]
    for tag in ordered:
        value = tag_values[tag]
        if tag == "Images":
            lines.append("    <Images>")
            for url in value:
                lines.append(f'      <Image url="{_xml_text(url)}"/>')
            lines.append("    </Images>")
            continue
        if tag == "Description":
            lines.append(f"    <Description>{_cdata(value)}</Description>")
        else:
            lines.append(f"    <{tag}>{_xml_text(value)}</{tag}>")
    lines.append("  </Ad>")
    return lines


def write_ads_xml(rows: list[dict[str, Any]], output_path: Path) -> int:
    """Записать Ads XML. Возвращает число объявлений."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Ads formatVersion="3" target="Avito.ru">',
    ]
    count = 0
    for row in rows:
        tags = _row_to_tags(row)
        if "Id" not in tags and "Title" not in tags:
            continue
        lines.extend(_format_ad(tags))
        count += 1
    lines.append("</Ads>")
    lines.append("")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return count


def rows_from_xlsx(path: Path) -> list[dict[str, Any]]:
    """Удалено: Excel battle path."""
    del path
    raise RuntimeError(
        "rows_from_xlsx удалён. Используйте listings SQLite / write_ads_xml."
    )


def write_ads_xml_from_xlsx(sources: list[Path], output_path: Path) -> int:
    """Удалено: Excel battle path."""
    del sources, output_path
    raise RuntimeError(
        "write_ads_xml_from_xlsx удалён. Используйте write_ads_xml из listings."
    )


def count_ads_in_xml(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        tree = ET.parse(path)
        return len(tree.getroot().findall("Ad"))
    except ET.ParseError:
        return 0
