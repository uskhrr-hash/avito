"""Определение собственных объявлений на Avito."""
from __future__ import annotations


def is_own_listing(
    *,
    seller: str = "",
    title: str = "",
    description: str = "",
    own_names: list[str],
) -> tuple[bool, str]:
    """
    Возвращает (is_own, matched_by).
    matched_by: seller | title | description | ''
    """
    if not own_names:
        return False, ""

    for name in own_names:
        if not name:
            continue
        if seller and name in seller:
            return True, "seller"
        if title and name in title:
            return True, "title"
        if description and name in description:
            return True, "description"
    return False, ""
