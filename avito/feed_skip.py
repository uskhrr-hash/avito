"""Список Id, которые не кладём в публикуемый фид (повторные ошибки Avito).

Файл: input/avito_feed_skip_ids.txt — по одному Id на строку (# комментарии).
После отчёта автозагрузки сюда попадают error_params / error_blocked / …
чтобы каждые 3 часа не слать те же ~700 объявлений с той же ошибкой.
Чтобы повторить попытку — удалите Id из файла.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

LOG = logging.getLogger(__name__)

# Секции отчёта Avito, после которых Id не перевыгружаем
FAIL_SECTIONS = frozenset(
    {
        "error_params",
        "error_blocked",
        "error_deleted",
        "error_several",
        "error",
    }
)


def default_skip_path(root: Path) -> Path:
    return root / "input" / "avito_feed_skip_ids.txt"


def load_skip_ids(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # "md_123  # reason" → md_123
        out.add(s.split()[0].strip())
    return out


def save_skip_ids(path: Path, ids: Iterable[str], *, header: str | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    uniq = sorted({str(x).strip() for x in ids if str(x).strip()})
    lines = [
        header
        or (
            "# Id объявлений, исключённые из XML-фида после ошибок Avito.\n"
            "# Удалите строку, чтобы снова попробовать выгрузить.\n"
        )
    ]
    if not str(lines[0]).endswith("\n"):
        lines[0] = str(lines[0]).rstrip() + "\n"
    lines.extend(f"{i}\n" for i in uniq)
    path.write_text("".join(lines), encoding="utf-8")
    return len(uniq)


def merge_skip_ids(path: Path, new_ids: Iterable[str]) -> tuple[set[str], int]:
    """Добавить Id в skip-файл. Возвращает (полный набор, сколько новых)."""
    existing = load_skip_ids(path)
    before = len(existing)
    for raw in new_ids:
        sid = str(raw or "").strip()
        if sid:
            existing.add(sid)
    added = len(existing) - before
    if added:
        save_skip_ids(path, existing)
    return existing, added


def default_skip_meta_path(root: Path) -> Path:
    return root / "input" / "avito_feed_skip_meta.json"


def load_skip_meta(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_skip_meta(path: Path, meta: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def harvest_failed_ad_ids(
    client: Any,
    *,
    upload_id: int | None = None,
    max_pages: int = 50,
    per_page: int = 100,
    meta_path: Path | None = None,
    force: bool = False,
) -> tuple[set[str], int | None]:
    """Собрать ad_id из секций ошибок последнего (или указанного) upload.

    Если meta_path задан и этот upload_id уже харвестили — возвращает пустой набор
    (чтобы ручной clear skip после фикса справочника не затирался старым отчётом).
    """
    from avito.avito_api import get_last_successful_upload

    rid = upload_id
    if rid is None:
        last = get_last_successful_upload(client)
        rid = last.get("upload_id") or last.get("report_id")
    if not rid:
        return set(), None
    rid_int = int(rid)

    if meta_path is not None and not force:
        meta = load_skip_meta(meta_path)
        prev = meta.get("last_harvest_upload_id")
        try:
            prev_i = int(prev) if prev is not None else None
        except (TypeError, ValueError):
            prev_i = None
        if prev_i == rid_int:
            LOG.info(
                "feed_skip harvest: upload_id=%s уже учтён — пропуск (не затираем clear)",
                rid_int,
            )
            return set(), rid_int

    failed: set[str] = set()
    page = 1
    while page <= max_pages:
        data = client.request(
            "GET",
            f"/autoload/v2/reports/{rid_int}/items",
            params={"per_page": per_page, "page": page},
        )
        batch = data.get("items") or []
        if not batch:
            break
        for it in batch:
            sec = ((it.get("section") or {}) or {}).get("slug") or ""
            if sec not in FAIL_SECTIONS and not str(sec).startswith("error"):
                continue
            ad_id = str(it.get("ad_id") or "").strip()
            if ad_id:
                failed.add(ad_id)
        meta = data.get("meta") or {}
        pages = int(meta.get("pages") or 1)
        if page >= pages:
            break
        page += 1
    LOG.info(
        "feed_skip harvest: upload_id=%s failed_ads=%s",
        rid_int,
        len(failed),
    )
    if meta_path is not None:
        meta = load_skip_meta(meta_path)
        meta["last_harvest_upload_id"] = rid_int
        save_skip_meta(meta_path, meta)
    return failed, rid_int
