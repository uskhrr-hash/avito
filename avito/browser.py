from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

FIREWALL_MARKERS = ("Доступ ограничен", "firewall-container", "проблема с IP")
CATALOG_SELECTOR = '[data-marker="item"]'


class AvitoBlockedError(RuntimeError):
    """Авито показал капчу / блокировку IP или выдача не загрузилась."""


def create_context(
    profile_dir: Path,
    *,
    headless: bool,
) -> tuple[object, BrowserContext]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir.resolve()),
        headless=headless,
        locale="ru-RU",
        viewport={"width": 1366, "height": 900},
        slow_mo=80 if not headless else 0,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    return playwright, context


def _is_firewall(page: Page) -> bool:
    try:
        html = page.content()
        title = page.title()
    except Exception:
        return False
    return any(m in html or m in title for m in FIREWALL_MARKERS)


def _catalog_count(page: Page) -> int:
    try:
        n = page.locator(CATALOG_SELECTOR).count()
        if n > 0:
            return n
        # запасной признак выдачи
        if page.locator('[data-marker="catalog-serp"]').count() > 0:
            return page.locator('h3 a[href*="/shiny/"], h3 a[href*="_"]').count()
        return 0
    except Exception:
        return 0


def wait_for_catalog(
    page: Page,
    *,
    interactive: bool = False,
    timeout_sec: float = 300,
) -> int:
    """
    Ждёт появления карточек в выдаче.
    interactive=True — не падаем сразу на капче, даём время решить вручную.
  Возвращает число карточек на странице.
    """
    if interactive:
        print(
            "\n>>> Откройте окно браузера. Если есть капча — решите её.\n"
            ">>> Скрипт ждёт появления объявлений (до "
            f"{int(timeout_sec)} с)...\n",
            flush=True,
        )

    deadline = time.time() + timeout_sec
    last_log = 0.0

    while time.time() < deadline:
        count = _catalog_count(page)
        if count > 0:
            if interactive:
                print(f"\n>>> Выдача загрузилась: {count} объявлений на странице.\n", flush=True)
            return count

        if not interactive and _is_firewall(page):
            raise AvitoBlockedError(
                "Авито заблокировал доступ. Запустите с --headed и пройдите капчу."
            )

        now = time.time()
        if interactive and now - last_log >= 15:
            left = int(deadline - now)
            state = "капча / проверка" if _is_firewall(page) else "загрузка"
            print(f">>> … ждём ({state}), осталось ~{left} с", flush=True)
            last_log = now

        page.wait_for_timeout(2000)

    raise AvitoBlockedError(
        f"За {int(timeout_sec)} с не появились объявления ({CATALOG_SELECTOR}). "
        "Проверьте URL в config.yaml или пройдите капчу ещё раз с --headed."
    )


def open_search(page: Page, url: str, *, interactive: bool = False) -> int:
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    _dismiss_popups(page)
    return wait_for_catalog(page, interactive=interactive)


def _dismiss_popups(page: Page) -> None:
    for sel in (
        'button:has-text("Понятно")',
        'button:has-text("Хорошо")',
        '[data-marker="popup-close"]',
    ):
        try:
            page.locator(sel).first.click(timeout=1500)
        except Exception:
            pass


def wait_between_pages(delay_sec: float) -> None:
    if delay_sec > 0:
        time.sleep(delay_sec)


def pause_before_close(*, interactive: bool) -> None:
    if not interactive:
        return
    if not sys.stdin or not sys.stdin.isatty():
        return
    try:
        input("\n>>> Нажмите Enter, чтобы закрыть браузер... ")
    except EOFError:
        pass
