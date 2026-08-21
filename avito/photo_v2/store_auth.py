"""Минимальная загрузка паролей магазинов для Photo v2 (без admin/points/chat)."""
from __future__ import annotations

import hmac
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path

import yaml

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoreLogin:
    prefix: str
    label: str
    password: str


@dataclass(frozen=True)
class PhotoV2Runtime:
    project_root: Path
    secrets_file: Path
    session_secret: str
    session_max_age_hours: int
    host: str
    port: int
    stores: tuple[StoreLogin, ...]
    public_mount_path: str = "/"


def verify_store_password(store: StoreLogin, password: str) -> bool:
    """Constant-time compare; unequal lengths → False (never 500)."""
    expected = str(store.password or "")
    given = str(password or "")
    if len(expected) != len(given):
        return False
    return hmac.compare_digest(expected, given)


def _resolve(root: Path, path: Path | str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (root / p)


def load_photo_v2_runtime(
    *,
    config_path: Path,
    project_root: Path | None = None,
    host: str | None = None,
    port: int | None = None,
) -> PhotoV2Runtime:
    """Читает stores + photo_upload.stores passwords из secrets — без SQLite/admin."""
    root = project_root or config_path.parent
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    # stores.yaml path (same as main config)
    stores_cfg = raw.get("stores") or {}
    if isinstance(stores_cfg, dict) and stores_cfg.get("file"):
        stores_path = _resolve(root, stores_cfg["file"])
    else:
        stores_path = root / "stores.yaml"

    stores_raw = yaml.safe_load(stores_path.read_text(encoding="utf-8")) or {}
    store_items = stores_raw.get("stores") or []

    stock_sources = raw.get("stock_sources") or {}
    secrets_path = _resolve(root, stock_sources.get("secrets_file") or "secrets.yaml")
    secrets_raw = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    pu_secrets = secrets_raw.get("photo_upload") or {}
    store_passwords = pu_secrets.get("stores") or {}

    session_secret = str(pu_secrets.get("session_secret", "")).strip()
    if not session_secret:
        session_secret = secrets.token_hex(32)
        LOG.warning("photo_upload.session_secret missing — ephemeral secret for this process")

    pu = raw.get("photo_upload") or {}
    session_hours = int(pu.get("session_max_age_hours", 72) or 72)

    stores: list[StoreLogin] = []
    for item in store_items:
        if not isinstance(item, dict):
            continue
        prefix = str(item.get("prefix", "")).strip()
        if not prefix:
            continue
        password = str(store_passwords.get(prefix, "")).strip()
        if not password:
            raise RuntimeError(
                f"Задайте photo_upload.stores.{prefix} в {secrets_path.name}"
            )
        stores.append(
            StoreLogin(
                prefix=prefix,
                label=str(item.get("label", prefix)).strip() or prefix,
                password=password,
            )
        )
    if not stores:
        raise RuntimeError(f"Нет магазинов в {stores_path}")

    return PhotoV2Runtime(
        project_root=root,
        secrets_file=secrets_path,
        session_secret=session_secret,
        session_max_age_hours=max(1, session_hours),
        host=host or "127.0.0.1",
        port=int(port if port is not None else 8766),
        stores=tuple(stores),
    )
