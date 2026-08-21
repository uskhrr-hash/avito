#!/usr/bin/env python3
"""Avito Photo v2 — greenfield service (S1 login + S2 upload). Port 8766."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from avito.photo_v2.app import create_app
from avito.photo_v2.storage import load_storage_runtime
from avito.photo_v2.store_auth import load_photo_v2_runtime

LOG = logging.getLogger("run_photo_v2")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Avito Photo v2 (S2)")
    p.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8766)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    runtime = load_photo_v2_runtime(
        config_path=args.config,
        project_root=ROOT,
        host=args.host,
        port=args.port,
    )
    storage = load_storage_runtime(
        config_path=args.config,
        project_root=ROOT,
    )
    LOG.info(
        "Photo v2: http://%s:%s/ (nginx: /) stores=%s photos=%s",
        runtime.host,
        runtime.port,
        ",".join(s.prefix for s in runtime.stores),
        storage.photos_dir,
    )
    # Single worker: isolates from old photo_upload; upload uses to_thread.
    uvicorn.run(
        create_app(runtime, storage),
        host=runtime.host,
        port=runtime.port,
        log_level="info",
        timeout_keep_alive=5,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
