"""Клиент сервиса нормализации номенклатуры (словари на 192.168.1.75)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class NomenclatureApiError(RuntimeError):
    pass


def normalize_titles(
    titles: list[str],
    *,
    base_url: str = "http://192.168.1.75/",
    batch_size: int = 40,
    pause_sec: float = 0.2,
    timeout_sec: float = 60,
) -> dict[str, dict[str, Any]]:
    """
    Возвращает {исходный_title: поля...} только для распознанных позиций.
    POST JSON-массив на base_url или GET ?a= для одного title.
    """
    base = base_url if base_url.endswith("/") else base_url + "/"
    unique = []
    seen: set[str] = set()
    for t in titles:
        s = str(t).strip()
        if s and s not in seen:
            seen.add(s)
            unique.append(s)

    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(unique), batch_size):
        chunk = unique[i : i + batch_size]
        out.update(_post_batch(base, chunk, timeout_sec))
        if pause_sec > 0 and i + batch_size < len(unique):
            time.sleep(pause_sec)
    return out


def normalize_titles_ordered(
    titles: list[str],
    *,
    base_url: str = "http://192.168.1.75/",
    batch_size: int = 40,
    pause_sec: float = 0.2,
    timeout_sec: float = 60,
) -> list[dict[str, Any] | None]:
    """
    Тот же batch POST, но результат в порядке входного массива.
    Для каждой строки — поля словаря или None, если не распознано.
    """
    parsed = normalize_titles(
        titles,
        base_url=base_url,
        batch_size=batch_size,
        pause_sec=pause_sec,
        timeout_sec=timeout_sec,
    )
    return [parsed.get(str(t).strip()) for t in titles]


def normalize_one(title: str, *, base_url: str = "http://192.168.1.75/", timeout_sec: float = 30) -> dict[str, Any] | None:
    base = base_url if base_url.endswith("/") else base_url + "/"
    q = urllib.parse.urlencode({"a": title})
    url = f"{base}?{q}"
    raw = _fetch(url, None, timeout_sec, method="GET")
    if raw is None:
        return None
    data = json.loads(raw)
    if isinstance(data, list):
        return None
    if isinstance(data, dict):
        if title in data and isinstance(data[title], dict):
            return data[title]
        if len(data) == 1:
            v = next(iter(data.values()))
            return v if isinstance(v, dict) else None
    return None


def _post_batch(base: str, titles: list[str], timeout_sec: float) -> dict[str, dict[str, Any]]:
    body = json.dumps(titles, ensure_ascii=False).encode("utf-8")
    raw = _fetch(
        base,
        body,
        timeout_sec,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    if raw is None:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _fetch(
    url: str,
    data: bytes | None,
    timeout_sec: float,
    *,
    method: str,
    headers: dict[str, str] | None = None,
) -> bytes | None:
    hdrs = headers or {}
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise NomenclatureApiError(f"HTTP {e.code} для {url}") from e
    except urllib.error.URLError as e:
        raise NomenclatureApiError(f"Нет связи с {url}: {e}") from e
