"""SVG-контуры для эталонов и камеры (4 типа кадра)."""
from __future__ import annotations

import math

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

WHEEL_SHOT_LABELS: dict[int, dict[str, str]] = {
    1: {
        "title": "Диск лицом",
        "short": "лицо",
        "hint": "Диск лицом к камере, весь обод в кадре",
    },
    2: {
        "title": "Профиль / вылет",
        "short": "профиль",
        "hint": "Сбоку — видно глубину и вылет",
    },
    3: {
        "title": "Крепёж / ступица",
        "short": "крепы",
        "hint": "Отверстия и центральное отверстие крупно",
    },
    4: {
        "title": "Маркировка",
        "short": "марка",
        "hint": "Размер, ET, PCD на диске или бирке",
    },
}

EXAMPLE_FILES: dict[int, str] = {
    1: "static/guide/examples/01-stack.jpg",
    2: "static/guide/examples/02-tread.jpg",
    3: "static/guide/examples/03-country.jpg",
    4: "static/guide/examples/04-dot.jpg",
}

# Пока снимаем только лицо диска (1 фото на артикул).
WHEEL_EXAMPLE_FILES: dict[int, str] = {
    1: "static/guide/examples/wheels/01-face.jpg",
}


def example_url_for_shot(index: int, *, product_kind: str = "tire") -> str:
    kind = str(product_kind).lower()
    if kind in ("wheel", "wheels", "диск", "диски"):
        return WHEEL_EXAMPLE_FILES.get(index, "")
    return EXAMPLE_FILES.get(index, "")

# Базовая форма шины (вариант B): лежащая 72×21, стоящая 21×72.
# Боковина — кольцо (два круга).
LYING_W, LYING_H, LYING_RX = 72, 21, 5
VERT_W, VERT_H, VERT_RX = 21, 72, 5
SIDE_CX, SIDE_CY = 50, 90
SIDE_R_OUT, SIDE_R_IN = 38, 24
# Крупный план боковины: дуги кольца, центр круга ниже кадра.
ZOOM_CX, ZOOM_CY = 50, 112
ZOOM_R_OUT, ZOOM_R_IN = 72, 54
ZOOM_ARC_A1, ZOOM_ARC_A2 = 228, 312


def shot_label(index: int, *, product_kind: str = "tire") -> dict[str, str]:
    labels = WHEEL_SHOT_LABELS if str(product_kind).lower() in (
        "wheel",
        "wheels",
        "диск",
        "диски",
    ) else SHOT_LABELS
    if index in labels:
        return labels[index]
    return {
        "title": f"Доп. фото {index}",
        "short": f"фото {index}",
        "hint": "Снимайте по стандарту магазина",
    }


def overlay_svg_for_shot(
    index: int, *, camera: bool = False, product_kind: str = "tire"
) -> str:
    """Контур поверх кадра (камера и страница-гайд)."""
    opacity = "0.92" if camera else "1"
    is_wheel = str(product_kind).lower() in ("wheel", "wheels", "диск", "диски")
    if is_wheel:
        if index == 1:
            return _svg_wheel_face(opacity=opacity, camera=camera)
        if index == 2:
            return _svg_wheel_profile(opacity=opacity, camera=camera)
        if index == 3:
            return _svg_wheel_hub(opacity=opacity, camera=camera)
        if index == 4:
            return _svg_wheel_mark(opacity=opacity, camera=camera)
        return _svg_generic(opacity=opacity, camera=camera)
    if index == 1:
        return _svg_stack(opacity=opacity, camera=camera)
    if index == 2:
        return _svg_tread(opacity=opacity, camera=camera)
    if index == 3:
        return _svg_country(opacity=opacity, camera=camera)
    if index == 4:
        return _svg_dot(opacity=opacity, camera=camera)
    return _svg_generic(opacity=opacity, camera=camera)


def ghost_image_for_shot(_index: int) -> str:
    """Зарезервировано; ghost-наложение отключено — только SVG."""
    return ""


def _camera_svg_header() -> str:
    # Как object-fit:cover у <video> — один режим для шин и дисков.
    return (
        '<svg viewBox="0 0 100 160" class="guide-svg camera-overlay-svg" '
        'preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">'
    )


# Один режим slice; масштабы разные — шины чуть меньше, диски чуть крупнее.
TIRE_CAMERA_SCALE = 0.68
WHEEL_CAMERA_SCALE = 0.90


def _camera_scaled_svg(title: str, body: str, *, scale: float) -> str:
    return f"""{_camera_svg_header()}
  <text x="50" y="12" text-anchor="middle" fill="#fff" font-size="5" font-family="system-ui,sans-serif" font-weight="700">{title}</text>
  <g transform="translate(50 84) scale({scale}) translate(-50 -84)">
{body}
  </g>
</svg>"""



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


def _sidewall_zoom_arcs(
    cx: float,
    cy: float,
    *,
    r_out: float = ZOOM_R_OUT,
    r_in: float = ZOOM_R_IN,
    stroke: str,
    sw: float = 1,
    a1: float = ZOOM_ARC_A1,
    a2: float = ZOOM_ARC_A2,
) -> str:
    """Крупный план: верхние дуги двух концентрических кругов."""

    def _arc(r: float) -> str:
        rad1 = math.radians(a1)
        rad2 = math.radians(a2)
        x1 = cx + r * math.cos(rad1)
        y1 = cy + r * math.sin(rad1)
        x2 = cx + r * math.cos(rad2)
        y2 = cy + r * math.sin(rad2)
        return f"M {x1:.2f} {y1:.2f} A {r} {r} 0 0 1 {x2:.2f} {y2:.2f}"

    return f"""  <path d="{_arc(r_out)}" fill="none" stroke="{stroke}" stroke-width="{sw}"/>
  <path d="{_arc(r_in)}" fill="none" stroke="{stroke}" stroke-width="{sw}"/>"""


def _capsule_cy_in_top_band(cy: float, r_out: float, r_in: float, h: float) -> float:
    """Y центра капсулы — строго между дугами наверху (внутри боковины)."""
    y_outer = cy - r_out
    band = r_out - r_in
    return y_outer + (band - h) / 2 + h / 2 + 2


def _zoom_label_capsule(
    cx: float,
    cy: float,
    *,
    w: float,
    h: float,
    stroke: str,
    text: str,
    sw: float = 0.9,
    font_size: float = 4,
) -> str:
    """Капсула с текстом на верхней дуге (крупный план)."""
    x = cx - w / 2
    y = cy - h / 2
    rx = h / 2
    text_y = cy + font_size * 0.32
    return f"""  <rect x="{x:.2f}" y="{y:.2f}" width="{w}" height="{h}" rx="{rx}" fill="none" stroke="{stroke}" stroke-width="{sw}"/>
  <text x="{cx}" y="{text_y:.2f}" text-anchor="middle" fill="{stroke}" font-size="{font_size}" font-family="system-ui,sans-serif" font-weight="700">{text}</text>"""


def _sidewall_marking_overlay(
    *,
    title: str,
    capsule_text: str,
    capsule_stroke: str,
    camera: bool,
) -> str:
    """Крупный план боковины: дуги + капсула внутри полосы наверху."""
    capsule_h = 10
    label_cy = _capsule_cy_in_top_band(ZOOM_CY, ZOOM_R_OUT, ZOOM_R_IN, capsule_h)
    arcs = _sidewall_zoom_arcs(ZOOM_CX, ZOOM_CY, stroke="#2563eb", sw=1)
    capsule_w = 42 if len(capsule_text) > 6 else 34
    capsule = _zoom_label_capsule(
        ZOOM_CX,
        label_cy,
        w=capsule_w,
        h=capsule_h,
        stroke=capsule_stroke,
        text=capsule_text,
        font_size=3.6,
    )
    if camera:
        return _camera_scaled_svg(
            title,
            f"""{arcs}
{capsule}""",
            scale=TIRE_CAMERA_SCALE,
        )

    scale = 2.2
    cx, cy = 160, 130
    capsule_h = 10 * scale
    label_cy = _capsule_cy_in_top_band(cy, ZOOM_R_OUT * scale, ZOOM_R_IN * scale, capsule_h)
    arcs = _sidewall_zoom_arcs(
        cx, cy,
        r_out=ZOOM_R_OUT * scale, r_in=ZOOM_R_IN * scale,
        stroke="#2563eb", sw=2.5,
    )
    capsule = _zoom_label_capsule(
        cx,
        label_cy,
        w=capsule_w * scale,
        h=capsule_h,
        stroke=capsule_stroke,
        text=capsule_text,
        sw=2,
        font_size=8,
    )
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:1">
  <rect width="320" height="220" fill="none"/>
{arcs}
{capsule}
  <text x="160" y="28" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">{title}</text>
</svg>"""


def _svg_stack(*, opacity: str, camera: bool = False) -> str:
    """3 шины лежат друг на друге (72×21), 4-я стоит вертикально (21×72)."""
    if camera:
        lying_x = 14
        stack = "\n".join(
            _lying_tire(lying_x, y, stroke="#60a5fa")
            for y in (97, 118, 139)
        )
        vertical = _vertical_tire(39.5, 25, stroke="#2563eb")
        return _camera_scaled_svg(
            "3 лежат + 1 стоит",
            f"""{stack}
{vertical}""",
            scale=TIRE_CAMERA_SCALE,
        )

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
        return _camera_scaled_svg("Протектор крупно", tire, scale=TIRE_CAMERA_SCALE)

    w, h, rx = 33 * 3.2, 112 * 3.2, 8 * 3.2
    x = (320 - w) / 2
    y = (220 - h) / 2
    tire = _vertical_tire(x, y, w=w, h=h, rx=rx, stroke="#2563eb", sw=3.5, lsw=1.8)
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect width="320" height="220" fill="none"/>
{tire}
  <text x="160" y="28" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Протектор крупно</text>
</svg>"""


def _svg_country(*, opacity: str, camera: bool = False) -> str:
    """Крупный план боковины, капсула «СТРАНА»."""
    svg = _sidewall_marking_overlay(
        title="Страна производства",
        capsule_text="СТРАНА",
        capsule_stroke="#fb923c",
        camera=camera,
    )
    if camera:
        return svg
    return svg.replace('style="opacity:1"', f'style="opacity:{opacity}"')


def _svg_dot(*, opacity: str, camera: bool = False) -> str:
    """Крупный план боковины, капсула «DOT 1526» (как на скетче)."""
    svg = _sidewall_marking_overlay(
        title="Год выпуска (DOT)",
        capsule_text="DOT 1526",
        capsule_stroke="#60a5fa",
        camera=camera,
    )
    if camera:
        return svg
    return svg.replace('style="opacity:1"', f'style="opacity:{opacity}"')


def _svg_wheel_face(*, opacity: str, camera: bool = False) -> str:
    """Лицо диска: по реальным кадрам (480×640) диск ≈ на всю ширину."""
    cx, cy = 50.0, 82.0
    r_out, r_hub, r_pcd, r_bolt = 46.0, 11.0, 17.0, 2.6
    bolts = []
    for i in range(5):
        ang = math.radians(-90.0 + i * 72.0)
        bx = cx + r_pcd * math.cos(ang)
        by = cy + r_pcd * math.sin(ang)
        bolts.append(
            f'  <circle cx="{bx:.1f}" cy="{by:.1f}" r="{r_bolt}" '
            f'fill="none" stroke="#93c5fd" stroke-width="0.9"/>'
        )
    bolts_svg = "\n".join(bolts)
    if camera:
        return _camera_scaled_svg(
            "Диск лицом",
            f"""  <circle cx="{cx}" cy="{cy}" r="{r_out}" fill="none" stroke="#2563eb" stroke-width="1.4"/>
  <circle cx="{cx}" cy="{cy}" r="{r_out - 2.2}" fill="none" stroke="#60a5fa" stroke-width="0.7" stroke-dasharray="2.5 2"/>
  <circle cx="{cx}" cy="{cy}" r="{r_hub}" fill="none" stroke="#2563eb" stroke-width="1.1"/>
{bolts_svg}""",
            scale=WHEEL_CAMERA_SCALE,
        )
    # Гайд (landscape preview)
    sx, sy = 160.0, 118.0
    s = 2.0
    g_bolts = []
    for i in range(5):
        ang = math.radians(-90.0 + i * 72.0)
        bx = sx + r_pcd * s * math.cos(ang)
        by = sy + r_pcd * s * math.sin(ang)
        g_bolts.append(
            f'  <circle cx="{bx:.1f}" cy="{by:.1f}" r="{r_bolt * s:.1f}" '
            f'fill="none" stroke="#93c5fd" stroke-width="2"/>'
        )
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <circle cx="{sx}" cy="{sy}" r="{r_out * s}" fill="none" stroke="#2563eb" stroke-width="3"/>
  <circle cx="{sx}" cy="{sy}" r="{r_hub * s}" fill="none" stroke="#2563eb" stroke-width="2.5"/>
{chr(10).join(g_bolts)}
  <text x="160" y="28" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Диск лицом</text>
</svg>"""


def _svg_wheel_profile(*, opacity: str, camera: bool = False) -> str:
    if camera:
        return _camera_scaled_svg(
            "Профиль / вылет",
            """  <ellipse cx="50" cy="82" rx="16" ry="46" fill="none" stroke="#2563eb" stroke-width="1.3"/>
  <line x1="34" y1="44" x2="66" y2="44" stroke="#93c5fd" stroke-width="0.8"/>
  <line x1="34" y1="120" x2="66" y2="120" stroke="#93c5fd" stroke-width="0.8"/>""",
            scale=WHEEL_CAMERA_SCALE,
        )
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <ellipse cx="160" cy="120" rx="40" ry="96" fill="none" stroke="#2563eb" stroke-width="3"/>
  <text x="160" y="28" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Профиль / вылет</text>
</svg>"""


def _svg_wheel_hub(*, opacity: str, camera: bool = False) -> str:
    """Крепёж крупно: обод почти на всю ширину, ступица и PCD в кадре."""
    cx, cy = 50.0, 82.0
    r_out, r_hub, r_pcd, r_bolt = 48.0, 14.0, 22.0, 3.6
    bolts = []
    for i in range(5):
        ang = math.radians(-90.0 + i * 72.0)
        bx = cx + r_pcd * math.cos(ang)
        by = cy + r_pcd * math.sin(ang)
        bolts.append(
            f'  <circle cx="{bx:.1f}" cy="{by:.1f}" r="{r_bolt}" '
            f'fill="none" stroke="#fb923c" stroke-width="1.1"/>'
        )
    bolts_svg = "\n".join(bolts)
    if camera:
        return _camera_scaled_svg(
            "Крепёж / ступица",
            f"""  <circle cx="{cx}" cy="{cy}" r="{r_out}" fill="none" stroke="#2563eb" stroke-width="1.3"/>
  <circle cx="{cx}" cy="{cy}" r="{r_hub}" fill="none" stroke="#2563eb" stroke-width="1.2"/>
{bolts_svg}""",
            scale=WHEEL_CAMERA_SCALE,
        )
    sx, sy, s = 160.0, 118.0, 1.7
    g_bolts = []
    for i in range(5):
        ang = math.radians(-90.0 + i * 72.0)
        bx = sx + r_pcd * s * math.cos(ang)
        by = sy + r_pcd * s * math.sin(ang)
        g_bolts.append(
            f'  <circle cx="{bx:.1f}" cy="{by:.1f}" r="{r_bolt * s:.1f}" '
            f'fill="none" stroke="#fb923c" stroke-width="2.5"/>'
        )
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <circle cx="{sx}" cy="{sy}" r="{r_out * s}" fill="none" stroke="#2563eb" stroke-width="3"/>
  <circle cx="{sx}" cy="{sy}" r="{r_hub * s}" fill="none" stroke="#2563eb" stroke-width="2.5"/>
{chr(10).join(g_bolts)}
  <text x="160" y="28" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Крепёж / ступица</text>
</svg>"""


def _svg_wheel_mark(*, opacity: str, camera: bool = False) -> str:
    if camera:
        return _camera_scaled_svg(
            "Маркировка",
            """  <rect x="18" y="52" width="64" height="56" rx="6" fill="none" stroke="#2563eb" stroke-width="1.2"/>
  <text x="50" y="76" text-anchor="middle" fill="#93c5fd" font-size="6.5" font-family="system-ui,sans-serif">7Jx17 ET40</text>
  <text x="50" y="90" text-anchor="middle" fill="#93c5fd" font-size="5.5" font-family="system-ui,sans-serif">5x114.3</text>""",
            scale=WHEEL_CAMERA_SCALE,
        )
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect x="50" y="55" width="220" height="120" rx="12" fill="none" stroke="#2563eb" stroke-width="3"/>
  <text x="160" y="115" text-anchor="middle" font-size="18" fill="#93c5fd" font-family="system-ui,sans-serif">7Jx17 ET40</text>
  <text x="160" y="28" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Маркировка</text>
</svg>"""


def _svg_generic(*, opacity: str, camera: bool = False) -> str:
    return f"""<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg" style="opacity:{opacity}">
  <rect x="24" y="24" width="272" height="172" rx="12" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="10 8"/>
  <text x="160" y="118" text-anchor="middle" font-size="14" fill="#fff" font-family="system-ui,sans-serif" font-weight="700">Держите шину в рамке</text>
</svg>"""
