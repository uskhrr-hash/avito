#!/usr/bin/env python3
"""Проверка прав PostgreSQL для схемы avito."""
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg2

secrets = yaml.safe_load((ROOT / "secrets.local.yaml").read_text(encoding="utf-8"))
d = secrets["db"]
conn = psycopg2.connect(
    host=d["host"],
    port=d["port"],
    dbname=d["database"],
    user=d["user"],
    password=d["password"],
)
cur = conn.cursor()
cur.execute("SELECT current_user, current_database()")
print("connected:", cur.fetchone())
cur.execute(
    "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
)
print("superuser, createdb, createrole:", cur.fetchone())
cur.execute(
    "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
)
print("CREATE on database:", cur.fetchone()[0])
cur.execute(
    "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
)
print("CREATE in public schema:", cur.fetchone()[0])
cur.execute(
    "SELECT has_schema_privilege(current_user, 'logistics', 'CREATE')"
)
print("CREATE in logistics schema:", cur.fetchone()[0])
cur.execute(
    "SELECT nspname FROM pg_namespace n "
    "WHERE has_schema_privilege(current_user, n.nspname, 'CREATE') "
    "ORDER BY 1 LIMIT 20"
)
print("schemas with CREATE:", [r[0] for r in cur.fetchall()])
cur.close()
conn.close()
