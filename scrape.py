#!/usr/bin/env python3
"""Сбор сырой выдачи Avito по config.yaml → output/."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from avito.browser import (
    AvitoBlockedError,
    create_context,
    open_search,
    pause_before_close,
    wait_between_pages,
)
from avito.config import load_config
from avito.pagination import (
    has_next_page,
    page_url,
    pagination_hint,
    should_continue_pagination,
)
from avito.parser import extract_page_items, mark_own_listings, write_csv, write_jsonl

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("avito_scrape")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Парсер шин Avito (Уфа, сырой дамп)")
    p.add_argument(
        "-c",
        "--config",
        type=Path,
        default=ROOT / "config.yaml",
        help="Путь к config.yaml",
    )
    p.add_argument(
        "--headed",
        action="store_true",
        help="Показать браузер; ждать капчу до 5 мин (не закрывать сразу)",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Лимит страниц (перекрывает config)",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=ROOT / "output",
        help="Каталог для CSV/JSONL",
    )
    return p.parse_args()


def _dedupe_batch(batch, seen_ids: set[str]) -> list:
    unique = []
    for item in batch:
        key = item.avito_id or item.url
        if not key or key in seen_ids:
            continue
        seen_ids.add(key)
        unique.append(item)
    return unique


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    app = load_config(args.config)
    settings = app.scrape
    own_names = app.compare.own_seller_names
    max_pages = args.max_pages if args.max_pages is not None else settings.max_pages
    headed = args.headed
    headless = not headed and settings.headless
    profile_dir = (ROOT / settings.browser_profile_dir).resolve()

    stamp = date.today().isoformat()
    out_csv = args.output_dir / f"avito_tires_{stamp}.csv"
    out_jsonl = args.output_dir / f"avito_tires_{stamp}.jsonl"

    all_items = []
    seen_ids: set[str] = set()
    pages_done = 0
    playwright = None
    context = None
    exit_code = 0

    try:
        playwright, context = create_context(profile_dir, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()

        page_num = 1
        while True:
            url = page_url(settings.search_url, page_num)
            LOG.info("Страница %s: %s", page_num, url[:120])
            interactive = headed and page_num == 1
            open_search(page, url, interactive=interactive)
            batch = extract_page_items(page, page_num)
            mark_own_listings(batch, own_names)
            unique = _dedupe_batch(batch, seen_ids)
            LOG.info(
                "  объявлений: %s (новых: %s)",
                len(batch),
                len(unique),
            )
            own_n = sum(1 for x in unique if x.is_own)
            if own_n:
                LOG.info("  из них своих: %s", own_n)
            all_items.extend(unique)
            pages_done = page_num

            if max_pages and page_num >= max_pages:
                LOG.info("  лимит max_pages=%s", max_pages)
                break

            ui_next = has_next_page(page)
            hint = pagination_hint(page)
            cont = should_continue_pagination(
                batch_size=len(batch),
                new_unique=len(unique),
                page_num=page_num,
                ui_has_next=ui_next,
            )
            if cont:
                via = hint or ("url ?p=" + str(page_num + 1) if not ui_next else "кнопка")
                LOG.info("  следующая страница (%s)", via)
            else:
                LOG.info("  конец выдачи (кнопка: %s, новых id: %s)", ui_next, len(unique))
                break

            page_num += 1
            wait_between_pages(settings.page_delay_sec)

    except AvitoBlockedError as exc:
        LOG.error("%s", exc)
        exit_code = 2
    except KeyboardInterrupt:
        LOG.warning("Остановлено пользователем (Ctrl+C)")
        exit_code = 130
    finally:
        pause_before_close(interactive=headed)
        if context:
            context.close()
        if playwright:
            playwright.stop()

    if exit_code != 0:
        return exit_code

    if not all_items:
        LOG.warning("Ничего не собрано — проверьте URL и доступ к Авито")
        return 1

    write_csv(out_csv, all_items)
    write_jsonl(out_jsonl, all_items)

    review = sum(1 for x in all_items if x.price_confidence == "needs_review")
    LOG.info("Готово: %s записей (%s стр.) → %s", len(all_items), pages_done, out_csv)
    LOG.info("  needs_review: %s", review)
    return 0


if __name__ == "__main__":
    sys.exit(main())
