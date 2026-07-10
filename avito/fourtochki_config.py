"""Общие пути fourtochki из config.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml


def load_raw_config(config_path: Path) -> dict:
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def fourtochki_path(root: Path, raw: dict, key: str, default: str) -> Path:
    four = raw.get("fourtochki") or {}
    val = four.get(key, default)
    path = Path(str(val))
    return path if path.is_absolute() else root / path


def fourtochki_fetch_kwargs(root: Path, raw: dict) -> dict:
    four = raw.get("fourtochki") or {}
    kw: dict = {
        "pause_sec": float(four.get("fetch_pause_sec", 1.0)),
        "timeout_sec": float(four.get("timeout_sec", 60)),
        "dummy_size": str(four.get("dummy_size", " 205/55R16 91V")),
    }
    ua = str(four.get("user_agent", "")).strip()
    if ua:
        kw["user_agent"] = ua
    return kw
