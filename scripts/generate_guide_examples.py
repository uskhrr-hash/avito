#!/usr/bin/env python3
"""Сгенерировать эталонные JPG для страницы /photo/guide (замените на реальные фото)."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "avito" / "photo_upload" / "static" / "guide" / "examples"
SIZE = (960, 720)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _base_canvas(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", SIZE, "#e8edf2")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, SIZE[1] - 120, SIZE[0], SIZE[1]), fill="#d1d9e0")
    draw.text((24, 20), title, fill="#0f172a", font=_font(34))
    draw.text((24, 64), "Эталон для продавцов", fill="#475569", font=_font(22))
    return img, draw


def _save(img: Image.Image, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    img.save(path, format="JPEG", quality=88, optimize=True)
    return path


def shot_stack() -> Path:
    img, draw = _base_canvas("Фото 1 — стопка")
    tires = [(180, 500), (360, 500), (540, 500)]
    for x, y in tires:
        draw.ellipse((x - 95, y - 28, x + 95, y + 28), fill="#cbd5e1", outline="#64748b", width=3)
        draw.rectangle((x - 95, y - 95, x + 95, y - 28), fill="#f8fafc", outline="#64748b", width=3)
    x, y = 360, 300
    draw.ellipse((x - 95, y + 70, x + 95, y + 126), fill="#cbd5e1", outline="#2563eb", width=4)
    draw.rectangle((x - 95, y - 20, x + 95, y + 70), fill="#eff6ff", outline="#2563eb", width=4)
    draw.ellipse((x - 95, y - 55, x + 95, y + 5), fill="#f8fafc", outline="#2563eb", width=4)
    draw.text((24, SIZE[1] - 90), "4-я шина сверху на трёх", fill="#1d4ed8", font=_font(28))
    return _save(img, "01-stack.jpg")


def shot_tread() -> Path:
    img, draw = _base_canvas("Фото 2 — протектор")
    draw.ellipse((120, 470, 840, 560), fill="#cbd5e1")
    draw.pieslice((180, 170, 780, 560), 200, 340, fill="#f8fafc", outline="#64748b", width=3)
    draw.rectangle((300, 250, 660, 430), outline="#16a34a", width=5)
    for i in range(6):
        x = 320 + i * 55
        draw.rectangle((x, 300, x + 30, 360), fill="#94a3b8")
    draw.text((24, SIZE[1] - 90), "Рисунок протектора в зелёной рамке", fill="#15803d", font=_font(28))
    return _save(img, "02-tread.jpg")


def shot_country() -> Path:
    img, draw = _base_canvas("Фото 3 — страна")
    draw.rounded_rectangle((330, 90, 630, 620), radius=120, fill="#f8fafc", outline="#64748b", width=4)
    draw.rounded_rectangle((390, 250, 570, 340), radius=10, fill="#fff7ed", outline="#ea580c", width=5)
    draw.text((410, 268), "MADE IN", fill="#9a3412", font=_font(28))
    draw.text((430, 302), "CHINA", fill="#9a3412", font=_font(28))
    draw.text((24, SIZE[1] - 90), "Страна читается без зума", fill="#c2410c", font=_font(28))
    return _save(img, "03-country.jpg")


def shot_dot() -> Path:
    img, draw = _base_canvas("Фото 4 — год (DOT)")
    draw.rounded_rectangle((330, 90, 630, 620), radius=120, fill="#f8fafc", outline="#64748b", width=4)
    draw.rounded_rectangle((360, 390, 600, 500), radius=10, fill="#eff6ff", outline="#2563eb", width=5)
    draw.text((390, 410), "DOT XXXX", fill="#1d4ed8", font=_font(24))
    draw.text((430, 448), "2524", fill="#1d4ed8", font=_font(36))
    draw.text((24, SIZE[1] - 90), "Год выпуска в синей рамке", fill="#1d4ed8", font=_font(28))
    return _save(img, "04-dot.jpg")


def main() -> int:
    paths = [shot_stack(), shot_tread(), shot_country(), shot_dot()]
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
