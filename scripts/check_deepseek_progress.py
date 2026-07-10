#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from avito.config import load_config
from avito.db import descriptions_connection, load_secrets
from avito.descriptions_db import configure_pg_schema, list_deepseek_models_map

ROOT = Path(__file__).resolve().parents[1]
# Вторая волна перегенерации — после правок промптов (UTC)
REGEN_CUTOFF = "2026-07-06 12:28:00"


def main() -> int:
    app = load_config(ROOT / "config.yaml")
    secrets = load_secrets(app.stock_sources.secrets_file)
    configure_pg_schema(app.descriptions_db.pg_schema)
    with descriptions_connection(secrets, project_root=ROOT) as conn:
        expected = list_deepseek_models_map(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT tm.model_key, md.updated_at, md.id
            FROM avito_model_descriptions md
            JOIN avito_tire_models tm ON tm.id = md.tire_model_id
            WHERE md.source = 'deepseek'
            ORDER BY md.updated_at DESC
            """
        )
        rows = cur.fetchall()
        latest: dict[str, tuple[str, int]] = {}
        for key, updated_at, desc_id in rows:
            if key not in latest:
                latest[key] = (str(updated_at), int(desc_id))

    done = sorted(k for k, (ts, _) in latest.items() if ts >= REGEN_CUTOFF)
    pending = sorted(k for k in expected if k not in done)

    print(f"Всего deepseek-моделей: {len(expected)}")
    print(f"Перегенерировано (новые промпты): {len(done)}")
    print(f"Осталось: {len(pending)}")
    if pending:
        print("\nЕщё не обновлены:")
        for k in pending:
            ts = latest.get(k, ("?", 0))[0]
            print(f"  {ts}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
