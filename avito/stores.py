"""Магазины: префикс фото → контакты для автозагрузки."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Поля магазина → ключи defaults в autoload
_STORE_FIELD_KEYS = (
    "contact_person",
    "phone",
    "address",
    "contact_method",
    "company",
    "email",
    "listing_type",
    "audience",
)


@dataclass(frozen=True)
class Store:
    prefix: str
    label: str
    fields: dict[str, str]
    ushk_supplier: str | None = None

    def listing_id(self, article: str) -> str:
        art = str(article).strip()
        return f"{self.prefix}_{art}" if art else self.prefix


@dataclass(frozen=True)
class StoresConfig:
    stores: tuple[Store, ...]
    legacy_unprefixed_store: str | None

    @property
    def prefixes(self) -> tuple[str, ...]:
        return tuple(s.prefix for s in self.stores)

    def by_prefix(self) -> dict[str, Store]:
        return {s.prefix: s for s in self.stores}

    def get(self, prefix: str) -> Store | None:
        return self.by_prefix().get(prefix)


def load_stores(path: Path) -> StoresConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = raw.get("stores") or []
    stores: list[Store] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        prefix = str(item.get("prefix", "")).strip()
        if not prefix:
            continue
        label = str(item.get("label", prefix)).strip()
        fields = {
            k: str(item[k]).strip()
            for k in _STORE_FIELD_KEYS
            if k in item and str(item[k]).strip()
        }
        ushk = str(item.get("ushk_supplier", "") or "").strip() or None
        stores.append(
            Store(prefix=prefix, label=label, fields=fields, ushk_supplier=ushk)
        )
    if not stores:
        raise ValueError(f"В {path} нет ни одного магазина (stores)")

    legacy = raw.get("legacy_unprefixed_store")
    legacy_s = str(legacy).strip() if legacy else None
    if legacy_s and legacy_s not in {s.prefix for s in stores}:
        raise ValueError(f"legacy_unprefixed_store={legacy_s!r} нет в stores")

    return StoresConfig(
        stores=tuple(stores),
        legacy_unprefixed_store=legacy_s,
    )


def merge_defaults(base: dict[str, str], store: Store) -> dict[str, str]:
    return {**base, **store.fields}
