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


def update_item_price(client: AvitoApiClient, item_id: int, price: int) -> dict[str, Any]:
    """POST /core/v1/items/{item_id}/update_price — цена сразу видна покупателям."""
    data = client.request(
        "POST",
        f"/core/v1/items/{int(item_id)}/update_price",
        json_body={"price": int(price)},
    )
    return data if isinstance(data, dict) else {}


def update_stocks(
    client: AvitoApiClient,
    stocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    PUT /stock-management/1/stocks — до 200 позиций за запрос.

    Каждый элемент: item_id (int), quantity (int), external_id (str, опционально).
    """
    if not stocks:
        return []
    if len(stocks) > 200:
        raise ValueError("Avito stocks: не более 200 позиций за запрос")
    data = client.request(
        "PUT",
        "/stock-management/1/stocks",
        json_body={"stocks": stocks},
    )
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
) -> dict[str, int]:
    """
    GET /autoload/v2/items/avito_ids — наш Id (md_123) → номер объявления на Avito.
    """
    clean = [str(x).strip() for x in ad_ids if str(x).strip()]
    if not clean:
        return {}
    out: dict[str, int] = {}
    step = max(1, min(int(batch_size), 200))
    for i in range(0, len(clean), step):
        chunk = clean[i : i + step]
        query = ",".join(chunk)
        data = client.request("GET", "/autoload/v2/items/avito_ids", params={"query": query})
        items = (data or {}).get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            continue
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
    return out

