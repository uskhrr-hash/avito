from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from avito.own import is_own_listing
from avito.price import PriceResult, parse_price

EXTRACT_ITEMS_JS = """
() => {
  const cards = [...document.querySelectorAll('[data-marker="item"]')];
  return cards.map(card => {
    const pick = (marker) => {
      const el = card.querySelector(`[data-marker="${marker}"]`);
      return el ? (el.textContent || '').trim() : '';
    };
    const title =
      card.querySelector('[itemprop="name"]')?.textContent?.trim() ||
      card.querySelector('[data-marker="item-title"]')?.textContent?.trim() ||
      card.querySelector('h3 a')?.textContent?.trim() ||
      card.querySelector('h3')?.textContent?.trim() ||
      '';
    const price =
      pick('item-price') ||
      card.querySelector('[itemprop="price"]')?.getAttribute('content') ||
      '';
    const link =
      card.querySelector('a[itemprop="url"]')?.href ||
      [...card.querySelectorAll('a[href]')].map(a => a.href).find(h =>
        h && h.includes('avito.ru') && /_\\d+(?:\\?|$)/.test(h)
      ) || '';
    const idMatch = link.match(/_(\\d+)(?:\\?|$)/);
    const location = pick('item-location') || pick('item-address');
    const date = pick('item-date');
    const seller =
      pick('seller-info/name') ||
      (card.querySelector('[data-marker="seller-link/link"]')?.textContent || '').trim() ||
      pick('item-seller') ||
      '';
    const badges = [...card.querySelectorAll('[data-marker="item-badge"]')]
      .map(el => (el.textContent || '').trim())
      .filter(Boolean);
    const description = pick('item-description') || pick('item-specific-params');
  const metaPrice = card.querySelector('meta[itemprop="price"]');
  const metaAmount = metaPrice ? metaPrice.getAttribute('content') : '';
    return {
      avito_id: idMatch ? idMatch[1] : '',
      title,
      price_text: price || (metaAmount ? metaAmount + ' ₽' : ''),
      url: link,
      location,
      date_text: date,
      seller,
      badges,
      description_snippet: description.slice(0, 500),
    };
  });
}
"""


@dataclass
class Listing:
    avito_id: str
    title: str
    url: str
    price_raw: str
    price_rub: int | None
    price_unit_count: int | None
    price_per_tire: float | None
    price_confidence: str
    price_note: str
    location: str = ""
    date_text: str = ""
    seller: str = ""
    badges: list[str] = field(default_factory=list)
    description_snippet: str = ""
    is_own: bool = False
    own_match: str = ""
    page_num: int = 1
    scraped_at: str = ""


def mark_own_listings(items: list[Listing], own_names: list[str]) -> None:
    for item in items:
        ok, by = is_own_listing(
            seller=item.seller,
            title=item.title,
            description=item.description_snippet,
            own_names=own_names,
        )
        item.is_own = ok
        item.own_match = by


def extract_page_items(page: Page, page_num: int) -> list[Listing]:
    scraped_at = datetime.now(timezone.utc).isoformat()
    raw_items: list[dict[str, Any]] = page.evaluate(EXTRACT_ITEMS_JS)
    listings: list[Listing] = []
    for raw in raw_items:
        if not raw.get("title"):
            continue
        price: PriceResult = parse_price(
            raw.get("price_text", ""),
            f"{raw.get('title', '')} {raw.get('description_snippet', '')}",
        )
        listings.append(
            Listing(
                avito_id=str(raw.get("avito_id") or ""),
                title=raw.get("title", ""),
                url=raw.get("url", ""),
                price_raw=price.price_raw,
                price_rub=price.price_rub,
                price_unit_count=price.price_unit_count,
                price_per_tire=price.price_per_tire,
                price_confidence=price.price_confidence,
                price_note=price.price_note,
                location=raw.get("location", ""),
                date_text=raw.get("date_text", ""),
                seller=raw.get("seller", ""),
                badges=raw.get("badges") or [],
                description_snippet=raw.get("description_snippet", ""),
                page_num=page_num,
                scraped_at=scraped_at,
            )
        )
    return listings


CSV_FIELDS = [
    "avito_id",
    "title",
    "url",
    "price_raw",
    "price_rub",
    "price_unit_count",
    "price_per_tire",
    "price_confidence",
    "price_note",
    "location",
    "date_text",
    "seller",
    "badges",
    "description_snippet",
    "is_own",
    "own_match",
    "page_num",
    "scraped_at",
]


def write_csv(path: Path, items: list[Listing]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for item in items:
            row = asdict(item)
            row["badges"] = "|".join(item.badges)
            writer.writerow(row)


def write_jsonl(path: Path, items: list[Listing]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
