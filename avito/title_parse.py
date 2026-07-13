"""Разбор полей из названия шины (для автозагрузки)."""

from __future__ import annotations



import re



_SIZE_RE = re.compile(

    r"(\d{2,3})\s*[/\-]\s*(\d{2})\s*[/\-]?\s*R?\s*(\d{2})",

    re.IGNORECASE,

)

_TRAIL_INDEX_RE = re.compile(r"(\d{2,3})\s*([A-Z]{1,2})\s*$", re.IGNORECASE)

_SEASON_WORDS = {
    "летн": "Летние",
    "зим": "Зимние",
    "шип": "Зимние шипованные",
    "нешип": "Зимние нешипованные",
    "всесез": "Всесезонные",
}

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
    "i*pike",
    "icept",
    "ice guard",
    "iceguard",
    "wintercontact",
    "contiwinter",
    "alpin",
    "stud",
    "spike",
    "sno-max",
    "snomax",
    "snowcross",
    "snow cross",
    "ice zero",
    "icezero",
    "wintercraft",
    "ice cruiser",
    "icecruiser",
    "ultragrip ice",
    "nordman",
    "frigo",
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


def infer_season_from_text(text: str) -> str:
    """Сезонность по названию/фактам: русские и английские маркеры модели."""
    if not text or not str(text).strip():
        return ""

    low = str(text).lower().replace("*", "")

    for key, val in _SEASON_WORDS.items():
        if key in low:
            return val

    for marker in _ALLSEASON_MARKERS:
        if marker in low:
            return "Всесезонные"

    for marker in _WINTER_MARKERS:
        if marker in low:
            if "шип" in low or "stud" in low or "spike" in low or "шипован" in low:
                return "Зимние шипованные"
            if "нешип" in low or "friction" in low or "friktion" in low:
                return "Зимние нешипованные"
            return "Зимние"

    for marker in _SUMMER_MARKERS:
        if marker in low:
            return "Летние"

    # «Ice» отдельно — частый зимний маркер (X-Ice уже выше)
    if re.search(r"\bice\b", low):
        return "Зимние"

    return ""



def _find_size_match(title: str) -> re.Match[str] | None:

    """Размер ищем в исходной строке; без пробелов — только для размеров."""

    match = _SIZE_RE.search(title)

    if match:

        return match

    return _SIZE_RE.search(title.replace(" ", ""))





def _prefix_before_size(title: str, size_m: re.Match[str]) -> str:

    """

    Текст до размера в исходном названии.



    Нельзя брать size_m.start() из строки без пробелов — иначе G015 → G0.

    """

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

    """Ширина, профиль, диаметр, LI, SI, сезон; бренд/модель — грубо."""

    t = title.strip()

    size_m = _find_size_match(t)

    width = profile = diameter = ""

    if size_m:

        width, profile, diameter = size_m.group(1), size_m.group(2), size_m.group(3)



    load_index = speed_index = ""

    trail = _TRAIL_INDEX_RE.search(t)

    if trail:

        load_index, speed_index = trail.group(1), trail.group(2).upper()



    season = infer_season_from_text(t)
    if not season:
        season = "Летние"



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
    """
    MultiName для мультиобъявлений Авито — группировка по размеру.

    Формат без спецсимволов: 19565R15 (ширина + профиль + R + диаметр).
    """
    fields = parse_title_fields(title)
    width = str(fields.get("width", "") or "").strip()
    profile = str(fields.get("profile", "") or "").strip()
    diameter = str(fields.get("diameter", "") or "").strip()
    if not (width and profile and diameter):
        return ""
    return f"{width}{profile}R{diameter}"

