#!/usr/bin/env python3
"""Проверка БД описаний (secrets → descriptions_db)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from avito.db import descriptions_connection, descriptions_db_config, load_secrets
from avito.descriptions_db import load_approved_descriptions

secrets = load_secrets(ROOT / "secrets.local.yaml")
cfg = descriptions_db_config(secrets, project_root=ROOT)
print("engine:", cfg["engine"])
if cfg["engine"] == "sqlite":
    print("path:", cfg["path"])
else:
    print("postgres:", cfg.get("host"), cfg.get("database"), cfg.get("user"))

with descriptions_connection(secrets, project_root=ROOT) as conn:
    approved = load_approved_descriptions(conn)
    print("approved descriptions:", len(approved))

for table in ("avito_tire_models", "avito_model_descriptions"):
    with descriptions_connection(secrets, project_root=ROOT) as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"{table}:", cur.fetchone()[0])

print("OK")
