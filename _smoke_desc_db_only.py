#!/usr/bin/env python3
"""Smoke: model descriptions resolve from DB only (no read_excel)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from avito.config import load_config
from avito.model_descriptions import resolve_model_descriptions


def main() -> int:
    cfg = load_config(ROOT / "config.yaml")
    models_path = cfg.autoload.model_descriptions_file
    if not models_path.is_absolute():
        models_path = ROOT / models_path
    secrets_path = cfg.stock_sources.secrets_file
    if not secrets_path.is_absolute():
        secrets_path = ROOT / secrets_path

    called = {"excel": 0}
    orig = pd.read_excel

    def guard(*a, **k):
        called["excel"] += 1
        raise AssertionError(f"read_excel called: args={a[:1]} kwargs={list(k)}")

    pd.read_excel = guard  # type: ignore[assignment]
    try:
        descs = resolve_model_descriptions(
            xlsx_path=models_path,
            descriptions_db_enabled=cfg.descriptions_db.enabled,
            secrets_path=secrets_path,
            fallback_to_xlsx=False,
            pg_schema=cfg.descriptions_db.pg_schema,
            project_root=ROOT,
        )
    finally:
        pd.read_excel = orig  # type: ignore[assignment]

    print("descriptions_db.enabled", cfg.descriptions_db.enabled)
    print("keys", len(descs))
    print("read_excel_calls", called["excel"])
    print("xlsx_exists", models_path.exists(), str(models_path))
    if called["excel"] != 0:
        print("FAIL: read_excel was used for descriptions")
        return 1
    if not cfg.descriptions_db.enabled:
        print("FAIL: descriptions_db must be enabled")
        return 1
    if len(descs) <= 0:
        print("FAIL: empty approved descriptions map")
        return 1
    print("OK: DB-only descriptions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
