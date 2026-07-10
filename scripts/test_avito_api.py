#!/usr/bin/env python3
"""Проверка OAuth и доступа к Avito API (без публикации)."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from avito.avito_api import AvitoApiClient, get_autoload_profile, get_self_user, load_avito_api_config
from avito.config import load_config
from avito.db import load_secrets

LOG = logging.getLogger("test_avito_api")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = load_config(ROOT / "config.yaml")
    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = ROOT / secrets_path
    secrets = load_secrets(secrets_path)

    try:
        cfg = load_avito_api_config(secrets)
    except ValueError as exc:
        LOG.error("%s", exc)
        LOG.error("Добавьте в %s блок avito: client_id, client_secret", secrets_path)
        return 1

    client = AvitoApiClient(cfg)
    token = client.get_token()
    LOG.info("Токен получен (%s символов)", len(token))

    try:
        user = get_self_user(client)
        LOG.info("Аккаунт: %s", json.dumps(user, ensure_ascii=False, indent=2)[:1500])
    except Exception as exc:
        LOG.warning("accounts/self: %s", exc)

    try:
        profile = get_autoload_profile(client)
        LOG.info("Автозагрузка profile:")
        LOG.info("%s", json.dumps(profile, ensure_ascii=False, indent=2)[:3000])
    except Exception as exc:
        LOG.warning("autoload/v2/profile: %s", exc)
        LOG.warning("Возможно, приложению не выдан доступ к API «Автозагрузка» в developers.avito.ru")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
