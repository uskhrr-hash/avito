#!/usr/bin/env python3
"""Экспорт описаний из БД → Excel для просмотра."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from avito.config import AppConfig, load_config
from avito.db import descriptions_connection, load_secrets
from avito.descriptions_db import configure_pg_schema, write_descriptions_xlsx

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("export_descriptions_db")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Экспорт описаний из БД в xlsx")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Путь xlsx (по умолчанию model_descriptions_file)",
    )
    return p.parse_args()


def export_descriptions_excel(
    app: AppConfig,
    *,
    config_path: Path,
    output: Path | None = None,
) -> Path:
    """Записать model_descriptions.xlsx из SQLite/PostgreSQL."""
    project_root = config_path.parent
    out = output or app.autoload.model_descriptions_file
    if not out.is_absolute():
        out = project_root / out

    secrets_path = app.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = project_root / secrets_path

    secrets = load_secrets(secrets_path)
    configure_pg_schema(app.descriptions_db.pg_schema)
    with descriptions_connection(secrets, project_root=project_root) as conn:
        n = write_descriptions_xlsx(conn, out)
    LOG.info("Экспорт %s строк → %s", n, out)
    return out


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    export_descriptions_excel(load_config(args.config), config_path=args.config, output=args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
