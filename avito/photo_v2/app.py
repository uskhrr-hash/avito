"""FastAPI Photo v2 — S1–S3.2 article check on Товары (no S4 admin panel)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from avito.photo_upload.settings import PhotoUploadRuntime
from avito.photo_v2.storage import (
    ARTICLES_DEFAULT_LIMIT,
    LISTINGS_DEFAULT_LIMIT,
    MAX_UPLOAD_BATCH,
    PHOTOS_DEFAULT_LIMIT,
    PHOTOS_PUBLIC_PREFIX,
    aggregate_lookup,
    delete_store_photo,
    list_articles_light,
    list_listings_page,
    list_photos_page,
    normalize_product_kind,
    save_store_uploads,
    validate_article,
)
from avito.photo_v2.store_auth import (
    PhotoV2Runtime,
    verify_store_password,
)

LOG = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"

SESSION_ROLE = "photo_v2_role"
SESSION_STORE = "photo_v2_store"
ROLE_STORE = "store"
COOKIE_NAME = "photo_v2_session"
COOKIE_PATH = "/"
ASSET_V = "14"


async def request_payload(request: Request) -> dict:
    """JSON or form; empty/invalid → {} or HTTP 400 (never 500)."""
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        return {str(k): ("" if v is None else str(v)) for k, v in form.items()}
    raw = await request.body()
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Некорректный JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Ожидается JSON-объект")
    return data


def _current_store(request: Request, runtime: PhotoV2Runtime):
    role = str(request.session.get(SESSION_ROLE, "")).strip()
    if role != ROLE_STORE:
        return None
    prefix = str(request.session.get(SESSION_STORE, "")).strip()
    for store in runtime.stores:
        if store.prefix == prefix:
            return store
    return None


def _require_store(request: Request, runtime: PhotoV2Runtime):
    store = _current_store(request, runtime)
    if store is None:
        raise HTTPException(status_code=401, detail="Нужен вход")
    return store


def _normalize_etag_token(token: str) -> str:
    tag = (token or "").strip()
    if tag.startswith("W/"):
        tag = tag[2:].strip()
    return tag


def _if_none_match_hits(if_none_match: str | None, etag: str) -> bool:
    raw = (if_none_match or "").strip()
    if not raw:
        return False
    if raw == "*":
        return True
    want = _normalize_etag_token(etag)
    for part in raw.split(","):
        if _normalize_etag_token(part) == want:
            return True
    return False


def _json_cached_response(request: Request, payload: object) -> Response:
    """JSON + ETag; If-None-Match → 304 empty body."""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    etag = '"' + hashlib.md5(raw.encode("utf-8")).hexdigest() + '"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, no-cache",
    }
    if _if_none_match_hits(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=raw,
        media_type="application/json; charset=utf-8",
        headers=headers,
    )


def _login_html(runtime: PhotoV2Runtime) -> str:
    options = "\n".join(
        f'<option value="{s.prefix}">{s.label}</option>' for s in runtime.stores
    )
    # Folder filter is locked to the logged-in shop (filled in JS after /api/me).
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Avito Photo v2 — вход</title>
  <link rel="stylesheet" href="static/style.css?v={ASSET_V}">
</head>
<body>
  <main class="shell">
    <h1>Photo v2</h1>
    <p id="subtitle" class="muted">Вход магазина</p>
    <form id="login-form" class="card" autocomplete="on">
      <label>
        Магазин
        <select name="store" id="store" required>
          {options}
        </select>
      </label>
      <label>
        Пароль
        <input name="password" id="password" type="password" required autocomplete="current-password">
      </label>
      <button type="submit" id="submit">Войти</button>
      <p id="err" class="err" hidden></p>
    </form>
    <section id="home" class="card home-card" hidden>
      <div class="home-chrome">
        <div class="home-head">
          <div class="home-head-text">
            <p class="home-hint">Магазин</p>
            <p id="who" class="home-shop"></p>
          </div>
          <button type="button" id="logout" class="secondary">Выйти</button>
        </div>

        <nav class="tabs" role="tablist" aria-label="Разделы">
          <button type="button" class="tab active" role="tab" data-tab="upload" id="tab-upload" aria-selected="true">Загрузка</button>
          <button type="button" class="tab" role="tab" data-tab="listings" id="tab-listings" aria-selected="false">Товары</button>
          <button type="button" class="tab" role="tab" data-tab="photos" id="tab-photos" aria-selected="false">Файлы</button>
        </nav>
      </div>

      <div id="panel-upload" class="tab-panel" data-panel="upload" role="tabpanel">
        <div class="kind-toggle" role="group" aria-label="Тип товара">
          <button type="button" class="kind-btn active" data-kind="tire" id="kind-tire">Шины</button>
          <button type="button" class="kind-btn" data-kind="wheel" id="kind-wheel">Диски</button>
        </div>

        <div class="article-row">
          <label class="article-label">
            Артикул
            <input id="article" name="article" inputmode="numeric" autocomplete="off" placeholder="например 122062">
          </label>
          <button type="button" id="pick-articles" class="secondary pick-btn">Подобрать</button>
        </div>
        <p id="lookup-hint" class="hint">Введите артикул или подберите без фото</p>
        <div id="article-picker" class="article-picker" hidden>
          <ul id="article-list" class="article-list"></ul>
          <button type="button" id="article-more" class="secondary" hidden>Ещё</button>
          <p id="article-picker-hint" class="hint" hidden></p>
        </div>

        <div class="file-actions">
          <label class="file-label">
            <span>Выбрать фото</span>
            <!-- capture + no multiple → camera on mobile; multiple ignores capture in some browsers -->
            <input type="file" id="files" accept="image/*" capture="environment">
          </label>
          <label class="file-label secondary-file">
            <span>Из галереи</span>
            <input type="file" id="files-gallery" accept="image/*" multiple>
          </label>
        </div>

        <ul id="pending" class="pending"></ul>
        <button type="button" id="upload">Отправить на сервер</button>
        <p id="progress" class="progress" hidden></p>
        <div id="saved" class="saved"></div>
      </div>

      <div id="panel-listings" class="tab-panel" data-panel="listings" role="tabpanel" hidden>
        <p class="hint">Проверка одного артикула — без списка всех товаров</p>
        <div class="check-row">
          <label class="article-label">
            Артикул
            <input id="listings-article" name="listings-article" inputmode="numeric" autocomplete="off" placeholder="например 122062">
          </label>
          <button type="button" id="listings-check">Проверить</button>
        </div>
        <p id="listings-hint" class="hint">Введите артикул и нажмите «Проверить»</p>
        <div id="listings-card" class="check-card" hidden></div>
      </div>

      <div id="panel-photos" class="tab-panel" data-panel="photos" role="tabpanel" hidden>
        <div class="photos-filters">
          <label>
            Артикул
            <input id="photos-article" inputmode="numeric" autocomplete="off" placeholder="фильтр">
          </label>
          <label>
            Папка
            <select id="photos-folder" disabled>
              <option value="">—</option>
            </select>
          </label>
          <button type="button" id="photos-apply" class="secondary">Показать</button>
        </div>
        <ul id="photos-list" class="data-list photos-grid"></ul>
        <button type="button" id="photos-more" class="secondary" hidden>Ещё</button>
        <p id="photos-hint" class="hint" hidden></p>
      </div>
    </section>
  </main>
  <script src="static/app.js?v={ASSET_V}" defer></script>
</body>
</html>"""


def create_app(
    runtime: PhotoV2Runtime,
    storage: PhotoUploadRuntime,
) -> FastAPI:
    app = FastAPI(title="Avito Photo v2", docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=runtime.session_secret,
        session_cookie=COOKIE_NAME,
        max_age=runtime.session_max_age_hours * 3600,
        path=COOKIE_PATH,
        same_site="lax",
        https_only=True,
    )
    app.state.runtime = runtime
    app.state.storage = storage
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"ok": True, "app": "photo_v2", "stage": "s5"})

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return HTMLResponse(_login_html(runtime))

    @app.get("/api/stores")
    async def api_stores() -> JSONResponse:
        return JSONResponse(
            [{"prefix": s.prefix, "label": s.label} for s in runtime.stores]
        )

    @app.post("/api/login")
    async def api_login(request: Request) -> JSONResponse:
        payload = await request_payload(request)
        store_prefix = str(payload.get("store", "")).strip()
        password = str(payload.get("password", ""))
        if not store_prefix:
            raise HTTPException(status_code=400, detail="Укажите магазин")
        store = next((s for s in runtime.stores if s.prefix == store_prefix), None)
        if store is None or not verify_store_password(store, password):
            raise HTTPException(status_code=401, detail="Неверный магазин или пароль")
        request.session.clear()
        request.session[SESSION_ROLE] = ROLE_STORE
        request.session[SESSION_STORE] = store.prefix
        return JSONResponse(
            {"ok": True, "role": ROLE_STORE, "store": store.prefix, "label": store.label}
        )

    @app.post("/api/logout")
    async def api_logout(request: Request) -> JSONResponse:
        request.session.clear()
        return JSONResponse({"ok": True})

    @app.get("/api/me")
    async def api_me(request: Request) -> JSONResponse:
        store = _require_store(request, runtime)
        return JSONResponse(
            {"role": ROLE_STORE, "store": store.prefix, "label": store.label}
        )

    @app.get("/api/articles")
    async def api_articles(
        request: Request,
        q: str = "",
        kind: str = "tire",
        limit: int = ARTICLES_DEFAULT_LIMIT,
        offset: int = 0,
        need_photos: int = 0,
    ) -> Response:
        """Light article list for picker. Lazy: call only when user opens/types."""
        store = _require_store(request, runtime)
        want_need = bool(int(need_photos or 0))
        query = str(q or "").strip()
        if not want_need and len(query) < 2:
            return _json_cached_response(
                request,
                {
                    "items": [],
                    "limit": ARTICLES_DEFAULT_LIMIT,
                    "offset": 0,
                    "has_more": False,
                    "mode": "search",
                },
            )
        try:
            page = await asyncio.to_thread(
                list_articles_light,
                storage,
                store_prefix=store.prefix,
                q=query,
                kind=kind,
                limit=limit,
                offset=offset,
                need_photos=want_need,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items = []
        for row in page.items:
            entry = {
                "article": row.article,
                "kind": row.kind,
                "nomenclature": row.nomenclature,
            }
            if row.quantity:
                entry["quantity"] = row.quantity
            if row.photo_count is not None:
                entry["photo_count"] = row.photo_count
            items.append(entry)
        return _json_cached_response(
            request,
            {
                "items": items,
                "limit": page.limit,
                "offset": page.offset,
                "has_more": page.has_more,
                "mode": page.mode,
            },
        )

    @app.get("/api/listings")
    async def api_listings(
        request: Request,
        kind: str = "",
        limit: int = LISTINGS_DEFAULT_LIMIT,
        offset: int = 0,
        q: str = "",
    ) -> Response:
        """Товары — slim DTO, ETag/304. Article check via q=; kind optional (empty = both)."""
        _require_store(request, runtime)
        try:
            page = await asyncio.to_thread(
                list_listings_page,
                storage,
                kind=kind,
                limit=limit,
                offset=offset,
                q=q,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items = []
        for row in page.items:
            entry = {
                "article": row.article,
                "kind": row.kind,
                "nomenclature": row.nomenclature,
                "photo_count": row.photo_count,
                "folders": list(row.folders),
            }
            if row.incoming is not None:
                entry["incoming"] = row.incoming
            if row.manual_price is not None:
                entry["manual_price"] = row.manual_price
            if row.calculated_price is not None:
                entry["calculated_price"] = row.calculated_price
            if row.price_rule:
                entry["price_rule"] = row.price_rule
            items.append(entry)
        return _json_cached_response(
            request,
            {
                "items": items,
                "count": len(items),
                "total": page.total,
                "limit": page.limit,
                "offset": page.offset,
                "has_more": page.has_more,
            },
        )

    @app.get("/api/photos")
    async def api_photos(
        request: Request,
        limit: int = PHOTOS_DEFAULT_LIMIT,
        offset: int = 0,
        article: str = "",
        folder: str = "",
    ) -> Response:
        """Файлы — только папка текущего магазина. Call only when tab opened."""
        store = _require_store(request, runtime)
        try:
            page = await asyncio.to_thread(
                list_photos_page,
                storage,
                store_prefix=store.prefix,
                folder=folder,
                article=article,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items = [
            {
                "relative_path": row.relative_path,
                "folder": row.folder,
                "filename": row.filename,
                "size": row.size,
                "url": PHOTOS_PUBLIC_PREFIX + row.relative_path.lstrip("/"),
            }
            for row in page.items
        ]
        return _json_cached_response(
            request,
            {
                "items": items,
                "count": len(items),
                "limit": page.limit,
                "offset": page.offset,
                "has_more": page.has_more,
                "folder": store.prefix,
            },
        )

    @app.post("/api/photos/delete")
    async def api_photos_delete(request: Request) -> JSONResponse:
        """Manager self-serve delete — disk unlink + photo index invalidate (v1)."""
        store = _require_store(request, runtime)
        payload = await request_payload(request)
        rel = str(payload.get("relative_path", "")).strip()
        if not rel:
            raise HTTPException(status_code=400, detail="Укажите relative_path")
        try:
            result = await asyncio.to_thread(
                delete_store_photo,
                storage,
                store_prefix=store.prefix,
                relative_path=rel,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception:  # noqa: BLE001 — soft-fail: never 500 for delete UX
            LOG.exception("photo delete failed store=%s path=%s", store.prefix, rel)
            raise HTTPException(
                status_code=400, detail="Не удалось удалить файл"
            ) from None
        return JSONResponse(
            {
                "ok": True,
                "deleted": result.deleted,
                "missing": bool(result.missing),
            }
        )

    @app.get("/api/lookup")
    async def api_lookup(
        request: Request, article: str = "", kind: str = "tire"
    ) -> JSONResponse:
        """Aggregated: stock + next index + folder (one round-trip)."""
        store = _require_store(request, runtime)
        try:
            result = await asyncio.to_thread(
                aggregate_lookup,
                storage,
                store_prefix=store.prefix,
                article=article,
                kind=kind,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(
            {
                "article": result.article,
                "kind": result.kind,
                "found": result.found,
                "nomenclature": result.nomenclature,
                "quantity": result.quantity,
                "star": result.star,
                "next_index": result.next_index,
                "filename": result.filename,
                "relative_path": result.relative_path,
                "folder": result.folder,
                "photos_url": PHOTOS_PUBLIC_PREFIX + result.relative_path.lstrip("/"),
            }
        )

    @app.post("/api/upload")
    async def api_upload(
        request: Request,
        article: str = Form(...),
        indices: str = Form(...),
        files: list[UploadFile] = File(...),
        kind: str = Form("tire"),
    ) -> JSONResponse:
        store = _require_store(request, runtime)
        try:
            art = validate_article(article)
            product_kind = normalize_product_kind(kind)
            index_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not index_list:
            raise HTTPException(status_code=400, detail="Нет номеров фото")
        if len(index_list) != len(files):
            raise HTTPException(status_code=400, detail="Число файлов и номеров не совпадает")
        if len(index_list) > MAX_UPLOAD_BATCH:
            raise HTTPException(
                status_code=400,
                detail=f"За один раз не больше {MAX_UPLOAD_BATCH} фото",
            )

        items: list[tuple[int, bytes]] = []
        for idx, upload in zip(index_list, files):
            data = await upload.read()
            if not data:
                raise HTTPException(status_code=400, detail=f"Пустой файл для фото {idx}")
            items.append((idx, data))

        try:
            result = await asyncio.to_thread(
                save_store_uploads,
                storage,
                store_prefix=store.prefix,
                article=art,
                items=items,
                kind=product_kind,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        saved_urls = [
            PHOTOS_PUBLIC_PREFIX + str(rel).replace("\\", "/").lstrip("/")
            for rel in result.saved
        ]
        return JSONResponse(
            {
                "ok": True,
                "article": result.article,
                "kind": product_kind,
                "saved": result.saved,
                "photos_urls": saved_urls,
            }
        )

    return app
