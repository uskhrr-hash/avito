"""База описаний по моделям шин (бренд + модель) — runtime читает только БД."""
from __future__ import annotations

from pathlib import Path

TABLE_COLUMNS = (
    "бренд",
    "модель",
    "ключ_модели",
    "имя_каноническое",
    "словарь_распознан",
    "каталог_4tochki",
    "описание_html",
    "источник",
    "обновлено",
)


def model_key(brand: str, model: str) -> str:
    return " ".join(x for x in (brand.strip(), model.strip()) if x).strip()


def lookup_model_description(
    descriptions: dict[str, str],
    *,
    nomenclature: str,
    brand: str,
    model: str,
) -> str:
    """Поиск по brand+model, затем по префиксу ключа модели в номенклатуре."""
    key = model_key(brand, model)
    if key and key in descriptions:
        return descriptions[key]
    nom = nomenclature.strip()
    if not nom:
        return ""
    hits = [k for k in descriptions if nom == k or nom.startswith(k + " ")]
    if hits:
        return descriptions[max(hits, key=len)]
    return ""


def resolve_model_descriptions(
    *,
    descriptions_db_enabled: bool = False,
    secrets_path: Path | None = None,
    pg_schema: str = "public",
    project_root: Path | None = None,
    # legacy kwargs ignored (xlsx path removed)
    xlsx_path: Path | None = None,
    fallback_to_xlsx: bool = False,
) -> dict[str, str]:
    """Источник описаний — БД (approved). Excel fallback удалён."""
    del xlsx_path, fallback_to_xlsx
    from avito.db import descriptions_connection, load_secrets
    from avito.descriptions_db import configure_pg_schema, load_approved_descriptions

    if not descriptions_db_enabled:
        raise RuntimeError(
            "descriptions_db.enabled=false: описания моделей недоступны "
            "(Excel fallback удалён)"
        )

    if not secrets_path or not secrets_path.exists():
        raise FileNotFoundError(
            f"descriptions_db включён, но secrets не найден: {secrets_path}"
        )

    try:
        configure_pg_schema(pg_schema)
        secrets = load_secrets(secrets_path)
        with descriptions_connection(secrets, project_root=project_root) as conn:
            return load_approved_descriptions(conn)
    except Exception as exc:
        raise RuntimeError(
            f"Не удалось загрузить описания моделей из БД: {exc}"
        ) from exc
