"""Обработка папки «входящие» — фото от менеджеров с телефона."""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from avito.photo_convert import ensure_jpeg_file

LOG = logging.getLogger(__name__)

# 124889.jpg, 124889-1.jpg
_ARTICLE_NAME_RE = re.compile(
    r"^(\d{4,})(?:[-_](\d+))?\.([a-z0-9]+)$",
    re.IGNORECASE,
)


@dataclass
class InboxStats:
    imported: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    by_store: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class InboxFile:
    article: str
    index: str | None
    store_prefix: str | None


def photo_filename(
    article: str,
    index: int | str | None,
    *,
    store_prefix: str | None,
    photo_layout: str = "flat",
    prefix_in_filename: bool = True,
) -> str:
    """Имя файла для автозагрузки (например 124889.jpg или 124889-2.jpg)."""
    idx = str(index).strip() if index is not None else None
    return _target_name(
        article,
        idx,
        store_prefix=store_prefix,
        photo_layout=photo_layout,
        prefix_in_filename=prefix_in_filename,
    )


def photo_relative_path(
    article: str,
    index: int | str | None,
    *,
    store_prefix: str,
    photo_layout: str = "flat",
    prefix_in_filename: bool = True,
) -> str:
    """Относительный путь внутри photos_local_dir (например md/124889.jpg)."""
    name = photo_filename(
        article,
        index,
        store_prefix=store_prefix,
        photo_layout=photo_layout,
        prefix_in_filename=prefix_in_filename,
    )
    layout = (photo_layout or "flat").lower()
    if layout == "store_subdir" and store_prefix:
        return f"{store_prefix.strip()}/{name}"
    if layout == "folder":
        art = str(article).strip()
        return f"{art}/{name}"
    return name


def photo_target_path(
    photos_root: Path,
    article: str,
    index: int | str | None,
    *,
    store_prefix: str,
    photo_layout: str = "flat",
    prefix_in_filename: bool = True,
) -> Path:
    rel = photo_relative_path(
        article,
        index,
        store_prefix=store_prefix,
        photo_layout=photo_layout,
        prefix_in_filename=prefix_in_filename,
    )
    return photos_root / Path(rel)


def _target_name(
    article: str,
    index: str | None,
    *,
    store_prefix: str | None,
    photo_layout: str = "flat",
    prefix_in_filename: bool = True,
) -> str:
    use_prefix = bool(store_prefix) and not (
        (photo_layout or "flat").lower() == "store_subdir" and not prefix_in_filename
    )
    stem = f"{store_prefix}{article}" if use_prefix else article
    if index in (None, "", "1"):
        return f"{stem}.jpg"
    return f"{stem}-{index}.jpg"


def parse_inbox_filename(
    name: str,
    store_prefixes: tuple[str, ...] = (),
) -> InboxFile | None:
    """
    124889.jpg → без магазина
    md124889-2.jpg → магазин md
  """
    raw = name.strip()
    for prefix in sorted(store_prefixes, key=len, reverse=True):
        pattern = re.compile(
            rf"^{re.escape(prefix)}(\d{{4,}})(?:[-_](\d+))?\.[a-z0-9]+$",
            re.IGNORECASE,
        )
        match = pattern.match(raw)
        if match:
            return InboxFile(
                article=match.group(1),
                index=match.group(2),
                store_prefix=prefix,
            )
    match = _ARTICLE_NAME_RE.match(raw)
    if match:
        return InboxFile(
            article=match.group(1),
            index=match.group(2),
            store_prefix=None,
        )
    return None


def _import_one(
    src: Path,
    target: Path,
    parsed: InboxFile,
    *,
    remove_source: bool,
    jpeg_quality: int,
    stats: InboxStats,
    photo_layout: str = "flat",
    prefix_in_filename: bool = True,
) -> None:
    dst_name = _target_name(
        parsed.article,
        parsed.index,
        store_prefix=parsed.store_prefix,
        photo_layout=photo_layout,
        prefix_in_filename=prefix_in_filename,
    )
    dst_dir = target
    if (photo_layout or "flat").lower() == "store_subdir" and parsed.store_prefix:
        dst_dir = target / parsed.store_prefix
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / dst_name
    if src.suffix.lower() in {".heic", ".heif", ".webp"}:
        jpg = ensure_jpeg_file(src, quality=jpeg_quality)
        if jpg is None:
            raise ValueError("не удалось конвертировать в JPEG")
        shutil.copy2(jpg, dst)
    else:
        shutil.copy2(src, dst)
    if remove_source:
        src.unlink(missing_ok=True)
    stats.imported += 1
    key = parsed.store_prefix or "_unprefixed"
    stats.by_store[key] = stats.by_store.get(key, 0) + 1
    store_label = parsed.store_prefix or "без префикса"
    LOG.info("Входящие: %s → %s (магазин %s)", src.name, dst.name, store_label)


def import_manager_inbox(
    inbox: Path,
    target: Path,
    *,
    store_prefixes: tuple[str, ...] = (),
    remove_source: bool = True,
    jpeg_quality: int = 85,
    photo_layout: str = "flat",
    prefix_in_filename: bool = True,
) -> InboxStats:
    """
    Перенести фото из «входящие» в папку «Авито».

    Привязка к магазину (контакты в автозагрузке):
    - папка «входящие/md/124889.jpg» → Авито/md/124889.jpg (store_subdir, без префикса в имени)
    - legacy: md124889.jpg в корне или в папке md — тоже находится при поиске
    - «входящие/124889.jpg» без папки — магазин неизвестен (legacy)
    """
    stats = InboxStats()
    if not inbox.is_dir():
        return stats
    target.mkdir(parents=True, exist_ok=True)
    known = {p.lower() for p in store_prefixes}

    for sub in sorted(inbox.iterdir()):
        if sub.is_dir() and sub.name.lower() in known:
            prefix = next(p for p in store_prefixes if p.lower() == sub.name.lower())
            for src in sorted(sub.iterdir()):
                if not src.is_file():
                    continue
                parsed = parse_inbox_filename(src.name, ())
                if not parsed:
                    stats.skipped += 1
                    continue
                parsed = InboxFile(
                    article=parsed.article,
                    index=parsed.index,
                    store_prefix=prefix,
                )
                try:
                    _import_one(
                        src,
                        target,
                        parsed,
                        remove_source=remove_source,
                        jpeg_quality=jpeg_quality,
                        stats=stats,
                        photo_layout=photo_layout,
                        prefix_in_filename=prefix_in_filename,
                    )
                except Exception as exc:
                    stats.errors.append((str(src), str(exc)))
                    LOG.warning("Входящие: не удалось %s: %s", src.name, exc)

    for src in sorted(inbox.iterdir()):
        if not src.is_file():
            continue
        parsed = parse_inbox_filename(src.name, store_prefixes)
        if not parsed:
            stats.skipped += 1
            LOG.debug("Пропуск (имя не артикул): %s", src.name)
            continue
        if parsed.store_prefix is None and store_prefixes:
            LOG.warning(
                "Входящие: %s без папки магазина — будет без префикса (неизвестный автор)",
                src.name,
            )
        try:
            _import_one(
                src,
                target,
                parsed,
                remove_source=remove_source,
                jpeg_quality=jpeg_quality,
                stats=stats,
                photo_layout=photo_layout,
                prefix_in_filename=prefix_in_filename,
            )
        except Exception as exc:
            stats.errors.append((src.name, str(exc)))
            LOG.warning("Входящие: не удалось %s: %s", src.name, exc)

    return stats


def resolve_inbox_folder(photos_dir: Path | None, subdir: str) -> Path | None:
    if not photos_dir or not subdir.strip():
        return None
    return photos_dir / subdir.strip().strip("/\\")
