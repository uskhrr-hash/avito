"""Настройки и пароли для веб-загрузки фото."""
from __future__ import annotations

import logging
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from avito.config import AppConfig, load_config
from avito.photo_upload import db as photo_db
from avito.stores import StoresConfig

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoreLogin:
    prefix: str
    label: str
    password: str
    ushk_supplier: str | None = None


@dataclass(frozen=True)
class PhotoUploadRuntime:
    project_root: Path
    config: AppConfig
    stores_config: StoresConfig
    secrets_file: Path
    photos_dir: Path
    stock_file: Path
    output_dir: Path
    session_secret: str
    stores: tuple[StoreLogin, ...]
    photo_layout: str
    prefix_in_filename: bool
    jpeg_quality: int
    jpeg_max_dimension: int
    max_upload_bytes: int
    public_mount_path: str
    db_path: Path
    contributors_prefix: str
    points_per_photo: int
    contributor_max_photos: int

    def db(self) -> sqlite3.Connection:
        conn = photo_db.connect(self.db_path)
        photo_db.init_db(conn)
        return conn

    def close_db(self, conn: sqlite3.Connection | None = None) -> None:
        if conn is not None:
            conn.close()


def load_photo_upload_runtime(
    *,
    config_path: Path,
    project_root: Path | None = None,
) -> PhotoUploadRuntime:
    root = project_root or config_path.parent
    app = load_config(config_path)
    if not app.photo_upload.enabled:
        raise RuntimeError("photo_upload.enabled=false в config.yaml")

    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = root / secrets_path
    secrets_raw = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    pu_secrets = secrets_raw.get("photo_upload") or {}

    session_secret = str(pu_secrets.get("session_secret", "")).strip()
    if not session_secret:
        session_secret = secrets.token_hex(32)

    store_passwords = pu_secrets.get("stores") or {}
    stores: list[StoreLogin] = []
    for store in app.stores.stores:
        password = str(store_passwords.get(store.prefix, "")).strip()
        if not password:
            raise RuntimeError(
                f"Задайте photo_upload.stores.{store.prefix} в {secrets_path.name}"
            )
        stores.append(
            StoreLogin(
                prefix=store.prefix,
                label=store.label,
                password=password,
                ushk_supplier=store.ushk_supplier,
            )
        )

    photos_dir = app.autoload.photos_local_dir
    if photos_dir is None:
        raise RuntimeError("Задайте autoload.photos_local_dir в config.yaml")
    if not photos_dir.is_absolute():
        photos_dir = root / photos_dir

    stock_file = app.compare.stock_file
    if not stock_file.is_absolute():
        stock_file = root / stock_file

    output_dir = root / "output"
    max_mb = max(1, app.photo_upload.max_upload_mb)
    stores_config = app.stores

    db_path = app.photo_upload.db_path
    if not db_path.is_absolute():
        db_path = root / db_path

    contrib = app.photo_upload.contributors_prefix.strip() or "contributors"

    runtime = PhotoUploadRuntime(
        project_root=root,
        config=app,
        stores_config=stores_config,
        secrets_file=secrets_path,
        photos_dir=photos_dir,
        stock_file=stock_file,
        output_dir=output_dir,
        session_secret=session_secret,
        stores=tuple(stores),
        photo_layout=app.autoload.photo_layout,
        prefix_in_filename=app.autoload.photo_store_prefix_in_filename,
        jpeg_quality=app.autoload.jpeg_quality,
        jpeg_max_dimension=app.autoload.jpeg_max_dimension,
        max_upload_bytes=max_mb * 1024 * 1024,
        public_mount_path=app.photo_upload.public_mount_path,
        db_path=db_path,
        contributors_prefix=contrib,
        points_per_photo=app.photo_upload.points_per_photo,
        contributor_max_photos=app.photo_upload.contributor_max_photos,
    )

    admin_cfg = pu_secrets.get("admin") or {}
    admin_login = str(admin_cfg.get("login", "")).strip()
    admin_password = str(admin_cfg.get("password", "")).strip()
    admin_name = str(admin_cfg.get("display_name", "Админ")).strip() or "Админ"
    if admin_login and admin_password:
        conn = runtime.db()
        try:
            photo_db.bootstrap_admin(
                conn,
                login=admin_login,
                password=admin_password,
                display_name=admin_name,
            )
        except Exception:
            LOG.exception("Не удалось создать admin из secrets")
        finally:
            conn.close()

    return runtime
