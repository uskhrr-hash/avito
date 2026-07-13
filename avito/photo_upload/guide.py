"""Публичная страница стандарта съёмки фото для продавцов."""
from __future__ import annotations

from avito.photo_upload.overlays import EXAMPLE_FILES, SHOT_LABELS, overlay_svg_for_shot


def render_guide_html(*, base: str) -> str:
    """HTML-инструкция: 4 обязательных кадра с эталонами и контурами."""
    base_href = base if base.endswith("/") else f"{base}/"
    cards = "\n".join(_guide_card(index, base_href) for index in range(1, 5))
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#2563eb">
  <base href="{base_href}">
  <title>Стандарт фото шин — Avito</title>
  <link rel="stylesheet" href="static/app.css">
  <link rel="stylesheet" href="static/guide.css">
</head>
<body class="page-guide">
  <header class="topbar">
    <div>
      <div class="topbar-title">Стандарт фото</div>
      <div class="topbar-sub">4 кадра на каждый артикул</div>
    </div>
    <a href="./" class="btn btn-ghost guide-back">Загрузка</a>
  </header>

  <main class="shell">
    <section class="card guide-intro">
      <h1>Как снимать шины одинаково</h1>
      <p class="lead">
        На каждый артикул нужно <strong>4 фото</strong> в одном порядке.
        Снимайте как на эталонах ниже — в приложении загрузки при съёмке
        появится такой же контур.
      </p>
      <ol class="guide-order">
        <li><strong>Фото 1</strong> — стопка шин</li>
        <li><strong>Фото 2</strong> — протектор крупно</li>
        <li><strong>Фото 3</strong> — страна производства</li>
        <li><strong>Фото 4</strong> — год выпуска (DOT)</li>
      </ol>
      <p class="muted guide-names">
        Имена файлов: <code>артикул.jpg</code>, <code>артикул-2.jpg</code>,
        <code>артикул-3.jpg</code>, <code>артикул-4.jpg</code>
      </p>
      <p class="muted guide-replace">
        Эталоны можно заменить на реальные фото: положите файлы в
        <code>avito/photo_upload/static/guide/examples/</code> с теми же именами.
      </p>
    </section>

{cards}

    <section class="card guide-tips">
      <h2>Общие правила</h2>
      <ul class="guide-checklist">
        <li class="ok">Снимайте вертикально, телефон держите ровно</li>
        <li class="ok">Порядок кадров: 1 → 2 → 3 → 4</li>
        <li class="ok">Фото 1–2 можно оставить, если модель та же</li>
        <li class="ok">Фото 3–4 обновляйте при смене партии</li>
        <li class="bad">Не добавляйте лишние кадры между стандартными</li>
      </ul>
    </section>

    <section class="card guide-cta">
      <p>В приложении загрузки контур появится поверх камеры при съёмке.</p>
      <a href="./" class="btn btn-primary">Перейти к загрузке фото</a>
    </section>
  </main>
</body>
</html>"""


def _guide_card(index: int, base_href: str) -> str:
    meta = SHOT_LABELS[index]
    example = EXAMPLE_FILES[index]
    checklist = _checklist_for_shot(index)
    return f"""    <section class="guide-card card">
      <div class="guide-card-head">
        <span class="guide-num">{index}</span>
        <div>
          <h2>{meta["title"]}</h2>
          <p class="muted">{meta["hint"]}</p>
        </div>
      </div>
      <div class="guide-example">
        <img src="{example}" alt="Эталон: {meta["title"]}" loading="lazy">
        <div class="guide-example-overlay" aria-hidden="true">
          {overlay_svg_for_shot(index, camera=True)}
        </div>
      </div>
      <ul class="guide-checklist">
{checklist}
      </ul>
    </section>"""


def _checklist_for_shot(index: int) -> str:
    items: dict[int, list[tuple[str, str]]] = {
        1: [
            ("ok", "Три шины в ряд, четвёртая сверху"),
            ("ok", "Шины занимают большую часть кадра"),
            ("ok", "Чистый фон"),
            ("bad", "Не снимать одну шину без комплекта"),
        ],
        2: [
            ("ok", "Рисунок протектора читается без зума"),
            ("ok", "Камера ближе, чем на фото 1"),
            ("ok", "Ровный свет, без сильных бликов"),
            ("bad", "Не размыто и не слишком далеко"),
        ],
        3: [
            ("ok", "Видна надпись страны (Made in / страна)"),
            ("ok", "Текст в оранжевой зоне, резкий"),
            ("ok", "При новой партии — переснять"),
            ("bad", "Не обрезать половину надписи"),
        ],
        4: [
            ("ok", "Виден блок DOT с годом"),
            ("ok", "Снимать вплотную, без засвета"),
            ("ok", "При новой партии — обновить фото 3 и 4"),
            ("bad", "Не снимать грязную маркировку"),
        ],
    }
    lines = []
    for kind, text in items[index]:
        lines.append(f'        <li class="{kind}">{text}</li>')
    return "\n".join(lines)
