#!/usr/bin/env python3
"""Копирует autoload xlsx в каталог фида на VPS и запускает upload через API."""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from avito.avito_api import (
    AvitoApiClient,
    get_autoload_profile,
    get_last_successful_upload,
    load_avito_api_config,
    trigger_autoload_upload,
    update_autoload_profile,
)
from avito.config import load_config
from avito.db import load_secrets

LOG = logging.getLogger("publish_avito_feed")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Публикация фида Avito (файл + API upload)")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "--source",
        type=Path,
        default=None,
        help="autoload xlsx (по умолчанию input/autoload_working.xlsx)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--no-profile", action="store_true")
    return p.parse_args()


def _load_publish_cfg(config_path: Path) -> dict:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return dict(raw.get("avito_publish") or {})


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    pub = _load_publish_cfg(args.config)
    if not pub.get("enabled", False) and not args.dry_run:
        LOG.error("avito_publish.enabled=false в config.yaml")
        return 1

    feed_url = str(pub.get("feed_public_url", "")).strip()
    feed_name = str(pub.get("feed_name", "shinaufa")).strip()
    feed_dir = Path(str(pub.get("feed_local_dir", "/var/www/avito-feed/feeds")))
    if not feed_url:
        LOG.error("Задайте avito_publish.feed_public_url")
        return 1

    app = load_config(args.config)
    source = args.source or (ROOT / app.autoload.working_file)
    if not source.is_absolute():
        source = args.config.parent / source
    if not source.is_file():
        LOG.error("Нет файла фида: %s (сначала build_autoload.py)", source)
        return 1

    target = feed_dir / "autoload.xlsx"
    LOG.info("Фид: %s → %s", source, target)
    if args.dry_run:
        LOG.info("dry-run: URL %s", feed_url)
        return 0

    feed_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    LOG.info("Скопировано (%s байт)", target.stat().st_size)

    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = args.config.parent / secrets_path
    client = AvitoApiClient(load_avito_api_config(load_secrets(secrets_path)))

    profile = get_autoload_profile(client)
    report_email = str(profile.get("report_email", "") or "").strip()
    feeds = profile.get("feeds_data") or []
    need_profile = not feeds or not any(
        str(f.get("feed_url", "")).strip() == feed_url for f in feeds if isinstance(f, dict)
    )

    if need_profile and not args.no_profile and pub.get("auto_set_profile", True):
        LOG.info("Обновляем профиль автозагрузки → %s", feed_url)
        update_autoload_profile(
            client,
            feed_name=feed_name,
            feed_url=feed_url,
            report_email=report_email,
        )
    elif need_profile:
        LOG.warning("feeds_data пустой — включите auto_set_profile или настройте URL в ЛК")

    if not args.no_upload and pub.get("auto_upload", True):
        LOG.info("Запуск upload…")
        try:
            trigger_autoload_upload(client)
            LOG.info("upload принят Avito")
        except RuntimeError as exc:
            if "429" in str(exc) or "час" in str(exc).lower():
                LOG.warning("%s (лимит 1 раз/час — нормально)", exc)
            else:
                raise
        try:
            last = get_last_successful_upload(client)
            if last:
                LOG.info("Последняя успешная загрузка:\n%s", json.dumps(last, ensure_ascii=False, indent=2)[:2000])
        except Exception as exc:
            LOG.warning("last_successful upload: %s", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
