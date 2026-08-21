"""Разбор полей из названия шины (для автозагрузки)."""

from __future__ import annotations

import re

_SIZE_RE = re.compile(
    r"(\d{2,3})\s*[/\-]\s*(\d{2})\s*[/\-]?\s*R?\s*(\d{2})",
    re.IGNORECASE,
)
_TRAIL_INDEX_RE = re.compile(r"(\d{2,3})\s*([A-Z]{1,2})\s*$", re.IGNORECASE)

# Только значения из справочника Avito (лист Спр-… / Сезонность).
_SEASON_SUMMER = "Летние"
_SEASON_ALL = "Всесезонные"
_SEASON_STUD = "Зимние шипованные"
_SEASON_FRICTION = "Зимние нешипованные"

_SEASON_WORDS = {
    "летн": _SEASON_SUMMER,
    "нешип": _SEASON_FRICTION,
    "шип": _SEASON_STUD,
    "всесез": _SEASON_ALL,
}

_STUD_MARKERS = (
    "шип",
    "шипован",
    "stud",
    "spike",
    "ice zero",
    "icezero",
    "formula ice",
    "ice cruiser",
    "icecruiser",
    "nordman 5",
    "nordman5",
    "nordman 7",
    "nordman7",
    "nordman 8",
    "nordman8",
    "snow cross",
    "snowcross",
    "i*pike",
    "i-pike",
    "i pike",
    "ipike",
    "winter i*pike",
    "winter i-pike",
    "wintercraft ice",
)

_WINTER_MARKERS = (
    "winter",
    "snow",
    "blizzak",
    "hakkapeliitta",
    "hakkapelitta",
    "nordic",
    "arctic",
    "polar",
    "x-ice",
    "xice",
    "ipike",
    "i-pike",
    "icept",
    "ice guard",
    "iceguard",
    "wintercontact",
    "contiwinter",
    "alpin",
    "sno-max",
    "snomax",
    "snowcross",
    "snow cross",
    "wintercraft",
    "ultragrip ice",
    "nordman",
    "frigo",
    "зим",
)

_ALLSEASON_MARKERS = (
    "all-season",
    "all season",
    "allseason",
    "4season",
    "4 season",
    "crossclimate",
    "quatrac",
    "vector 4",
    "vector4",
    "multiseason",
    "weatherproof",
    "all weather",
)

_SUMMER_MARKERS = (
    "summer",
    "ecowing",
    "primacy",
    "efficientgrip",
    "energy saver",
)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def infer_season_from_text(text: str) -> str:
    """Сезонность строго из 4 значений справочника Avito (без голого «Зимние»)."""
    if not text or not str(text).strip():
        return ""

    low = str(text).lower().replace("*", "")

    # Явные русские маркеры (кроме голого «зим» — ниже)
    for key, val in _SEASON_WORDS.items():
        if key in low:
            return val

    if _has_any(low, _ALLSEASON_MARKERS):
        return _SEASON_ALL

    winterish = _has_any(low, _WINTER_MARKERS) or bool(re.search(r"\bice\b", low))
    if winterish:
        if _has_any(low, _STUD_MARKERS):
            return _SEASON_STUD
        return _SEASON_FRICTION

    if _has_any(low, _SUMMER_MARKERS):
        return _SEASON_SUMMER

    return ""


def _find_size_match(title: str) -> re.Match[str] | None:
    match = _SIZE_RE.search(title)
    if match:
        return match
    return _SIZE_RE.search(title.replace(" ", ""))


def _prefix_before_size(title: str, size_m: re.Match[str]) -> str:
    if not size_m:
        return ""
    if size_m.string == title:
        return title[: size_m.start()].strip()

    width, profile, diameter = size_m.group(1), size_m.group(2), size_m.group(3)
    orig = re.search(
        rf"{re.escape(width)}\s*[/\-]\s*{re.escape(profile)}\s*[/\-]?\s*R?\s*{re.escape(diameter)}",
        title,
        re.IGNORECASE,
    )
    if orig:
        return title[: orig.start()].strip()
    return ""


def parse_title_fields(title: str) -> dict[str, str]:
    """Ширина, профиль, диаметр, LI, SI, сезон; бренд/модель — грубо (уточняет tire_catalog)."""
    t = title.strip()
    size_m = _find_size_match(t)
    width = profile = diameter = ""
    if size_m:
        width, profile, diameter = size_m.group(1), size_m.group(2), size_m.group(3)

    load_index = speed_index = ""
    trail = _TRAIL_INDEX_RE.search(t)
    if trail:
        load_index, speed_index = trail.group(1), trail.group(2).upper()

    season = infer_season_from_text(t) or _SEASON_SUMMER

    brand = model = ""
    before = _prefix_before_size(t, size_m) if size_m else ""
    if before:
        parts = before.split()
        if parts:
            brand = parts[0]
            if len(parts) > 1:
                model = " ".join(parts[1:])

    return {
        "brand": brand,
        "model": model,
        "width": width,
        "profile": profile,
        "diameter": diameter,
        "load_index": load_index,
        "speed_index": speed_index,
        "season": season,
    }


def build_multi_name_from_title(title: str) -> str:
    """MultiName: 19565R15."""
    fields = parse_title_fields(title)
    width = str(fields.get("width", "") or "").strip()
    profile = str(fields.get("profile", "") or "").strip()
    diameter = str(fields.get("diameter", "") or "").strip()
    if not (width and profile and diameter):
        return ""
    return f"{width}{profile}R{diameter}"
