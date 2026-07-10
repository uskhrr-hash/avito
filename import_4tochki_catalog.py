#!/usr/bin/env python3
"""MarkaModelNote.xml (4tochki) → data/4tochki_model_urls.json."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from avito.fourtochki import parse_marka_model_xml, save_catalog_json

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("import_4tochki_catalog")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Импорт каталога описаний 4tochki из XML")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument(
        "--xml",
        type=Path,
        default=None,
        help="MarkaModelNote.xml (по умолчанию fourtochki.catalog_xml из config)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="JSON-каталог (по умолчанию fourtochki.catalog_json)",
    )
    return p.parse_args()


def _cfg_path(root: Path, raw: dict, key: str, default: str) -> Path:
    four = raw.get("fourtochki") or {}
    val = four.get(key, default)
    path = Path(str(val))
    return path if path.is_absolute() else root / path


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    raw = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    xml_path = args.xml or _cfg_path(ROOT, raw, "catalog_xml", "data/MarkaModelNote.xml")
    out_path = args.output or _cfg_path(ROOT, raw, "catalog_json", "data/4tochki_model_urls.json")

    if not xml_path.is_file():
        LOG.error("XML не найден: %s", xml_path)
        return 2

    catalog = parse_marka_model_xml(xml_path)
    save_catalog_json(catalog, out_path)
    LOG.info(
        "Каталог: %s моделей, %s брендов → %s",
        len(catalog.models),
        len(catalog.brands),
        out_path,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOG.error("%s", exc)
        raise
