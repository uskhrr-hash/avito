"""Фото моделей с shinaufa.ru (hotlink).

Шины:  /images/large/tyres/{brand}/{model}.jpg
Диски: /images/large/wheels/{brand}/{model}_{color}.jpg
       Только exact color (HEAD на .jpg). Без HTML-fallback.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

LOG = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_CACHE_LOCK = Lock()
_HEAD_CACHE_KEY = "__head__"
_CACHE_SAVE_EVERY = 50
_cache_save_counter = 0
_last_request_mono = 0.0

# Транслит под имена файлов shinaufa.ru (ч→c, ж→j; не ISO/ГОСТ).
_RU_TRANS = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "j",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "c",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

_WHEEL_BRAND_ALIAS = {
    "кик": "kik",
    "k&k": "kik",
    "скад": "skad",
    "тзск": "tzsk",
    "евразиа": "evrazia",
    "тапо": "tapo",
    "tech line": "tech-line",
    "wheels up": "wheels-up",
    "x'trike": "xtrike",
    "x-trike": "xtrike",
    "xtrike": "xtrike",
    "x-race": "x-race",
    "cross street": "cross-street",
    "khomen wheels": "khomen-wheels",
    "replica fr": "replica-fr",
    "premium series": "premium-series",
    "gold wheel": "gold-wheel",
    "alcar stahlrad": "alcar-stahlrad",
    "yamato segun": "yamato-segun",
    "oz racing": "oz-racing",
}

_COLOR_RE = re.compile(
    r"(?P<color>"
    r"Алмаз\s+Ч[её]рный|Алмаз\s+Белый|Алмаз|"
    r"Дарк\s+Платинум|Dark\s+Platinum|"
    r"Ice\s+Black|Matt\s+Black\s+Painted|Black\s+Front\s+Polished|"
    r"Silver\s+Classic|Dark\s+Chrome|F-Silver|"
    r"Black-FP|Gray-FP|BK/FP|HSB|BDM|GRD|"
    r"Блэк\s+Джек|Хай\s+В[еэ]й|Нео\s+Классик|Бархат\s+новый|Бархат|"
    r"Ч[её]рный|Серебристый|Белый|Графит|Селена|Кварц|Серый|Сильвер|"
    r"\bBD\b|\bBL\b|\bSL\b|\bMB\b|\bSB\b|\bAB\b|\bBK\b|\bSF\b|\bGMF\b|\bBKF\b|\bS\b|\bHS\b|"
    r"Black|Gray|Grey|Silver|White"
    r")\s*$",
    re.IGNORECASE,
)

_COLOR_SLUG_ALIAS = {
    "chernyj": "cernyj",
    "almaz-chernyj": "almaz-cernyj",
    "blek-dzhek": "blek-djek",
    "bk-fp": "bkfp",
}


@dataclass(frozen=True)
class ShinaufaModelPhotoSettings:
    enabled: bool = False
    base_url: str = "https://shinaufa.ru/images/large/tyres"
    cache_file: Path | None = None
    head_timeout_sec: float = 5.0
    rate_limit_sec: float = 0.05  # ~20 req/s max to shinaufa.ru
    index_path: Path | None = None  # sqlite URL index
    live_fetch: bool = False  # False = только индекс (build_autoload)


def _is_wheels_base(base_url: str) -> bool:
    return "/wheels" in str(base_url or "").lower()


def shinaufa_slug(value: str) -> str:
    """Brand/model → URL slug (шины, латиница): 'Formula Energy' → 'formula'…"""
    s = str(value or "").strip().lower().replace("&", " and ")
    s = s.replace("/", "")
    s = _SLUG_RE.sub("-", s).strip("-")
    return s


def _translit_ru(value: str) -> str:
    out: list[str] = []
    for ch in str(value or "").lower():
        out.append(_RU_TRANS.get(ch, ch))
    return "".join(out)


def shinaufa_wheel_slug(value: str) -> str:
    """Brand/model/color → slug как на shinaufa.ru для дисков."""
    s = str(value or "").strip().lower().replace("&", " and ")
    s = s.replace("'", "").replace("'", "").replace("`", "")
    s = s.replace("/", "")
    s = _translit_ru(s)
    s = _SLUG_RE.sub("-", s).strip("-")
    return s


def shinaufa_wheel_brand_slug(brand: str) -> str:
    raw = str(brand or "").strip().lower()
    if raw in _WHEEL_BRAND_ALIAS:
        return _WHEEL_BRAND_ALIAS[raw]
    s = shinaufa_wheel_slug(brand)
    return _WHEEL_BRAND_ALIAS.get(s, s)


def extract_wheel_color_from_title(title: str) -> str:
    m = _COLOR_RE.search(str(title or "").strip())
    return m.group("color").strip() if m else ""


def shinaufa_model_photo_url(brand: str, model: str, *, base_url: str) -> str:
    if _is_wheels_base(base_url):
        b = shinaufa_wheel_brand_slug(brand)
        m = shinaufa_wheel_slug(model)
    else:
        b = shinaufa_slug(brand)
        m = shinaufa_slug(model)
    if not b or not m:
        return ""
    root = str(base_url or "").rstrip("/")
    return f"{root}/{b}/{m}.jpg"


def _wheel_color_slugs(color: str) -> list[str]:
    c = str(color or "").strip()
    if not c:
        return []
    primary = shinaufa_wheel_slug(c)
    out: list[str] = []
    for item in (primary, _COLOR_SLUG_ALIAS.get(primary, "")):
        if item and item not in out:
            out.append(item)
    return out


def _wheel_url_candidates(
    brand: str,
    model: str,
    *,
    base_url: str,
    color: str = "",
) -> list[str]:
    root = str(base_url or "").rstrip("/")
    b = shinaufa_wheel_brand_slug(brand)
    m = shinaufa_wheel_slug(model)
    if not b or not m:
        return []
    urls: list[str] = []
    for c in _wheel_color_slugs(color):
        urls.append(f"{root}/{b}/{m}_{c}.jpg")
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _cache_key(
    brand: str,
    model: str,
    *,
    base_url: str = "",
    color: str = "",
) -> str:
    kind = str(base_url or "").rstrip("/").rsplit("/", 1)[-1] or "tyres"
    if kind == "wheels":
        b = shinaufa_wheel_brand_slug(brand)
        m = shinaufa_wheel_slug(model)
        c = shinaufa_wheel_slug(color) if color else ""
        return f"{b}|{m}|{c}|wheels_v3"
    return f"{shinaufa_slug(brand)}|{shinaufa_slug(model)}|{kind}"


def _load_cache(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(path: Path | None, cache: dict) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        LOG.warning("shinaufa photo cache write failed: %s", exc)


def flush_shinaufa_photo_cache(settings: ShinaufaModelPhotoSettings) -> None:
    """Сохранить кэш на диск (вызов в конце build_autoload)."""
    global _cache_save_counter
    with _CACHE_LOCK:
        if _cache_save_counter <= 0 or settings.cache_file is None:
            return
        cache = _load_cache(settings.cache_file)
        _save_cache(settings.cache_file, cache)
        _cache_save_counter = 0


def _maybe_save_cache(path: Path | None, cache: dict) -> None:
    global _cache_save_counter
    _cache_save_counter += 1
    if _cache_save_counter >= _CACHE_SAVE_EVERY:
        _save_cache(path, cache)
        _cache_save_counter = 0


def _rate_limit_wait(rate_limit_sec: float) -> None:
    global _last_request_mono
    if rate_limit_sec <= 0:
        return
    now = time.monotonic()
    wait = rate_limit_sec - (now - _last_request_mono)
    if wait > 0:
        time.sleep(wait)
    _last_request_mono = time.monotonic()


def head_url_ok(
    url: str,
    *,
    timeout_sec: float = 5.0,
    cache: dict | None = None,
    rate_limit_sec: float = 0.05,
) -> bool:
    if not url:
        return False
    head_cache = None
    if cache is not None:
        head_cache = cache.setdefault(_HEAD_CACHE_KEY, {})
        hit = head_cache.get(url)
        if isinstance(hit, dict) and "ok" in hit:
            return bool(hit["ok"])

    _rate_limit_wait(rate_limit_sec)
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "shinaufa-avito-autoload/1.0"},
    )
    ok = False
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            ok = 200 <= int(code) < 300
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        ok = False

    if head_cache is not None:
        head_cache[url] = {"ok": ok}
    return ok


def lookup_shinaufa_model_photo_url(
    brand: str,
    model: str,
    settings: ShinaufaModelPhotoSettings,
    *,
    color: str = "",
    title: str = "",
) -> str | None:
    """
    Вернуть публичный URL фото модели или None.

    Порядок:
      1) sqlite-индекс (data/shinaufa_photo_index.sqlite)
      2) JSON-кэш (legacy)
      3) live HEAD — только если settings.live_fetch=True (warm_*)

    Шины: brand/model.jpg. Диски: model_{color}.jpg, exact color only.
    """
    if not settings.enabled:
        return None

    base = settings.base_url
    color_s = str(color or "").strip()
    if not color_s and title and _is_wheels_base(base):
        color_s = extract_wheel_color_from_title(title)

    key = _cache_key(brand, model, base_url=base, color=color_s)
    parts = key.split("|")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None

    kind = "wheels" if _is_wheels_base(base) else "tyres"

    # 1) sqlite index
    if settings.index_path is not None:
        try:
            from avito.shinaufa_photo_index import get_entry, index_connection

            with index_connection(settings.index_path) as conn:
                entry = get_entry(conn, key)
            if entry is not None:
                if int(entry.get("ok") or 0):
                    return str(entry.get("url") or "") or None
                return None
        except OSError as exc:
            LOG.warning("shinaufa photo index read failed: %s", exc)

    # 2) JSON cache (legacy) / 3) live HEAD
    with _CACHE_LOCK:
        cache = _load_cache(settings.cache_file)
        hit = cache.get(key)
        if isinstance(hit, dict) and "ok" in hit:
            return str(hit.get("url") or "") if hit.get("ok") else None

        if not settings.live_fetch:
            LOG.debug(
                "shinaufa index miss (no live): brand=%r model=%r color=%r",
                brand,
                model,
                color_s,
            )
            return None

        url: str | None = None
        rl = float(settings.rate_limit_sec or 0.05)
        if kind == "wheels":
            for cand in _wheel_url_candidates(
                brand, model, base_url=base, color=color_s
            ):
                if head_url_ok(
                    cand,
                    timeout_sec=settings.head_timeout_sec,
                    cache=cache,
                    rate_limit_sec=rl,
                ):
                    url = cand
                    break
        else:
            cand = shinaufa_model_photo_url(brand, model, base_url=base)
            if cand and head_url_ok(
                cand,
                timeout_sec=settings.head_timeout_sec,
                cache=cache,
                rate_limit_sec=rl,
            ):
                url = cand

        ok = bool(url)
        cache[key] = {"ok": ok, "url": url or ""}
        _maybe_save_cache(settings.cache_file, cache)

        if settings.index_path is not None:
            try:
                from avito.shinaufa_photo_index import index_connection, upsert_entry

                with index_connection(settings.index_path) as conn:
                    upsert_entry(
                        conn,
                        cache_key=key,
                        kind=kind,
                        brand=brand,
                        model=model,
                        color=color_s,
                        url=url or "",
                        ok=ok,
                        source="head",
                    )
            except OSError as exc:
                LOG.warning("shinaufa photo index write failed: %s", exc)

        if ok:
            LOG.info("shinaufa model photo OK: %s", url)
            return url
        LOG.info(
            "shinaufa model photo miss: brand=%r model=%r color=%r base=%s",
            brand,
            model,
            color_s,
            base,
        )
        return None
