"""Маппинг параметров дисков ERP → поля Avito (Диски)."""
from __future__ import annotations

import re
from typing import Any

# ERP model/brand params.type → подпись для Avito «Тип диска» (RimType)
# Официальные значения: Кованые, Литые, Штампованные, Спицованные, Сборные, Карбоновые
WHEEL_TYPE_AVITO: dict[str, str] = {
    "1": "Штампованные",
    "2": "Литые",
    "3": "Кованые",
}

# Русские заголовки Excel-шаблона (labels из user-docs leaf=diski)
AVITO_WHEEL_HEADERS = {
    "disk_type": "Тип диска",
    "brand": "Производитель диска",
    "model": "Модель диска",
    "rim_width": "Ширина обода",
    "rim_diameter": "Диаметр",
    "bolt_count": "Количество отверстий",
    "pcd": "Диаметр расположения отверстий",
    "offset": "Вылет (ET)",
    "dia": "Центральное отверстие (DIA)",
}

# Английские теги XML formatVersion=3 (официальный API autoload leaf=diski)
AVITO_WHEEL_XML_TAGS = {
    "disk_type": "RimType",
    "brand": "RimBrand",
    "model": "RimModel",
    "rim_width": "RimWidth",
    "rim_diameter": "RimDiameter",
    "bolt_count": "RimBolts",
    "pcd": "RimBoltsDiameter",
    "offset": "RimOffset",
    "dia": "RimDIA",
}

PRODUCT_TYPE_WHEELS = "Диски"
PRODUCT_TYPE_TIRES = "Шины"

# Размер в названии: 6,5x16 5x112 ET46 57,1
_WHEEL_SIZE_RE = re.compile(
    r"(?P<width>\d+(?:[.,]\d+)?)\s*[xх]\s*(?P<diameter>\d+(?:[.,]\d+)?)"
    r"\s+(?P<studs>\d+)\s*[xх]\s*(?P<circle>\d+(?:[.,]\d+)?)"
    r"(?:\s*ET\s*(?P<et>-?\d+(?:[.,]\d+)?))?"
    r"(?:\s+(?P<hub>\d+(?:[.,]\d+)?))?",
    re.IGNORECASE,
)


def _fmt_num(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip().replace(",", ".")
    if not s or s.lower() in ("nan", "none"):
        return ""
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
        # Avito часто ждёт 6.5 / 114.3
        return f"{f:g}"
    except ValueError:
        return s.replace(".", ",")


def wheel_type_label(erp_type: str | int | None) -> str:
    key = str(erp_type or "").strip()
    return WHEEL_TYPE_AVITO.get(key, "")


def parse_wheel_title_fallback(title: str) -> dict[str, str]:
    """Грубый разбор из номенклатуры, если params нет."""
    t = str(title or "").strip()
    out = {
        "brand": "",
        "model": "",
        "rim_width": "",
        "rim_diameter": "",
        "bolt_count": "",
        "pcd": "",
        "offset": "",
        "dia": "",
        "disk_type": "",
    }
    m = _WHEEL_SIZE_RE.search(t)
    if not m:
        return out
    out["rim_width"] = _fmt_num(m.group("width"))
    out["rim_diameter"] = _fmt_num(m.group("diameter"))
    out["bolt_count"] = _fmt_num(m.group("studs"))
    out["pcd"] = _fmt_num(m.group("circle"))
    if m.group("et") is not None:
        out["offset"] = _fmt_num(m.group("et"))
    if m.group("hub") is not None:
        out["dia"] = _fmt_num(m.group("hub"))
    prefix = t[: m.start()].strip()
    if prefix:
        parts = prefix.split()
        out["brand"] = parts[0]
        out["model"] = " ".join(parts[1:]) if len(parts) > 1 else ""
    return out


def map_wheel_fields(
    *,
    brand: str = "",
    model: str = "",
    wheel_type: str = "",
    width: str = "",
    diameter: str = "",
    studs: str = "",
    circle: str = "",
    et: str = "",
    hub: str = "",
    title: str = "",
) -> dict[str, str]:
    """
    Поля для автозагрузки диска.

    Возвращает ключи: brand, model, disk_type, rim_width, rim_diameter,
    bolt_count, pcd, offset, dia, product_type.
    """
    fallback = parse_wheel_title_fallback(title) if title else {}
    rim_width = _fmt_num(width) or fallback.get("rim_width", "")
    rim_diameter = _fmt_num(diameter) or fallback.get("rim_diameter", "")
    bolt_count = _fmt_num(studs) or fallback.get("bolt_count", "")
    pcd = _fmt_num(circle) or fallback.get("pcd", "")
    offset = _fmt_num(et) or fallback.get("offset", "")
    dia = _fmt_num(hub) or fallback.get("dia", "")
    disk_type = wheel_type_label(wheel_type) or fallback.get("disk_type", "")
    brand_s = str(brand or "").strip() or fallback.get("brand", "")
    model_s = str(model or "").strip() or fallback.get("model", "")
    return {
        "brand": brand_s,
        "model": model_s,
        "disk_type": disk_type,
        "rim_width": rim_width,
        "rim_diameter": rim_diameter,
        "bolt_count": bolt_count,
        "pcd": pcd,
        "offset": offset,
        "dia": dia,
        "product_type": PRODUCT_TYPE_WHEELS,
    }


def is_wheel_kind(value: Any) -> bool:
    s = str(value or "").strip().lower()
    return s in ("wheel", "wheels", "диск", "диски", "disk", "disks")


def is_tire_kind(value: Any) -> bool:
    s = str(value or "").strip().lower()
    if not s:
        return True
    return s in ("tire", "tires", "tyre", "tyres", "шина", "шины")
