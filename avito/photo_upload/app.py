"""FastAPI-приложение для загрузки фото с телефона."""
from __future__ import annotations

import hmac
import json
import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from avito.photo_upload.guide import render_guide_html
from avito.photo_upload.overlays import EXAMPLE_FILES, overlay_svg_for_shot, shot_label
from avito.photo_upload.service import (
    load_no_photos_queue_info,
    lookup_stock,
    next_photo_index,
    pending_photo_meta,
    save_upload_batch,
    search_stock,
    validate_article,
)
from avito.photo_upload.settings import PhotoUploadRuntime, StoreLogin, load_photo_upload_runtime

LOG = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
SESSION_STORE_KEY = "photo_upload_store"


def _verify_password(store: StoreLogin, password: str) -> bool:
    return hmac.compare_digest(store.password, password)


def _current_store(request: Request, runtime: PhotoUploadRuntime) -> StoreLogin | None:
    prefix = str(request.session.get(SESSION_STORE_KEY, "")).strip()
    if not prefix:
        return None
    for store in runtime.stores:
        if store.prefix == prefix:
            return store
    return None


def _require_store(request: Request, runtime: PhotoUploadRuntime) -> StoreLogin:
    store = _current_store(request, runtime)
    if store is None:
        raise HTTPException(status_code=401, detail="Нужен вход")
    return store


def create_app(runtime: PhotoUploadRuntime) -> FastAPI:
    app = FastAPI(title="Avito Photo Upload", docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=runtime.session_secret,
        max_age=runtime.config.photo_upload.session_max_age_hours * 3600,
        https_only=False,
        same_site="lax",
    )
    app.state.runtime = runtime
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/shot-guide")
    async def api_shot_guide(index: int = 1) -> JSONResponse:
        idx = max(1, int(index))
        meta = shot_label(idx)
        return JSONResponse(
            {
                "index": idx,
                "title": meta["title"],
                "hint": meta["hint"],
                "short": meta["short"],
                "overlay_svg": overlay_svg_for_shot(idx, camera=True),
                "example_url": EXAMPLE_FILES.get(idx, ""),
            }
        )

    @app.get("/guide", response_class=HTMLResponse)
    async def guide() -> HTMLResponse:
        return HTMLResponse(render_guide_html(base=_mount_base(runtime)))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        if _current_store(request, runtime) is None:
            return HTMLResponse(_login_html(runtime))
        return HTMLResponse(_app_html(runtime, _current_store(request, runtime)))

    @app.get("/api/stores")
    async def api_stores() -> JSONResponse:
        payload = [
            {"prefix": s.prefix, "label": s.label}
            for s in runtime.stores
        ]
        return JSONResponse(payload)

    @app.post("/api/login")
    async def api_login(request: Request) -> JSONResponse:
        payload = await request.json()
        prefix = str(payload.get("store", "")).strip()
        password = str(payload.get("password", ""))
        store = next((s for s in runtime.stores if s.prefix == prefix), None)
        if store is None or not _verify_password(store, password):
            raise HTTPException(status_code=401, detail="Неверный магазин или пароль")
        request.session[SESSION_STORE_KEY] = store.prefix
        return JSONResponse(
            {"ok": True, "store": store.prefix, "label": store.label}
        )

    @app.post("/api/logout")
    async def api_logout(request: Request) -> JSONResponse:
        request.session.clear()
        return JSONResponse({"ok": True})

    @app.get("/api/me")
    async def api_me(request: Request) -> JSONResponse:
        store = _current_store(request, runtime)
        if store is None:
            raise HTTPException(status_code=401, detail="Нужен вход")
        return JSONResponse(
            {"store": store.prefix, "label": store.label}
        )

    @app.get("/api/stock/lookup")
    async def api_stock_lookup(request: Request, article: str = "") -> JSONResponse:
        _require_store(request, runtime)
        item = lookup_stock(runtime, article)
        if item is None:
            return JSONResponse({"found": False})
        return JSONResponse(
            {
                "found": True,
                "article": item.article,
                "nomenclature": item.nomenclature,
                "quantity": item.quantity,
            }
        )

    @app.get("/api/stock/search")
    async def api_stock_search(request: Request, q: str = "") -> JSONResponse:
        _require_store(request, runtime)
        rows = search_stock(runtime, q)
        return JSONResponse(
            [
                {
                    "article": r.article,
                    "nomenclature": r.nomenclature,
                    "quantity": r.quantity,
                }
                for r in rows
            ]
        )

    @app.get("/api/no-photos")
    async def api_no_photos(
        request: Request,
        limit: int = 80,
        in_store: int = 0,
    ) -> JSONResponse:
        store = _require_store(request, runtime)
        result = load_no_photos_queue_info(
            runtime,
            store_prefix=store.prefix,
            limit=min(limit, 200),
            in_store_only=bool(in_store),
        )
        return JSONResponse(
            {
                "items": [
                    {
                        "article": r.article,
                        "nomenclature": r.nomenclature,
                        "stores": r.stores,
                        "problem": r.problem,
                    }
                    for r in result.items
                ],
                "source_file": result.source_file,
                "hint": result.hint,
                "count": len(result.items),
                "in_store_only": bool(in_store),
                "ushk_supplier": store.ushk_supplier,
            }
        )

    @app.get("/api/next-index")
    async def api_next_index(request: Request, article: str = "") -> JSONResponse:
        store = _require_store(request, runtime)
        art = validate_article(article)
        idx = next_photo_index(runtime, store_prefix=store.prefix, article=art)
        meta = pending_photo_meta(
            runtime, store_prefix=store.prefix, article=art, index=idx
        )
        return JSONResponse(
            {
                "index": meta.index,
                "filename": meta.filename,
                "relative_path": meta.relative_path,
            }
        )

    @app.post("/api/upload")
    async def api_upload(
        request: Request,
        article: str = Form(...),
        indices: str = Form(...),
        files: list[UploadFile] = File(...),
    ) -> JSONResponse:
        store = _require_store(request, runtime)
        art = validate_article(article)
        try:
            index_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректные номера фото") from exc
        if not index_list:
            raise HTTPException(status_code=400, detail="Нет номеров фото")
        if len(index_list) != len(files):
            raise HTTPException(status_code=400, detail="Число файлов и номеров не совпадает")

        items: list[tuple[int, bytes]] = []
        for idx, upload in zip(index_list, files):
            data = await upload.read()
            if not data:
                raise HTTPException(status_code=400, detail=f"Пустой файл для фото {idx}")
            items.append((idx, data))

        try:
            result = save_upload_batch(
                runtime,
                store_prefix=store.prefix,
                article=art,
                items=items,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return JSONResponse(
            {
                "ok": True,
                "article": result.article,
                "saved": result.saved,
            }
        )

    return app


def _mount_base(runtime: PhotoUploadRuntime) -> str:
    mount = (runtime.public_mount_path or "/photo").strip()
    if not mount.startswith("/"):
        mount = f"/{mount}"
    return mount.rstrip("/") + "/"


def _login_html(runtime: PhotoUploadRuntime) -> str:
    base = _mount_base(runtime)
    store_cards = "\n".join(
        f'''        <button type="button" class="store-card" data-prefix="{s.prefix}">
          <strong>{s.label}</strong>
          <span>Магазин {s.prefix}</span>
        </button>'''
        for s in runtime.stores
    )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1">
  <meta name="theme-color" content="#2563eb">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <base href="{base}">
  <title>Вход — фото Avito</title>
  <link rel="stylesheet" href="static/app.css">
</head>
<body class="page-login">
  <main class="shell">
    <h1>Фото Avito</h1>
    <p class="lead">Нажмите на свой магазин и введите пароль</p>
    <a class="login-guide-link" href="guide">📷 Стандарт съёмки: 4 фото с контурами</a>
    <form id="login-form" class="card">
      <p class="field"><span>Магазин</span></p>
      <div class="store-grid" id="store-grid">
{store_cards}
      </div>
      <input type="hidden" id="store" name="store" value="">
      <label class="field">
        <span>Пароль</span>
        <input id="password" type="password" autocomplete="current-password" inputmode="text" required placeholder="Пароль магазина">
      </label>
      <p id="login-error" class="error hidden"></p>
      <button type="submit" class="btn btn-primary">Войти</button>
    </form>
  </main>
  <script src="static/login.js"></script>
</body>
</html>"""


def _app_html(runtime: PhotoUploadRuntime, store: StoreLogin) -> str:
    base = _mount_base(runtime)
    store_json = json.dumps(
        {"prefix": store.prefix, "label": store.label},
        ensure_ascii=False,
    )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1">
  <meta name="theme-color" content="#2563eb">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <base href="{base}">
  <title>Фото — {store.label}</title>
  <link rel="stylesheet" href="static/app.css">
  <link rel="stylesheet" href="static/camera.css?v=3">
</head>
<body class="page-app">
  <header class="topbar">
    <div>
      <div class="topbar-title">Фото Avito</div>
      <div class="topbar-sub">{store.label}</div>
    </div>
    <div class="topbar-actions">
      <a href="guide" class="topbar-guide">Стандарт</a>
      <button type="button" id="logout" class="btn btn-ghost">Выйти</button>
    </div>
  </header>

  <main class="shell">
    <section class="card card-article">
      <label class="field">
        <span>Артикул</span>
        <input id="article" type="search" inputmode="numeric" pattern="[0-9]*" autocomplete="off" placeholder="124889" enterkeyhint="done">
      </label>
      <div id="article-hint" class="hint">Введите артикул шины</div>
      <div id="search-results" class="search-results hidden"></div>
    </section>

    <section class="card card-camera">
      <div class="row-between">
        <h2>Снимки</h2>
        <span id="pending-count" class="badge">0</span>
      </div>
      <div id="pending-list" class="pending-list"></div>
      <p id="next-shot-hint" class="shot-hint muted">Введите артикул — подскажем следующий кадр</p>
      <button type="button" id="open-camera" class="btn btn-camera">📷 Сфотографировать</button>
      <label class="btn btn-secondary file-btn camera-fallback-btn">
        <input id="camera-fallback" type="file" accept="image/*" capture="environment" hidden>
        Системная камера / галерея
      </label>
    </section>

    <details class="card section-queue" open>
      <summary>Нет фото — снять из списка</summary>
      <p class="muted queue-hint">Нажмите на позицию — подставится артикул</p>
      <label class="toggle-row">
        <input type="checkbox" id="in-store-only">
        <span>Есть в магазине (по реестру УШК)</span>
      </label>
      <button type="button" id="refresh-queue" class="btn btn-ghost btn-block">Обновить список</button>
      <div id="queue-list" class="queue-list"></div>
    </details>
  </main>

  <div class="bottom-bar">
    <button type="button" id="upload" class="btn btn-primary" disabled>Отправить на сервер</button>
  </div>

  <div id="loading" class="loading hidden" aria-live="polite" aria-busy="false">
    <div class="loading-box">
      <div class="spinner" aria-hidden="true"></div>
      <p id="loading-text">Загрузка на сервер…</p>
    </div>
  </div>

  <div id="toast" class="toast"></div>

  <div id="camera-modal" class="camera-modal hidden" aria-hidden="true">
    <div class="camera-top">
      <div>
        <div id="camera-title" class="camera-title">Фото 1</div>
        <div id="camera-hint" class="camera-sub">Стопка шин</div>
      </div>
      <button type="button" id="camera-close" class="btn btn-ghost" aria-label="Закрыть">✕</button>
    </div>
    <div class="camera-stage">
      <video id="camera-video" autoplay playsinline muted></video>
      <div id="camera-overlay" class="camera-overlay"></div>
      <img id="camera-example" class="camera-example hidden" alt="">
    </div>
    <div class="camera-bottom">
      <button type="button" id="camera-capture" class="btn btn-primary camera-shutter">Снять</button>
      <button type="button" id="camera-system" class="btn btn-secondary camera-system-btn">Системная камера</button>
      <a id="camera-example-link" class="camera-example-link" href="guide" target="_blank" rel="noopener">Эталон</a>
    </div>
  </div>

  <script>window.PHOTO_UPLOAD_SESSION = {store_json};</script>
  <script src="static/app.js?v=3"></script>
</body>
</html>"""
