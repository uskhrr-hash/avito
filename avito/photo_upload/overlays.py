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
        "hint": "Совместите шину с контуром — протектор крупно",
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

# Базовая форма шины (вариант B): лежащая 72×21, стоящая 21×72.
LYING_W, LYING_H, LYING_RX = 72, 21, 5
VERT_W, VERT_H, VERT_RX = 21, 72, 5


def shot_label(index: int) -> dict[str, str]:
    if index in SHOT_LABELS:
        return SHOT_LABELS[index]
    return {
        "title": f"Доп. фото {index}",
        "short": f"фото {index}",
        "hint": "Снимайте по стандарту магазина",
    }


def overlay_svg_for_shot(index: int, *, camera: bool = False) -> str:
    """Контур поверх кадра (камера и страница-гайд)."""
    opacity = "0.92" if camera else "1"
    if index == 1:
        return _svg_stack(opacity=opacity, camera=camera)
    if index == 2:
        return _svg_tread(opacity=opacity, camera=camera)
    if index == 3:
        return _svg_country(opacity=opacity, camera=camera)
    if index == 4:
        return _svg_dot(opacity=opacity, camera=camera)
    return _svg_generic(opacity=opacity)


def ghost_image_for_shot(_index: int) -> str:
    """Зарезервировано; ghost-наложение отключено — только SVG."""
    return ""


def _camera_svg_header() -> str:
    return (
        '<svg viewBox="0 0 100 160" class="guide-svg camera-overlay-svg" '
        'preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">'
    )


def _lying_tire(
    x: float,
    y: float,
    *,
    w: float = LYING_W,
    h: float = LYING_H,
    rx: float = LYING_RX,
    stroke: str,
    sw: float = 0.9,
    lsw: float = 0.45,
) -> str:
    line_inset = 8
    line1 = y + h * 7 / 21
    line2 = y + h * 14 / 21
    return f"""  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="none" stroke="{stroke}" stroke-width="{sw}"/>
  <line x1="{x + line_inset}" y1="{line1}" x2="{x + w - line_inset}" y2="{line1}" stroke="{stroke}" stroke-width="{lsw}"/>
  <line x1="{x + line_inset}" y1="{line2}" x2="{x + w - line_inset}" y2="{line2}" stroke="{stroke}" stroke-width="{lsw}"/>"""


def _vertical_tire(
    x: float,
    y: float,
    *,
    w: float = VERT_W,
    h: float = VERT_H,
    rx: float = VERT_RX,
    stroke: str,
    sw: float = 1,
    lsw: float = 0.5,
) -> str:
    lx1 = x + w * 6.5 / 21
    lx2 = x + w * 14.5 / 21
    ly1 = y + h * 8 / 72
    ly2 = y + h * 64 / 72
    return f"""  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="none" stroke="{stroke}" stroke-width="{sw}"/>
  <line x1="{lx1}" y1="{ly1}" x2="{lx1}" y2="{ly2}" stroke="{stroke}" stroke-width="{lsw}"/>
  <line x1="{lx2}" y1="{ly1}" x2="{lx2}" y2="{ly2}" stroke="{stroke}" stroke-width="{lsw}"/>"""


def _svg_stack(*, opacity: str, camera: bool = False) -> str:
    """3 шины лежат друг на друге (72×21), 4-я стоит вертикально (21×72)."""
    if camera:
        lying_x = 14
        stack = "\n".join(
            _lying_tire(lying_x, y, stroke="#60a5fa")
            for y in (97, 118, 139)
        )
        vertical = _vertical_tire(39.5, 25, stroke="#2563eb")
        return f"""{_camera_svg_header()}
  <text x="50" y="12" text-anchor="middle" fill="#fff" font-size="5" font-family="system-ui,sans-serif" font-weight="700">3 лежат + 1 стоит</text>
{stack}
{vertical}
</svg>"""

    scale = 3.2
    lying_x = 14 * scale
    lying_w = LYING_W * scale
    lying_h = LYING_H * scale
    lying_rx = LYING_RX * scale
    vert_w = VERT_W * scale
    vert_h = VERT_H * scale
    vert_rx = VERT_RX * scale
    vert_x = (320 - vert_w) / 2
    stack = "\n".join(
        _lying_tire(
            lying_x,
            y * scale,
            w=lying_w,
            h=lying_h,
            rx=lying_rx,
            stroke="#60a5fa",
            sw=2.8,
            lsw=1.4,
        )
        for y in (97, 118, 139)
    )
    vertical = _vertical_tire(
        vert_x,
        25 * scale,
        w=vert_w,
        h=vert_h,
        rx=vert_rx,
        stroke="#2563eb",
        sw=3.2,
        lsw=1.6,
    )
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect width="320" height="220" fill="none"/>
{stack}
{vertical}
  <text x="160" y="28" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">3 лежат + 1 стоит</text>
</svg>"""


def _svg_tread(*, opacity: str, camera: bool = False) -> str:
    """Одна стоящая шина — та же форма, увеличенная для крупного протектора."""
    if camera:
        # ~1.55× от стоящей в стопке: 33×112, по центру кадра
        w, h, rx = 33, 112, 8
        x = (100 - w) / 2
        y = (160 - h) / 2
        tire = _vertical_tire(x, y, w=w, h=h, rx=rx, stroke="#2563eb", sw=1.1, lsw=0.55)
        return f"""{_camera_svg_header()}
  <text x="50" y="12" text-anchor="middle" fill="#fff" font-size="5" font-family="system-ui,sans-serif" font-weight="700">Протектор крупно</text>
{tire}
</svg>"""

    w, h, rx = 33 * 3.2, 112 * 3.2, 8 * 3.2
    x = (320 - w) / 2
    y = (220 - h) / 2
    tire = _vertical_tire(x, y, w=w, h=h, rx=rx, stroke="#2563eb", sw=3.5, lsw=1.8)
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect width="320" height="220" fill="none"/>
{tire}
  <text x="160" y="28" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Протектор крупно</text>
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
