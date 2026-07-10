#!/usr/bin/env python3
"""Веб-страница для съёмки и загрузки фото на сервер."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from avito.photo_upload.app import create_app
from avito.photo_upload.settings import load_photo_upload_runtime

LOG = logging.getLogger("run_photo_upload")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Веб-загрузка фото Avito")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    runtime = load_photo_upload_runtime(config_path=args.config, project_root=ROOT)
    host = args.host or runtime.config.photo_upload.host
    port = args.port or runtime.config.photo_upload.port
    app = create_app(runtime)
    LOG.info("Фото-загрузка: http://%s:%s/ (nginx: /photo/)", host, port)
    LOG.info("Папка фото: %s", runtime.photos_dir)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
