"""Подключение к БД: ERP PostgreSQL и локальная БД описаний."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import yaml

DB_REQUIRED_KEYS = ("host", "port", "database", "user", "password")

ERP_DB_SECTION = "db"
DESCRIPTIONS_DB_SECTION = "descriptions_db"


def load_secrets(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Не найден файл секретов: {path}. Создайте secrets.local.yaml"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def descriptions_db_config(
    secrets: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    cfg = dict(secrets.get(DESCRIPTIONS_DB_SECTION) or {})
    engine = str(cfg.get("engine", "sqlite")).strip().lower()
    if engine not in ("sqlite", "postgres", "postgresql"):
        raise ValueError(f"descriptions_db.engine: sqlite или postgres, не {engine!r}")
    if engine == "postgres":
        engine = "postgresql"
    cfg["engine"] = engine
    if engine == "sqlite":
        raw_path = str(cfg.get("path", "data/avito_descriptions.db")).strip()
        path = Path(raw_path)
        if not path.is_absolute() and project_root:
            path = project_root / path
        cfg["path"] = path
    else:
        missing = [k for k in DB_REQUIRED_KEYS if not str(cfg.get(k, "")).strip()]
        if missing:
            raise ValueError(
                f"descriptions_db (postgres): заполните {', '.join(missing)}"
            )
    return cfg


def db_config_from_secrets(
    secrets: dict[str, Any],
    *,
    section: str = ERP_DB_SECTION,
) -> dict[str, Any]:
    cfg = secrets.get(section) or {}
    missing = [k for k in DB_REQUIRED_KEYS if not str(cfg.get(k, "")).strip()]
    if missing:
        raise ValueError(
            f"В secrets.local.yaml не заполнены {section}-поля: {', '.join(missing)}"
        )
    return cfg


@contextmanager
def pg_connection(
    secrets: dict[str, Any],
    *,
    section: str = ERP_DB_SECTION,
) -> Iterator[Any]:
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("Установите зависимость: pip install psycopg2-binary") from exc

    d_cfg = db_config_from_secrets(secrets, section=section)
    conn = psycopg2.connect(
        host=str(d_cfg["host"]),
        port=int(d_cfg["port"]),
        dbname=str(d_cfg["database"]),
        user=str(d_cfg["user"]),
        password=str(d_cfg["password"]),
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def descriptions_connection(
    secrets: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> Iterator[Any]:
    """БД описаний Avito — SQLite (по умолчанию) или отдельный PostgreSQL."""
    from avito.descriptions_db import configure_descriptions_store

    cfg = descriptions_db_config(secrets, project_root=project_root)
    engine = cfg["engine"]

    if engine == "sqlite":
        path: Path = cfg["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        configure_descriptions_store("sqlite", pg_schema="")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    configure_descriptions_store("postgresql", pg_schema="public")
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("pip install psycopg2-binary") from exc

    conn = psycopg2.connect(
        host=str(cfg["host"]),
        port=int(cfg["port"]),
        dbname=str(cfg["database"]),
        user=str(cfg["user"]),
        password=str(cfg["password"]),
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# обратная совместимость
pg_descriptions_connection = descriptions_connection


def run_sql_file(conn: Any, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
