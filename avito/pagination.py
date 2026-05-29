"""Пагинация выдачи Avito."""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.sync_api import Page

LOG = logging.getLogger("avito_scrape")

_HAS_NEXT_JS = """
() => {
  const markers = [
    'pagination-button/next',
    'pagination-button/nextPage',
  ];
  for (const m of markers) {
    const el = document.querySelector(`[data-marker="${m}"]`);
    if (!el) continue;
    const disabled =
      el.getAttribute('aria-disabled') === 'true' ||
      el.hasAttribute('disabled') ||
      /disabled/i.test(el.className || '');
    if (!disabled) return { next: true, via: 'button:' + m };
  }
  const cur = parseInt(new URLSearchParams(location.search).get('p') || '1', 10);
  const links = [...document.querySelectorAll('[data-marker^="pagination"] a[href]')];
  for (const a of links) {
    try {
      const p = parseInt(new URL(a.href, location.origin).searchParams.get('p') || '0', 10);
      if (p > cur) return { next: true, via: 'link:p=' + p };
    } catch (_) {}
  }
  return { next: false, via: '' };
}
"""


def page_url(base: str, page_num: int) -> str:
    """Собирает URL с параметром p=N (без дублирования p=)."""
    parsed = urlparse(base)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("p", None)
    if page_num > 1:
        qs["p"] = [str(page_num)]
    query = urlencode(qs, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment)
    )


def has_next_page(page: Page) -> bool:
    try:
        result = page.evaluate(_HAS_NEXT_JS)
        return bool(result.get("next"))
    except Exception:
        return False


def pagination_hint(page: Page) -> str:
    try:
        result = page.evaluate(_HAS_NEXT_JS)
        return str(result.get("via") or "")
    except Exception:
        return ""


def should_continue_pagination(
    *,
    batch_size: int,
    new_unique: int,
    page_num: int,
    ui_has_next: bool,
    min_items_to_try_next_url: int = 15,
) -> bool:
    """
    Решает, загружать ли следующую страницу по ?p=N.
    На Авито кнопка «Далее» часто не попадает в DOM — тогда идём по URL,
    пока на странице достаточно объявлений и появляются новые id.
    """
    if batch_size == 0:
        return False
    if page_num > 1 and new_unique == 0:
        return False
    if ui_has_next:
        return True
    if batch_size >= min_items_to_try_next_url:
        return True
    return False
