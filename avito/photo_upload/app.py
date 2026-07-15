"""FastAPI-приложение для загрузки фото с телефона."""
from __future__ import annotations

import hmac
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from avito.photo_upload import db as photo_db
from avito.photo_upload.admin import render_admin_html
from avito.photo_upload.guide import render_guide_html
from avito.photo_upload.overlays import (
    EXAMPLE_FILES,
    ghost_image_for_shot,
    overlay_svg_for_shot,
    shot_label,
)
from avito.photo_upload.service import (
    delete_photo_file,
    list_photo_files,
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
SESSION_ROLE = "photo_upload_role"
SESSION_STORE = "photo_upload_store"
SESSION_USER_ID = "photo_upload_user_id"

ROLE_STORE = "store"
ROLE_CONTRIBUTOR = "contributor"
ROLE_ADMIN = "admin"


@dataclass(frozen=True)
class SessionIdentity:
    role: str
    prefix: str
    label: str
    user_id: int | None = None
    points_balance: int | None = None
    ushk_supplier: str = ""


def _verify_store_password(store: StoreLogin, password: str) -> bool:
    return hmac.compare_digest(store.password, password)


def _current_identity(
    request: Request, runtime: PhotoUploadRuntime
) -> SessionIdentity | None:
    role = str(request.session.get(SESSION_ROLE, "")).strip()
    if role == ROLE_STORE:
        prefix = str(request.session.get(SESSION_STORE, "")).strip()
        for store in runtime.stores:
            if store.prefix == prefix:
                return SessionIdentity(
                    role=ROLE_STORE, prefix=store.prefix, label=store.label
                )
        return None
    if role in (ROLE_CONTRIBUTOR, ROLE_ADMIN):
        user_id = request.session.get(SESSION_USER_ID)
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None
        user = None
        balance = None
        with runtime.db() as conn:
            user = photo_db.get_user_by_id(conn, uid)
            if user is not None and user.active and user.role == role:
                if role == ROLE_CONTRIBUTOR:
                    balance = photo_db.user_balance(conn, uid)
        if user is None or not user.active or user.role != role:
            return None
        if role == ROLE_CONTRIBUTOR:
            return SessionIdentity(
                role=ROLE_CONTRIBUTOR,
                prefix=runtime.contributors_prefix,
                label=user.display_name or user.login,
                user_id=uid,
                points_balance=balance,
                ushk_supplier=user.ushk_supplier,
            )
        return SessionIdentity(
            role=ROLE_ADMIN,
            prefix="",
            label=user.display_name or user.login,
            user_id=uid,
        )
    # backward compat: old sessions only had store key
    prefix = str(request.session.get(SESSION_STORE, "")).strip()
    if prefix:
        for store in runtime.stores:
            if store.prefix == prefix:
                return SessionIdentity(
                    role=ROLE_STORE, prefix=store.prefix, label=store.label
                )
    return None


def _require_identity(
    request: Request, runtime: PhotoUploadRuntime
) -> SessionIdentity:
    ident = _current_identity(request, runtime)
    if ident is None:
        raise HTTPException(status_code=401, detail="Нужен вход")
    return ident


def _require_uploader(
    request: Request, runtime: PhotoUploadRuntime
) -> SessionIdentity:
    ident = _require_identity(request, runtime)
    if ident.role not in (ROLE_STORE, ROLE_CONTRIBUTOR):
        raise HTTPException(status_code=403, detail="Нет доступа к загрузке")
    return ident


def _require_admin(
    request: Request, runtime: PhotoUploadRuntime
) -> SessionIdentity:
    ident = _require_identity(request, runtime)
    if ident.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Только админ")
    return ident


def _max_index_for(ident: SessionIdentity, runtime: PhotoUploadRuntime) -> int:
    if ident.role == ROLE_CONTRIBUTOR:
        return runtime.contributor_max_photos
    return 19


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
                "ghost_url": ghost_image_for_shot(idx),
            }
        )

    @app.get("/guide", response_class=HTMLResponse)
    async def guide() -> HTMLResponse:
        return HTMLResponse(render_guide_html(base=_mount_base(runtime)))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        ident = _current_identity(request, runtime)
        if ident is None:
            return HTMLResponse(_login_html(runtime))
        if ident.role == ROLE_ADMIN:
            return RedirectResponse(url="admin", status_code=302)
        return HTMLResponse(_app_html(runtime, ident))

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page(request: Request) -> HTMLResponse:
        ident = _current_identity(request, runtime)
        if ident is None:
            return RedirectResponse(url="./", status_code=302)
        if ident.role != ROLE_ADMIN:
            raise HTTPException(status_code=403, detail="Только админ")
        return HTMLResponse(render_admin_html(base=_mount_base(runtime)))

    @app.get("/api/stores")
    async def api_stores() -> JSONResponse:
        payload = [{"prefix": s.prefix, "label": s.label} for s in runtime.stores]
        return JSONResponse(payload)

    @app.post("/api/login")
    async def api_login(request: Request) -> JSONResponse:
        payload = await request.json()
        store_prefix = str(payload.get("store", "")).strip()
        login = str(payload.get("login", "")).strip()
        password = str(payload.get("password", ""))

        if store_prefix:
            store = next((s for s in runtime.stores if s.prefix == store_prefix), None)
            if store is None or not _verify_store_password(store, password):
                raise HTTPException(status_code=401, detail="Неверный магазин или пароль")
            request.session.clear()
            request.session[SESSION_ROLE] = ROLE_STORE
            request.session[SESSION_STORE] = store.prefix
            return JSONResponse(
                {"ok": True, "role": ROLE_STORE, "store": store.prefix, "label": store.label}
            )

        if login:
            with runtime.db() as conn:
                user = photo_db.authenticate_user(conn, login, password)
            if user is None:
                raise HTTPException(status_code=401, detail="Неверный логин или пароль")
            request.session.clear()
            request.session[SESSION_ROLE] = user.role
            request.session[SESSION_USER_ID] = user.id
            if user.role == ROLE_CONTRIBUTOR:
                request.session[SESSION_STORE] = runtime.contributors_prefix
            return JSONResponse(
                {
                    "ok": True,
                    "role": user.role,
                    "label": user.display_name or user.login,
                    "redirect": "admin" if user.role == ROLE_ADMIN else "./",
                }
            )

        raise HTTPException(status_code=400, detail="Укажите магазин или логин")

    @app.post("/api/logout")
    async def api_logout(request: Request) -> JSONResponse:
        request.session.clear()
        return JSONResponse({"ok": True})

    @app.get("/api/me")
    async def api_me(request: Request) -> JSONResponse:
        ident = _require_identity(request, runtime)
        payload = {
            "role": ident.role,
            "store": ident.prefix,
            "label": ident.label,
        }
        if ident.role == ROLE_CONTRIBUTOR:
            payload["points_balance"] = ident.points_balance
            payload["points_per_photo"] = runtime.points_per_photo
            payload["max_photos"] = runtime.contributor_max_photos
            payload["ushk_supplier"] = ident.ushk_supplier
        elif ident.role == ROLE_STORE:
            store = next((s for s in runtime.stores if s.prefix == ident.prefix), None)
            payload["ushk_supplier"] = store.ushk_supplier if store else None
        return JSONResponse(payload)

    @app.get("/api/stock/lookup")
    async def api_stock_lookup(request: Request, article: str = "") -> JSONResponse:
        _require_uploader(request, runtime)
        item = lookup_stock(runtime, article)
        if item is None:
            return JSONResponse({"found": False})
        return JSONResponse(
            {
                "found": True,
                "article": item.article,
                "nomenclature": item.nomenclature,
                "quantity": item.quantity,
                "star": item.star,
            }
        )

    @app.get("/api/stock/search")
    async def api_stock_search(request: Request, q: str = "") -> JSONResponse:
        _require_uploader(request, runtime)
        rows = search_stock(runtime, q)
        return JSONResponse(
            [
                {
                    "article": r.article,
                    "nomenclature": r.nomenclature,
                    "quantity": r.quantity,
                    "star": r.star,
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
        ident = _require_uploader(request, runtime)
        want_in_store = bool(in_store)
        ushk_override: str | None = None

        if ident.role == ROLE_CONTRIBUTOR:
            # Все артикулы без фото (md/pg), фильтр «в магазине» — по складу сотрудника
            store_prefix = ""
            ushk_override = ident.ushk_supplier or None
            in_store_only = want_in_store
        else:
            store_prefix = ident.prefix
            in_store_only = want_in_store
            store = next((s for s in runtime.stores if s.prefix == store_prefix), None)
            ushk_override = store.ushk_supplier if store else None

        result = load_no_photos_queue_info(
            runtime,
            store_prefix=store_prefix,
            limit=min(limit, 200),
            in_store_only=in_store_only,
            ushk_supplier=ushk_override,
        )
        return JSONResponse(
            {
                "items": [
                    {
                        "article": r.article,
                        "nomenclature": r.nomenclature,
                        "stores": r.stores,
                        "problem": r.problem,
                        "star": r.star,
                    }
                    for r in result.items
                ],
                "source_file": result.source_file,
                "hint": result.hint,
                "count": len(result.items),
                "in_store_only": in_store_only,
                "ushk_supplier": ushk_override,
            }
        )

    @app.get("/api/next-index")
    async def api_next_index(request: Request, article: str = "") -> JSONResponse:
        ident = _require_uploader(request, runtime)
        art = validate_article(article)
        max_idx = _max_index_for(ident, runtime)
        try:
            idx = next_photo_index(
                runtime,
                store_prefix=ident.prefix,
                article=art,
                max_index=max_idx,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        meta = pending_photo_meta(
            runtime,
            store_prefix=ident.prefix,
            article=art,
            index=idx,
            max_index=max_idx,
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
        ident = _require_uploader(request, runtime)
        art = validate_article(article)
        max_idx = _max_index_for(ident, runtime)
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
                store_prefix=ident.prefix,
                article=art,
                items=items,
                max_index=max_idx,
                contributor_user_id=(
                    ident.user_id if ident.role == ROLE_CONTRIBUTOR else None
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return JSONResponse(
            {
                "ok": True,
                "article": result.article,
                "saved": result.saved,
                "points_awarded": result.points_awarded,
                "balance": result.balance,
            }
        )

    # --- admin APIs ---

    @app.get("/api/admin/users")
    async def admin_users(request: Request) -> JSONResponse:
        _require_admin(request, runtime)
        with runtime.db() as conn:
            users = photo_db.list_users(conn)
        return JSONResponse(
            {
                "users": [
                    {
                        "id": u.id,
                        "login": u.login,
                        "display_name": u.display_name,
                        "role": u.role,
                        "active": u.active,
                        "created_at": u.created_at,
                        "ushk_supplier": u.ushk_supplier,
                    }
                    for u in users
                ]
            }
        )

    @app.get("/api/admin/shops")
    async def admin_shops(request: Request) -> JSONResponse:
        """Подсказки складов УШК для привязки сотрудника."""
        _require_admin(request, runtime)
        names: list[str] = []
        seen: set[str] = set()

        def _add(name: str) -> None:
            n = name.strip()
            if n and n not in seen:
                seen.add(n)
                names.append(n)

        for shop in runtime.config.photo_upload.contributor_shops:
            _add(shop)
        for store in runtime.stores:
            if store.ushk_supplier:
                _add(store.ushk_supplier)

        try:
            import yaml as _yaml
            from avito.store_registry import list_suppliers_by_prefix

            secrets = (
                _yaml.safe_load(runtime.secrets_file.read_text(encoding="utf-8")) or {}
            )
            for name in list_suppliers_by_prefix(
                secrets, name_prefix=runtime.config.stock_sources.db_ushk_prefix
            ):
                _add(name)
        except Exception as exc:
            LOG.warning("Не удалось загрузить склады УШК из ERP: %s", exc)

        names.sort(key=str.casefold)
        return JSONResponse({"shops": names})

    @app.post("/api/admin/users")
    async def admin_create_user(request: Request) -> JSONResponse:
        _require_admin(request, runtime)
        payload = await request.json()
        try:
            with runtime.db() as conn:
                user = photo_db.create_user(
                    conn,
                    login=str(payload.get("login", "")),
                    password=str(payload.get("password", "")),
                    role=str(payload.get("role") or photo_db.ROLE_CONTRIBUTOR),
                    display_name=str(payload.get("display_name", "")),
                    ushk_supplier=str(payload.get("ushk_supplier", "")),
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(
            {
                "ok": True,
                "user": {
                    "id": user.id,
                    "login": user.login,
                    "display_name": user.display_name,
                    "role": user.role,
                    "ushk_supplier": user.ushk_supplier,
                },
            }
        )

    @app.post("/api/admin/users/{user_id}/shop")
    async def admin_set_shop(request: Request, user_id: int) -> JSONResponse:
        _require_admin(request, runtime)
        payload = await request.json()
        try:
            with runtime.db() as conn:
                user = photo_db.set_user_ushk_supplier(
                    conn, user_id, str(payload.get("ushk_supplier", ""))
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(
            {"ok": True, "ushk_supplier": user.ushk_supplier, "id": user.id}
        )

    @app.post("/api/admin/users/{user_id}/active")
    async def admin_set_active(request: Request, user_id: int) -> JSONResponse:
        _require_admin(request, runtime)
        payload = await request.json()
        try:
            with runtime.db() as conn:
                user = photo_db.set_user_active(
                    conn, user_id, bool(payload.get("active", True))
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "active": user.active})

    @app.post("/api/admin/users/{user_id}/password")
    async def admin_reset_password(request: Request, user_id: int) -> JSONResponse:
        _require_admin(request, runtime)
        payload = await request.json()
        try:
            with runtime.db() as conn:
                photo_db.reset_password(
                    conn, user_id, str(payload.get("password", ""))
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True})

    @app.get("/api/admin/balances")
    async def admin_balances(request: Request) -> JSONResponse:
        _require_admin(request, runtime)
        with runtime.db() as conn:
            items = photo_db.list_balances(conn)
        return JSONResponse({"items": items})

    @app.get("/api/admin/ledger")
    async def admin_ledger(
        request: Request, user_id: int | None = None, limit: int = 50
    ) -> JSONResponse:
        _require_admin(request, runtime)
        with runtime.db() as conn:
            rows = photo_db.list_ledger(conn, user_id=user_id, limit=limit)
        return JSONResponse(
            {
                "items": [
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "login": r.login,
                        "display_name": r.display_name,
                        "delta": r.delta,
                        "reason": r.reason,
                        "article": r.article,
                        "photo_index": r.photo_index,
                        "created_at": r.created_at,
                    }
                    for r in rows
                ]
            }
        )

    @app.post("/api/admin/points/deduct")
    async def admin_deduct(request: Request) -> JSONResponse:
        admin = _require_admin(request, runtime)
        payload = await request.json()
        try:
            with runtime.db() as conn:
                balance = photo_db.deduct_points(
                    conn,
                    user_id=int(payload.get("user_id")),
                    amount=int(payload.get("amount", 0)),
                    reason=str(payload.get("reason", "")),
                    admin_id=admin.user_id or 0,
                )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "balance": balance})

    @app.get("/api/admin/photos")
    async def admin_photos(
        request: Request, folder: str = "", article: str = "", limit: int = 80
    ) -> JSONResponse:
        _require_admin(request, runtime)
        items = list_photo_files(
            runtime, folder=folder, article=article, limit=min(limit, 200)
        )
        return JSONResponse({"items": items})

    @app.post("/api/admin/photos/delete")
    async def admin_photos_delete(request: Request) -> JSONResponse:
        _require_admin(request, runtime)
        payload = await request.json()
        try:
            deleted = delete_photo_file(
                runtime, str(payload.get("relative_path", ""))
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "deleted": deleted})

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
    <p class="lead">Магазин или логин сотрудника</p>
    <a class="login-guide-link" href="guide">📷 Стандарт съёмки: 4 фото с контурами</a>

    <form id="login-form" class="card">
      <p class="field"><span>Магазин (Авито)</span></p>
      <div class="store-grid" id="store-grid">
{store_cards}
      </div>
      <input type="hidden" id="store" name="store" value="">
      <label class="field">
        <span>Пароль магазина</span>
        <input id="password" type="password" autocomplete="current-password" placeholder="Если выбран магазин">
      </label>
      <hr class="login-divider">
      <p class="field"><span>Или сотрудник / админ</span></p>
      <label class="field">
        <span>Логин</span>
        <input id="login" type="text" autocomplete="username" placeholder="логин">
      </label>
      <label class="field">
        <span>Пароль</span>
        <input id="user-password" type="password" autocomplete="current-password" placeholder="пароль сотрудника">
      </label>
      <p id="login-error" class="error hidden"></p>
      <button type="submit" class="btn btn-primary">Войти</button>
    </form>
  </main>
  <script src="static/login.js?v=2"></script>
</body>
</html>"""


def _app_html(runtime: PhotoUploadRuntime, ident: SessionIdentity) -> str:
    base = _mount_base(runtime)
    is_contrib = ident.role == ROLE_CONTRIBUTOR
    session = {
        "role": ident.role,
        "prefix": ident.prefix,
        "label": ident.label,
        "points_balance": ident.points_balance,
        "points_per_photo": runtime.points_per_photo if is_contrib else None,
        "max_photos": runtime.contributor_max_photos if is_contrib else 19,
        "ushk_supplier": ident.ushk_supplier if is_contrib else None,
    }
    store_json = json.dumps(session, ensure_ascii=False)
    points_bar = ""
    if is_contrib:
        bal = ident.points_balance or 0
        shop = ident.ushk_supplier or "магазин не назначен"
        points_bar = f'''
      <div class="topbar-points">Баллы: <strong id="points-balance">{bal}</strong>
        <span class="muted">(+{runtime.points_per_photo}/фото, до {runtime.contributor_max_photos})</span>
      </div>
      <div class="topbar-shop muted" id="user-shop">{shop}</div>'''
    queue_toggle = ""
    if is_contrib:
        if ident.ushk_supplier:
            queue_toggle = f"""
      <label class="toggle-row">
        <input type="checkbox" id="in-store-only" checked>
        <span>Есть в моём магазине ({ident.ushk_supplier})</span>
      </label>"""
        else:
            queue_toggle = """
      <p class="muted queue-hint">Магазин не назначен — попросите админа указать склад УШК. Показаны все позиции без фото.</p>
      <input type="checkbox" id="in-store-only" hidden>"""
    else:
        queue_toggle = """
      <label class="toggle-row">
        <input type="checkbox" id="in-store-only">
        <span>Есть в магазине (по реестру УШК)</span>
      </label>"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1">
  <meta name="theme-color" content="#2563eb">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <base href="{base}">
  <title>Фото — {ident.label}</title>
  <link rel="stylesheet" href="static/app.css">
  <link rel="stylesheet" href="static/camera.css?v=4">
</head>
<body class="page-app">
  <header class="topbar">
    <div>
      <div class="topbar-title">Фото Avito</div>
      <div class="topbar-sub">{ident.label}</div>
      {points_bar}
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
      {queue_toggle}
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
  <script src="static/app.js?v=7"></script>
</body>
</html>"""
