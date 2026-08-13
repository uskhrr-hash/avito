#!/usr/bin/env python3
"""Веб-страница для съёмки и загрузки фото на сервер."""
from __future__ import annotations

import argparse
import logging
import os
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
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Число uvicorn workers (по умолчанию PHOTO_UPLOAD_WORKERS или 2)",
    )
    return p.parse_args()


def app_factory():
    """Factory для uvicorn multi-worker (каждый worker поднимает свой app)."""
    runtime = load_photo_upload_runtime(
        config_path=ROOT / "config.yaml", project_root=ROOT
    )
    return create_app(runtime)


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    runtime = load_photo_upload_runtime(config_path=args.config, project_root=ROOT)
    host = args.host or runtime.config.photo_upload.host
    port = args.port or runtime.config.photo_upload.port
    workers_raw = args.workers
    if workers_raw is None:
        workers_raw = int(os.environ.get("PHOTO_UPLOAD_WORKERS", "2") or "2")
    workers = max(1, min(int(workers_raw), 4))

    LOG.info("Фото-загрузка: http://%s:%s/ (nginx: /photo/) workers=%s", host, port, workers)
    LOG.info("Папка фото: %s", runtime.photos_dir)

    if workers > 1:
        # import-string + factory обязательны для workers>1
        uvicorn.run(
            "run_photo_upload:app_factory",
            factory=True,
            host=host,
            port=port,
            workers=workers,
            log_level="info",
        )
    else:
        uvicorn.run(create_app(runtime), host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
