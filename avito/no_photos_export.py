"""Excel со списком позиций без фото — в папку Авито на Яндекс.Диске."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


def export_no_photos_excel(
    folder: Path,
    filename: str,
    items: list[dict],
) -> Path:
    """Перезаписывает no_photos.xlsx в папке синхронизации Диска."""
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / filename
    stamp = datetime.now().replace(microsecond=0).isoformat(sep=" ")

    rows = []
    for item in items:
        rows.append(
            {
                "артикул": str(item.get("артикул", "") or "").strip(),
                "номенклатура": str(item.get("номенклатура", "") or "").strip(),
                "проблема": str(item.get("проблема", "") or "").strip(),
                "обновлено": stamp,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=["артикул", "номенклатура", "проблема", "обновлено"]
        )

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="без фото", index=False)

    return out
