#!/usr/bin/env python3
"""Генерация описаний моделей через DeepSeek → PostgreSQL."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from avito.config import load_config
from avito.db import descriptions_connection, load_secrets
from avito.deepseek_client import load_deepseek_config
from avito.description_generator import ModelGenInput, generate_model_html
from avito.descriptions_db import (
    STATUS_APPROVED,
    STATUS_DRAFT,
    html_to_plain,
    insert_description,
    insert_generation_log,
    list_deepseek_models_map,
    get_latest_generation_facts,
    list_models_without_approved,
    prompt_hash,
    upsert_tire_model,
)
from avito.model_descriptions import load_model_descriptions, load_model_descriptions_table, model_key
from avito.title_parse import infer_season_from_text
from avito.title_parse import parse_title_fields

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("generate_descriptions")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DeepSeek: описания моделей → БД")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "--goods",
        type=Path,
        default=None,
        help="goods.xlsx (по умолчанию compare.stock_file)",
    )
    p.add_argument(
        "--posting",
        type=Path,
        default=None,
        help="posting_*.xlsx вместо goods",
    )
    p.add_argument(
        "--only-missing",
        action="store_true",
        help="Только модели без approved в БД",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--model-key",
        action="append",
        default=[],
        help="Сгенерировать одну модель (можно несколько раз)",
    )
    p.add_argument(
        "--only-deepseek",
        action="store_true",
        help="Перегенерировать только модели с source=deepseek в БД (~30 шт.)",
    )
    p.add_argument(
        "--skip-if-updated-after",
        default=None,
        metavar="UTC",
        help="С --only-deepseek: пропустить модели, уже обновлённые после даты (2026-07-06 12:28:00)",
    )
    p.add_argument(
        "--all-catalog",
        action="store_true",
        help="Все модели из model_descriptions.xlsx (полная перегенерация каталога)",
    )
    p.add_argument(
        "--no-export",
        action="store_true",
        help="Не обновлять model_descriptions.xlsx после генерации",
    )
    p.add_argument(
        "--print",
        action="store_true",
        help="Показать текст описания в терминале (авто при одной модели)",
    )
    p.add_argument(
        "--print-html",
        action="store_true",
        help="С --print: вывести HTML, иначе — plain text",
    )
    return p.parse_args()


def _print_generation_result(
    *,
    model_key_str: str,
    season: str,
    html: str,
    as_html: bool = False,
) -> None:
    print("\n" + "=" * 72, flush=True)
    print(f"Модель: {model_key_str}", flush=True)
    if season:
        print(f"Сезон:  {season}", flush=True)
    print(f"Длина:  {len(html)} символов HTML", flush=True)
    print("-" * 72, flush=True)
    body = html if as_html else html_to_plain(html)
    print(body, flush=True)
    print("=" * 72 + "\n", flush=True)


def _nomenclatures_from_goods(path: Path, *, has_header: bool, col_index: int) -> list[str]:
    if not path.is_file():
        return []
    if has_header:
        df = pd.read_excel(path, sheet_name=0, header=0)
        col = df.columns[col_index] if col_index < len(df.columns) else df.columns[1]
        return [str(x).strip() for x in df[col] if str(x).strip()]
    df = pd.read_excel(path, sheet_name=0, header=None)
    return [str(x).strip() for x in df.iloc[:, col_index] if str(x).strip()]


def _nomenclatures_from_posting(path: Path) -> list[str]:
    if not path.is_file():
        return []
    df = pd.read_excel(path, sheet_name=0)
    col = "номенклатура" if "номенклатура" in df.columns else df.columns[0]
    return [str(x).strip() for x in df[col] if str(x).strip()]


def collect_model_keys(noms: list[str]) -> dict[str, dict[str, str]]:
    """{model_key: {brand, model, season, example_nom}}"""
    out: dict[str, dict[str, str]] = {}
    for nom in noms:
        fields = parse_title_fields(nom)
        brand = fields.get("brand", "")
        model = fields.get("model", "")
        key = model_key(brand, model)
        if not key:
            continue
        season = fields.get("season", "")
        if season == "Летние":
            inferred = infer_season_from_text(nom)
            if inferred:
                season = inferred
        if key not in out:
            out[key] = {
                "brand": brand,
                "model": model,
                "season": season,
                "example_nom": nom,
            }
    return out


def _resolve_season(
    *,
    meta: dict[str, str],
    model_key_str: str,
    source_facts: str,
) -> str:
    season = (meta.get("season") or "").strip()
    if season and season != "Летние":
        return season
    for text in (meta.get("example_nom", ""), model_key_str, source_facts):
        inferred = infer_season_from_text(text)
        if inferred:
            return inferred
    return season


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = load_config(args.config)
    autoload_cfg = app.autoload
    db_cfg = app.descriptions_db
    if not db_cfg.enabled:
        LOG.error("descriptions_db.enabled=false в config.yaml")
        return 1

    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = args.config.parent / secrets_path
    project_root = args.config.parent
    secrets = load_secrets(secrets_path)
    deepseek = load_deepseek_config(secrets)

    xlsx_path = app.autoload.model_descriptions_file
    if not xlsx_path.is_absolute():
        xlsx_path = args.config.parent / xlsx_path
    xlsx_facts = load_model_descriptions(xlsx_path)

    if args.only_deepseek:
        with descriptions_connection(secrets, project_root=project_root) as conn:
            models_map = list_deepseek_models_map(
                conn,
                skip_if_updated_after=args.skip_if_updated_after or "",
            )
    elif args.all_catalog:
        models_map = {}
        df = load_model_descriptions_table(xlsx_path)
        for _, row in df.iterrows():
            key = str(row.get("ключ_модели", "") or "").strip()
            if not key:
                continue
            brand = str(row.get("бренд", "") or "").strip()
            model = str(row.get("модель", "") or "").strip()
            if not brand and " " in key:
                brand, model = key.split(" ", 1)
            models_map[key] = {
                "brand": brand,
                "model": model,
                "season": "",
                "example_nom": "",
            }
    elif args.model_key:
        models_map: dict[str, dict[str, str]] = {}
        for k in args.model_key:
            kk = k.strip()
            if not kk:
                continue
            brand, model = "", ""
            if " " in kk:
                brand, model = kk.split(" ", 1)
            models_map[kk] = {
                "brand": brand,
                "model": model,
                "season": "",
                "example_nom": "",
            }
    elif args.posting:
        posting = args.posting if args.posting.is_absolute() else args.config.parent / args.posting
        noms = _nomenclatures_from_posting(posting)
        models_map = collect_model_keys(noms)
    else:
        goods = args.goods or app.compare.stock_file
        if not goods.is_absolute():
            goods = args.config.parent / goods
        cmp = app.compare
        col_i = int(cmp.stock_indexes.get("nomenclature", 1))
        noms = _nomenclatures_from_goods(
            goods,
            has_header=cmp.stock_has_header,
            col_index=col_i,
        )
        models_map = collect_model_keys(noms)

    keys = list(models_map.keys())
    if args.only_missing:
        with descriptions_connection(secrets, project_root=project_root) as conn:
            keys = list_models_without_approved(conn, keys)
    if args.limit:
        keys = keys[: args.limit]

    if not keys:
        LOG.info("Нет моделей для генерации")
        return 0

    LOG.info("К генерации: %s моделей", len(keys))
    show_result = args.print or len(keys) == 1
    if args.dry_run:
        for k in keys:
            LOG.info("  %s", k)
        return 0

    status = STATUS_APPROVED if db_cfg.auto_approve_llm else STATUS_DRAFT
    ok = err = 0

    with descriptions_connection(secrets, project_root=project_root) as conn:
        for key in keys:
            meta = models_map.get(key, {})
            brand = meta.get("brand", "")
            model = meta.get("model", "")
            if not brand and " " in key:
                brand, model = key.split(" ", 1)

            tire_id = upsert_tire_model(
                conn,
                model_key=key,
                brand=brand,
                model=model,
            )
            source_facts = xlsx_facts.get(key, "")
            if args.only_deepseek:
                logged_facts = get_latest_generation_facts(conn, tire_id)
                if logged_facts:
                    source_facts = logged_facts
            season = _resolve_season(meta=meta, model_key_str=key, source_facts=source_facts)
            inp = ModelGenInput(
                model_key=key,
                brand=brand,
                model=model,
                season=season,
                source_facts=source_facts,
            )
            try:
                html, chat, user_prompt = generate_model_html(
                    inp,
                    cfg=deepseek,
                    max_output_chars=db_cfg.llm_max_chars,
                    store_brief=autoload_cfg.llm_store_brief,
                )
            except Exception as exc:
                LOG.error("%s: %s", key, exc)
                err += 1
                continue

            desc_id = insert_description(
                conn,
                tire_model_id=tire_id,
                html=html,
                status=status,
                source="deepseek",
            )
            ph = prompt_hash(user_prompt)
            insert_generation_log(
                conn,
                tire_model_id=tire_id,
                model_description_id=desc_id,
                provider="deepseek",
                model_name=deepseek.model,
                prompt_hash=ph,
                prompt_text=user_prompt,
                input_facts=source_facts,
                raw_response=chat.content,
                tokens_in=chat.tokens_in,
                tokens_out=chat.tokens_out,
            )
            LOG.info(
                "%s → %s chars, status=%s, tokens=%s/%s",
                key,
                len(html),
                status,
                chat.tokens_in,
                chat.tokens_out,
            )
            if show_result:
                _print_generation_result(
                    model_key_str=key,
                    season=season,
                    html=html,
                    as_html=args.print_html,
                )
            ok += 1

    LOG.info("Готово: успешно %s, ошибок %s", ok, err)

    if ok and not args.no_export and not args.dry_run:
        from export_descriptions_db import export_descriptions_excel

        try:
            export_descriptions_excel(app, config_path=args.config)
        except Exception as exc:
            LOG.error(
                "Описания в БД есть, но Excel не обновлён: %s. "
                "Запустите: python export_descriptions_db.py",
                exc,
            )
            return 1

    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
