#!/usr/bin/env python3
"""Сбор сырой выдачи Avito по config.yaml → output/."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from avito.browser import (
    AvitoBlockedError,
    create_context,
    open_search,
    pause_before_close,
    sleep_scrape_pause,
)
from avito.config import load_config
from avito.pagination import (
    has_next_page,
    page_url,
    pagination_hint,
    should_continue_pagination,
)
from avito.parser import Listing, extract_page_items, mark_own_listings, write_csv, write_jsonl

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
        help="Показать браузер; ждать капчу до 5 мин на каждой странице",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Лимит страниц (перекрывает config)",
    )
    p.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Начать с страницы N (продолжение после блокировки)",
    )
    p.add_argument(
        "--page-delay",
        type=float,
        default=None,
        help="Базовая пауза между страницами, сек (перекрывает config)",
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


def _opt_int(value) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_float(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_listings_csv(path: Path) -> tuple[list[Listing], set[str]]:
    if not path.is_file():
        return [], set()
    df = pd.read_csv(path, encoding="utf-8-sig")
    items: list[Listing] = []
    seen: set[str] = set()
    for _, row in df.iterrows():
        badges_raw = row.get("badges", "")
        badges = (
            [b for b in str(badges_raw).split("|") if b]
            if pd.notna(badges_raw) and str(badges_raw).strip()
            else []
        )
        item = Listing(
            avito_id=str(row.get("avito_id", "") or ""),
            title=str(row.get("title", "") or ""),
            url=str(row.get("url", "") or ""),
            price_raw=str(row.get("price_raw", "") or ""),
            price_rub=_opt_int(row.get("price_rub")),
            price_unit_count=_opt_int(row.get("price_unit_count")),
            price_per_tire=_opt_float(row.get("price_per_tire")),
            price_confidence=str(row.get("price_confidence", "") or ""),
            price_note=str(row.get("price_note", "") or ""),
            location=str(row.get("location", "") or ""),
            date_text=str(row.get("date_text", "") or ""),
            seller=str(row.get("seller", "") or ""),
            badges=badges,
            description_snippet=str(row.get("description_snippet", "") or ""),
            is_own=str(row.get("is_own", "")).strip().lower() in ("true", "1", "yes", "да"),
            own_match=str(row.get("own_match", "") or ""),
            page_num=_opt_int(row.get("page_num")) or 1,
            scraped_at=str(row.get("scraped_at", "") or ""),
        )
        items.append(item)
        key = item.avito_id or item.url
        if key:
            seen.add(key)
    return items, seen


def _save_dump(out_csv: Path, out_jsonl: Path, all_items) -> None:
    write_csv(out_csv, all_items)
    write_jsonl(out_jsonl, all_items)
    review = sum(1 for x in all_items if x.price_confidence == "needs_review")
    LOG.info("  needs_review: %s", review)


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
    page_delay = (
        args.page_delay if args.page_delay is not None else settings.page_delay_sec
    )
    start_page = max(1, args.start_page)
    headed = args.headed
    headless = not headed and settings.headless
    profile_dir = (ROOT / settings.browser_profile_dir).resolve()

    stamp = date.today().isoformat()
    out_csv = args.output_dir / f"avito_tires_{stamp}.csv"
    out_jsonl = args.output_dir / f"avito_tires_{stamp}.jsonl"

    all_items: list[Listing] = []
    seen_ids: set[str] = set()
    if start_page > 1:
        if not out_csv.is_file():
            LOG.error("Нет дампа за сегодня для продолжения: %s", out_csv)
            return 1
        all_items, seen_ids = _load_listings_csv(out_csv)
        LOG.info(
            "Продолжение: стр. %s, уже в дампе: %s записей → %s",
            start_page,
            len(all_items),
            out_csv,
        )

    pages_done = start_page - 1
    playwright = None
    context = None
    exit_code = 0

    try:
        playwright, context = create_context(profile_dir, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()

        page_num = start_page
        while True:
            url = page_url(settings.search_url, page_num)
            LOG.info("Страница %s: %s", page_num, url[:120])
            if headed and page_num > 1:
                print(
                    f"\n>>> Страница {page_num}: если капча — решите в окне браузера.\n",
                    flush=True,
                )
            open_search(page, url, interactive=headed)
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
            pause, note = sleep_scrape_pause(
                page_num,
                base_sec=page_delay,
                jitter_sec=settings.page_delay_jitter_sec,
                step_sec=settings.page_delay_step_sec,
                step_from_page=settings.page_delay_step_from,
                rest_every=settings.page_rest_every,
                rest_sec=settings.page_rest_sec,
                rest_jitter_sec=settings.page_rest_jitter_sec,
            )
            LOG.info("  пауза %.1f с перед стр. %s%s", pause, page_num, note)

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

    if not all_items:
        LOG.warning("Ничего не собрано — проверьте URL и доступ к Авито")
        return 1 if exit_code == 0 else exit_code

    _save_dump(out_csv, out_jsonl, all_items)

    if exit_code != 0:
        LOG.warning(
            "Частичный дамп: %s записей (до стр. %s) → %s",
            len(all_items),
            pages_done,
            out_csv,
        )
        if exit_code == 2:
            LOG.info(
                "Продолжить после капчи: python scrape.py --headed --start-page %s",
                pages_done + 1,
            )
        return exit_code

    LOG.info("Готово: %s записей (%s стр.) → %s", len(all_items), pages_done, out_csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
