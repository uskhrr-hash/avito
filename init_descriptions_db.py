#!/usr/bin/env python3
"""Создать БД описаний и импортировать model_descriptions.xlsx."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from avito.config import load_config
from avito.db import descriptions_connection, descriptions_db_config, load_secrets
from avito.descriptions_db import import_xlsx_row, init_schema
from avito.model_descriptions import load_model_descriptions_table

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("init_descriptions_db")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Инициализация БД описаний моделей")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "--xlsx",
        type=Path,
        default=None,
        help="Импорт из Excel (по умолчанию model_descriptions_file)",
    )
    p.add_argument("--skip-import", action="store_true")
    p.add_argument("--schema-only", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = load_config(args.config)
    db_cfg = app.descriptions_db
    project_root = args.config.parent
    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = project_root / secrets_path

    secrets = load_secrets(secrets_path)
    dcfg = descriptions_db_config(secrets, project_root=project_root)
    engine = dcfg["engine"]
    if engine == "sqlite":
        schema_sql = db_cfg.sqlite_schema_sql
        if not schema_sql.is_absolute():
            schema_sql = project_root / schema_sql
        target = f"SQLite {dcfg['path']}"
    else:
        schema_sql = db_cfg.schema_sql
        if not schema_sql.is_absolute():
            schema_sql = project_root / schema_sql
        target = f"PostgreSQL {dcfg.get('database')}"

    if not schema_sql.is_file():
        LOG.error("SQL-схема не найдена: %s", schema_sql)
        return 1

    try:
        with descriptions_connection(secrets, project_root=project_root) as conn:
            init_schema(
                conn,
                schema_sql,
                pg_schema=db_cfg.pg_schema,
                engine=engine,
            )
            LOG.info("Таблицы созданы: %s", target)

            if args.schema_only or args.skip_import:
                return 0

            xlsx = args.xlsx or app.autoload.model_descriptions_file
            if not xlsx.is_absolute():
                xlsx = project_root / xlsx
            if not xlsx.is_file():
                LOG.warning("Excel для импорта не найден: %s", xlsx)
                return 0

            df = load_model_descriptions_table(xlsx)
            imported = skipped = 0
            for _, row in df.iterrows():
                item = {c: row.get(c, "") for c in df.columns}
                if import_xlsx_row(conn, item):
                    imported += 1
                else:
                    skipped += 1
            LOG.info("Импорт из %s: добавлено %s, пропущено %s", xlsx.name, imported, skipped)
    except Exception as exc:
        LOG.error("Ошибка БД описаний: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
