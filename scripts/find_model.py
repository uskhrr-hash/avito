import sqlite3
import sys
from pathlib import Path

q = sys.argv[1] if len(sys.argv) > 1 else "ES31"
db = Path(__file__).resolve().parents[1] / "data" / "avito_descriptions.db"
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute(
    "SELECT model_key FROM avito_tire_models WHERE model_key LIKE ?",
    (f"%{q}%",),
)
print([r[0] for r in cur.fetchall()])
conn.close()
