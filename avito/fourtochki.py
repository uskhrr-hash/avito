"""Каталог описаний моделей с 4tochki.ru (MarkaModelNote.xml + info.html)."""
from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from avito.model_descriptions import model_key
from avito.nomenclature_api import normalize_titles
from avito.title_parse import parse_title_fields

LOG = logging.getLogger(__name__)

ALLOWED_TAGS = frozenset({"p", "br", "strong", "em", "ul", "ol", "li"})
MAX_MODEL_DESCRIPTION_LEN = 3500
DEFAULT_DUMMY_SIZE = " 205/55 R16 91V"
DUMMY_SIZE_VARIANTS = (
    " 205/55 R16 91V",
    " 205/55R16 91V",
    " 195/65 R15 91T",
    " 225/45R17 91Y",
)
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ModelCatalogEntry:
    brand: str
    model: str
    url: str
    youtube_urls: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return model_key(self.brand, self.model)


@dataclass(frozen=True)
class BrandCatalogEntry:
    url: str
    logo: str = ""


@dataclass
class FourtochkiCatalog:
    models: dict[str, ModelCatalogEntry]
    brands: dict[str, BrandCatalogEntry]
    source: str = ""
    generated_at: str = ""

    def lookup_url(self, nomenclature: str) -> tuple[str, str] | None:
        """Возвращает (catalog_key, url) или None."""
        nom = nomenclature.strip()
        if not nom:
            return None
        key = match_catalog_key(nom, self.models)
        if not key:
            return None
        return key, self.models[key].url


def parse_marka_model_xml(path: Path) -> FourtochkiCatalog:
    root = ET.parse(path).getroot()
    models: dict[str, ModelCatalogEntry] = {}
    brands: dict[str, BrandCatalogEntry] = {}

    tyre = root.find("tyre")
    if tyre is None:
        raise ValueError("В XML нет секции <tyre>")

    for marka in tyre.findall("marka"):
        brand = (marka.findtext("name") or "").strip()
        if not brand:
            continue
        brand_url = (marka.findtext("html") or "").strip()
        brand_logo = (marka.findtext("logo") or "").strip()
        if brand_url or brand_logo:
            brands[brand] = BrandCatalogEntry(url=brand_url, logo=brand_logo)

        models_el = marka.find("models")
        if models_el is None:
            continue
        for mod in models_el.findall("model"):
            name = (mod.findtext("name") or "").strip()
            url = (mod.findtext("html") or "").strip()
            if not name or not url:
                continue
            yt = tuple(
                (el.text or "").strip()
                for el in mod.findall("youtube_url")
                if (el.text or "").strip()
            )
            entry = ModelCatalogEntry(
                brand=brand, model=name, url=url, youtube_urls=yt
            )
            models[entry.key] = entry

    return FourtochkiCatalog(
        models=models,
        brands=brands,
        source=str(path),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def save_catalog_json(catalog: FourtochkiCatalog, path: Path) -> None:
    payload = {
        "source": catalog.source,
        "generated_at": catalog.generated_at,
        "models": {
            k: {
                "brand": v.brand,
                "model": v.model,
                "url": v.url,
                "youtube_urls": list(v.youtube_urls),
            }
            for k, v in sorted(catalog.models.items())
        },
        "brands": {
            k: {"url": v.url, "logo": v.logo}
            for k, v in sorted(catalog.brands.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_catalog_json(path: Path) -> FourtochkiCatalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    models: dict[str, ModelCatalogEntry] = {}
    for key, item in (raw.get("models") or {}).items():
        models[str(key)] = ModelCatalogEntry(
            brand=str(item.get("brand", "")),
            model=str(item.get("model", "")),
            url=str(item.get("url", "")),
            youtube_urls=tuple(item.get("youtube_urls") or []),
        )
    brands: dict[str, BrandCatalogEntry] = {}
    for name, item in (raw.get("brands") or {}).items():
        brands[str(name)] = BrandCatalogEntry(
            url=str(item.get("url", "")),
            logo=str(item.get("logo", "")),
        )
    return FourtochkiCatalog(
        models=models,
        brands=brands,
        source=str(raw.get("source", "")),
        generated_at=str(raw.get("generated_at", "")),
    )


def match_catalog_key(
    nomenclature: str,
    catalog_models: dict[str, ModelCatalogEntry],
) -> str | None:
    """Сопоставляет номенклатуру с ключом каталога «Бренд Модель»."""
    nom = nomenclature.strip()
    if not nom:
        return None

    keys = catalog_models.keys()
    prefix_hits = [k for k in keys if nom == k or nom.startswith(k + " ")]
    if prefix_hits:
        return max(prefix_hits, key=len)

    fields = parse_title_fields(nom)
    parsed = model_key(fields.get("brand", ""), fields.get("model", ""))
    if parsed in catalog_models:
        return parsed

    brand = fields.get("brand", "")
    if brand:
        brand_hits = [
            k
            for k in keys
            if catalog_models[k].brand == brand
            and nom.startswith(model_key(brand, catalog_models[k].model) + " ")
        ]
        if brand_hits:
            return max(brand_hits, key=len)

    return None


class _AvitoHtmlCleaner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._tag_stack: list[str] = []
        self._pending_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "img", "meta", "link"):
            return
        self._flush_text()
        if tag == "br":
            self.parts.append("<br>")
            return
        if tag in ALLOWED_TAGS:
            if tag in ("ul", "ol"):
                self.parts.append(f"<{tag}>")
            elif tag == "li":
                self.parts.append("<li>")
            elif tag == "p":
                self.parts.append("<p>")
            elif tag in ("strong", "em"):
                self.parts.append(f"<{tag}>")
            self._tag_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in ALLOWED_TAGS or tag == "br":
            return
        self._flush_text()
        if tag in self._tag_stack:
            while self._tag_stack:
                open_tag = self._tag_stack.pop()
                if open_tag in ("ul", "ol", "p", "li", "strong", "em"):
                    if open_tag == "li":
                        self.parts.append("</li>")
                    elif open_tag in ("ul", "ol", "p", "strong", "em"):
                        self.parts.append(f"</{open_tag}>")
                if open_tag == tag:
                    break

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._pending_text.append(data)

    def _flush_text(self) -> None:
        if not self._pending_text:
            return
        chunk = "".join(self._pending_text).strip()
        self._pending_text.clear()
        if not chunk:
            return
        if self._tag_stack and self._tag_stack[-1] in ("strong", "em", "li"):
            self.parts.append(escape(chunk))
        else:
            self.parts.append(f"<p>{escape(chunk)}</p>")

    def get_html(self) -> str:
        self._flush_text()
        while self._tag_stack:
            tag = self._tag_stack.pop()
            if tag in ("ul", "ol", "p", "li", "strong", "em"):
                if tag == "li":
                    self.parts.append("</li>")
                else:
                    self.parts.append(f"</{tag}>")
        html = "".join(self.parts)
        html = re.sub(r"</p>\s*<p>", " ", html)
        html = re.sub(r"<p>\s*</p>", "", html)
        html = re.sub(r"\s+", " ", html)
        html = re.sub(r">\s+<", "><", html)
        return html.strip()


def _normalize_raw_html(html: str) -> str:
    text = html.strip()
    text = re.sub(r"<b\b", "<strong", text, flags=re.IGNORECASE)
    text = re.sub(r"</b>", "</strong>", text, flags=re.IGNORECASE)
    text = re.sub(
        r'<span[^>]*font-weight:\s*bold[^>]*>',
        "<strong>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"</span>", "</strong>", text, flags=re.IGNORECASE)
    text = re.sub(r"<img[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s+clear[^>]*>", "<br>", text, flags=re.IGNORECASE)
    return text


def html_to_avito_description(html: str, *, max_len: int = MAX_MODEL_DESCRIPTION_LEN) -> str:
    """Конвертирует info.html 4tochki в разрешённый Avito HTML."""
    normalized = _normalize_raw_html(html)
    parser = _AvitoHtmlCleaner()
    parser.feed(normalized)
    parser.close()
    out = parser.get_html()
    if len(out) > max_len:
        out = out[: max_len - 3].rstrip() + "..."
    return out


def _request_timeout(timeout_sec: float) -> float | tuple[float, float]:
    """(connect, read) — connect не дольше 15 с, read до timeout_sec."""
    connect = min(15.0, max(3.0, timeout_sec / 4))
    return (connect, timeout_sec)


def fetch_page_html(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout_sec: float = 60,
    user_agent: str = _DEFAULT_UA,
) -> str:
    sess = session or requests.Session()
    resp = sess.get(
        url,
        timeout=_request_timeout(timeout_sec),
        headers={"User-Agent": user_agent},
    )
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def load_or_fetch_description(
    url: str,
    cache_path: Path,
    *,
    session: requests.Session | None = None,
    timeout_sec: float = 60,
    user_agent: str = _DEFAULT_UA,
    refresh: bool = False,
) -> str:
    if cache_path.exists() and not refresh:
        raw = cache_path.read_text(encoding="utf-8")
    else:
        raw = fetch_page_html(
            url,
            session=session,
            timeout_sec=timeout_sec,
            user_agent=user_agent,
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(raw, encoding="utf-8")
    return html_to_avito_description(raw)


def dict_model_key(fields: dict[str, Any]) -> str:
    return model_key(str(fields.get("brand", "")), str(fields.get("model", "")))


def strip_size_from_canonical_name(name: str) -> str:
    """Убирает типоразмер из поля name словаря → каноническое имя модели."""
    from avito.title_parse import _SIZE_RE, _TRAIL_INDEX_RE

    t = name.strip()
    if not t:
        return ""
    # Только по строке с пробелами — иначе «S01 185» склеивается в ложный типоразмер.
    size_m = _SIZE_RE.search(t)
    if size_m:
        return t[: size_m.start()].strip()
    trail = _TRAIL_INDEX_RE.search(t)
    if trail:
        return t[: trail.start()].strip()
    return t


def dictionary_fields_to_canonical(fields: dict[str, Any]) -> dict[str, str]:
    """
    Ответ словаря (с типоразмером в name) → канон модели без размера.
    brand/model уже без размера; name режем через strip_size_from_canonical_name.
    """
    brand = str(fields.get("brand", "") or "").strip()
    model = str(fields.get("model", "") or "").strip()
    name = str(fields.get("name", "") or "").strip()
    canon_name = strip_size_from_canonical_name(name) or model_key(brand, model)
    key = model_key(brand, model) or canon_name
    return {
        "бренд": brand,
        "модель": model,
        "ключ_модели": key,
        "имя_каноническое": canon_name,
    }


def resolve_canonical_model(
    *,
    catalog_key: str,
    catalog_brand: str,
    catalog_model: str,
    dictionary: DictionaryIndex | None = None,
    normalized_catalog: dict[str, dict[str, Any]] | None = None,
    goods_nom: str = "",
    goods_fields: dict[str, Any] | None = None,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
) -> dict[str, str]:
    """
    Канон модели для таблицы описаний.

    Словарь без типоразмера не отвечает → к имени 4tochki добавляем dummy_size,
    batch POST, из ответа берём brand/model/name и срезаем размер из name.
    """
    fields: dict[str, Any] | None = goods_fields
    match_src = "goods" if goods_fields else ""

    if not fields and dictionary is not None:
        fields, match_src = dictionary.lookup(
            catalog_key=catalog_key,
            catalog_brand=catalog_brand,
            catalog_model=catalog_model,
            goods_nom=goods_nom,
            goods_fields=None,
            dummy_size=dummy_size,
        )
    elif not fields and normalized_catalog:
        for q in catalog_query_variants(catalog_key, dummy_size):
            fields = normalized_catalog.get(q)
            if fields:
                match_src = "catalog_query"
                break
        if not fields:
            fields = normalized_catalog.get(catalog_key)

    if fields:
        canon = dictionary_fields_to_canonical(fields)
        return {
            **canon,
            "словарь_распознан": "да",
            "словарь_источник": match_src,
            "каталог_4tochki": catalog_key,
        }

    return {
        "бренд": catalog_brand.strip(),
        "модель": catalog_model.strip(),
        "ключ_модели": "",
        "имя_каноническое": "",
        "словарь_распознан": "нет",
        "словарь_источник": "",
        "каталог_4tochki": catalog_key,
    }


def normalize_catalog_through_dictionary(
    catalog: FourtochkiCatalog,
    *,
    base_url: str,
    batch_size: int = 40,
    pause_sec: float = 0.2,
    timeout_sec: float = 90,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
) -> DictionaryIndex:
    return normalize_catalog_dictionary(
        catalog,
        base_url=base_url,
        batch_size=batch_size,
        pause_sec=pause_sec,
        timeout_sec=timeout_sec,
        dummy_size=dummy_size,
    )


def make_description_table_row(
    *,
    catalog_key: str,
    catalog_brand: str,
    catalog_model: str,
    description_html: str,
    dictionary: DictionaryIndex | None = None,
    normalized_catalog: dict[str, dict[str, Any]] | None = None,
    goods_nom: str = "",
    goods_fields: dict[str, Any] | None = None,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
    source: str = "4tochki",
) -> dict[str, Any]:
    row = resolve_canonical_model(
        catalog_key=catalog_key,
        catalog_brand=catalog_brand,
        catalog_model=catalog_model,
        dictionary=dictionary,
        normalized_catalog=normalized_catalog,
        goods_nom=goods_nom,
        goods_fields=goods_fields,
        dummy_size=dummy_size,
    )
    row["описание_html"] = description_html
    row["источник"] = source
    return row


def catalog_query_title(catalog_key: str, dummy_size: str = DEFAULT_DUMMY_SIZE) -> str:
    """Имя модели 4tochki + фиктивный типоразмер для запроса в словарь."""
    return f"{catalog_key.strip()}{dummy_size}"


def catalog_query_variants(
    catalog_key: str,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
) -> list[str]:
    """Варианты строки для словаря: словарь требует типоразмер в конце."""
    key = catalog_key.strip()
    if not key:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for size in (dummy_size, *DUMMY_SIZE_VARIANTS):
        q = f"{key}{size}".strip() if size else key
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def catalog_dictionary_queries(
    catalog_keys: list[str],
    *,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
) -> list[str]:
    """Все уникальные строки для batch POST в словарь."""
    seen: set[str] = set()
    out: list[str] = []
    for key in catalog_keys:
        for q in catalog_query_variants(key, dummy_size):
            if q not in seen:
                seen.add(q)
                out.append(q)
    return out


def map_catalog_dictionary_results(
    catalog_keys: list[str],
    parsed: dict[str, dict[str, Any]],
    *,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
) -> dict[str, dict[str, Any]]:
    """Сопоставляет ответ словаря с ключами каталога 4tochki."""
    out: dict[str, dict[str, Any]] = {}
    for key in catalog_keys:
        for q in catalog_query_variants(key, dummy_size):
            fields = parsed.get(q)
            if fields:
                out[key] = fields
                break
    return out


@dataclass
class DictionaryIndex:
    """Индекс ответов словаря: по запросу, model_key и каталогу 4tochki."""

    by_query: dict[str, dict[str, Any]]
    by_model_key: dict[str, dict[str, Any]]
    by_catalog_key: dict[str, dict[str, Any]]

    def lookup(
        self,
        *,
        catalog_key: str,
        catalog_brand: str,
        catalog_model: str,
        goods_nom: str = "",
        goods_fields: dict[str, Any] | None = None,
        dummy_size: str = DEFAULT_DUMMY_SIZE,
    ) -> tuple[dict[str, Any] | None, str]:
        if goods_fields:
            return goods_fields, "goods"
        nom = goods_nom.strip()
        if nom and nom in self.by_query:
            return self.by_query[nom], "goods_nom"
        ck = catalog_key.strip()
        if ck and ck in self.by_catalog_key:
            return self.by_catalog_key[ck], "catalog_index"
        for q in catalog_query_variants(ck, dummy_size):
            if q in self.by_query:
                return self.by_query[q], "catalog_query"
        mk = model_key(catalog_brand, catalog_model) or ck
        if mk in self.by_model_key:
            return self.by_model_key[mk], "model_key"
        if ck in self.by_model_key:
            return self.by_model_key[ck], "model_key_catalog"
        return None, ""


def build_dictionary_index(
    parsed: dict[str, dict[str, Any]],
    *,
    catalog: FourtochkiCatalog | None = None,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
    goods_nomenclatures: list[str] | None = None,
) -> DictionaryIndex:
    by_model_key: dict[str, dict[str, Any]] = {}
    for fields in parsed.values():
        mk = dict_model_key(fields)
        if mk:
            by_model_key.setdefault(mk, fields)
        name = str(fields.get("name", "") or "").strip()
        stripped = strip_size_from_canonical_name(name)
        if stripped:
            by_model_key.setdefault(stripped, fields)

    by_catalog_key: dict[str, dict[str, Any]] = {}
    if catalog:
        by_catalog_key = map_catalog_dictionary_results(
            list(catalog.models.keys()),
            parsed,
            dummy_size=dummy_size,
        )
    if catalog and goods_nomenclatures:
        for nom in goods_nomenclatures:
            nom = str(nom or "").strip()
            fields = parsed.get(nom)
            if not fields:
                continue
            hit = match_catalog_key(nom, catalog.models)
            if hit and hit not in by_catalog_key:
                by_catalog_key[hit] = fields

    return DictionaryIndex(
        by_query=parsed,
        by_model_key=by_model_key,
        by_catalog_key=by_catalog_key,
    )


def normalize_catalog_batch(
    catalog_keys: list[str],
    *,
    base_url: str,
    batch_size: int = 40,
    pause_sec: float = 0.2,
    timeout_sec: float = 90,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
) -> dict[str, dict[str, Any]]:
    """
    Массив имён моделей каталога → {catalog_key: поля словаря}.
    В словарь уходит JSON-массив строк (модель + типоразмер).
    """
    queries = catalog_dictionary_queries(catalog_keys, dummy_size=dummy_size)
    parsed = normalize_titles(
        queries,
        base_url=base_url,
        batch_size=batch_size,
        pause_sec=pause_sec,
        timeout_sec=timeout_sec,
    )
    return map_catalog_dictionary_results(
        catalog_keys,
        parsed,
        dummy_size=dummy_size,
    )


def normalize_catalog_dictionary(
    catalog: FourtochkiCatalog,
    *,
    base_url: str,
    batch_size: int = 40,
    pause_sec: float = 0.2,
    timeout_sec: float = 90,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
) -> DictionaryIndex:
    """
    Каталог 4tochki → словарь → канон моделей.

    1. К каждому имени каталога дописываем dummy_size (словарь иначе молчит).
    2. Batch POST массива строк на 192.168.1.75.
    3. Ответ сопоставляем с каталогом; размер из name снимается при экспорте в Excel.
    """
    catalog_keys = list(catalog.models.keys())
    queries = catalog_dictionary_queries(catalog_keys, dummy_size=dummy_size)
    parsed = normalize_titles(
        queries,
        base_url=base_url,
        batch_size=batch_size,
        pause_sec=pause_sec,
        timeout_sec=timeout_sec,
    )
    return build_dictionary_index(parsed, catalog=catalog, dummy_size=dummy_size)


def normalize_for_descriptions(
    catalog: FourtochkiCatalog,
    goods_nomenclatures: list[str],
    *,
    base_url: str,
    batch_size: int = 40,
    pause_sec: float = 0.2,
    timeout_sec: float = 90,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
) -> DictionaryIndex:
    """Каталог + опционально goods (для link, не для export)."""
    titles: set[str] = set()
    for nom in goods_nomenclatures:
        s = str(nom or "").strip()
        if s:
            titles.add(s)
    for key in catalog.models:
        titles.update(catalog_query_variants(key, dummy_size))
    parsed = normalize_titles(
        sorted(titles),
        base_url=base_url,
        batch_size=batch_size,
        pause_sec=pause_sec,
        timeout_sec=timeout_sec,
    )
    return build_dictionary_index(
        parsed,
        catalog=catalog,
        dummy_size=dummy_size,
        goods_nomenclatures=goods_nomenclatures,
    )


def load_descriptions_bulk(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"models": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_descriptions_bulk(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_all_catalog_descriptions(
    catalog: FourtochkiCatalog,
    *,
    cache_dir: Path,
    bulk_path: Path | None = None,
    session: requests.Session | None = None,
    pause_sec: float = 1.0,
    timeout_sec: float = 60,
    user_agent: str | None = None,
    refresh: bool = False,
    resume: bool = True,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Скачивает описания для всех моделей каталога в JSON-базу."""
    bulk = load_descriptions_bulk(bulk_path) if bulk_path and resume else {"models": {}}
    models_data: dict[str, Any] = bulk.setdefault("models", {})
    bulk["catalog_source"] = catalog.source or bulk.get("catalog_source", "")
    bulk["generated_at"] = datetime.now(timezone.utc).isoformat()

    report: list[dict[str, Any]] = []
    sess = session or requests.Session()
    ua = user_agent or _DEFAULT_UA
    items = sorted(catalog.models.items())
    total = len(items)
    if limit is not None:
        items = items[:limit]
        total = len(items)

    for i, (catalog_key, entry) in enumerate(items, start=1):
        row: dict[str, Any] = {
            "каталог": catalog_key,
            "url": entry.url,
            "статус": "",
            "символов": 0,
        }
        prev = models_data.get(catalog_key) or {}
        if (
            resume
            and not refresh
            and prev.get("status") == "ok"
            and prev.get("description_html")
        ):
            row["статус"] = "кэш bulk"
            row["символов"] = len(str(prev.get("description_html", "")))
            report.append(row)
            if i % 100 == 0 or i == total:
                LOG.info("Прогресс %s/%s (кэш bulk)", i, total)
            continue

        LOG.info("Прогресс %s/%s: %s", i, total, catalog_key)
        cache_name = re.sub(r"[^\w\-]+", "_", catalog_key)[:120] + ".html"
        cache_path = cache_dir / cache_name
        try:
            desc = load_or_fetch_description(
                entry.url,
                cache_path,
                session=sess,
                timeout_sec=timeout_sec,
                user_agent=ua,
                refresh=refresh,
            )
            status = "ok" if desc else "пусто"
            models_data[catalog_key] = {
                "brand": entry.brand,
                "model": entry.model,
                "url": entry.url,
                "description_html": desc,
                "status": status,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            row["статус"] = status
            row["символов"] = len(desc)
            if bulk_path and (i % 10 == 0 or i == total):
                save_descriptions_bulk(bulk_path, bulk)
        except Exception as exc:  # noqa: BLE001
            models_data[catalog_key] = {
                "brand": entry.brand,
                "model": entry.model,
                "url": entry.url,
                "description_html": prev.get("description_html", ""),
                "status": f"ошибка: {exc}",
                "fetched_at": prev.get("fetched_at", ""),
            }
            row["статус"] = f"ошибка: {exc}"
            LOG.warning("4tochki %s/%s %s: %s", i, total, catalog_key, exc)
            if bulk_path and (i % 10 == 0 or i == total):
                save_descriptions_bulk(bulk_path, bulk)
        report.append(row)
        if pause_sec > 0:
            time.sleep(pause_sec)

    if bulk_path:
        save_descriptions_bulk(bulk_path, bulk)
    return bulk, report


def build_model_description_index(
    bulk: dict[str, Any],
    dictionary: DictionaryIndex,
    catalog: FourtochkiCatalog,
    *,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
) -> dict[str, str]:
    """Индекс ключ модели (канон словаря) → HTML."""
    index: dict[str, str] = {}
    models_data = bulk.get("models") or {}

    for catalog_key, entry in catalog.models.items():
        item = models_data.get(catalog_key) or {}
        html = str(item.get("description_html", "") or "").strip()
        if not html:
            continue
        index[catalog_key] = html
        index[model_key(entry.brand, entry.model)] = html

        fields, _src = dictionary.lookup(
            catalog_key=catalog_key,
            catalog_brand=entry.brand,
            catalog_model=entry.model,
            dummy_size=dummy_size,
        )
        if fields:
            mk = dict_model_key(fields)
            if mk:
                index[mk] = html
            stripped = strip_size_from_canonical_name(str(fields.get("name", "") or ""))
            if stripped:
                index[stripped] = html

    return index


def lookup_description_for_nom(
    nomenclature: str,
    *,
    goods_fields: dict[str, Any] | None,
    model_index: dict[str, str],
    catalog: FourtochkiCatalog,
) -> tuple[str, str, str]:
    """Возвращает (html, matched_by, catalog_key)."""
    nom = nomenclature.strip()
    if goods_fields:
        mk = dict_model_key(goods_fields)
        if mk and mk in model_index:
            cat_key = match_catalog_key(nom, catalog.models) or mk
            return model_index[mk], "dict_model", cat_key

    cat_key = match_catalog_key(nom, catalog.models)
    if cat_key and cat_key in model_index:
        return model_index[cat_key], "catalog_prefix", cat_key

    if nom:
        prefix_hits = [k for k in model_index if nom == k or nom.startswith(k + " ")]
        if prefix_hits:
            best = max(prefix_hits, key=len)
            return model_index[best], "index_prefix", best

    return "", "", ""


def link_descriptions_to_goods(
    bulk: dict[str, Any],
    catalog: FourtochkiCatalog,
    goods_nomenclatures: list[str],
    dictionary: DictionaryIndex,
    *,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
    goods_only: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Строки для Excel-таблицы описаний (одна строка = одна модель, без типоразмера)."""
    model_index = build_model_description_index(
        bulk,
        dictionary,
        catalog,
        dummy_size=dummy_size,
    )
    table_rows: dict[str, dict[str, Any]] = {}
    report: list[dict[str, Any]] = []
    seen_noms: set[str] = set()

    def _add_model_row(
        *,
        catalog_key: str,
        catalog_brand: str,
        catalog_model: str,
        html: str,
        goods_nom: str = "",
        goods_fields: dict[str, Any] | None = None,
        source: str = "4tochki",
    ) -> None:
        if not html:
            return
        row = make_description_table_row(
            catalog_key=catalog_key or model_key(catalog_brand, catalog_model),
            catalog_brand=catalog_brand,
            catalog_model=catalog_model,
            description_html=html,
            dictionary=dictionary,
            goods_nom=goods_nom,
            goods_fields=goods_fields,
            dummy_size=dummy_size,
            source=source,
        )
        key = row.get("ключ_модели", "")
        if key:
            table_rows[key] = row

    for nom in goods_nomenclatures:
        nom = str(nom or "").strip()
        if not nom or nom in seen_noms:
            continue
        seen_noms.add(nom)

        fields = dictionary.by_query.get(nom)
        html, matched_by, cat_key = lookup_description_for_nom(
            nom,
            goods_fields=fields,
            model_index=model_index,
            catalog=catalog,
        )
        entry = catalog.models.get(cat_key) if cat_key else None
        canon = resolve_canonical_model(
            catalog_key=cat_key or "",
            catalog_brand=entry.brand if entry else "",
            catalog_model=entry.model if entry else "",
            dictionary=dictionary,
            goods_nom=nom,
            goods_fields=fields,
            dummy_size=dummy_size,
        )

        row = {
            "номенклатура": nom,
            "словарь": bool(fields),
            "бренд": canon["бренд"],
            "модель": canon["модель"],
            "ключ_модели": canon["ключ_модели"],
            "имя_каноническое": canon["имя_каноническое"],
            "словарь_распознан": canon["словарь_распознан"],
            "каталог_4tochki": cat_key,
            "совпадение": matched_by,
            "есть_описание": bool(html),
            "символов": len(html),
        }
        report.append(row)

        if html and entry:
            _add_model_row(
                catalog_key=cat_key,
                catalog_brand=entry.brand,
                catalog_model=entry.model,
                html=html,
                goods_nom=nom,
                goods_fields=fields,
            )

    if not goods_only:
        models_data = bulk.get("models") or {}
        for catalog_key, entry in catalog.models.items():
            item = models_data.get(catalog_key) or {}
            html = str(item.get("description_html", "") or "").strip()
            if html:
                _add_model_row(
                    catalog_key=catalog_key,
                    catalog_brand=entry.brand,
                    catalog_model=entry.model,
                    html=html,
                )

    return list(table_rows.values()), report


def collect_model_keys_from_nomenclatures(
    nomenclatures: list[str],
    catalog: FourtochkiCatalog,
) -> dict[str, str]:
    """nom_key → catalog_key (только те, что нашлись в каталоге)."""
    out: dict[str, str] = {}
    for nom in nomenclatures:
        nom = str(nom or "").strip()
        if not nom:
            continue
        hit = catalog.lookup_url(nom)
        if not hit:
            continue
        catalog_key, _url = hit
        fields = parse_title_fields(nom)
        nom_key = model_key(fields.get("brand", ""), fields.get("model", ""))
        if not nom_key:
            nom_key = catalog_key
        out[nom_key] = catalog_key
    return out


def fetch_descriptions_for_keys(
    catalog: FourtochkiCatalog,
    keys: dict[str, str],
    *,
    cache_dir: Path,
    session: requests.Session | None = None,
    pause_sec: float = 1.0,
    timeout_sec: float = 60,
    user_agent: str = _DEFAULT_UA,
    refresh: bool = False,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """keys: nom_key → catalog_key. Возвращает строки таблицы (модель без типоразмера)."""
    table_rows: dict[str, dict[str, Any]] = {}
    report: list[dict[str, Any]] = []
    sess = session or requests.Session()

    items = list(keys.items())
    if limit is not None:
        items = items[:limit]

    for nom_key, catalog_key in items:
        entry = catalog.models.get(catalog_key)
        row: dict[str, Any] = {
            "ключ": nom_key,
            "каталог": catalog_key,
            "url": entry.url if entry else "",
            "статус": "",
            "символов": 0,
        }
        if not entry or not entry.url:
            row["статус"] = "нет в каталоге"
            report.append(row)
            continue

        cache_name = re.sub(r"[^\w\-]+", "_", catalog_key)[:120] + ".html"
        cache_path = cache_dir / cache_name
        try:
            desc = load_or_fetch_description(
                entry.url,
                cache_path,
                session=sess,
                timeout_sec=timeout_sec,
                user_agent=user_agent,
                refresh=refresh,
            )
            if not desc:
                row["статус"] = "пусто"
            else:
                # Ключи без словаря; link/export дополнят каноном
                mk = model_key(entry.brand, entry.model) or catalog_key
                table_rows[mk] = make_description_table_row(
                    catalog_key=catalog_key,
                    catalog_brand=entry.brand,
                    catalog_model=entry.model,
                    description_html=desc,
                    normalized_catalog=None,
                )
                row["статус"] = "ok"
                row["символов"] = len(desc)
        except Exception as exc:  # noqa: BLE001
            row["статус"] = f"ошибка: {exc}"
            LOG.warning("4tochki %s: %s", catalog_key, exc)
        report.append(row)
        if pause_sec > 0:
            time.sleep(pause_sec)

    return list(table_rows.values()), report


def bulk_json_to_table_rows(
    bulk: dict[str, Any],
    catalog: FourtochkiCatalog,
    dictionary: DictionaryIndex,
    *,
    dummy_size: str = DEFAULT_DUMMY_SIZE,
    canonical_only: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Описания bulk → строки Excel. Ключи только в каноне словаря."""
    models_data = bulk.get("models") or {}
    rows: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []

    for catalog_key, entry in catalog.models.items():
        item = models_data.get(catalog_key) or {}
        html = str(item.get("description_html", "") or "").strip()
        if not html:
            continue
        row = make_description_table_row(
            catalog_key=catalog_key,
            catalog_brand=entry.brand,
            catalog_model=entry.model,
            description_html=html,
            dictionary=dictionary,
            dummy_size=dummy_size,
        )
        if row.get("словарь_распознан") != "да":
            skipped.append(
                {
                    "каталог_4tochki": catalog_key,
                    "бренд_4tochki": entry.brand,
                    "модель_4tochki": entry.model,
                    "символов": len(html),
                }
            )
            if canonical_only:
                continue
        key = row.get("ключ_модели", "")
        if not key:
            continue
        rows[key] = row

    return list(rows.values()), skipped
