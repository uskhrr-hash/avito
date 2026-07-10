"""Прямые https-ссылки на файлы Яндекс.Диска (API cloud-api.yandex.net)."""
from __future__ import annotations

import logging
from pathlib import Path

import requests
import yaml

LOG = logging.getLogger(__name__)

API_DOWNLOAD = "https://cloud-api.yandex.net/v1/disk/resources/download"
API_UPLOAD = "https://cloud-api.yandex.net/v1/disk/resources/upload"


def load_yandex_oauth_token(secrets_path: Path) -> str:
    if not secrets_path.is_file():
        return ""
    raw = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    yd = raw.get("yandex_disk") or {}
    return str(yd.get("oauth_token", "")).strip()


def disk_resource_path(yandex_disk_root: str, relative_name: str) -> str:
    root = yandex_disk_root.strip("/").strip("\\")
    name = relative_name.lstrip("/").replace("\\", "/")
    return f"disk:/{root}/{name}"


class YandexDiskDownloadUrls:
    """Кэширует href из GET /v1/disk/resources/download."""

    def __init__(self, token: str, *, timeout: float = 30.0):
        if not token:
            raise ValueError(
                "Для image_mode=yandex_https нужен yandex_disk.oauth_token "
                "в secrets.local.yaml"
            )
        self.token = token
        self.timeout = timeout
        self.upload_if_missing = True
        self._cache: dict[str, str] = {}
        self._upload_blocked = False

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("Authorization", f"OAuth {self.token}")
        return requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)

    def href_for_disk_path(self, disk_path: str) -> str:
        key = disk_path.strip()
        if key in self._cache:
            return self._cache[key]
        response = self._request("GET", API_DOWNLOAD, params={"path": key})
        response.raise_for_status()
        href = str(response.json().get("href", "")).strip()
        if not href:
            raise ValueError(f"Yandex Disk API: пустой href для {key}")
        self._cache[key] = href
        return href

    def upload_local_file(self, local_path: Path, disk_path: str) -> None:
        response = self._request(
            "GET",
            API_UPLOAD,
            params={"path": disk_path.strip(), "overwrite": "true"},
        )
        response.raise_for_status()
        upload_href = str(response.json().get("href", "")).strip()
        if not upload_href:
            raise ValueError(f"Yandex Disk API: пустой upload href для {disk_path}")
        with local_path.open("rb") as handle:
            put = self._request(
                "PUT",
                upload_href,
                data=handle,
                headers={"Content-Type": "application/octet-stream"},
            )
        put.raise_for_status()
        self._cache.pop(disk_path.strip(), None)

    def href_for_disk_file(
        self,
        disk_path: str,
        *,
        local_path: Path | None = None,
        upload_if_missing: bool = True,
    ) -> str | None:
        variants = _disk_path_name_variants(disk_path)
        last_error: requests.HTTPError | None = None
        for variant in variants:
            try:
                return self.href_for_disk_path(variant)
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code != 404:
                    raise
                last_error = exc
        if (
            upload_if_missing
            and self.upload_if_missing
            and not self._upload_blocked
            and local_path is not None
            and local_path.is_file()
        ):
            target = variants[0]
            try:
                LOG.info("Загрузка на Я.Диск: %s → %s", local_path.name, target)
                self.upload_local_file(local_path, target)
                return self.href_for_disk_path(target)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else 0
                if code in (403, 401):
                    self._upload_blocked = True
                    LOG.warning(
                        "Нет прав на загрузку в Я.Диск (нужен cloud_api:disk.write) — "
                        "дальнейшие попытки загрузки отключены"
                    )
                else:
                    LOG.warning(
                        "Не удалось загрузить %s на Я.Диск: %s",
                        local_path.name,
                        exc,
                    )
        if last_error is not None:
            LOG.warning(
                "На Я.Диске нет файла %s (локально: %s)",
                disk_path,
                local_path.name if local_path else "—",
            )
        return None


def _disk_path_name_variants(disk_path: str) -> list[str]:
    key = disk_path.strip()
    if not key.startswith("disk:/"):
        return [key]
    rest = key[len("disk:/") :]
    if "/" in rest:
        folder, filename = rest.rsplit("/", 1)
        dir_prefix = f"disk:/{folder}/"
    else:
        folder, filename = "", rest
        dir_prefix = "disk:/"
    stem = Path(filename)
    base, ext = stem.stem, stem.suffix
    variants = [key]
    if ext:
        for alt in {ext, ext.lower(), ext.upper()}:
            variants.append(f"{dir_prefix}{base}{alt}")
    seen: list[str] = []
    for item in variants:
        if item not in seen:
            seen.append(item)
    return seen
