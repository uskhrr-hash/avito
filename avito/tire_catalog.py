"""Справочник Brand/Model/Сезонность Avito + нормализация из названия."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

LOG = logging.getLogger(__name__)

_DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "data" / "avito_tire_catalog.json"

# Частые расхождения названия склада ↔ справочник Avito.
_BRAND_ALIASES: dict[str, str] = {
    "yazd": "Yazd Tire",
    "yazd tire": "Yazd Tire",
    "ikon": "Ikon Tyres",
    "ikon tyres": "Ikon Tyres",
    "kama": "КАМА (Нижнекамский шинный завод)",
    "кама": "КАМА (Нижнекамский шинный завод)",
    "нкшз": "КАМА (Нижнекамский шинный завод)",
    "bfgoodrich": "BFGoodrich",
    "bf goodrich": "BFGoodrich",
    "michelin": "Michelin",
    "pirelli": "Pirelli",
    "nokian": "Nokian Tyres",
    "nokian tyres": "Nokian Tyres",
    "hankook": "Hankook",
    "goodyear": "Goodyear",
    "continental": "Continental",
    "bridgestone": "Bridgestone",
    "yokohama": "Yokohama",
    "toyo": "Toyo",
    "kumho": "Kumho",
    "sailun": "Sailun",
    "viatti": "Viatti",
    "cordiant": "Cordiant",
    "gislaved": "Gislaved",
    "formula": "Formula",
    "landsail": "Landsail",
    "doublestar": "DoubleStar",
    "double star": "DoubleStar",
    "doubleestar": "DoubleStar",
    "ling long": "Linglong",
    "linglong": "Linglong",
    "nortec": "NorTec",
    "nor tec": "NorTec",
    "voltyre": "Волтайр",
    "вольтайр": "Волтайр",
    "волтайр": "Волтайр",
    "voltair": "Волтайр",
}

# Явные синонимы модели (после soft-ключа), если автоматика всё ещё мимо.
# Ключ — _soft_model_key(сырое имя без бренда).
_MODEL_ALIASES: dict[str, str] = {
    "iceguard stud ig65": "IceGuard Stud IG65",
    "ice guard stud ig65": "IceGuard Stud IG65",
    "iceguard studless ig60": "Ice Guard IG60",
    "ice guard studless ig60": "Ice Guard IG60",
    "iceguard studless ig60a": "Ice Guard IG60A",
    "ice guard studless ig60a": "Ice Guard IG60A",
    "bluarth van all season ry61": "BluEarth-Van RY61",
    "blu earth van all season ry61": "BluEarth-Van RY61",
    "ion i cept iw01": "Winter i'cept iON X IW01A",
    "ion icept iw01": "Winter i'cept iON X IW01A",
    "ion i cept suv iw01a": "Winter iON i'cept SUV IW01A",
    "ion icept suv iw01a": "Winter iON i'cept SUV IW01A",
    "bravo hp m3": "Bravo HP-M3",
    "hp m3 bravo": "Bravo HP-M3",
    "cinturato p7c2": "Cinturato P7 (P7C2)",
    "cinturato p7 c2": "Cinturato P7 (P7C2)",
    "solus 4s ha31": "Solus HA31",
    "solus 4 s ha31": "Solus HA31",
    "geolandar g031a": "Geolandar A/T G031A",
    "geolandar g031 a": "Geolandar A/T G031A",
}

# Слишком короткие/общие имена модели — только точное soft-совпадение.
_GENERIC_MODEL_SOFT = frozenset(
    {
        "ice",
        "winter",
        "summer",
        "gt",
        "ultra",
        "sport",
        "suv",
        "van",
        "at",
        "ht",
        "mt",
        "me",
        "rs",
        "rs2",
    }
)


def _norm(s: str) -> str:
    s = str(s or "").strip().lower().replace("ё", "е")
    s = re.sub(r"[\"'`*]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _soft_model_key(s: str) -> str:
    """Ключ для сопоставления склада ↔ Avito (апострофы, дефисы, i'Pike, LW 71…)."""
    s = _norm(s)
    s = s.replace("-", " ").replace("/", " ").replace("_", " ")
    s = s.replace("&", " ")
    s = re.sub(r"[()]", " ", s)
    # Частые семейства с разным написанием.
    s = s.replace("ice guard", "iceguard")
    s = s.replace("contiwintercontact", "wintercontact")
    s = s.replace("conti wintercontact", "wintercontact")
    s = re.sub(r"\bgreen\s*max\b", "greenmax", s)
    s = re.sub(r"\bx\s*fit\b", "xfit", s)
    s = re.sub(r"\bp\s*zero\b", "pzero", s)
    s = re.sub(r"\bblu\s*earth\b", "bluarth", s)
    # Hankook: i'Pike / i Pike / I'Cept → ipike / icept
    s = re.sub(r"\bi\s*pike\b", "ipike", s)
    s = re.sub(r"\bi\s*cept\b", "icept", s)
    # Буква+номер: LW 71 → lw71, Evo 3 → evo3, V 522 → v522
    s = re.sub(r"([a-zа-я])\s+(\d)", r"\1\2", s)
    # Номер+буквы: 4S → 4 s, 4Seasons → 4 seasons, TS850P → ts850 p, W429A → w429 a
    s = re.sub(r"(\d)([a-zа-я]+)", r"\1 \2", s)
    # Короткие фрагменты: AT M → atm, A T → at, H T → ht, S T → st
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\b([a-zа-я]{1,3})\s+([a-zа-я])\b", r"\1\2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _token_sort_key(s: str) -> str:
    return " ".join(sorted(_soft_model_key(s).split()))


def _has_code_token(tokens: set[str]) -> bool:
    """Есть ли артикул модели (W429, IG65, V522, LD01…)."""
    for t in tokens:
        if re.search(r"\d", t) and len(t) >= 2:
            return True
    return False


@dataclass(frozen=True)
class TireCatalog:
    seasons: frozenset[str]
    quantities: frozenset[str]
    brands: tuple[str, ...]
    models: tuple[str, ...]
    brands_by_norm: dict[str, str]
    models_by_norm: dict[str, str]
    models_by_soft: dict[str, str]
    models_by_tokens: dict[str, str]


@lru_cache(maxsize=4)
def load_tire_catalog(path: str | None = None) -> TireCatalog | None:
    p = Path(path) if path else _DEFAULT_CATALOG
    if not p.is_file():
        LOG.warning("Нет справочника шин Avito: %s", p)
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    brands = tuple(str(x).strip() for x in (raw.get("brands") or []) if str(x).strip())
    models = tuple(str(x).strip() for x in (raw.get("models") or []) if str(x).strip())
    seasons = frozenset(str(x).strip() for x in (raw.get("seasons") or []) if str(x).strip())
    quantities = frozenset(
        str(x).strip() for x in (raw.get("quantities") or []) if str(x).strip()
    )
    models_by_soft: dict[str, str] = {}
    models_by_tokens: dict[str, str] = {}
    for m in models:
        soft = _soft_model_key(m)
        # Более длинное каноническое имя предпочтительнее при коллизии soft-ключа.
        prev = models_by_soft.get(soft)
        if prev is None or len(m) >= len(prev):
            models_by_soft[soft] = m
        tk = _token_sort_key(m)
        prev_t = models_by_tokens.get(tk)
        if prev_t is None or len(m) >= len(prev_t):
            models_by_tokens[tk] = m
    return TireCatalog(
        seasons=seasons,
        quantities=quantities,
        brands=brands,
        models=models,
        brands_by_norm={_norm(b): b for b in brands},
        models_by_norm={_norm(m): m for m in models},
        models_by_soft=models_by_soft,
        models_by_tokens=models_by_tokens,
    )


def match_brand(prefix: str, catalog: TireCatalog) -> tuple[str, str]:
    """
    По тексту до размера → (канонический brand, остаток для модели).
    Сначала longest catalog brand, затем alias.
    """
    text = str(prefix or "").strip()
    if not text:
        return "", ""
    low = _norm(text)
    words = text.split()

    best = ""
    best_canon = ""
    for norm_b, canon in catalog.brands_by_norm.items():
        if low == norm_b or low.startswith(norm_b + " "):
            if len(norm_b) > len(best):
                best = norm_b
                best_canon = canon
    if best_canon:
        matched_words = len(best.split())
        rest = " ".join(words[matched_words:]).strip()
        return best_canon, rest

    for alias, target in sorted(_BRAND_ALIASES.items(), key=lambda x: -len(x[0])):
        if low == alias or low.startswith(alias + " "):
            if _norm(target) not in catalog.brands_by_norm:
                continue
            canon = catalog.brands_by_norm[_norm(target)]
            matched_words = len(alias.split())
            rest = " ".join(words[matched_words:]).strip()
            return canon, rest

    if not words:
        return "", ""
    first = _norm(words[0])
    if first in catalog.brands_by_norm:
        return catalog.brands_by_norm[first], " ".join(words[1:]).strip()
    if first in _BRAND_ALIASES:
        target = _BRAND_ALIASES[first]
        if _norm(target) in catalog.brands_by_norm:
            return catalog.brands_by_norm[_norm(target)], " ".join(words[1:]).strip()
    return words[0], " ".join(words[1:]).strip()


@lru_cache(maxsize=1)
def _model_aliases_soft() -> dict[str, str]:
    return {_soft_model_key(k): v for k, v in _MODEL_ALIASES.items()}


def _resolve_alias(soft: str, catalog: TireCatalog) -> str:
    target = _model_aliases_soft().get(soft) or _MODEL_ALIASES.get(soft)
    if not target:
        return ""
    if _norm(target) in catalog.models_by_norm:
        return catalog.models_by_norm[_norm(target)]
    soft_t = _soft_model_key(target)
    if soft_t in catalog.models_by_soft:
        return catalog.models_by_soft[soft_t]
    return ""


def match_model(model_raw: str, brand: str, catalog: TireCatalog) -> str:
    """Подобрать модель из справочника; пусто если нет уверенного совпадения."""
    raw = str(model_raw or "").strip()
    if not raw:
        return ""

    brand_short = brand.split("(")[0].strip() if brand else ""
    brand_token = _norm(brand_short)
    soft_raw = _soft_model_key(raw)

    probes = [raw]
    if brand_short:
        probes.append(f"{brand_short} {raw}")
    probes = sorted({p for p in probes if p}, key=lambda x: (-len(x), x))

    # 1) Точное совпадение по norm / soft / token-reorder / alias
    for probe in probes:
        low = _norm(probe)
        if low in catalog.models_by_norm:
            return catalog.models_by_norm[low]
        soft = _soft_model_key(probe)
        if soft in catalog.models_by_soft:
            return catalog.models_by_soft[soft]
        tok = _token_sort_key(probe)
        if tok in catalog.models_by_tokens:
            return catalog.models_by_tokens[tok]
        aliased = _resolve_alias(soft, catalog)
        if aliased:
            return aliased

    # Alias только по сырой модели (без бренда)
    aliased = _resolve_alias(soft_raw, catalog)
    if aliased:
        return aliased
    # Также по «сырому» norm до soft (на случай ключей в _MODEL_ALIASES)
    aliased = _resolve_alias(_norm(raw), catalog)
    if aliased:
        return aliased

    q_tokens = set(soft_raw.split())
    if not q_tokens:
        return ""

    candidates: list[tuple[int, str]] = []
    for soft_m, canon in catalog.models_by_soft.items():
        m_tokens = set(soft_m.split())
        if len(soft_m) < 3 or len(m_tokens) == 0:
            continue

        # Не цеплять общие «Ice»/«Winter» без точного soft-ключа.
        if soft_m in _GENERIC_MODEL_SOFT and soft_m != soft_raw:
            continue
        if soft_m in _GENERIC_MODEL_SOFT and soft_raw != soft_m:
            continue

        inter = q_tokens & m_tokens
        if not inter:
            continue

        # Подмножество: все токены каталога есть в запросе (каталог короче)
        # или почти все токены запроса есть в каталоге.
        cover_q = len(inter) / len(q_tokens)
        cover_m = len(inter) / len(m_tokens)
        if cover_q < 0.6 and cover_m < 0.85:
            continue
        # Короткие кандидаты без кода модели — только почти полное покрытие.
        if len(soft_m) < 8 and not _has_code_token(m_tokens) and cover_m < 0.99:
            continue
        # Если в запросе есть код (W429…), кандидат должен делить хотя бы один код.
        if _has_code_token(q_tokens) and not (inter & {t for t in q_tokens if re.search(r"\d", t)}):
            continue

        score = int(cover_q * 50 + cover_m * 40)
        if soft_m == soft_raw:
            score += 50
        if _token_sort_key(raw) == _token_sort_key(canon):
            score += 40
        if brand_token and brand_token in soft_m:
            score += 15
        # Предпочитать более длинные/конкретные имена
        score += min(15, len(soft_m) // 4)
        score -= min(15, abs(len(soft_m) - len(soft_raw)) // 3)
        # Штраф за лишние токены у кандидата (Winter …) при коротком запросе
        extra = m_tokens - q_tokens
        if extra and cover_q >= 0.85:
            score -= 5 * len(extra)
        candidates.append((score, canon))

    if not candidates:
        return ""
    candidates.sort(key=lambda x: (-x[0], -len(x[1]), x[1]))
    best_score, best = candidates[0]
    if best_score < 70:
        return ""
    # Защита от ложных коротких совпадений
    if _soft_model_key(best) in _GENERIC_MODEL_SOFT and _soft_model_key(best) != soft_raw:
        return ""
    return best


def normalize_title_fields(
    fields: dict[str, str],
    *,
    title: str = "",
    catalog: TireCatalog | None = None,
    catalog_path: str | None = None,
) -> dict[str, str]:
    """Уточнить brand/model/season по справочнику Avito."""
    out = dict(fields)
    cat = catalog or load_tire_catalog(catalog_path)
    if out.get("season") == "Зимние":
        out["season"] = "Зимние нешипованные"
    if cat is None:
        return out
    if out.get("season") and out["season"] not in cat.seasons:
        out["season"] = "Летние" if "Летние" in cat.seasons else out["season"]

    b0 = str(fields.get("brand") or "").strip()
    m0 = str(fields.get("model") or "").strip()
    prefix = (b0 + " " + m0).strip()
    if title and not prefix:
        prefix = str(title).strip()

    brand, model_rest = match_brand(prefix, cat)
    if brand and _norm(brand) in cat.brands_by_norm:
        out["brand"] = cat.brands_by_norm[_norm(brand)]
    else:
        aliased = _BRAND_ALIASES.get(_norm(b0))
        if aliased and _norm(aliased) in cat.brands_by_norm:
            out["brand"] = cat.brands_by_norm[_norm(aliased)]
            model_rest = m0
        else:
            out["brand"] = b0

    model_src = model_rest or m0
    matched = match_model(model_src, out.get("brand") or "", cat)
    # Не оставляем значение вне справочника — иначе Avito 1073 на Модель.
    out["model"] = matched or ""
    return out
