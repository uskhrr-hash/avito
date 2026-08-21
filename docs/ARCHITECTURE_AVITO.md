# Avito architecture (185.198.152.108) — short vs long nginx classes

Server: `avito.shinaufa.ru` on AdminVPS booking host (`185.198.152.108`).
**Do not** confuse with shinaufa shop (`185.250.44.140`). Booking phase is separate.

Canon config: `local_lab/avito.shinaufa.ru.conf` → `/etc/nginx/sites-available/avito.shinaufa.ru.conf`.

## A1 DONE (2026-08-20) — split short / long / static

Goal: one upload/chat/session must not poison the short TLS/UI path via long `proxy_*_timeout`.

| Class | Locations | Timeouts | limit_conn |
|-------|-----------|----------|------------|
| **SHORT** | `/photo/` (UI, healthz), `/photo/api/` (except upload) | connect **5s**, send/read **15s** | `conn_avito_photo` **6** |
| **LONG** | `=/photo/api/upload` | connect 5s, send/read **120s** | `conn_avito_upload` **2** |
| **LONG** | `/chat/` | connect 5s, send/read **120s** | `conn_avito_chat` **6** |
| **STATIC** | `/photos/`, `/photo/static/` | n/a (disk) | photos **4**; static unlimited zone |

### HTTP/2 decision (A1)

- **Already off** site-wide on `:443` (`listen 443 ssl;` — no `http2`).
- Avito shares `0.0.0.0:443` with booking, tyren1, sms-api, sms-gate.
- nginx requires **identical listen options** for the same address:port → cannot disable/enable HTTP/2 for avito alone.
- **No listen change in A1** (experiment already satisfied: HTTP/1.1 only).
- **Revert note:** to re-enable HTTP/2 later, add `http2` (or `http2 on`) to **every** `listen 443` on this IP, not only avito.

### Backup on VPS

`/etc/nginx/sites-available/avito.shinaufa.ru.conf.bak-a1-shortlong-*`

### Verify

```bash
nginx -t && systemctl reload nginx
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 8 https://avito.shinaufa.ru/photo/
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 8 https://avito.shinaufa.ru/photo/healthz
# pick any public jpeg under /photos/
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 8 https://avito.shinaufa.ru/photos/<file>.jpg
# empty upload body → FastAPI validation (typically 422)
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 8 -X POST https://avito.shinaufa.ru/photo/api/upload
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 8 https://avito.shinaufa.ru/chat/
```

Also confirm timeouts in live config:

```bash
nginx -T 2>/dev/null | awk '/server_name avito/,/^}/' | grep -E 'location |proxy_.*_timeout|limit_conn'
```

## A2 DONE (2026-08-20) — light listings DTO + real HTTP 304

Scope: `/opt/avito_tires_parser/avito/photo_upload/` only (booking / shinaufa shop untouched).

| Item | Change |
|------|--------|
| **Listings DTO** | `/api/admin/listings` returns slim rows: `article`, `nomenclature`, `incoming`, `photo_count`, `folders`, `manual_price`, `calculated_price`, `price_rule` (dropped `mtime` / `has_photos` / `effective_price`) |
| **Photos list** | Dropped unused `mtime` from file rows |
| **ETag server** | Stable MD5 of canonical JSON body; robust `If-None-Match` (* / weak / list); `Cache-Control: private, no-cache`; HTTP **304** empty body |
| **ETag client** | `static/net.js`: memory TTL 45s + single-flight; after TTL / `forceRevalidate` sends `If-None-Match`; `fetch cache:"no-store"` so browser cache cannot hide 304 |
| **Kept** | Pagination 40, tab-lazy photos, AbortController on hidden tab |
| **Static bump** | `net.js?v=4`, `admin.js?v=10`, `app.js?v=15` |

### Backup on VPS

- `/opt/avito_tires_parser/avito/photo_upload/*.bak-a2-etag-20260820_220455`
- `/opt/avito_tires_parser/avito/photo_upload/backup_a2_20260820_220455/`

### Smoke (2026-08-20)

Authenticated store login → `GET /photo/api/admin/listings?limit=40&offset=0`:
1. **200** ~8KB, ETag `"55bb…"`, slim keys only
2. same URL + `If-None-Match` → **304**, 0 bytes, same ETag

`systemctl restart avito-photo-upload` → active; `/photo/healthz` → 200.

## A3 DONE (2026-08-20) — mobile upload queue (1 file at a time)

Scope: `/opt/avito_tires_parser/avito/photo_upload/static/app.js` (+ `app.py` cache-bust). Booking / shinaufa shop untouched. `admin.js` unchanged (no store upload path).

| Item | Change |
|------|--------|
| **Client queue** | Multi-file send no longer one giant multipart; each photo → separate `POST /photo/api/upload` |
| **Mobile** | UA iPhone/iPad/iPod/Android/Mobile → **max 1** concurrent upload |
| **Desktop** | **max 2** concurrent (aligned with nginx `conn_avito_upload` limit from A1) |
| **UX** | Button/overlay: «Загрузка 2/5…»; partial success keeps failed items in pending |
| **Single-file** | Still one request; same API contract (`indices` + one `files`) |
| **Static bump** | `app.js?v=16` |

### Backup on VPS

- `/opt/avito_tires_parser/avito/photo_upload/static/app.js.bak-a3-uploadq-20260820_221008`
- `/opt/avito_tires_parser/avito/photo_upload/app.py.bak-a3-uploadq-20260820_221008`

### Smoke (2026-08-20)

`systemctl restart avito-photo-upload` → active; `/photo/healthz` → 200; HTML cache-bust `app.js?v=16`; live static contains `uploadPendingQueue` / concurrency 1 mobile / 2 desktop.

## Remaining (infra)

- **A4** — isolate Avito worker pool / upstream capacity so long requests cannot exhaust workers shared with booking; measure after A3 client backpressure.
- **A5** — (planned) further TLS/accept hardening after A4 measurement.
- **A6** — (planned) booking-side equivalent short/long split (separate phase; do not start until approved).

---

## Photo v2 greenfield (canon locked 2026-08-20)

**Rule:** clean architecture; Photo v1 UI deleted in **S6**. Shared disk/stock helpers remain under `avito/photo_upload/{service,settings,db}.py`.

| | |
|--|--|
| **Path** | `https://avito.shinaufa.ru/` (**S5 cutover 2026-08-21**) |
| **Code** | `/opt/avito_tires_parser/avito/photo_v2/` (local: `local_lab/avito_stock_migrate/avito/photo_v2/`) |
| **Process** | `avito-photo-v2.service` → uvicorn `127.0.0.1:8766` (`run_photo_v2.py`) |
| **Auth** | Same shop passwords as v1 (`secrets.yaml` → `photo_upload.stores`); cookie `photo_v2_session` **path=`/`** |
| **Shops (v1)** | `md`, `pg` only |
| **Old URLs** | `/photo/`, `/photo/v2/` → **301 /** (v1 deleted in S6) |

### In scope (roadmap)

| Stage | Screens / API |
|-------|----------------|
| **S1** | Login page; `POST /api/login`, `POST /api/logout`, `GET /api/me`; `GET /api/stores`; `GET /healthz` |
| **S2** | Upload UI after login: kind tire/wheel, article, **one** aggregated `GET /api/lookup`, file queue (mobile 1 / desktop 2), `POST /api/upload` → same disk as v1 (`/opt/avito_tires_photos/...`); thumbs via `/photos/...` |
| **S2.1** | Light article picker on upload screen: `GET /api/articles` (search / `need_photos=1`), slim DTO, client memory cache 50s + single-flight + ETag/304; no full catalog on login |
| **S3 (now)** | Tabs after login: **Загрузка** / **Товары** / **Файлы**; listings & photos load only when tab opened; abort on tab switch |
| **S3.1** | Manager self-serve photo delete on **Файлы** (`POST /api/photos/delete`); shop-scoped list/delete; **S4 admin panel skipped** |
| **S3.2** | **Товары** = check one article (lookup + focused listings/photos); no infinite list on tab open |
| **S5** | Cutover: Photo v2 at `/` (no `/photo` prefix); cookie path `/`; old `/photo*` → 301 `/` |

### Out of scope for v1 (do not port)

- Chat (`/chat/`)
- Баллы / contributors
- Сотрудники / admin users
- **Full S4 admin panel** — managers delete photos themselves in S3.1 instead
- Monitoring / client-log beacons from old UI
- Old static `app.js` / `admin.js` / tab architecture

### nginx

```
location ^~ /static/              → alias …/photo_v2/static/
location = /api/login|logout      → 8766, connect 3s / send-read 5s
location = /api/upload            → 8766, LONG 120s, limit_conn conn_avito_upload 2, body 20M
location /api/                    → 8766, SHORT connect 5s / send-read 15s
location = /healthz               → 8766/healthz, SHORT
location = /                      → 8766/, SHORT
location /photo/ + /photo/v2/     → 301 /
```

HTTP `:80` → `301 https://$host$request_uri` (photo old paths → `https://$host/`).

`/chat/`, `/feeds/`, `/photos/`, `/health` unchanged.

### Smoke (S2)

```bash
curl -sk -o /dev/null -w '%{http_code}\n' --max-time 8 https://avito.shinaufa.ru/
curl -sk -o /dev/null -w '%{http_code}\n' --max-time 8 https://avito.shinaufa.ru/healthz
# login md → GET /api/lookup?article=…&kind=tire → POST /api/upload (1–2 JPEG) → files under /opt/avito_tires_photos/
curl -sk -o /dev/null -w '%{http_code} %{redirect_url}\n' --max-time 8 https://avito.shinaufa.ru/photo/v2/
curl -sk -o /dev/null -w '%{http_code}\n' --max-time 8 https://avito.shinaufa.ru/chat/
```

### S5 DONE (2026-08-21) — Photo v2 at domain root

| Item | Detail |
|------|--------|
| **URL** | `https://avito.shinaufa.ru/` (login + app) |
| **Cookie** | `photo_v2_session` path=`/` (re-login after cutover) |
| **Redirects** | `/photo`, `/photo/`, `/photo/v2`, `/photo/v2/` → **301 /** |
| **v1** | Removed in **S6** (was `:8765`, not proxied after S5) |
| **Static** | `?v=13`; healthz stage `s5` |
| **Untouched** | `/chat/`, booking host, shop `185.250.44.140` |

Backup on VPS: `avito.shinaufa.ru.conf.bak-s5-root-*` + `/var/backups/avito_photo_v2_s5_*`.

### S6 DONE (2026-08-21) — delete Photo v1

| Item | Detail |
|------|--------|
| **Stop** | `systemctl disable --now avito-photo-upload`; unit removed |
| **Delete UI** | `run_photo_upload.py`, `avito/photo_upload/{app,admin,guide,overlays}.py`, `static/` |
| **Keep lib** | `avito/photo_upload/{service,settings,db}.py` — used by `photo_v2.storage` |
| **Process** | Only `avito-photo-v2` on `127.0.0.1:8766` |
| **nginx** | Unchanged from S5 (`/photo*` → 301 `/`); no proxy to `:8765` |
| **Bookmarks** | Old `/photo/` URLs still redirect to `/` |

### S2.1 — light articles picker (2026-08-20)

| Item | Detail |
|------|--------|
| **API** | `GET /api/articles?q=&kind=tire\|wheel&limit=40&offset=0&need_photos=0\|1` |
| **DTO** | `article`, optional `nomenclature` (short), `quantity`, `photo_count`; plus `has_more` / `mode` |
| **Sources** | `search_stock` (typeahead) / `load_no_photos_queue` («Подобрать») via `photo_v2.storage` |
| **Cache** | Server ETag + 304; client memory TTL **50s**, single-flight, `If-None-Match` after TTL |
| **Lazy** | No catalog fetch on login — only on «Подобрать» or typeahead (≥2 chars) |
| **Static** | `?v=4` |

### S3 — Товары + Файлы (2026-08-21)

| Item | Detail |
|------|--------|
| **UI** | Tabs: Загрузка (S2/S2.1), Товары, Файлы — after login only |
| **API Товары** | `GET /api/listings?kind=tire\|wheel&limit=40&offset=0&q=` — slim DTO, ETag/304 |
| **API Файлы** | `GET /api/photos?limit=40&offset=0&article=&folder=` — thumbs via `/photos/...` |
| **Lazy** | No listings/photos fetch on login; load on tab open; «Ещё» pagination; abort in-flight on tab switch |
| **Cache** | Client memory TTL **50s** + single-flight + `If-None-Match`; server ETag |
| **Thumbs** | Lazy `data-src`, max **3** concurrent loads |
| **Disk** | Same as v1 (`photo_upload` helpers / `/opt/avito_tires_photos`) |
| **Static** | `?v=5` |
| **healthz** | `{"ok":true,"app":"photo_v2","stage":"s3"}` |

### S3.1 — manager photo delete (2026-08-21)

| Item | Detail |
|------|--------|
| **Why** | Managers delete their own photos → **S4 admin panel not needed** |
| **UI** | Tab **Файлы**: button «Удалить» + `confirm()` (mobile-friendly) |
| **API** | `POST /api/photos/delete` JSON `{relative_path}`; auth cookie; shop-scoped |
| **Disk** | Same as v1 `delete_photo_file` → unlink under `/opt/avito_tires_photos/` + invalidate photo index cache |
| **Scope** | List & delete only `{store}/…` (md/pg); cross-shop rejected |
| **Soft-fail** | Missing file → `ok:true, missing:true`; bad path → 400 (no 500) |
| **Static** | `?v=6` |
| **healthz** | `{"ok":true,"app":"photo_v2","stage":"s3.1"}` |

### S3.2 — Товары: check one article (2026-08-21)

| Item | Detail |
|------|--------|
| **Why** | Managers need to verify **one** SKU, not scroll an infinite product dump |
| **UI** | Tab **Товары**: kind + article input + «Проверить» → one result card (exists?, title, stock, photo count, price, thumbs); «В загрузку» |
| **No dump** | Opening the tab does **not** call `/api/listings` without `q`; no «Ещё» list |
| **APIs** | Reuses `GET /api/lookup`, `GET /api/listings?q=&limit=10`, `GET /api/photos?article=` (thumbs); pagination listings still available internally |
| **Static** | `?v=9` |
| **healthz** | `{"ok":true,"app":"photo_v2","stage":"s3.2"}` |

## Related

- TLS hang root cause & heal: `deploy/NGINX_TLS_HEAL.md`
- Unit file: `deploy/avito-photo-v2.service`
