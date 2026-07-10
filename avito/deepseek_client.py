"""Клиент DeepSeek (OpenAI-совместимый chat/completions)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

LOG = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_sec: float = 120.0
    temperature: float = 0.7
    max_tokens: int = 1500


@dataclass(frozen=True)
class ChatResult:
    content: str
    tokens_in: int | None
    tokens_out: int | None
    raw: dict[str, Any]


def load_deepseek_config(secrets: dict[str, Any]) -> DeepSeekConfig:
    raw = secrets.get("deepseek") or {}
    api_key = str(raw.get("api_key", "") or "").strip()
    if not api_key:
        raise ValueError("В secrets.local.yaml не задан deepseek.api_key")
    return DeepSeekConfig(
        api_key=api_key,
        base_url=str(raw.get("base_url", DEFAULT_BASE_URL)).strip().rstrip("/"),
        model=str(raw.get("model", DEFAULT_MODEL)).strip(),
        timeout_sec=float(raw.get("timeout_sec", 120)),
        temperature=float(raw.get("temperature", 0.7)),
        max_tokens=int(raw.get("max_tokens", 1500)),
    )


def chat_completion(
    cfg: DeepSeekConfig,
    *,
    system: str,
    user: str,
) -> ChatResult:
    url = f"{cfg.base_url}/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=cfg.timeout_sec,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"DeepSeek HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"DeepSeek: пустой ответ: {data}")
    content = str(choices[0].get("message", {}).get("content", "") or "").strip()
    usage = data.get("usage") or {}
    return ChatResult(
        content=content,
        tokens_in=usage.get("prompt_tokens"),
        tokens_out=usage.get("completion_tokens"),
        raw=data,
    )
