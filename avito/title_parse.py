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


def parse_title_fields(title: str) -> dict[str, str]:
    """Ширина, профиль, диаметр, LI, SI, сезон; бренд/модель — грубо."""
    t = title.strip()
    size_m = _SIZE_RE.search(t.replace(" ", "")) or _SIZE_RE.search(t)
    width = profile = diameter = ""
    if size_m:
        width, profile, diameter = size_m.group(1), size_m.group(2), size_m.group(3)

    load_index = speed_index = ""
    trail = _TRAIL_INDEX_RE.search(t)
    if trail:
        load_index, speed_index = trail.group(1), trail.group(2).upper()

    season = ""
    low = t.lower()
    for key, val in _SEASON_WORDS.items():
        if key in low:
            season = val
            break
    if not season:
        season = "Летние"

    brand = model = ""
    if size_m:
        before = t[: size_m.start()].strip()
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
