"""OAuth и базовые вызовы Avito Business API."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

LOG = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.avito.ru"
DEFAULT_TOKEN_URL = f"{DEFAULT_API_BASE}/token"

# Расписание по умолчанию: каждый день в 04:00 МСК, до 1000 объявлений за слот.
DEFAULT_AUTOLOAD_SCHEDULE: list[dict[str, Any]] = [
    {"rate": 1000, "weekdays": [0, 1, 2, 3, 4, 5, 6], "time_slots": [4]},
]


@dataclass(frozen=True)
class AvitoApiConfig:
    client_id: str
    client_secret: str
    api_base: str = DEFAULT_API_BASE
    token_url: str = DEFAULT_TOKEN_URL
    timeout_sec: float = 60.0


@dataclass
class AvitoToken:
    access_token: str
    expires_at: float
    token_type: str = "Bearer"

    @property
    def valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - 30


class AvitoApiClient:
    def __init__(self, cfg: AvitoApiConfig) -> None:
        self._cfg = cfg
        self._token: AvitoToken | None = None

    def get_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._token and self._token.valid:
            return self._token.access_token
        self._token = fetch_token(self._cfg)
        return self._token.access_token

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self._cfg.api_base.rstrip('/')}/{path.lstrip('/')}"
        token = self.get_token()
        resp = requests.request(
            method.upper(),
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            json=json_body,
            timeout=self._cfg.timeout_sec,
        )
        if resp.status_code == 401:
            token = self.get_token(force_refresh=True)
            resp = requests.request(
                method.upper(),
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                json=json_body,
                timeout=self._cfg.timeout_sec,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Avito API {method.upper()} {path}: HTTP {resp.status_code}: {resp.text[:800]}")
        if not resp.content:
            return None
        return resp.json()


def load_avito_api_config(secrets: dict[str, Any]) -> AvitoApiConfig:
    raw = secrets.get("avito") or {}
    client_id = str(raw.get("client_id", "") or "").strip()
    client_secret = str(raw.get("client_secret", "") or "").strip()
    if not client_id or not client_secret:
        raise ValueError("В secrets.local.yaml не заданы avito.client_id и avito.client_secret")
    api_base = str(raw.get("api_base", DEFAULT_API_BASE)).strip().rstrip("/")
    token_url = str(raw.get("token_url", f"{api_base}/token")).strip()
    return AvitoApiConfig(
        client_id=client_id,
        client_secret=client_secret,
        api_base=api_base,
        token_url=token_url,
        timeout_sec=float(raw.get("timeout_sec", 60)),
    )


def fetch_token(cfg: AvitoApiConfig) -> AvitoToken:
    resp = requests.post(
        cfg.token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=cfg.timeout_sec,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Avito token HTTP {resp.status_code}: {resp.text[:800]}")
    data = resp.json()
    access_token = str(data.get("access_token", "") or "").strip()
    if not access_token:
        raise RuntimeError(f"Avito token: нет access_token в ответе: {data}")
    expires_in = int(data.get("expires_in", 3600) or 3600)
    return AvitoToken(
        access_token=access_token,
        expires_at=time.time() + expires_in,
        token_type=str(data.get("token_type", "Bearer") or "Bearer"),
    )


def get_autoload_profile(client: AvitoApiClient) -> dict[str, Any]:
    data = client.request("GET", "/autoload/v2/profile")
    return data if isinstance(data, dict) else {}


def get_self_user(client: AvitoApiClient) -> dict[str, Any]:
    data = client.request("GET", "/core/v1/accounts/self")
    return data if isinstance(data, dict) else {}


def update_autoload_profile(
    client: AvitoApiClient,
    *,
    feed_name: str,
    feed_url: str,
    report_email: str,
    schedule: list[dict[str, Any]] | None = None,
    autoload_enabled: bool = True,
    agreement: bool | None = None,
) -> dict[str, Any]:
    email = str(report_email or "").strip()
    if not email:
        raise ValueError("report_email обязателен для POST /autoload/v2/profile")
    sched = list(schedule or DEFAULT_AUTOLOAD_SCHEDULE)
    body: dict[str, Any] = {
        "autoload_enabled": autoload_enabled,
        "feeds_data": [{"feed_name": feed_name, "feed_url": feed_url}],
        "report_email": email,
        "schedule": sched,
    }
    if agreement is not None:
        body["agreement"] = agreement
    data = client.request("POST", "/autoload/v2/profile", json_body=body)
    return data if isinstance(data, dict) else {}


def trigger_autoload_upload(client: AvitoApiClient) -> dict[str, Any]:
    data = client.request("POST", "/autoload/v1/upload")
    return data if isinstance(data, dict) else {}


def get_last_successful_upload(client: AvitoApiClient) -> dict[str, Any]:
    data = client.request("GET", "/autoload/v4/uploads/last_successful")
    return data if isinstance(data, dict) else {}


def update_item_price(
    client: AvitoApiClient,
    item_id: int,
    price: int,
    *,
    max_retries: int = 4,
) -> dict[str, Any]:
    """POST /core/v1/items/{item_id}/update_price — цена сразу видна покупателям.

    При HTTP 429 — экспоненциальный backoff (как у fetch_avito_ids).
    """
    last_exc: Exception | None = None
    for attempt in range(max(1, int(max_retries))):
        try:
            data = client.request(
                "POST",
                f"/core/v1/items/{int(item_id)}/update_price",
                json_body={"price": int(price)},
            )
            return data if isinstance(data, dict) else {}
        except RuntimeError as exc:
            last_exc = exc
            msg = str(exc)
            if "429" in msg and attempt + 1 < max_retries:
                wait = min(60.0, float(2**attempt))
                LOG.warning(
                    "update_price rate-limit item=%s, sleep %.1fs (attempt %s/%s)",
                    item_id,
                    wait,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(wait)
                continue
            raise
    if last_exc:
        raise last_exc
    return {}


def update_stocks(
    client: AvitoApiClient,
    stocks: list[dict[str, Any]],
    *,
    max_retries: int = 4,
) -> list[dict[str, Any]]:
    """
    PUT /stock-management/1/stocks — до 200 позиций за запрос.

    Каждый элемент: item_id (int), quantity (int), external_id (str, опционально).
    При HTTP 429 — экспоненциальный backoff.
    """
    if not stocks:
        return []
    if len(stocks) > 200:
        raise ValueError("Avito stocks: не более 200 позиций за запрос")
    last_exc: Exception | None = None
    data: Any = None
    for attempt in range(max(1, int(max_retries))):
        try:
            data = client.request(
                "PUT",
                "/stock-management/1/stocks",
                json_body={"stocks": stocks},
            )
            break
        except RuntimeError as exc:
            last_exc = exc
            msg = str(exc)
            if "429" in msg and attempt + 1 < max_retries:
                wait = min(60.0, float(2**attempt))
                LOG.warning(
                    "stocks rate-limit (%s items), sleep %.1fs (attempt %s/%s)",
                    len(stocks),
                    wait,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(wait)
                continue
            raise
    else:
        if last_exc:
            raise last_exc
        return []
    if isinstance(data, dict):
        items = data.get("stocks") or data.get("items")
        if isinstance(items, list):
            return items
    if isinstance(data, list):
        return data
    return []


def fetch_avito_ids_by_ad_ids(
    client: AvitoApiClient,
    ad_ids: list[str],
    *,
    batch_size: int = 100,
    pause_sec: float = 0.15,
    max_retries: int = 4,
) -> dict[str, int]:
    """
    GET /autoload/v2/items/avito_ids — наш Id (md_123) → номер объявления на Avito.

    При HTTP 429 — экспоненциальный backoff; при прочих ошибках батча — warn и дальше.
    """
    clean = [str(x).strip() for x in ad_ids if str(x).strip()]
    if not clean:
        return {}
    out: dict[str, int] = {}
    step = max(1, min(int(batch_size), 200))
    total_batches = (len(clean) + step - 1) // step
    for bi, i in enumerate(range(0, len(clean), step), start=1):
        chunk = clean[i : i + step]
        query = ",".join(chunk)
        data: Any = None
        for attempt in range(max(1, int(max_retries))):
            try:
                data = client.request(
                    "GET",
                    "/autoload/v2/items/avito_ids",
                    params={"query": query},
                )
                break
            except RuntimeError as exc:
                msg = str(exc)
                if "429" in msg and attempt + 1 < max_retries:
                    wait = min(60.0, float(2**attempt))
                    LOG.warning(
                        "avito_ids API rate-limit (батч %s/%s), sleep %.1fs",
                        bi,
                        total_batches,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                LOG.warning(
                    "avito_ids API батч %s/%s (%s Id): %s",
                    bi,
                    total_batches,
                    len(chunk),
                    msg[:300],
                )
                data = None
                break
        items = (data or {}).get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            for row in items:
                if not isinstance(row, dict):
                    continue
                ad_id = str(row.get("ad_id", "") or "").strip()
                avito_id = row.get("avito_id")
                if ad_id and avito_id is not None:
                    try:
                        out[ad_id] = int(avito_id)
                    except (TypeError, ValueError):
                        pass
        if pause_sec > 0 and i + step < len(clean):
            time.sleep(float(pause_sec))
    LOG.info(
        "avito_ids API: запрошено %s Id, получено %s соответствий (%s батчей)",
        len(clean),
        len(out),
        total_batches,
    )
    return out


def fetch_avito_ids_from_report_items(
    client: AvitoApiClient,
    *,
    report_id: str | int | None = None,
    per_page: int = 100,
    max_pages: int = 200,
) -> dict[str, int]:
    """
    ad_id → avito_id из отчёта автозагрузки (последний успешный upload, если report_id не задан).

    Дополняет /items/avito_ids: видны свежие публикации из фида.
    """
    rid = report_id
    if rid is None:
        last = get_last_successful_upload(client)
        rid = (last or {}).get("report_id") or (last or {}).get("id")
        if not rid and isinstance(last, dict):
            upload = last.get("upload") if isinstance(last.get("upload"), dict) else last
            rid = (upload or {}).get("report_id") or (upload or {}).get("id")
    if not rid:
        return {}
    out: dict[str, int] = {}
    page = 1
    rate_hits = 0
    while page <= max(1, int(max_pages)):
        try:
            data = client.request(
                "GET",
                f"/autoload/v2/reports/{rid}/items",
                params={"page": page, "per_page": max(1, min(int(per_page), 100))},
            )
            rate_hits = 0
        except RuntimeError as exc:
            if "429" in str(exc) and rate_hits < 4:
                rate_hits += 1
                wait = min(60.0, float(2**rate_hits))
                LOG.warning("report items rate-limit page=%s, sleep %.1fs", page, wait)
                time.sleep(wait)
                continue
            LOG.warning("report items page=%s: %s", page, exc)
            break
        items = (data or {}).get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            break
        for row in items:
            if not isinstance(row, dict):
                continue
            ad_id = str(row.get("ad_id", "") or "").strip()
            avito_id = row.get("avito_id")
            if not ad_id or avito_id is None:
                continue
            try:
                out[ad_id] = int(avito_id)
            except (TypeError, ValueError):
                continue
        meta = (data or {}).get("meta") if isinstance(data, dict) else None
        pages = int((meta or {}).get("pages") or 0) if isinstance(meta, dict) else 0
        if pages and page >= pages:
            break
        if len(items) < max(1, min(int(per_page), 100)):
            break
        page += 1
    if out:
        LOG.info("avito_ids из отчёта %s: %s соответствий", rid, len(out))
    return out

