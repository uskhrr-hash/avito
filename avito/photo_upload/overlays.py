"""SVG-контуры для эталонов и камеры (4 типа кадра)."""
from __future__ import annotations

SHOT_LABELS: dict[int, dict[str, str]] = {
    1: {
        "title": "Стопка шин",
        "short": "стопка",
        "hint": "3 шины лежат, 4-я стоит сверху",
    },
    2: {
        "title": "Протектор крупно",
        "short": "протектор",
        "hint": "Фокус на рисунке протектора",
    },
    3: {
        "title": "Страна производства",
        "short": "страна",
        "hint": "Маркировка страны на боковине",
    },
    4: {
        "title": "Год выпуска (DOT)",
        "short": "год",
        "hint": "Код DOT с годом выпуска",
    },
}

EXAMPLE_FILES: dict[int, str] = {
    1: "static/guide/examples/01-stack.jpg",
    2: "static/guide/examples/02-tread.jpg",
    3: "static/guide/examples/03-country.jpg",
    4: "static/guide/examples/04-dot.jpg",
}

# Кадры с реальным эталоном: в камере — полупрозрачный ghost, не SVG-схема.
REAL_EXAMPLE_SHOTS: frozenset[int] = frozenset({1})


def shot_label(index: int) -> dict[str, str]:
    if index in SHOT_LABELS:
        return SHOT_LABELS[index]
    return {
        "title": f"Доп. фото {index}",
        "short": f"фото {index}",
        "hint": "Снимайте по стандарту магазина",
    }


def overlay_svg_for_shot(index: int, *, camera: bool = False) -> str:
    """Контур поверх кадра. Для реальных эталонов в камере — пусто (используется ghost)."""
    if camera and index in REAL_EXAMPLE_SHOTS:
        return ""
    opacity = "0.92" if camera else "1"
    if index == 1:
        return _svg_stack(opacity=opacity, camera=camera)
    if index == 2:
        return _svg_tread(opacity=opacity)
    if index == 3:
        return _svg_country(opacity=opacity)
    if index == 4:
        return _svg_dot(opacity=opacity)
    return _svg_generic(opacity=opacity)


def ghost_image_for_shot(index: int) -> str:
    """URL полупрозрачного эталона для выравнивания в камере."""
    if index in REAL_EXAMPLE_SHOTS:
        return EXAMPLE_FILES.get(index, "")
    return ""


def _svg_stack(*, opacity: str, camera: bool = False) -> str:
    """Портретный контур: 3 шины лежат внизу, 4-я стоит вертикально."""
    if camera:
        return f"""<svg viewBox="0 0 100 100" class="guide-svg camera-overlay-svg" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="vignette" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#000" stop-opacity="0.15"/>
      <stop offset="100%" stop-color="#000" stop-opacity="0.35"/>
    </linearGradient>
  </defs>
  <rect width="100" height="100" fill="url(#vignette)"/>
  <!-- 3 шины лежат (стопка сбоку) -->
  <ellipse cx="50" cy="86" rx="34" ry="5.5" fill="none" stroke="#93c5fd" stroke-width="0.55"/>
  <ellipse cx="50" cy="81" rx="33" ry="5" fill="none" stroke="#93c5fd" stroke-width="0.55"/>
  <ellipse cx="50" cy="76" rx="32" ry="4.8" fill="none" stroke="#93c5fd" stroke-width="0.55"/>
  <path d="M18 76 Q18 88 50 88 Q82 88 82 76" fill="none" stroke="#60a5fa" stroke-width="0.45" stroke-dasharray="2 1.5"/>
  <!-- 4-я шина стоит вертикально -->
  <ellipse cx="50" cy="30" rx="28" ry="8.5" fill="none" stroke="#2563eb" stroke-width="0.75"/>
  <path d="M22 30 Q22 72 50 74 Q78 72 78 30" fill="none" stroke="#2563eb" stroke-width="0.75"/>
  <ellipse cx="50" cy="73" rx="28" ry="7.5" fill="none" stroke="#2563eb" stroke-width="0.75"/>
  <rect x="20" y="22" width="60" height="56" rx="4" fill="none" stroke="#fff" stroke-width="0.5" stroke-dasharray="3 2" opacity="0.9"/>
  <text x="50" y="10" text-anchor="middle" font-size="4.2" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">3 лежат + 1 сверху</text>
</svg>"""
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect width="320" height="220" fill="none"/>
  <rect x="8" y="8" width="304" height="204" rx="12" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="10 8" opacity="0.85"/>
  <ellipse cx="72" cy="168" rx="46" ry="14" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <ellipse cx="72" cy="152" rx="46" ry="14" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <ellipse cx="160" cy="168" rx="46" ry="14" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <ellipse cx="160" cy="152" rx="46" ry="14" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <ellipse cx="248" cy="168" rx="46" ry="14" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <ellipse cx="248" cy="152" rx="46" ry="14" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <g transform="translate(160 78) rotate(-8)">
    <ellipse cx="0" cy="42" rx="46" ry="14" fill="none" stroke="#60a5fa" stroke-width="3"/>
    <rect x="-46" y="-18" width="92" height="58" rx="8" fill="none" stroke="#2563eb" stroke-width="4"/>
    <ellipse cx="0" cy="-18" rx="46" ry="14" fill="none" stroke="#2563eb" stroke-width="4"/>
  </g>
  <text x="160" y="28" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">3 лежат + 1 сверху</text>
</svg>"""


def _svg_tread(*, opacity: str) -> str:
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect width="320" height="220" fill="none"/>
  <rect x="8" y="8" width="304" height="204" rx="12" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="10 8" opacity="0.85"/>
  <ellipse cx="160" cy="178" rx="88" ry="22" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <path d="M72 178 C72 92, 248 92, 248 178 Z" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <rect x="98" y="98" width="124" height="62" rx="8" fill="none" stroke="#4ade80" stroke-width="4" stroke-dasharray="8 6"/>
  <text x="160" y="36" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Протектор в рамке</text>
</svg>"""


def _svg_country(*, opacity: str) -> str:
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect width="320" height="220" fill="none"/>
  <rect x="8" y="8" width="304" height="204" rx="12" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="10 8" opacity="0.85"/>
  <rect x="108" y="24" width="104" height="172" rx="52" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <rect x="124" y="72" width="72" height="36" rx="6" fill="none" stroke="#fb923c" stroke-width="4"/>
  <text x="160" y="36" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Страна в оранжевой рамке</text>
</svg>"""


def _svg_dot(*, opacity: str) -> str:
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect width="320" height="220" fill="none"/>
  <rect x="8" y="8" width="304" height="204" rx="12" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="10 8" opacity="0.85"/>
  <rect x="108" y="24" width="104" height="172" rx="52" fill="none" stroke="#93c5fd" stroke-width="3"/>
  <rect x="118" y="118" width="84" height="44" rx="6" fill="none" stroke="#60a5fa" stroke-width="4"/>
  <text x="160" y="36" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">DOT / год в синей рамке</text>
</svg>"""


def _svg_generic(*, opacity: str) -> str:
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect x="24" y="24" width="272" height="172" rx="12" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="10 8"/>
  <text x="160" y="118" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Держите шину в рамке</text>
</svg>"""
