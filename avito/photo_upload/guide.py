"""Публичная страница стандарта съёмки фото для продавцов."""
from __future__ import annotations


def render_guide_html(*, base: str) -> str:
    """HTML-инструкция: 4 обязательных кадра с контурами и чеклистом."""
    base_href = base if base.endswith("/") else f"{base}/"
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
        Снимайте по этим контурам — так объявления выглядят аккуратно,
        а покупатель сразу видит комплект, протектор, страну и год.
      </p>
      <ol class="guide-order">
        <li><strong>Фото 1</strong> — стопка шин</li>
        <li><strong>Фото 2</strong> — протектор крупно</li>
        <li><strong>Фото 3</strong> — страна производства</li>
        <li><strong>Фото 4</strong> — год выпуска (DOT)</li>
      </ol>
      <p class="muted guide-names">
        Имена файлов на сервере: <code>артикул.jpg</code>,
        <code>артикул-2.jpg</code>, <code>артикул-3.jpg</code>, <code>артикул-4.jpg</code>
      </p>
    </section>

    <section class="guide-card card">
      <div class="guide-card-head">
        <span class="guide-num">1</span>
        <div>
          <h2>Стопка шин</h2>
          <p class="muted">Четвёртая шина стоит на стопке из трёх</p>
        </div>
      </div>
      <div class="guide-frame" aria-hidden="true">
        {_svg_stack()}
      </div>
      <ul class="guide-checklist">
        <li class="ok">Три шины в ряд, четвёртая сверху</li>
        <li class="ok">Шины занимают большую часть кадра</li>
        <li class="ok">Чистый фон, без мусора и посторонних предметов</li>
        <li class="bad">Не снимать одну шину без комплекта</li>
      </ul>
    </section>

    <section class="guide-card card">
      <div class="guide-card-head">
        <span class="guide-num">2</span>
        <div>
          <h2>Протектор крупно</h2>
          <p class="muted">Одна шина ближе, фокус на рисунке</p>
        </div>
      </div>
      <div class="guide-frame" aria-hidden="true">
        {_svg_tread()}
      </div>
      <ul class="guide-checklist">
        <li class="ok">Рисунок протектора читается без зума</li>
        <li class="ok">Камера ближе, чем на фото 1</li>
        <li class="ok">Ровный свет, без сильных бликов</li>
        <li class="bad">Не размыто и не слишком далеко</li>
      </ul>
    </section>

    <section class="guide-card card">
      <div class="guide-card-head">
        <span class="guide-num">3</span>
        <div>
          <h2>Страна производства</h2>
          <p class="muted">Крупно маркировка на боковине</p>
        </div>
      </div>
      <div class="guide-frame" aria-hidden="true">
        {_svg_country()}
      </div>
      <ul class="guide-checklist">
        <li class="ok">Видна надпись страны (Made in / страна)</li>
        <li class="ok">Текст в зоне контура, резкий и читаемый</li>
        <li class="ok">При новой партии — переснять это фото</li>
        <li class="bad">Не обрезать половину надписи</li>
      </ul>
    </section>

    <section class="guide-card card">
      <div class="guide-card-head">
        <span class="guide-num">4</span>
        <div>
          <h2>Год выпуска (DOT)</h2>
          <p class="muted">Код недели и года на боковине</p>
        </div>
      </div>
      <div class="guide-frame" aria-hidden="true">
        {_svg_dot()}
      </div>
      <ul class="guide-checklist">
        <li class="ok">Виден блок DOT с годом (например 2524)</li>
        <li class="ok">Снимать вплотную, без засвета</li>
        <li class="ok">При новой партии — обновить фото 3 и 4</li>
        <li class="bad">Не снимать грязную или нечитаемую маркировку</li>
      </ul>
    </section>

    <section class="card guide-tips">
      <h2>Общие правила</h2>
      <ul class="guide-checklist">
        <li class="ok">Снимайте вертикально, телефон держите ровно</li>
        <li class="ok">Порядок кадров не менять: 1 → 2 → 3 → 4</li>
        <li class="ok">Фото 1–2 можно оставить, если модель та же</li>
        <li class="ok">Фото 3–4 обновляйте при смене партии</li>
        <li class="bad">Не добавляйте лишние кадры между стандартными</li>
      </ul>
    </section>

    <section class="card guide-cta">
      <p>Готово? Вернитесь к загрузке, введите артикул и отправьте 4 снимка.</p>
      <a href="./" class="btn btn-primary">Перейти к загрузке фото</a>
    </section>
  </main>
</body>
</html>"""


def _svg_stack() -> str:
    return """<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg">
  <rect width="320" height="220" fill="#f8fafc"/>
  <rect x="8" y="8" width="304" height="204" rx="12" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="8 6"/>
  <ellipse cx="72" cy="168" rx="46" ry="14" fill="#cbd5e1"/>
  <ellipse cx="72" cy="152" rx="46" ry="14" fill="#e2e8f0" stroke="#64748b" stroke-width="2"/>
  <ellipse cx="160" cy="168" rx="46" ry="14" fill="#cbd5e1"/>
  <ellipse cx="160" cy="152" rx="46" ry="14" fill="#e2e8f0" stroke="#64748b" stroke-width="2"/>
  <ellipse cx="248" cy="168" rx="46" ry="14" fill="#cbd5e1"/>
  <ellipse cx="248" cy="152" rx="46" ry="14" fill="#e2e8f0" stroke="#64748b" stroke-width="2"/>
  <g transform="translate(160 78) rotate(-8)">
    <ellipse cx="0" cy="42" rx="46" ry="14" fill="#cbd5e1"/>
    <rect x="-46" y="-18" width="92" height="58" rx="8" fill="#e2e8f0" stroke="#2563eb" stroke-width="3"/>
    <ellipse cx="0" cy="-18" rx="46" ry="14" fill="#f1f5f9" stroke="#2563eb" stroke-width="3"/>
  </g>
  <text x="160" y="28" text-anchor="middle" font-size="13" fill="#475569" font-family="system-ui,sans-serif">4-я шина на стопке из 3-х</text>
</svg>"""


def _svg_tread() -> str:
    return """<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg">
  <rect width="320" height="220" fill="#f8fafc"/>
  <rect x="8" y="8" width="304" height="204" rx="12" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="8 6"/>
  <ellipse cx="160" cy="178" rx="88" ry="22" fill="#cbd5e1"/>
  <path d="M72 178 C72 92, 248 92, 248 178 Z" fill="#e2e8f0" stroke="#64748b" stroke-width="2"/>
  <rect x="98" y="98" width="124" height="62" rx="8" fill="none" stroke="#16a34a" stroke-width="3" stroke-dasharray="6 4"/>
  <path d="M108 128 h20 v-8 h-20 z M132 136 h24 v-10 h-24 z M160 124 h22 v-12 h-22 z M186 138 h26 v-8 h-26 z M216 122 h18 v-14 h-18 z" fill="#94a3b8"/>
  <text x="160" y="36" text-anchor="middle" font-size="13" fill="#475569" font-family="system-ui,sans-serif">Фокус на протекторе</text>
</svg>"""


def _svg_country() -> str:
    return """<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg">
  <rect width="320" height="220" fill="#f8fafc"/>
  <rect x="8" y="8" width="304" height="204" rx="12" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="8 6"/>
  <rect x="108" y="24" width="104" height="172" rx="52" fill="#e2e8f0" stroke="#64748b" stroke-width="2"/>
  <rect x="124" y="72" width="72" height="36" rx="6" fill="#fff7ed" stroke="#ea580c" stroke-width="3"/>
  <text x="160" y="88" text-anchor="middle" font-size="11" fill="#9a3412" font-family="system-ui,sans-serif" font-weight="700">MADE IN</text>
  <text x="160" y="102" text-anchor="middle" font-size="11" fill="#9a3412" font-family="system-ui,sans-serif">CHINA</text>
  <text x="160" y="36" text-anchor="middle" font-size="13" fill="#475569" font-family="system-ui,sans-serif">Страна на боковине</text>
</svg>"""


def _svg_dot() -> str:
    return """<svg viewBox="0 0 320 220" class="guide-svg" xmlns="http://www.w3.org/2000/svg">
  <rect width="320" height="220" fill="#f8fafc"/>
  <rect x="8" y="8" width="304" height="204" rx="12" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="8 6"/>
  <rect x="108" y="24" width="104" height="172" rx="52" fill="#e2e8f0" stroke="#64748b" stroke-width="2"/>
  <rect x="118" y="118" width="84" height="44" rx="6" fill="#eff6ff" stroke="#2563eb" stroke-width="3"/>
  <text x="160" y="136" text-anchor="middle" font-size="10" fill="#1d4ed8" font-family="monospace" font-weight="700">DOT XXXX</text>
  <text x="160" y="152" text-anchor="middle" font-size="12" fill="#1d4ed8" font-family="monospace" font-weight="700">2524</text>
  <text x="160" y="36" text-anchor="middle" font-size="13" fill="#475569" font-family="system-ui,sans-serif">Год выпуска (DOT)</text>
</svg>"""
