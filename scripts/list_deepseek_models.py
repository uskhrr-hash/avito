#!/usr/bin/env python3
"""Список моделей с описаниями source=deepseek."""
from __future__ import annotations

from pathlib import Path

from avito.config import load_config
from avito.db import descriptions_connection, load_secrets
from avito.descriptions_db import configure_pg_schema

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    app = load_config(ROOT / "config.yaml")
    secrets = load_secrets(app.stock_sources.secrets_file)
    configure_pg_schema(app.descriptions_db.pg_schema)
    with descriptions_connection(secrets, project_root=ROOT) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT tm.model_key
            FROM avito_model_descriptions md
            JOIN avito_tire_models tm ON tm.id = md.tire_model_id
            WHERE md.source = 'deepseek'
            ORDER BY tm.model_key
            """
        )
        keys = [str(r[0]) for r in cur.fetchall()]
    print(len(keys))
    for k in keys:
        print(k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
