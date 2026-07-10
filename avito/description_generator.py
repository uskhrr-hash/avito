"""Генерация продающих описаний моделей через LLM."""

from __future__ import annotations



import re

from dataclasses import dataclass



from avito.deepseek_client import ChatResult, DeepSeekConfig, chat_completion

from avito.descriptions_db import html_to_plain



_FENCE_RE = re.compile(r"^```(?:html)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)



_DEFAULT_STORE_BRIEF = "Шинный Центр №1, Уфа"


def build_system_prompt(*, store_brief: str = "") -> str:
    return """Ты копирайтер каталога шин. Пиши на русском живо и продающе: выгоды для покупателя, сценарии использования.

Без выдуманных цифр и характеристик, которых нет во входных фактах.

КРИТИЧНО: сезонность модели (летняя / зимняя / всесезонная) — из поля «Сезон» и названия модели.
Никогда не описывай зимнюю шину как летнюю и наоборот. Упоминай снег, лёд, мороз только для зимних;
жару, дождь, асфальт — для летних, если это соответствует сезону.

Разрешённые HTML-теги: p, br, strong, em, ul, ol, li. Без markdown, без ```.

Не пиши про магазин, шиномонтаж, подбор, цену, артикул, телефон и адрес — это в другом блоке объявления.
Только описание модели шины, без призыва «купите у нас».

Длина: 700–1400 символов HTML."""





@dataclass(frozen=True)

class ModelGenInput:

    model_key: str

    brand: str

    model: str

    season: str = ""

    source_facts: str = ""





def build_user_prompt(inp: ModelGenInput, *, max_chars: int = 2500) -> str:
    from avito.title_parse import infer_season_from_text

    season = (inp.season or "").strip()
    if not season:
        season = infer_season_from_text(f"{inp.brand} {inp.model} {inp.model_key}")
    if not season and inp.source_facts:
        season = infer_season_from_text(inp.source_facts)

    parts = [
        f"Модель шины: {inp.model_key}",
    ]
    if season:
        parts.append(
            f"Сезон (обязательно соблюдать в тексте): {season}. "
            f"В первом абзаце явно укажи тип: летняя / зимняя / всесезонная — по этому полю."
        )
    else:
        parts.append(
            "Сезон по названию неочевиден — не приписывай летнюю или зимнюю "
            "без явных признаков в фактах ниже."
        )

    if inp.source_facts:

        plain = html_to_plain(inp.source_facts)

        if len(plain) > 2000:

            plain = plain[:2000] + "…"

        parts.append(

            "Исходные факты с каталога (перефразируй, не копируй дословно):\n" + plain

        )

    parts.append(
        "Напиши продающее описание модели для Avito:\n"
        "- для кого и каких условий подходит эта модель;\n"
        "- 3–5 конкретных выгод (сцепление, комфорт, экономия, тишина и т.д. — по фактам).\n"
        "Только HTML, без упоминания магазина и услуг."
    )

    text = "\n\n".join(parts)

    return text[: max_chars + 500]





def normalize_llm_html(text: str) -> str:

    t = text.strip()

    t = _FENCE_RE.sub("", t).strip()

    if t and not t.lstrip().startswith("<"):

        t = f"<p>{t}</p>"

    return t





def generate_model_html(

    inp: ModelGenInput,

    *,

    cfg: DeepSeekConfig,

    max_output_chars: int = 2500,

    store_brief: str = "",

) -> tuple[str, ChatResult, str]:

    user_prompt = build_user_prompt(inp)

    system = build_system_prompt(store_brief=store_brief)

    result = chat_completion(cfg, system=system, user=user_prompt)

    html = normalize_llm_html(result.content)

    if len(html) > max_output_chars:

        html = html[:max_output_chars].rsplit("<", 1)[0] + "…</p>"

    if not html.strip():

        raise RuntimeError("LLM вернул пустой текст")

    return html, result, user_prompt


